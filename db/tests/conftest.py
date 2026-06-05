'''Shared fixtures + sys.path setup for db/tests/.

Adds ``db/`` (the parent dir) and ``eda/`` to sys.path so tests can import
``connection`` / ``create_tables`` / ``ingest_raw`` ... and the ``eda_utils_*``
treatment modules directly by bare name -- mirroring eda/tests/conftest.py.
'''
import sys
from pathlib import Path

import pytest

DB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DB_DIR.parent
EDA_DIR = REPO_ROOT / 'eda'
for _p in (DB_DIR, EDA_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DATA_DIR = REPO_ROOT / 'data' / 'nhtsa'
EARLY_CSV = DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_to_2025_06_16.csv'
LATER_CSV = DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_2025_06_16_to_2026_03_16.csv'


@pytest.fixture
def sqlite_url(tmp_path):
    '''File-based sqlite URL (file-backed so schema survives reconnects).'''
    return f'sqlite:///{(tmp_path / "test.db").as_posix()}'


@pytest.fixture
def engine(sqlite_url):
    from connection import get_engine
    eng = get_engine(sqlite_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def csv_paths():
    '''The two real SGO CSVs (early + later schema versions).'''
    return [EARLY_CSV, LATER_CSV]
