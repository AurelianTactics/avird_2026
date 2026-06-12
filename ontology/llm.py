'''Shared LLM client: structured output, content-addressed cache, retries.

Every paid call flows through ``CachedLLM.call(prompt, schema)``:

- **Cache key** = sha256(model id + rendered prompt). The rendered prompt
  embeds the document text, the schema-derived structure, and the task, so any
  prompt or schema change invalidates by content — no trust in human-declared
  version labels. One JSON file per call under ``artifacts/cache/<model>/``,
  written atomically as each call completes (a crash keeps everything paid
  for so far).
- **Retries** with exponential backoff for transient failures only (timeouts
  and 408/429/5xx/529). ``max_attempts=1`` means zero retries and *raises* on
  failure — never returns None (the embeddings-pattern bug this fixes).
- **--dry-run** counts cache misses without spending; ``call`` returns None
  per miss and ``stats`` carries the would-pay count.

Tests inject a ``StubLLMClient`` via ``_client``; nothing here needs a key or
network until a real call is made.
'''
import hashlib
import json
import re
import sys
import threading
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

DEFAULT_MODEL_ID = 'claude-haiku-4-5'
GOLDEN_PRELABEL_MODEL_ID = 'claude-sonnet-4-6'
DEFAULT_CACHE_DIR = _HERE / 'artifacts' / 'cache'

TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504, 529}


class LLMCallError(RuntimeError):
    '''A call failed permanently (non-transient, or retries exhausted).'''


def cache_key(prompt, model_id):
    payload = model_id.encode('utf-8') + b'\x00' + prompt.encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _model_slug(model_id):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', model_id)


def is_transient(exc):
    '''Duck-typed transient check: status_code, timeout-ish, or connection-ish.

    Connection-level failures (anthropic.APIConnectionError, httpx
    ConnectError, builtin ConnectionError) carry no status_code and no
    "timeout" in their class name, but are exactly the blips a long batch
    run must retry through.
    '''
    status = getattr(exc, 'status_code', None)
    if status in TRANSIENT_STATUS:
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    name = type(exc).__name__.lower()
    return 'timeout' in name or 'connect' in name


class AnthropicStructuredClient:
    '''Thin real client: ChatAnthropic + with_structured_output.

    Prefers ``method="json_schema"`` (native structured outputs); falls back
    to default tool-calling once if the model rejects it.
    '''

    def __init__(self, model_id):
        from langchain_anthropic import ChatAnthropic
        self.model_id = model_id
        self._chat = ChatAnthropic(model=model_id, max_retries=0, timeout=120.0)
        self._method = 'json_schema'
        self._runnables = {}

    def _runnable(self, schema):
        key = (schema, self._method)
        if key not in self._runnables:
            kwargs = {'method': self._method} if self._method else {}
            self._runnables[key] = self._chat.with_structured_output(schema, **kwargs)
        return self._runnables[key]

    def invoke(self, prompt, schema):
        try:
            return self._runnable(schema).invoke(prompt)
        except Exception as e:
            # Model lacks native structured outputs -> retry via tool calling.
            if self._method == 'json_schema' and not is_transient(e):
                self._method = None
                return self._runnable(schema).invoke(prompt)
            raise


class CachedLLM:
    '''Content-address-cached, retrying structured-output caller.'''

    def __init__(self, model_id=DEFAULT_MODEL_ID, cache_dir=DEFAULT_CACHE_DIR,
                 max_attempts=4, backoff_base=2.0, dry_run=False,
                 _client=None, _sleep=time.sleep):
        if max_attempts < 1:
            raise ValueError('max_attempts must be >= 1')
        self.model_id = model_id
        self.cache_dir = Path(cache_dir)
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.dry_run = dry_run
        self._client = _client
        self._sleep = _sleep
        # extract.py shares one CachedLLM across Send fan-out threads
        self._lock = threading.Lock()
        self.stats = {'cache_hits': 0, 'llm_calls': 0, 'retries': 0,
                      'dry_run_misses': 0}

    def _bump(self, stat):
        with self._lock:
            self.stats[stat] += 1

    def _cache_path(self, key):
        return self.cache_dir / _model_slug(self.model_id) / f'{key}.json'

    def call(self, prompt, schema):
        '''Return a validated ``schema`` instance (None on dry-run miss).'''
        key = cache_key(prompt, self.model_id)
        path = self._cache_path(key)
        if path.exists():
            self._bump('cache_hits')
            payload = json.loads(path.read_text(encoding='utf-8'))
            return schema.model_validate(payload['result'])

        if self.dry_run:
            self._bump('dry_run_misses')
            return None

        result = self._invoke_with_retry(prompt, schema)
        self._persist(path, key, result)
        return result

    def _invoke_with_retry(self, prompt, schema):
        client = self._ensure_client()
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = self._coerce(client.invoke(prompt, schema), schema)
                self._bump('llm_calls')
                return result
            except Exception as e:
                if isinstance(e, LLMCallError):
                    raise
                if not is_transient(e) or attempt == self.max_attempts:
                    raise LLMCallError(
                        f'LLM call failed after {attempt} attempt(s) '
                        f'({type(e).__name__}: {e})'
                    ) from e
                self._bump('retries')
                self._sleep(self.backoff_base ** (attempt - 1))
        raise AssertionError('unreachable')  # pragma: no cover

    @staticmethod
    def _coerce(result, schema):
        if result is None:
            # Structured-output parse failure must be loud, never a None
            # that poisons downstream stages.
            raise LLMCallError('LLM returned no parseable structured output')
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)

    def _persist(self, path, key, result):
        '''Atomic per-call write so interrupts keep completed work.'''
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'model_id': self.model_id,
            'cache_key': key,
            'schema': type(result).__name__,
            'result': result.model_dump(mode='json'),
        }
        # uuid suffix: fan-out threads share a PID, and two docs with
        # byte-identical text race on the same cache key's tmp file.
        tmp = path.with_suffix(f'.tmp-{uuid.uuid4().hex}')
        tmp.write_text(json.dumps(payload, indent=1), encoding='utf-8')
        tmp.replace(path)

    def _ensure_client(self):
        with self._lock:
            if self._client is None:
                self._client = AnthropicStructuredClient(self.model_id)
            return self._client
