"""Structured filter schema + allow-list validation (U1).

This module is the **security boundary** for the natural-language query path
(plan KTD 3). The LLM only ever produces *candidate* free-text values; this
module resolves them against allow-listed known values sourced from the data
layer. Only a resolved value — always one of the known constants, never the raw
candidate — survives into a `DerivedFilter`. Unresolvable candidates are
**dropped**, not guessed, so a malicious string (`"Waymo'; DROP TABLE"`) can
never be surfaced as an identifier.

Mirrors the allow-list-resolution discipline in `app/data.py` (`SORT_COLUMNS`):
the resolved value is always a constant from a known set, the raw input is
never interpolated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..severity import BUCKET_ORDER
from ..severity import normalize as normalize_severity

# US state name -> 2-letter code (50 + DC). The treated build's `State Clean`
# column holds the 2-letter code (via the EDA `normalize_state`); we map a raw
# name candidate to a code, then confirm the code against the known-state set.
# Lean copy of the EDA map — `eda/` (pandas) must never be imported here.
_STATE_NAME_TO_CODE: dict[str, str] = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


@dataclass(frozen=True)
class DerivedFilter:
    """A validated, allow-list-resolved filter the rest of W5 speaks in.

    Every populated field holds a known constant (an exact `master_entity`, a
    2-letter `State Clean` code, or a `severity.BUCKET_ORDER` label) — never a
    raw caller-supplied string. v1 dimensions only; date-range is deferred.
    """

    entity: str | None = None
    state: str | None = None
    severity_bucket: str | None = None

    def is_empty(self) -> bool:
        return self.entity is None and self.state is None and self.severity_bucket is None

    def as_dict(self) -> dict[str, str]:
        """The resolved dimensions only (drops `None`), for `applied_filter`."""
        out: dict[str, str] = {}
        if self.entity is not None:
            out["entity"] = self.entity
        if self.state is not None:
            out["state"] = self.state
        if self.severity_bucket is not None:
            out["severity"] = self.severity_bucket
        return out


@dataclass(frozen=True)
class Resolution:
    """Outcome of `resolve`: the validated filter plus what resolved/dropped."""

    filter: DerivedFilter
    resolved: dict[str, str] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _resolve_entity(candidate: str, known_entities: Iterable[str]) -> str | None:
    """Match a candidate to a known `master_entity`, case-insensitively.

    Exact (case-insensitive) match first; otherwise the candidate must be a
    substring *of* a known value (e.g. "merc" -> "Mercedes Benz"). The reverse
    direction is intentionally not allowed: it would let "Waymo'; DROP TABLE"
    match "Waymo". The resolved value is always the known constant.
    """
    cand = candidate.lower()
    if not cand:
        return None
    known = sorted(known_entities)
    for entity in known:
        if entity.lower() == cand:
            return entity
    # Substring of a known value -> resolve to the shortest (closest) match.
    contains = [e for e in known if cand in e.lower()]
    if contains:
        return min(contains, key=len)
    return None


def _resolve_state(candidate: str, known_states: Iterable[str]) -> str | None:
    """Map a name or code candidate to a known 2-letter `State Clean` code."""
    known = {s.upper() for s in known_states}
    up = candidate.upper()
    if up in known:
        return up
    code = _STATE_NAME_TO_CODE.get(candidate.lower())
    if code is not None and code in known:
        return code
    return None


def _resolve_severity(candidate: str) -> str | None:
    """Resolve a candidate to a `BUCKET_ORDER` label, or `None` if unmapped.

    Reuses `severity.normalize`; an unmapped string normalizes to ``"Unknown"``,
    which we treat as *no constraint* (a "filter on Unknown" is not useful and
    is the unmapped-drop case the tests pin down).
    """
    bucket = normalize_severity(candidate)
    return bucket if bucket != "Unknown" else None


def resolve(
    raw: Mapping[str, object] | None,
    *,
    known_entities: Iterable[str],
    known_states: Iterable[str],
) -> Resolution:
    """Resolve free-text candidate values into a validated `DerivedFilter`.

    `raw` carries optional ``entity`` / ``state`` / ``severity`` candidates
    (e.g. from the LLM or query params). The known-value sets are supplied by
    the data layer (`IncidentData.fetch_known_values`) — never trusted from the
    caller. Candidates that do not resolve to a known value are dropped and
    recorded in `Resolution.dropped`; never raised.
    """
    raw = raw or {}
    resolved: dict[str, str] = {}
    dropped: list[str] = []

    entity_raw = _clean(raw.get("entity"))
    if entity_raw:
        match = _resolve_entity(entity_raw, known_entities)
        if match is not None:
            resolved["entity"] = match
        else:
            dropped.append("entity")

    state_raw = _clean(raw.get("state"))
    if state_raw:
        match = _resolve_state(state_raw, known_states)
        if match is not None:
            resolved["state"] = match
        else:
            dropped.append("state")

    severity_raw = _clean(raw.get("severity"))
    if severity_raw:
        bucket = _resolve_severity(severity_raw)
        if bucket is not None:
            resolved["severity"] = bucket
        else:
            dropped.append("severity")

    filt = DerivedFilter(
        entity=resolved.get("entity"),
        state=resolved.get("state"),
        severity_bucket=resolved.get("severity"),
    )
    return Resolution(filter=filt, resolved=resolved, dropped=dropped)


__all__ = [
    "BUCKET_ORDER",
    "DerivedFilter",
    "Resolution",
    "resolve",
]
