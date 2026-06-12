'''Deterministic seed schema from the SGO structured columns.

No LLM involved: node/relationship types here are facts the treated table
already carries (incident, subject + partner vehicle, company, location,
environmental conditions). Every property names its source column, and the
builder fails loudly if a referenced column is missing from
``docs/avird-sgo-database-data-dictionary/column_dictionary.json`` — the seed
must never silently drift from the data it claims to describe.

Concept discovery (discover.py) later merges narrative-discovered types into
this seed; the human approval pass adds competency questions.

Run from the repo root::

    python ontology/seed_schema.py        # writes ontology/schema/drafts/seed.yaml
'''
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from schema_model import (  # noqa: E402
    NodeType,
    OntologySchema,
    PropertySpec,
    RelationshipType,
    dump_schema,
)

REPO_ROOT = _HERE.parent
COLUMN_DICTIONARY = (REPO_ROOT / 'docs' / 'avird-sgo-database-data-dictionary'
                     / 'column_dictionary.json')
DEFAULT_OUT = _HERE / 'schema' / 'drafts' / 'seed.yaml'

SEED_VERSION = 'draft-seed'

# (property name, type, required, source columns) per node type. Property
# names are graph-side snake_case; source columns are treated-table columns
# and must exist in the column dictionary.
NODE_SPECS = {
    'Incident': {
        'description': 'One canonical crash incident (one row of the treated '
                       'table after Same-Incident dedupe).',
        'props': [
            ('incident_key', 'STRING', True, ['Same Incident ID', 'Report ID']),
            ('report_id', 'STRING', False, ['Report ID']),
            ('incident_date', 'DATE', False, ['incident_date']),
            ('incident_time', 'STRING', False, ['Incident Time (24:00)']),
            ('highest_injury_severity', 'STRING', False,
             ['Highest Injury Severity Alleged']),
            ('crash_with', 'STRING', False, ['Crash With']),
        ],
    },
    'Vehicle': {
        'description': 'A vehicle involved in the incident. The subject (ADS/'
                       'ADAS) vehicle is seeded from columns; crash-partner '
                       'vehicles come from CP columns or the narrative.',
        'props': [
            ('vehicle_key', 'STRING', True, ['VIN', 'Same Incident ID']),
            ('vin', 'STRING', False, ['VIN']),
            ('make', 'STRING', False, ['Make Clean']),
            ('model', 'STRING', False, ['Model Clean']),
            ('model_year', 'STRING', False, ['Model Year']),
            ('mileage', 'STRING', False, ['Mileage']),
            ('automation_system_type', 'STRING', False,
             ['automation_system_type']),
            ('automation_engaged', 'STRING', False,
             ['automation_engaged_clean']),
            ('precrash_speed_mph', 'FLOAT', False, ['sv_precrash_speed_mph']),
            ('precrash_movement', 'STRING', False,
             ['SV Pre-Crash Movement', 'CP Pre-Crash Movement']),
            ('is_subject_vehicle', 'BOOLEAN', False, ['VIN']),
        ],
    },
    'Company': {
        'description': 'Operating / reporting entity, canonicalized to '
                       'master_entity.',
        'props': [
            ('name', 'STRING', True, ['master_entity']),
            ('reporting_entity', 'STRING', False, ['Reporting Entity']),
        ],
    },
    'Location': {
        'description': 'Where the incident occurred: place plus roadway '
                       'context.',
        'props': [
            ('location_key', 'STRING', True, ['Same Incident ID', 'Report ID']),
            ('city', 'STRING', False, ['City']),
            ('state', 'STRING', False, ['State']),
            ('zip_code', 'STRING', False, ['Zip Code']),
            ('roadway_type', 'STRING', False, ['Roadway Type']),
            ('roadway_surface', 'STRING', False, ['Roadway Surface']),
            ('roadway_description', 'STRING', False, ['Roadway Description']),
            ('posted_speed_limit_mph', 'STRING', False,
             ['Posted Speed Limit (MPH)']),
        ],
    },
    'EnvironmentalCondition': {
        'description': 'A weather / lighting / roadway condition present at '
                       'the incident (one node per condition value, shared '
                       'across incidents).',
        'props': [
            ('name', 'STRING', True,
             ['weather_clear_clean', 'weather_rain_clean', 'Lighting']),
            ('category', 'STRING', False,
             ['weather_clear_clean', 'roadway_wet_surface_clean', 'Lighting']),
        ],
    },
}

REL_SPECS = {
    'INVOLVES': 'Incident involves a vehicle (subject or crash partner).',
    'OPERATED_BY': 'Vehicle is operated by a company (master_entity).',
    'REPORTED_BY': 'Incident was reported to NHTSA by a company.',
    'OCCURRED_AT': 'Incident occurred at a location.',
    'HAD_CONDITION': 'Environmental condition present during the incident.',
    'COLLIDED_WITH': 'Subject vehicle collided with the crash partner.',
}

PATTERNS = [
    ('Incident', 'INVOLVES', 'Vehicle'),
    ('Vehicle', 'OPERATED_BY', 'Company'),
    ('Incident', 'REPORTED_BY', 'Company'),
    ('Incident', 'OCCURRED_AT', 'Location'),
    ('Incident', 'HAD_CONDITION', 'EnvironmentalCondition'),
    ('Vehicle', 'COLLIDED_WITH', 'Vehicle'),
]


def load_column_names(dictionary_path=COLUMN_DICTIONARY):
    data = json.loads(Path(dictionary_path).read_text(encoding='utf-8'))
    return {c['name'] for c in data['columns']}


def build_seed_schema(dictionary_path=COLUMN_DICTIONARY):
    '''Build the seed OntologySchema, verifying every source column exists.'''
    known = load_column_names(dictionary_path)
    missing = sorted({
        col
        for spec in NODE_SPECS.values()
        for _, _, _, cols in [p for p in spec['props']]
        for col in cols
        if col not in known
    })
    if missing:
        raise ValueError(f'seed spec references unknown treated columns: {missing}')

    node_types = [
        NodeType(
            label=label,
            description=spec['description'],
            provenance='column',
            properties=[
                PropertySpec(
                    name=name, type=ptype, required=required,
                    description=f'source: {", ".join(cols)}',
                )
                for name, ptype, required, cols in spec['props']
            ],
        )
        for label, spec in NODE_SPECS.items()
    ]
    relationship_types = [
        RelationshipType(label=label, description=desc, provenance='column')
        for label, desc in REL_SPECS.items()
    ]
    return OntologySchema(
        version=SEED_VERSION,
        description='Deterministic seed schema from SGO structured columns. '
                    'Narrative-discovered types are merged in by discover.py; '
                    'competency questions are added at human approval.',
        node_types=node_types,
        relationship_types=relationship_types,
        patterns=PATTERNS,
        competency_questions=[],
    )


def main(argv=None):
    out = Path(argv[0]) if argv else DEFAULT_OUT
    schema = build_seed_schema()
    header = ('# Generated by ontology/seed_schema.py - do not hand-edit this '
              'draft;\n# the approval pass edits the merged v001 draft instead.')
    dump_schema(schema, out, header=header)
    print(f'wrote {out} ({len(schema.node_types)} node types, '
          f'{len(schema.relationship_types)} relationship types)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
