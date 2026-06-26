'''Shared fixtures + sys.path setup for fault/tests/.

Adds ``fault/`` plus ``db/`` and ``ontology/`` to sys.path so tests import the
batch modules and reuse the ontology LLM client by bare name. No test here may
hit the network or require a key — the LLM client is always the in-process
``StubClient``.
'''
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

FAULT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = FAULT_DIR.parent
for _p in (REPO_ROOT / 'db', REPO_ROOT / 'ontology', FAULT_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_FAULT_DDL = (REPO_ROOT / 'db' / 'sql' / '005_fault_analysis.sql').read_text()


class StubClient:
    '''Deterministic stand-in for ``llm.AnthropicStructuredClient``.

    ``invoke(prompt, schema)`` returns ``response`` (a schema instance or a raw
    dict — ``CachedLLM`` coerces dicts) or, if ``response_factory`` is given,
    ``response_factory(prompt, schema)``. Every call is recorded so cache-hit
    tests can assert zero new calls on a re-run.
    '''

    def __init__(self, response=None, response_factory=None):
        self.response = response
        self.response_factory = response_factory
        self.calls = []

    def invoke(self, prompt, schema):
        self.calls.append((prompt, schema))
        if self.response_factory is not None:
            return self.response_factory(prompt, schema)
        return self.response


@pytest.fixture
def engine(tmp_path):
    '''File-backed sqlite engine with only fault_analysis created (schema
    survives reconnects, the way db/tests/conftest.py does it).'''
    eng = create_engine(f'sqlite:///{(tmp_path / "fault.db").as_posix()}')
    with eng.begin() as conn:
        for stmt in _FAULT_DDL.split(';'):
            stmt = '\n'.join(
                ln for ln in stmt.splitlines() if not ln.strip().startswith('--')
            ).strip()
            if stmt:
                conn.execute(text(stmt))
    try:
        yield eng
    finally:
        eng.dispose()
