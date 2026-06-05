'''Tests for eda_utils_dedupe.flag_incident_reports (the non-destructive
canonical-row flag) plus a characterization tie-back to dedupe_same_incident.
'''
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import eda_utils_dedupe as ded
import eda_utils_sgo

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / 'data' / 'nhtsa'
EARLY_CSV = DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_to_2025_06_16.csv'
LATER_CSV = DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_2025_06_16_to_2026_03_16.csv'

FLAG = 'is_latest_of_multiple_report'
MULTI = 'has_multiple_reports'
NARR_OUT = 'Narrative - Same Incident ID'


@pytest.fixture(scope='module')
def combined_df():
    return eda_utils_sgo.load_and_concat_csvs([EARLY_CSV, LATER_CSV])


# ---------------------------------------------------------------------------
# Small synthetic frames
# ---------------------------------------------------------------------------
def _frame(rows):
    return pd.DataFrame(rows)


def test_two_report_group_flags_only_the_latest():
    df = _frame([
        {'Report ID': 'a', 'Report Version': '1', 'Same Incident ID': 'SID1',
         'Report Submission Date': '2024-01-01', 'Narrative': 'first'},
        {'Report ID': 'b', 'Report Version': '2', 'Same Incident ID': 'SID1',
         'Report Submission Date': '2024-02-01', 'Narrative': 'second'},
    ])
    out = ded.flag_incident_reports(df)
    assert len(out) == 2                       # no drops
    assert out[FLAG].sum() == 1                # exactly one canonical
    # canonical is the most recent submission / version / id
    canon = out[out[FLAG]].iloc[0]
    assert canon['Report ID'] == 'b'
    assert out[MULTI].tolist() == [True, True]


def test_single_report_incident_is_canonical_and_not_multiple():
    df = _frame([
        {'Report ID': 'solo', 'Report Version': '1', 'Same Incident ID': '',
         'Reporting Entity': 'E', 'Incident Date': '2024-03-01',
         'Incident Time (24:00)': '12:00', 'VIN': 'V1',
         'Report Submission Date': '2024-03-02', 'Narrative': 'lone'},
    ])
    out = ded.flag_incident_reports(df)
    assert out[FLAG].tolist() == [True]
    assert out[MULTI].tolist() == [False]


def test_blank_sid_falls_back_to_composite_key():
    # Same fallback key (entity/date/time/vin) -> one group of 2.
    df = _frame([
        {'Report ID': 'a', 'Report Version': '1', 'Same Incident ID': '   ',
         'Reporting Entity': 'E', 'Incident Date': '2024-03-01',
         'Incident Time (24:00)': '12:00', 'VIN': 'V1',
         'Report Submission Date': '2024-03-01', 'Narrative': 'x'},
        {'Report ID': 'b', 'Report Version': '2', 'Same Incident ID': '',
         'Reporting Entity': 'E', 'Incident Date': '2024-03-01',
         'Incident Time (24:00)': '12:00', 'VIN': 'V1',
         'Report Submission Date': '2024-03-05', 'Narrative': 'y'},
    ])
    out = ded.flag_incident_reports(df)
    assert out[FLAG].sum() == 1
    assert out[MULTI].tolist() == [True, True]
    assert out[out[FLAG]].iloc[0]['Report ID'] == 'b'


def test_missing_fallback_component_is_standalone():
    # Blank SID and a missing VIN component -> each row standalone.
    df = _frame([
        {'Report ID': 'a', 'Report Version': '1', 'Same Incident ID': '',
         'Reporting Entity': 'E', 'Incident Date': '2024-03-01',
         'Incident Time (24:00)': '12:00', 'VIN': '',
         'Report Submission Date': '2024-03-01', 'Narrative': 'x'},
        {'Report ID': 'b', 'Report Version': '1', 'Same Incident ID': '',
         'Reporting Entity': 'E', 'Incident Date': '2024-03-01',
         'Incident Time (24:00)': '12:00', 'VIN': '',
         'Report Submission Date': '2024-03-02', 'Narrative': 'y'},
    ])
    out = ded.flag_incident_reports(df)
    assert out[FLAG].tolist() == [True, True]
    assert out[MULTI].tolist() == [False, False]


def test_merged_narrative_on_canonical_only_and_deduped():
    df = _frame([
        {'Report ID': 'a', 'Report Version': '1', 'Same Incident ID': 'SID1',
         'Report Submission Date': '2024-01-01', 'Narrative': 'dup'},
        {'Report ID': 'b', 'Report Version': '2', 'Same Incident ID': 'SID1',
         'Report Submission Date': '2024-02-01', 'Narrative': 'dup'},
        {'Report ID': 'c', 'Report Version': '3', 'Same Incident ID': 'SID1',
         'Report Submission Date': '2024-03-01', 'Narrative': 'latest'},
    ])
    out = ded.flag_incident_reports(df)
    canon = out[out[FLAG]].iloc[0]
    non_canon = out[~out[FLAG]]
    # latest-first, exact duplicates collapsed
    assert canon[NARR_OUT] == 'latest' + ded._DEFAULT_NARRATIVE_SEP + 'dup'
    assert non_canon[NARR_OUT].isna().all()


def test_row_count_and_index_preserved():
    df = _frame([
        {'Report ID': 'a', 'Report Version': '1', 'Same Incident ID': 'SID1',
         'Report Submission Date': '2024-01-01', 'Narrative': 'n'},
        {'Report ID': 'b', 'Report Version': '2', 'Same Incident ID': 'SID2',
         'Report Submission Date': '2024-02-01', 'Narrative': 'm'},
    ])
    df.index = [10, 20]
    out = ded.flag_incident_reports(df)
    assert list(out.index) == [10, 20]
    assert len(out) == len(df)


# ---------------------------------------------------------------------------
# Characterization against the real data
# ---------------------------------------------------------------------------
def test_flag_true_count_matches_dedupe_on_real_data(combined_df):
    out = ded.flag_incident_reports(combined_df)
    n_dedupe = len(ded.dedupe_same_incident(combined_df))
    assert int(out[FLAG].sum()) == n_dedupe == 2344
    assert len(out) == len(combined_df) == 3120  # no rows dropped
