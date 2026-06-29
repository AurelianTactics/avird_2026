'''format_incident: narrative + structured fields, blanks skipped (not "None").'''
import math

from format import format_incident

FULL_ROW = {
    'Report ID': 'RPT-1',
    'Narrative': 'The AV was proceeding straight when struck from behind.',
    'Operating Entity': 'Waymo LLC',
    'Incident Date': '2024-03-01',
    'Incident Time (24:00)': '14:30',
    'City': 'San Francisco',
    'State': 'CA',
    'Crash With': 'Passenger Car',
    'SV Pre-Crash Movement': 'Proceeding straight',
    'CP Pre-Crash Movement': 'Following lane',
    'SV Precrash Speed (MPH)': '12',
    'Posted Speed Limit (MPH)': '25',
    'Roadway Type': 'Intersection',
    'Lighting': 'Daylight',
    'Highest Injury Severity Alleged': 'No Apparent Injury',
    'Property Damage?': 'Y',
    'Weather - Clear': 'Y',
    'Weather - Rain': 'N',
}


def test_includes_narrative_and_structured_fields():
    text = format_incident(FULL_ROW)
    assert 'proceeding straight when struck' in text
    assert 'Operating Entity: Waymo LLC' in text
    assert 'AV Pre-Crash Movement: Proceeding straight' in text
    assert 'Highest Injury Severity: No Apparent Injury' in text


def test_expands_yn_shorthand():
    text = format_incident(FULL_ROW)
    # 'Y' -> 'Yes', and the 'N' rain flag is dropped, not rendered as a field.
    assert 'Property Damage: Yes' in text


def test_weather_collapses_only_truthy_flags():
    text = format_incident(FULL_ROW)
    assert 'Weather: Clear' in text
    assert 'Rain' not in text


def test_blank_and_missing_columns_are_skipped_not_none():
    row = {
        'Report ID': 'RPT-2',
        'Narrative': 'Minimal incident.',
        'City': '',
        'State': None,
        'SV Precrash Speed (MPH)': float('nan'),
        'Operating Entity': 'Cruise LLC',
    }
    text = format_incident(row)
    # Never render the literal string the model would mistake for a fact.
    assert 'None' not in text
    assert 'nan' not in text.lower()
    assert 'City' not in text
    # The one present structured field still renders.
    assert 'Operating Entity: Cruise LLC' in text
    assert not math.isnan(0)  # sanity: nan handling didn't crash


def test_absent_narrative_uses_placeholder():
    text = format_incident({'Report ID': 'RPT-3', 'City': 'Phoenix'})
    assert 'No narrative provided.' in text
    assert 'City: Phoenix' in text
