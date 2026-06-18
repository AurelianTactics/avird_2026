"""Raw `Highest Injury Severity Alleged` -> display-bucket normalization.

Single source of bucket logic for the TREATED groupings matrix (U4). The
raw incident list does **not** use this — it shows the raw severity string
untouched (plan KTD 5).

Seven buckets, ordered left->right by decreasing harm. The raw->bucket map
is matched case-insensitively on a normalized (lower, collapsed-whitespace)
key; anything null, empty, or unmapped falls to `Unknown` and is never lost.
Adding a newly-observed raw value is a one-line edit to `_RAW_TO_BUCKET`.
"""

from __future__ import annotations

# Display order — the matrix column order in U4/U9.
BUCKET_ORDER: list[str] = [
    "Fatality",
    "Serious",
    "Moderate",
    "Minor",
    "No Injuries",
    "Property",
    "Unknown",
]

# Normalized raw value (lower-cased, whitespace-collapsed) -> bucket.
# Covers the NHTSA SGO "Highest Injury Severity Alleged" value space and its
# common phrasings across schema revisions. Unmapped -> Unknown.
_RAW_TO_BUCKET: dict[str, str] = {
    "fatality": "Fatality",
    "fatal": "Fatality",
    "serious": "Serious",
    "severe": "Serious",
    "serious w/ hospitalization": "Serious",
    "serious w/o hospitalization": "Serious",
    "moderate": "Moderate",
    "moderate w/ hospitalization": "Moderate",
    "moderate w/o hospitalization": "Moderate",
    "minor": "Minor",
    "minor w/ hospitalization": "Minor",
    "minor w/o hospitalization": "Minor",
    "possible injury": "Minor",
    "no apparent injury": "No Injuries",
    "no injuries reported": "No Injuries",
    "no injured reported": "No Injuries",
    "no injuries": "No Injuries",
    "none": "No Injuries",
    "no injury": "No Injuries",
    "property damage": "Property",
    "property damage only": "Property",
    "property damage. no injured reported": "Property",
    "no apparent injury - property damage only": "Property",
    "unknown": "Unknown",
    "no data": "Unknown",
}


def _key(raw: str) -> str:
    return " ".join(raw.split()).strip().lower()


def normalize(raw: str | None) -> str:
    """Map a raw severity string to one of the seven `BUCKET_ORDER` labels.

    Null / empty / whitespace / unmapped -> ``"Unknown"``. Never raises.
    """
    if raw is None:
        return "Unknown"
    key = _key(raw)
    if not key:
        return "Unknown"
    return _RAW_TO_BUCKET.get(key, "Unknown")
