"""Tests for the severity normalization helper (U2, covers R5).

Pure function — no DB, no I/O. Each known raw value maps to its bucket;
null/empty/unmapped fall to ``Unknown`` and never raise.
"""

from __future__ import annotations

import pytest

from app.severity import BUCKET_ORDER, normalize


@pytest.mark.parametrize(
    ("raw", "bucket"),
    [
        ("Fatality", "Fatality"),
        ("Serious", "Serious"),
        ("Moderate", "Moderate"),
        ("Moderate W/ Hospitalization", "Moderate"),
        ("Moderate W/O Hospitalization", "Moderate"),
        ("Minor", "Minor"),
        ("Minor W/ Hospitalization", "Minor"),
        ("Minor W/O Hospitalization", "Minor"),
        ("No Apparent Injury", "No Injuries"),
        ("No Injuries Reported", "No Injuries"),
        ("No Injured Reported", "No Injuries"),
        ("Property Damage", "Property"),
        # The dominant raw property-damage spelling in the SGO CSVs.
        ("Property Damage. No Injured Reported", "Property"),
        ("Unknown", "Unknown"),
    ],
)
def test_known_values_map_to_expected_bucket(raw: str, bucket: str):
    assert normalize(raw) == bucket


def test_each_bucket_is_reachable():
    # One representative raw value per display bucket.
    reached = {
        normalize(r)
        for r in [
            "Fatality",
            "Serious",
            "Moderate",
            "Minor",
            "No Apparent Injury",
            "Property Damage Only",
            "Unknown",
        ]
    }
    assert reached == set(BUCKET_ORDER)


def test_none_maps_to_unknown():
    assert normalize(None) == "Unknown"


def test_empty_and_whitespace_map_to_unknown():
    assert normalize("") == "Unknown"
    assert normalize("   ") == "Unknown"


def test_unmapped_string_maps_to_unknown_without_raising():
    assert normalize("Catastrophic Mega-Injury") == "Unknown"


def test_case_and_whitespace_robustness():
    assert normalize("  fAtAlItY ") == "Fatality"
    assert normalize("no   apparent   injury") == "No Injuries"


def test_bucket_order_is_exactly_seven_in_display_order():
    assert BUCKET_ORDER == [
        "Fatality",
        "Serious",
        "Moderate",
        "Minor",
        "No Injuries",
        "Property",
        "Unknown",
    ]
