'''Smoke tests for db.run_pipeline against a throwaway sqlite database.'''
import json

import pytest
from sqlalchemy import text

import run_pipeline


def _argv(sqlite_url, *flags):
    return ['--database-url', sqlite_url, *flags]


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------
def test_full_run_executes_all_stages(sqlite_url, tmp_path, capsys):
    args = run_pipeline.parse_args(
        _argv(sqlite_url, '--manifest-out', str(tmp_path)))
    rc = run_pipeline.run(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert 'preflight OK' in out
    assert 'build :' in out
    assert 'manifest:' in out
    assert (tmp_path / 'cleaning_manifest.json').exists()
    assert (tmp_path / 'column_dictionary.json').exists()
    cleaning = json.loads((tmp_path / 'cleaning_manifest.json').read_text())
    assert len(cleaning['steps']) >= 8


# ---------------------------------------------------------------------------
# --build-only on an already-ingested DB
# ---------------------------------------------------------------------------
def test_build_only_rebuilds_without_reingesting(sqlite_url, tmp_path):
    # full run primes the DB
    run_pipeline.run(run_pipeline.parse_args(
        _argv(sqlite_url, '--manifest-out', str(tmp_path))))
    # now run --build-only and confirm ingest didn't happen again
    rc = run_pipeline.run(run_pipeline.parse_args(
        _argv(sqlite_url, '--build-only', '--manifest-out', str(tmp_path))))
    assert rc == 0
    from connection import get_engine
    eng = get_engine(sqlite_url)
    with eng.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM ingest_batches')).scalar() == 2
        assert conn.execute(
            text('SELECT COUNT(*) FROM raw_incident_reports')).scalar() == 3120


# ---------------------------------------------------------------------------
# Missing DATABASE_URL aborts at preflight
# ---------------------------------------------------------------------------
def test_missing_database_url_aborts_at_preflight(monkeypatch, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    args = run_pipeline.parse_args([])  # no --database-url
    rc = run_pipeline.run(args)
    assert rc == 2
    assert 'DATABASE_URL' in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --reset without --yes (non-interactive) refuses
# ---------------------------------------------------------------------------
def test_reset_without_yes_refuses(sqlite_url, capsys, monkeypatch):
    # ensure non-interactive stdin
    class _NotATTY:
        def isatty(self): return False
    monkeypatch.setattr('sys.stdin', _NotATTY())
    args = run_pipeline.parse_args(_argv(sqlite_url, '--reset'))
    rc = run_pipeline.run(args)
    assert rc == 2
    assert 'requires --yes' in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Idempotency: full run twice -> 0 new rows on second
# ---------------------------------------------------------------------------
def test_second_full_run_ingests_zero_new_rows(sqlite_url, tmp_path):
    run_pipeline.run(run_pipeline.parse_args(
        _argv(sqlite_url, '--manifest-out', str(tmp_path))))
    run_pipeline.run(run_pipeline.parse_args(
        _argv(sqlite_url, '--manifest-out', str(tmp_path))))
    from connection import get_engine
    eng = get_engine(sqlite_url)
    with eng.connect() as conn:
        # sha256 guard => still 2 batches, 3120 rows
        assert conn.execute(text('SELECT COUNT(*) FROM ingest_batches')).scalar() == 2
        assert conn.execute(
            text('SELECT COUNT(*) FROM raw_incident_reports')).scalar() == 3120


# ---------------------------------------------------------------------------
# --reset --yes on a populated DB returns to a clean schema and re-ingests
# ---------------------------------------------------------------------------
def test_reset_yes_round_trips_to_same_row_counts(sqlite_url, tmp_path):
    run_pipeline.run(run_pipeline.parse_args(
        _argv(sqlite_url, '--manifest-out', str(tmp_path))))
    rc = run_pipeline.run(run_pipeline.parse_args(
        _argv(sqlite_url, '--reset', '--yes', '--manifest-out', str(tmp_path))))
    assert rc == 0
    from connection import get_engine
    eng = get_engine(sqlite_url)
    with eng.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM ingest_batches')).scalar() == 2
        assert conn.execute(
            text('SELECT COUNT(*) FROM raw_incident_reports')).scalar() == 3120
