'''Incident row -> neutral-adjuster prompt text.

Ports the old ``format_incident_for_llm`` field set to the treated-table
column names. The LLM judge sees the **narrative plus key structured columns**
(not the narrative alone): operating entity, date/time, location, crash-with,
pre-crash movements + speed, posted speed, roadway, lighting, weather, injury
severity, property damage.

Blank / missing / NaN columns are *skipped*, never rendered as the literal
string "None" (a value the model would otherwise treat as a fact). The
rendered text is what ``llm.py``'s content-addressed cache keys on, so this
must be byte-stable for a given row.
'''
from __future__ import annotations

NARRATIVE_COL = 'Narrative'

# (treated column, human-readable label). Order is the render order.
FIELDS: list[tuple[str, str]] = [
    ('Operating Entity', 'Operating Entity'),
    ('Incident Date', 'Incident Date'),
    ('Incident Time (24:00)', 'Incident Time'),
    ('City', 'City'),
    ('State', 'State'),
    ('Crash With', 'Crash With'),
    ('SV Pre-Crash Movement', 'AV Pre-Crash Movement'),
    ('CP Pre-Crash Movement', 'Other Party Pre-Crash Movement'),
    ('SV Precrash Speed (MPH)', 'AV Pre-Crash Speed (MPH)'),
    ('Posted Speed Limit (MPH)', 'Posted Speed Limit (MPH)'),
    ('Roadway Type', 'Roadway Type'),
    ('Roadway Description', 'Roadway Description'),
    ('Lighting', 'Lighting'),
    ('Highest Injury Severity Alleged', 'Highest Injury Severity'),
    ('Property Damage?', 'Property Damage'),
]

# Boolean-ish weather columns collapsed into a single "Weather" line.
WEATHER_COLS: dict[str, str] = {
    'Weather - Clear': 'Clear',
    'Weather - Snow': 'Snow',
    'Weather - Cloudy': 'Cloudy',
    'Weather - Fog/Smoke': 'Fog/Smoke',
    'Weather - Rain': 'Rain',
    'Weather - Severe Wind': 'Severe Wind',
}

_FALSEY = {'', 'no', 'false', '0', 'n', 'none', 'nan'}
_YES = {'y', 'yes', 'true', '1'}


def _cell(value) -> str | None:
    '''NaN/blank-tolerant cell read: a stripped string, or None when empty.'''
    if value is None:
        return None
    # pandas NaN is a float that is not equal to itself.
    if isinstance(value, float) and value != value:
        return None
    s = str(value).strip()
    if s == '' or s.lower() == 'nan':
        return None
    return s


def _yn(value: str) -> str:
    '''Expand the raw Y/N checkbox shorthand to readable words.'''
    low = value.lower()
    if low in _YES:
        return 'Yes'
    if low in _FALSEY:
        return 'No'
    return value


def _truthy(value) -> bool:
    cell = _cell(value)
    return cell is not None and cell.lower() not in _FALSEY


def format_incident(row: dict) -> str:
    '''Render one treated incident row into adjuster-prompt text.'''
    narrative = _cell(row.get(NARRATIVE_COL)) or 'No narrative provided.'
    parts = [f'Incident narrative:\n{narrative}']

    lines: list[str] = []
    for col, label in FIELDS:
        cell = _cell(row.get(col))
        if cell is not None:
            lines.append(f'- {label}: {_yn(cell)}')

    weather = [name for col, name in WEATHER_COLS.items() if _truthy(row.get(col))]
    if weather:
        lines.append(f'- Weather: {", ".join(weather)}')

    if lines:
        parts.append('Structured details:\n' + '\n'.join(lines))
    return '\n\n'.join(parts)
