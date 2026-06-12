'''JSONL run records — the durable system of record for every pipeline stage.

One record per document plus a run-level summary, appended incrementally so a
crash loses nothing. Records pin everything needed to reproduce or audit a
run: run id, git SHA, schema version *and content hash* (tamper check), prompt
and model versions, data snapshot, cache hits vs paid calls, per-counter
drops/corrections, retries, latency, tokens.

Raw records stay gitignored under ``ontology/artifacts/runs/``; eval commits
metric *summaries* to ``ontology/results/``.
'''
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

DEFAULT_RUNS_DIR = _HERE / 'artifacts' / 'runs'


def new_run_id(prefix='run'):
    return f'{prefix}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}'


def git_sha(repo_root=None):
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_root or _HERE.parent, capture_output=True, text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except OSError:
        pass
    return 'unknown'


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RunRecorder:
    '''Incremental per-doc JSONL records + a run-level summary.'''

    def __init__(self, stage, runs_dir=DEFAULT_RUNS_DIR, run_id=None,
                 schema_path=None, schema_version=None, prompt_version=None,
                 model_id=None, data_snapshot=None, extra=None):
        self.run_id = run_id or new_run_id(stage)
        self.stage = stage
        self.started_at = time.time()
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.docs_path = self.runs_dir / f'{self.run_id}.docs.jsonl'
        self.summary_path = self.runs_dir / f'{self.run_id}.summary.json'
        self.meta = {
            'run_id': self.run_id,
            'stage': stage,
            'git_sha': git_sha(),
            'schema_version': schema_version,
            'schema_sha256': file_sha256(schema_path) if schema_path else None,
            'prompt_version': prompt_version,
            'model_id': model_id,
            'data_snapshot': data_snapshot,
            **(extra or {}),
        }
        self._doc_count = 0

    def record_doc(self, doc_key, **fields):
        record = {'run_id': self.run_id, 'doc_key': doc_key,
                  'ts': time.time(), **fields}
        with self.docs_path.open('a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(record, default=str) + '\n')
        self._doc_count += 1

    def write_summary(self, **fields):
        summary = {
            **self.meta,
            'docs_recorded': self._doc_count,
            'elapsed_seconds': round(time.time() - self.started_at, 3),
            **fields,
        }
        self.summary_path.write_text(
            json.dumps(summary, indent=2, default=str), encoding='utf-8')
        return self.summary_path
