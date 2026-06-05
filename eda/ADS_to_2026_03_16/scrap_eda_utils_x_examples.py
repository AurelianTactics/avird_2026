'''
Scrap file - paste cells into a notebook.

Each `# %%` block is one notebook cell.
'''

# %% imports + load
from pathlib import Path
import sys

import pandas as pd

EDA_DIR = Path('..').resolve()  # adjust to point at eda/
sys.path.insert(0, str(EDA_DIR))

from eda_utils_sgo import load_and_concat_csvs  # noqa: E402
import eda.eda_utils_co_impact as ex                        # noqa: E402

DATA_DIR = Path('../../data/nhtsa').resolve()
paths = [
    str(DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_to_2025_06_16.csv'),
    str(DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_2025_06_16_to_2026_03_16.csv'),
]
df = load_and_concat_csvs(paths)
print(df.shape)


# ===========================================================================
# 1. SV / CP contact-area pair co-occurrence
# ===========================================================================

# %% top SV-CP pairs across the full incident set
pairs = ex.contact_area_pairs(df, drop_no_pair=False)  # prints sv_only/cp_only/neither
pairs.head(15)

# %% same thing, ignoring the "Unknown" bucket
pairs_known = ex.contact_area_pairs(df, include_unknown=False)
pairs_known.head(15)

# %% matrix view (raw counts)
ex.contact_area_pair_matrix(df, include_unknown=False)

# %% matrix normalized within each SV row (% of CP impacts given an SV area)
ex.contact_area_pair_matrix(df, include_unknown=False, normalize='rows')

# %% heatmap visualization
import matplotlib.pyplot as plt  # noqa: E402
ex.plot_contact_area_pair_heatmap(df, include_unknown=False, normalize='rows',
                                  title='SV->CP contact areas (row %)')
plt.show()

# %% subset: same function works on an arbitrary slice
waymo = df[df['Reporting Entity'].str.contains('Waymo', na=False)]
ex.contact_area_pairs(waymo).head(10)

# %% subset: only injury rows
injury = df[df['Highest Injury Severity Alleged'].notna()
            & (df['Highest Injury Severity Alleged'].str.lower() != 'no injuries reported')]
print('injury rows:', injury.shape)
ex.contact_area_pairs(injury).head(10)


# ===========================================================================
# 2. Categorical consolidation
# ===========================================================================

# %% straight normalizers (no fuzzy matching, just deterministic cleanup)
state_clean = ex.apply_normalizer(df['State'], ex.normalize_state)
print('State unique  :', df['State'].nunique(dropna=False),
      '->', state_clean.nunique(dropna=False))

org_clean = ex.apply_normalizer(df['Operating Entity'], ex.normalize_org_name)
print('OpEnt unique  :', df['Operating Entity'].nunique(dropna=False),
      '->', org_clean.nunique(dropna=False))

permit_clean = ex.apply_normalizer(df['State or Local Permit'], ex.normalize_org_name)
print('Permit unique :', df['State or Local Permit'].nunique(dropna=False),
      '->', permit_clean.nunique(dropna=False))


# %% suggest a consolidation mapping (rapidfuzz under the hood)
sugg_make = ex.suggest_consolidation(
    df['Make'], score_cutoff=85, normalizer=ex.normalize_org_name,
)
sugg_make.head(30)

# %% turn suggestions into a mapping, then apply
mapping_make = ex.mapping_from_suggestions(sugg_make)
print('mapping size:', len(mapping_make))
make_clean = ex.apply_mapping(df['Make'], mapping_make)
ex.consolidation_diff(df['Make'], make_clean)

# %% override with a hand-curated mapping (case-insensitive lookup)
manual = {
    'JAGUAR': 'Jaguar',
    'JLR': 'Jaguar',         # JLR == Jaguar Land Rover
    'TOYOTA': 'Toyota',
    'HYUNDAI': 'Hyundai',
    'TESLA': 'Tesla',
    'ZOOX': 'Zoox',
}
make_manual = ex.apply_mapping(df['Make'], manual,
                               normalizer=ex.normalize_org_name)
make_manual.value_counts(dropna=False).head(15)


# %% Investigating Agency: usually want a higher cutoff and a top_k cap
sugg_agency = ex.suggest_consolidation(
    df['Investigating Agency'], score_cutoff=88, top_k=80,
    normalizer=ex.normalize_org_name,
)
# Look at non-trivial groups (>1 member)
grp_sizes = sugg_agency.groupby('canonical').size()
multi = grp_sizes[grp_sizes > 1].index
sugg_agency[sugg_agency['canonical'].isin(multi)]


# %% combine Make + Model into one consolidated field
make_model = ex.combine_columns(df, ['Make', 'Model'],
                                normalizer=ex.normalize_org_name,
                                name='make_model')
make_model.value_counts(dropna=False).head(15)


# ===========================================================================
# 3. Workflow recipe: normalize -> suggest -> review -> apply
# ===========================================================================

# %%
col = 'Operating Entity'

# step 1: light deterministic clean
clean = ex.apply_normalizer(df[col], ex.normalize_org_name)

# step 2: fuzzy-suggest the rest
sugg = ex.suggest_consolidation(clean, score_cutoff=88)

# step 3: turn into a mapping; eyeball before applying
auto_map = ex.mapping_from_suggestions(sugg)
print('auto mapping size:', len(auto_map))

# step 4: optionally splice in manual fixes that the LLM/fuzzy missed
manual_overrides = {
    # 'cruise': 'Cruise',
    # 'waymo': 'Waymo',
}
final_map = {**auto_map, **manual_overrides}

# step 5: apply
df['Operating Entity Clean'] = ex.apply_mapping(clean, final_map)
df['Operating Entity Clean'].value_counts(dropna=False).head(15)
