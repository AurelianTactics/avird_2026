'''Shared pytest fixtures and sys.path setup for ontology/tests/.

Adds ``ontology/`` (the parent dir) plus ``db/`` and ``eda/`` to sys.path so
tests import pipeline modules directly, the way ``db/`` modules import
``eda_utils_*``. Provides the two hermetic seams every test relies on:

- ``StubLLMClient`` — deterministic stand-in for the structured-output
  Anthropic client built by ``llm.make_client``. Queued or factory-built
  responses, call recording, and transient/permanent failure injection.
- ``StubNeo4jDriver`` — records every (query, params) pair handed to
  ``execute_query`` so graph-load tests assert on generated Cypher without a
  live AuraDB.

No test in this package may hit the network or require credentials.
'''
import sys
from pathlib import Path

import pytest

ONTOLOGY_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ONTOLOGY_DIR.parent
for _p in (ONTOLOGY_DIR, REPO_ROOT / 'db', REPO_ROOT / 'eda'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _api_error(status=429):
    '''Synthetic API error carrying a status_code, like anthropic's errors.'''
    e = RuntimeError(f'HTTP {status}')
    e.status_code = status
    return e


class StubLLMClient:
    '''Deterministic stand-in for ``llm.make_client(...)``.

    ``invoke(prompt, schema)`` returns the next queued response, or
    ``response_factory(prompt, schema)`` when a factory is given. Every call
    is recorded in ``calls`` as ``(prompt, schema)``. The first
    ``fail_first_n`` calls raise a synthetic error with ``status`` so retry
    and permanent-failure paths can be exercised.
    '''

    def __init__(self, responses=None, response_factory=None,
                 fail_first_n=0, status=429):
        self.responses = list(responses or [])
        self.response_factory = response_factory
        self.fail_first_n = fail_first_n
        self.status = status
        self.calls = []

    def invoke(self, prompt, schema):
        self.calls.append((prompt, schema))
        if len(self.calls) <= self.fail_first_n:
            raise _api_error(self.status)
        if self.response_factory is not None:
            return self.response_factory(prompt, schema)
        if not self.responses:
            raise AssertionError('StubLLMClient ran out of queued responses')
        return self.responses.pop(0)


@pytest.fixture
def stub_llm_factory():
    '''Builder for StubLLMClient with parameterized behavior.'''
    def make(**kwargs):
        return StubLLMClient(**kwargs)
    return make


class _StubResult:
    '''Shape-compatible subset of neo4j EagerResult: records + summary.'''

    def __init__(self, records=None):
        self.records = records or []
        self.summary = None

    def __iter__(self):
        return iter(self.records)


class StubNeo4jDriver:
    '''Records execute_query calls; optionally raises on connectivity.

    ``queries`` collects ``(query, params)`` tuples. ``results`` maps a
    substring of the query text to the records to return, so tests can fake
    read paths. ``connectivity_error`` makes ``verify_connectivity`` raise
    (e.g. neo4j's ServiceUnavailable) to exercise the paused-instance path.
    '''

    def __init__(self, results=None, connectivity_error=None):
        self.queries = []
        self.results = results or {}
        self.connectivity_error = connectivity_error
        self.closed = False

    def verify_connectivity(self):
        if self.connectivity_error is not None:
            raise self.connectivity_error

    def execute_query(self, query, parameters_=None, **kwargs):
        params = parameters_ if parameters_ is not None else kwargs or {}
        self.queries.append((query, params))
        for fragment, records in self.results.items():
            if fragment in query:
                return _StubResult(records)
        return _StubResult()

    def close(self):
        self.closed = True


@pytest.fixture
def stub_driver_factory():
    '''Builder for StubNeo4jDriver with parameterized behavior.'''
    def make(**kwargs):
        return StubNeo4jDriver(**kwargs)
    return make
