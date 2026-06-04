'''Tests for eda_utils_harmonize cross-version analogue harmonization.'''
import pandas as pd

import eda_utils_harmonize as hz


def _df(rows):
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------
def test_engagement_states():
    df = _df([
        {'Automation System Engaged?': 'ADS'},                 # early
        {'Engagement Status': 'Verified Engaged'},             # later
        {'Engagement Status': 'Verified Not Engaged'},         # later
        {'Engagement Status': 'Alleged Engaged'},              # later
        {'Engagement Status': 'Unknown - see Narrative'},      # later
        {'Automation System Engaged?': 'Unknown, see Narrative'},
    ])
    out = hz.harmonize_engagement(df)
    assert out['automation_engaged_clean'].tolist() == [
        'Engaged', 'Engaged', 'Not Engaged', 'Engaged', 'Unknown', 'Unknown',
    ]


def test_engagement_system_type():
    df = _df([
        {'Automation System Engaged?': 'ADS'},
        {'Automation System Engaged?': 'ADAS'},
        {'Automation System Engaged?': 'Unknown, see Narrative'},
    ])
    out = hz.harmonize_engagement(df)
    assert out['automation_system_type'].tolist() == ['ADS', 'ADAS', 'Unknown']


def test_engagement_column_missing_tolerance():
    # early-only frame: no 'Engagement Status' column at all
    early = _df([{'Automation System Engaged?': 'ADS'}])
    assert hz.harmonize_engagement(early)['automation_engaged_clean'].iloc[0] == 'Engaged'
    # later-only frame: no 'Automation System Engaged?' column at all
    later = _df([{'Engagement Status': 'Verified Engaged'}])
    out = hz.harmonize_engagement(later)
    assert out['automation_engaged_clean'].iloc[0] == 'Engaged'
    assert out['automation_system_type'].iloc[0] == 'Unknown'  # no source col


# ---------------------------------------------------------------------------
# Belted
# ---------------------------------------------------------------------------
def test_belted_all_belted_and_no_passengers():
    df = _df([
        {'SV Were All Passengers Belted?': 'Yes'},
        {'Were All Passengers Belted?': 'Subject Vehicle - All Belted'},
        {'SV Were All Passengers Belted?': 'No Passengers in Vehicle'},
        {'Were All Passengers Belted?': 'Subject Vehicle - No Passenger In Vehicle'},
        {'SV Were All Passengers Belted?': 'No, see Narrative'},
        {'Were All Passengers Belted?': 'Subject Vehicle - Not Belted - see Narrative'},
        {'SV Were All Passengers Belted?': 'Unknown'},
    ])
    out = hz.harmonize_belted(df)
    assert out['passengers_belted_clean'].tolist() == [
        'All Belted', 'All Belted', 'No Passengers', 'No Passengers',
        'Not Belted', 'Not Belted', 'Unknown',
    ]


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def test_weather_fog_smoke_cross_version_maps_same_flag():
    df = _df([
        {'Weather - Fog/Smoke': 'Y'},          # early
        {'Weather - Fog/Smoke/Haze': 'Y'},     # later
        {'Weather - Clear': 'Y'},              # neither fog
    ])
    out = hz.harmonize_weather(df)
    assert out['weather_fog_smoke_clean'].tolist() == [True, True, False]


def test_weather_partly_cloudy_folds_into_cloudy():
    df = _df([
        {'Weather - Cloudy': 'Y'},
        {'Weather - Partly Cloudy': 'Y'},
        {'Weather - Clear': 'Y'},
    ])
    out = hz.harmonize_weather(df)
    assert out['weather_cloudy_clean'].tolist() == [True, True, False]


def test_weather_later_only_categories_present():
    df = _df([{'Weather - Dust Storm': 'Y', 'Weather - Severe Hurricane': '',
               'Weather - Structure-Indoor': 'Y'}])
    out = hz.harmonize_weather(df)
    assert out['weather_dust_storm_clean'].iloc[0]
    assert not out['weather_severe_hurricane_clean'].iloc[0]
    assert out['weather_structure_indoor_clean'].iloc[0]


# ---------------------------------------------------------------------------
# Roadway
# ---------------------------------------------------------------------------
def test_roadway_wet_surface_cross_version():
    df = _df([
        {'Roadway Surface': 'Wet'},                      # early
        {'Roadway-Wet Surface Condition': 'Y'},          # later
        {'Roadway Surface': 'Dry'},                      # neither
    ])
    out = hz.harmonize_roadway(df)
    assert out['roadway_wet_surface_clean'].tolist() == [True, True, False]


def test_roadway_work_zone_and_traffic_incident():
    df = _df([
        {'Roadway Description': 'Work Zone'},
        {'Roadway-Work Zone': 'Y'},
        {'Roadway Description': 'Traffic Incident'},
        {'Roadway-Traffic Incident': 'Y'},
        {'Roadway Description': 'No Unusual Conditions'},
    ])
    out = hz.harmonize_roadway(df)
    assert out['roadway_work_zone_clean'].tolist() == [True, True, False, False, False]
    assert out['roadway_traffic_incident_clean'].tolist() == [False, False, True, True, False]


# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------
def test_lighting_maps_and_is_early_only():
    df = _df([
        {'Lighting': 'Daylight'},
        {'Lighting': 'Dark - Lighted'},
        {'Engagement Status': 'Verified Engaged'},   # later row, no Lighting value
    ])
    out = hz.harmonize_lighting(df)
    assert out['lighting_clean'].tolist()[:2] == ['Daylight', 'Dark - Lighted']
    assert pd.isna(out['lighting_clean'].iloc[2])    # later -> NULL


def test_lighting_later_only_frame_all_null():
    later = _df([{'Engagement Status': 'Verified Engaged'}])  # no Lighting column
    out = hz.harmonize_lighting(later)
    assert out['lighting_clean'].isna().all()


# ---------------------------------------------------------------------------
# harmonize_all
# ---------------------------------------------------------------------------
def test_harmonize_all_safe_on_empty_columns():
    # a frame with none of the source columns must not raise
    df = _df([{'Report ID': 'r1'}, {'Report ID': 'r2'}])
    out = hz.harmonize_all(df)
    for col in hz.harmonized_columns():
        assert col in out.columns
    assert len(out) == 2


def test_harmonize_all_additive_keeps_raw_columns():
    df = _df([{'Automation System Engaged?': 'ADS', 'Weather - Clear': 'Y'}])
    out = hz.harmonize_all(df)
    assert 'Automation System Engaged?' in out.columns   # raw retained
    assert 'Weather - Clear' in out.columns
    assert out['automation_engaged_clean'].iloc[0] == 'Engaged'
