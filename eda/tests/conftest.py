'''Shared pytest fixtures and sys.path setup for eda/tests/.

Adds ``eda/`` (the parent dir) to sys.path so tests can import
``eda_utils_*`` modules directly without packaging gymnastics.
'''
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

EDA_DIR = Path(__file__).resolve().parents[1]
if str(EDA_DIR) not in sys.path:
    sys.path.insert(0, str(EDA_DIR))


@pytest.fixture
def tiny_embeddings():
    '''20 docs x 8 dims, fixed seed - cheap synthetic matrix.'''
    rng = np.random.default_rng(0)
    return rng.normal(size=(20, 8)).astype(np.float32)


@pytest.fixture
def tiny_texts():
    return pd.Series([f'doc_{i}' for i in range(20)])


class StubInferenceClient:
    '''Deterministic stand-in for ``huggingface_hub.InferenceClient``.

    Returns a 1D float32 vector seeded from the text content so repeated
    calls on the same text return identical bytes. Optionally fails the
    first ``fail_first_n`` calls with a synthetic HTTP error so retry/backoff
    paths can be exercised.
    '''
    def __init__(self, dim=8, fail_first_n=0, status=500):
        self.dim = dim
        self.calls = []
        self.fail_first_n = fail_first_n
        self.status = status

    def feature_extraction(self, text):
        self.calls.append(text)
        if len(self.calls) <= self.fail_first_n:
            raise _http_error(self.status)
        rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
        return rng.normal(size=self.dim).astype(np.float32).tolist()


def _http_error(status):
    class _Resp:
        def __init__(self, code):
            self.status_code = code
    e = RuntimeError(f"HTTP {status}")
    e.response = _Resp(status)
    return e


@pytest.fixture
def stub_client_factory():
    '''Builder for StubInferenceClient with parameterized behavior.'''
    def make(**kwargs):
        return StubInferenceClient(**kwargs)
    return make
