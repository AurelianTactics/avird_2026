---
title: "feat: Injury Reported target analysis utils + notebook"
type: feat
status: active
date: 2026-05-22
origin: docs/brainstorms/nhtsa-crash-project-requirements.md
---

# feat: Injury Reported target analysis utils + notebook

## Summary

Build a three-file EDA utils layer for binary-classification analysis against the `Injury Reported` target (load/treat/target construction reuses the existing pipeline used by `eda/ADS_to_2026_03_16/04_eda_target_exploration.ipynb`). New `eda/eda_utils_target_univariate.py` covers per-target value-counts / describes plus AUC, KS, mutual information, chi-square, and correlation rankings; `eda/eda_utils_target_models.py` covers LightGBM random forest, scikit-learn logistic regression, and LightGBM gradient boosting with SHAP feature importance; `eda/eda_utils_target_interactions.py` covers two-way target-rate heatmaps and a stub shallow decision tree. A single notebook `eda/ADS_to_2026_03_16/06_eda_target_injury_2026.ipynb` exercises all three modules end-to-end on the deduped + treated `treated_df` and writes CSV / PNG artifacts to `artifacts_target_injury/<section>/`.

---

## Problem Frame

`eda/ADS_to_2026_03_16/04_eda_target_exploration.ipynb` already constructs seven candidate targets via `eda_utils_targets.add_all_targets`, but there is no downstream analysis layer that takes a chosen target and produces a portable signal-ranking + quick-model + interaction summary. `eda_to_do.md` (lines 56–62) lists this work explicitly — "against target (displays, percents), univariate (AUC, KS, mutual information, chi2, correlation), quick RF / LR / lightgbm test (with SHAP), maybe interactions (heatmap & 2 stub tree)" — and singles out `Injury Reported` (and `SV Speed >= 15`) as the targets worth keeping. The user wants this scoped to `Injury Reported` only for v1: imbalanced (~9.5% positives, 222 / 2344 rows), grounded in `Highest Injury Severity Alleged`, and meaningful enough to support the P2 severity-classification track in the project brainstorm (R14, see origin: `docs/brainstorms/nhtsa-crash-project-requirements.md`).

---

## Requirements

- R1. Three new utils files exist at the repo `eda/` root following the existing `eda_utils_x.py` convention: `eda_utils_target_univariate.py`, `eda_utils_target_models.py`, `eda_utils_target_interactions.py`. Each is independently importable from the notebook via `sys.path.append('..')`.
- R2. The notebook `eda/ADS_to_2026_03_16/06_eda_target_injury_2026.ipynb` loads the SGO CSVs, runs `dedupe_same_incident` + `apply_all_treatments`, attaches every candidate target via `eda_utils_targets.add_all_targets`, and selects `Injury Reported` as the single target column for the rest of the notebook.
- R3. Basic-EDA section: for each feature column, the notebook produces (a) value counts segmented by target value (0 vs 1) and (b) numeric `describe()` segmented by target value, written as CSV artifacts.
- R4. Univariate-ranking section: produces a single tidy DataFrame `[feature, dtype, n_non_null, auc, auc_direction, ks, mutual_info, chi2_p, correlation]` ranking every feature column against the binary target, plus per-feature CSV artifacts. NaN handling is explicit (not silently dropped); each metric documents which subset of feature dtypes it accepts. The `auc` column reports the discrimination magnitude `max(auc, 1 - auc)` for ranking; `auc_direction` carries the sign (`+1` when higher feature values predict positive class, `-1` otherwise, `NaN` for categorical features) so direction is recoverable.
- R5. Modeling section: three model fits against the full feature set (the user-confirmed approach is "use full feature set, let LGBM/SHAP rank") — (a) LightGBM random forest (`boosting_type='rf'`), (b) scikit-learn logistic regression with one-hot-encoded categoricals + numeric standardization, (c) LightGBM gradient boosting. Each reports holdout AUC + PR-AUC; LightGBM gradient boosting also emits a SHAP-based feature-importance table + summary plot. Class imbalance is handled with `class_weight='balanced'` / `is_unbalance=True` (documented; no SMOTE in v1).
- R6. Two-way-interactions section: a heatmap util that renders target rate over (feat_i × feat_j) cells with cell counts, plus a stub `DecisionTreeClassifier(max_depth=3)` fit that prints the tree text and saves a tree PNG. The top-K features (default K=8) are passed in by the notebook — the util does not pick them itself.
- R7. All artifacts persist to `eda/ADS_to_2026_03_16/artifacts_target_injury/<section>/` (sections: `basic_eda/`, `univariate/`, `models/`, `interactions/`) so results survive a kernel restart.
- R8. `lightgbm` and `shap` are installed into the existing main env (`~/claude_code_repos/my-uv-envs/avird-2026-eda/`, Python 3.14) via `uv pip install` if both publish 3.14 wheels compatible with numpy 2.4.4 / pandas 3.0.2 / scikit-learn 1.8.0. If either does not, fall back to creating a new sidecar env `~/claude_code_repos/my-uv-envs/avird-2026-eda-target/` on Python 3.12 mirroring the existing `avird-2026-eda-spacy/` sidecar pattern. In either case, the chosen env's `requirements.txt` records the installed packages for reproducibility. The existing main env's pins are preserved.
- R9. Each utils function takes well-defined inputs (DataFrame + column lists, or numpy arrays) and returns a pandas DataFrame / matplotlib Axes / dict-of-DataFrames — matching the existing `eda_utils_basic.py` / `eda_utils_topics.py` contract. No class hierarchy.
- R10. Pytest coverage for the univariate and interactions util files exists under `eda/tests/` matching the existing `test_eda_utils_*.py` pattern. The models utils file is exercised end-to-end through the notebook (matching the spaCy plan's choice for runtime-heavy utils).

---

## Scope Boundaries

- Other candidate targets (`No Injury Reported`, `Multi Class Injury`, `Binary Airbag Deployed`, `Binary Vehicle Towed`, `SV Speed >= N`, `Potential Non-Trivial Accident`) — explicitly out of scope. User asked for `Injury Reported` only.
- Hyperparameter sweeping / cross-validation grids. `Quick` models per the user request — fixed reasonable defaults, single holdout split.
- Calibration analysis, reliability curves, prediction-thresholding study, cost-sensitive evaluation.
- Stacking / ensembling / blending across the three models.
- SHAP for the logistic regression or RF — only the gradient-boosting fit gets SHAP per R5.
- Narrative-text features (BERTopic / spaCy / embeddings columns). The features are the tabular SGO columns only.
- Permutation importance, drop-column importance, partial dependence plots — backlog.
- Production-grade model serialization, model registry, MLflow / W&B integration (R16 in origin — deferred to a separate P2 planning pass).
- Refactoring `eda_utils_targets.py` or any upstream utility. Read-only consumer.

### Deferred to Follow-Up Work

- Same analysis applied to `SV Speed >= 15` (also listed in `eda_to_do.md` line 58). Mirrors this plan once `Injury Reported` lands; a follow-up plan can reuse all three util files with only a different target column passed in.
- Multi-class severity (`Multi Class Injury`) classification — needs OvR/multinomial LR + multi-class SHAP plumbing; separate plan.
- Pushing the resulting importance rankings or interaction findings to the Next.js site — site-side work belongs in the P1 EDA-page or P2 model writeup plan.

---

## Context & Research

### Relevant Code and Patterns

- `eda/eda_utils_targets.py` — owns target construction. `make_injury_reported_target(df)` (lines 115-131) returns the binary series. `add_all_targets(df)` (lines 282-307) appends every candidate target under user-facing names; the notebook uses the `'Injury Reported'` column from that output.
- `eda/eda_utils_sgo.py::load_and_concat_csvs` + `eda/eda_utils_dedupe.py::dedupe_same_incident` + `eda/eda_utils_treatment.py::apply_all_treatments` — the load/treat pipeline. The new notebook copies the preamble verbatim from `04_eda_target_exploration.ipynb` cells 36464cee / 93da2370 / e412b197.
- `eda/eda_utils_basic.py` — establishes the "function takes a DataFrame + column name, returns a tidy DataFrame or a matplotlib Axes" contract: `value_counts_top`, `plot_top_values`, `crosstab_pct`, `missing_summary`. The new univariate util mirrors this shape.
- `eda/eda_utils_topics.py` — establishes `_clean_series` / `_build_stopword_set` helpers and `(result_df, doc_topic, doc_index)` return tuples. The interactions util borrows the "return a DataFrame plus optional matplotlib Axes" idea from this file.
- `eda/eda_utils_spacy.py` (plan: `docs/plans/2026-05-20-001-feat-spacy-narrative-eda-plan.md`) — closest sibling plan/file for sizing the work. Its `_docbin` caching idea is not needed here (analysis is fast), but its per-section artifact layout and notebook structure are the template for U10/U11.
- `eda/tests/conftest.py` + `eda/tests/test_eda_utils_keybert.py` — establishes the pytest fixture style for the new test files.
- `eda/ADS_to_2026_03_16/04_eda_target_exploration.ipynb` — origin notebook for load/treat/target construction (cells 36464cee → 126532b2).
- `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb` — closest structural sibling for the new notebook (Section 0 setup, Section 1 load+treat, then per-capability sections with artifacts).

### Institutional Learnings

- Two CSV files have different schemas (older has `CP/SV Any Air Bags Deployed?`, newer has compound `Any Air Bags Deployed?`). `eda_utils_targets._safe_col` (lines 81-85) returns an all-NaN series for missing columns. Feature-listing in the new utils must use the same defensive pattern — never assume a column exists.
- The treated DataFrame has free-text columns (`Narrative`, `Narrative - Same Incident ID`, `Investigating Officer Name/Phone/Email`, redacted markers `[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION]`, `XXX`). These belong on a hardcoded drop-list for feature analysis. Likewise drop ID-like columns (`Report ID`, `Report Version`, `VIN`, `Serial Number`, `Same Vehicle ID`, `Same Incident ID`, `Latitude`, `Longitude`, `Address`, `Zip Code`).
- `Highest Injury Severity Alleged` is the source of the target — drop it from the feature set to avoid leakage. Likewise drop the other six generated target columns (`No Injury Reported`, `Multi Class Injury`, `Binary Airbag Deployed`, `Binary Vehicle Towed`, `SV Speed >= 15`, `Potential Non-Trivial Accident`) — they correlate with `Injury Reported` for definitional reasons.
- Class imbalance is ~9.5% positives. AUC + PR-AUC on a stratified holdout is the right pair; raw accuracy is not informative.
- Many columns have >50% missingness (e.g., `Notice Received Date`, `Lighting`, `Property Damage?` only exist in the older schema). Univariate utilities must report `n_non_null` per metric so the reader can sanity-check small-sample scores.
- The repo uses Python 3.14 in the main env (`avird-2026-eda`). LightGBM ships Python 3.14 wheels as of 2026; verify pin before install. SHAP also publishes 3.14 wheels for recent releases.

### External References

- LightGBM Python API: https://lightgbm.readthedocs.io/en/stable/Python-API.html — covers `boosting_type='rf'` for the random forest variant and the sklearn-compatible `LGBMClassifier` interface used here.
- LightGBM categorical features handling: https://lightgbm.readthedocs.io/en/stable/Advanced-Topics.html#categorical-feature-support — LightGBM accepts pandas `category`-dtype columns directly. The notebook converts the object-dtype categoricals once before fitting.
- SHAP TreeExplainer docs: https://shap.readthedocs.io/en/latest/example_notebooks/tabular_examples/tree_based_models/Census%20income%20classification%20with%20LightGBM.html — canonical recipe for LightGBM + SHAP feature ranking.
- scikit-learn univariate selection: `sklearn.feature_selection.mutual_info_classif`, `sklearn.feature_selection.chi2`, `sklearn.metrics.roc_auc_score`. Standard library — already pinned.
- KS statistic via `scipy.stats.ks_2samp` (separates positive-class and negative-class distributions of a continuous feature). scipy is already a transitive dep of sklearn.

---

## Key Technical Decisions

- **Three files, not one** (user-confirmed): `eda_utils_target_univariate.py` (basic value-counts/describes + univariate ranking), `eda_utils_target_models.py` (RF/LR/LGBM + SHAP), `eda_utils_target_interactions.py` (heatmap + stub tree). Cleaner separation than a single ~1000-line file; matches the per-domain split already in the repo.
- **Try main env first, sidecar as fallback** (user-confirmed update on 2026-05-22): Install `lightgbm` and `shap` into the main `avird-2026-eda` env via `uv pip install`. If the install fails because either package lacks a Python 3.14 wheel compatible with the existing numpy 2.4.4 / pandas 3.0.2 / sklearn 1.8.0 pins, fall back to a new sidecar `avird-2026-eda-target` on Python 3.12 — same pattern as `avird-2026-eda-spacy` (see `docs/plans/2026-05-20-001-feat-spacy-narrative-eda-plan.md`). Do NOT downgrade the main env's pins to force a 3.14 install; the sidecar route is cheaper and safer.
- **Use full feature set, let SHAP rank** (user-confirmed): All eligible columns enter the model fits. Univariate analysis still runs in parallel but does not pre-gate model inputs. SHAP-importance ordering from the LightGBM gradient boosting fit drives the K-feature selection for the interactions section, with the top-K passed explicitly into the interactions util.
- **One target only — `Injury Reported`**: Hardcode the target column name in the notebook; pass it explicitly into every util. Avoids over-generalizing utils before the second target is wanted. The `SV Speed >= 15` follow-up will just re-call the same utils with a different target column.
- **Feature schema lives in the utils, not the notebook**: A shared `default_feature_columns(df, target_col)` helper (in `eda_utils_target_univariate.py`) returns the list of eligible feature columns after hardcoded drop-lists (free text, IDs, the seven target columns themselves). Every util that needs a feature list either accepts an explicit `feature_cols=` arg or falls back to this helper.
- **Numeric vs categorical dispatch**: The univariate-ranking util introspects each feature's dtype: numeric columns (`number` dtype after `pd.to_numeric(errors='coerce')`) get AUC + KS + correlation; categorical columns get chi-square. Mutual information runs on both (sklearn handles mixed types via `discrete_features='auto'` after label encoding). Missing values are filled with a `__MISSING__` sentinel for categorical, and kept as NaN with explicit per-metric masking for numeric.
- **Stratified holdout, no CV**: 80/20 stratified train/test split, `random_state=0`. Cross-validation is deferred — the user said "quick." Reproducibility seed is `0` everywhere for parity with `eda_utils_topics.py`.
- **LightGBM categorical handling**: Cast object-dtype features to pandas `category` dtype once at the top of the modeling section and pass `categorical_feature='auto'`. Avoids hand-rolled label encoding for the LightGBM fits. The logistic regression fit gets its own `OneHotEncoder` + `StandardScaler` pipeline.
- **SHAP scope**: TreeExplainer on the trained `LGBMClassifier` gradient-boosting model only. Produces a `(feature, mean_abs_shap)` ranking DataFrame and a beeswarm/bar `summary_plot` PNG. RF + LR get sklearn `coef_` / `feature_importances_` rankings instead, kept lightweight.
- **Imbalance handling = built-in weights, not SMOTE**: `LGBMClassifier(is_unbalance=True)` and `LogisticRegression(class_weight='balanced')`. Avoids adding `imbalanced-learn` as a dep.
- **Tests live under `eda/tests/`**: Match the existing pattern (`test_eda_utils_keybert.py`, etc.). The models util is notebook-exercised; the univariate + interactions utils get unit tests on small synthetic frames.

---

## Open Questions

### Resolved During Planning

- Util file organization: three files (user-confirmed).
- Env: main `avird-2026-eda` (user-confirmed).
- Feature selection for modeling: full feature set + SHAP ranking (user-confirmed).
- Target: `Injury Reported` only (user-stated in request).
- Class imbalance: handled via model-side weights, no resampling.
- Notebook location and number: `eda/ADS_to_2026_03_16/06_eda_target_injury_2026.ipynb` (next number after 05).

### Deferred to Implementation

- Exact `min_data_in_leaf` / `num_leaves` for LightGBM on 2344 rows. Start with `num_leaves=15, min_data_in_leaf=20, n_estimators=200` and tune downward only if the model overfits on the small holdout.
- Whether `master_entity` is too high-cardinality to one-hot for LR cleanly. The notebook prints `nunique()` per categorical at the top of the modeling section; if any column exceeds ~30 distinct values it gets re-bucketed (rare-bucket = "other") before LR.
- The exact top-K for the interactions section: notebook default `K=8`; user can override after seeing the SHAP ranking. Below ~6 the heatmap matrix becomes too sparse; above ~12 the (K choose 2) cell grid becomes hard to read.
- Whether to also generate a precision-recall curve PNG per model. Default yes if it falls out for free; do not add a separate util for it.
- Whether `Highest Injury Severity Alleged` itself should be shown as a sanity-check univariate score (perfect AUC, perfect MI — it is the target's parent). Default: leave it out by hardcoding it in the drop-list; mention in the README/markdown if useful as an integrity check.
- **Co-observed crash-outcome features in the feature set** (`Was Any Vehicle Towed?`, `CP/SV Was Vehicle Towed?`, `Any Air Bags Deployed?`, `CP/SV Any Air Bags Deployed?`, `SV Precrash Speed (MPH)`). These are NOT pre-incident features — they are co-measurements on the same SGO form as the injury severity. Default behavior (per U2 drop-list): keep them. Decide at implementation: (a) drop them all from `DEFAULT_DROP_COLS` so the SHAP ranking surfaces pre-incident signal only, OR (b) keep them and run an explicit contrast pass (second model fit on a `pre_incident_feature_cols = [c for c in feature_cols if c not in CO_OBSERVED_OUTCOME_COLS]` subset) and present both SHAP rankings side-by-side. The notebook should make this choice visible to the reader either way.
- **`prepare_modeling_frame` rare-bucketing scope.** U5 currently describes rare-bucketing as "LR-pathway-only" but returns a single `X` consumed by all three models. Decide at implementation: (a) move rare-bucketing INSIDE the `fit_logistic` `ColumnTransformer` step so `prepare_modeling_frame` returns one un-bucketed X that all three models share (recommended — keeps LightGBM on full cardinality per the Risks-table promise), OR (b) return two X frames (`X_native`, `X_lr_safe`) from `prepare_modeling_frame` and have U11 Section 6 pass each to the appropriate model. Option (a) is simpler and matches the documented intent.
- **Two-way heatmap default `max_levels`.** With K=8 features and ~2 expected positives per cell at `max_levels=10`, most cells are statistically uninformative. Decide at implementation: (a) lower default `max_levels` to 5 (so 25 cells per pair, ~9 expected positives/cell), OR (b) keep `max_levels=10` but raise the `min_cell_count` threshold to gate on expected positives (e.g., `min_cell_count = max(10, ceil(3 / positive_rate)) ≈ 32` for the injury target), OR (c) add a visual indicator (hatch fill) for low-confidence cells. Option (b) is the most defensible.
- **SHAP-vs-LightGBM-gain disagreement.** U6's test scenario asserts the two rankings agree on the synthetic frame but does not pin a Spearman threshold and does not say what to do when real data disagrees. Decide at implementation: (a) drop the agreement assertion and document that SHAP and gain measure different things, presenting both rankings side-by-side in the notebook; (b) state a concrete threshold (Spearman ≥ 0.6 on synthetic; log only on real data). Option (a) is more honest.

---

## Implementation Units

- U1. **Install `lightgbm` + `shap` — main env first, Python 3.12 sidecar fallback**

**Goal:** Get LightGBM and SHAP importable from the notebook. Prefer the existing `avird-2026-eda` main env (Python 3.14) so there's no env-switching friction; fall back to a fresh `avird-2026-eda-target` Python 3.12 sidecar if the main env can't accommodate the packages.

**Requirements:** R8

**Dependencies:** None

**Files:**
- Primary path (main env): Modify `~/claude_code_repos/my-uv-envs/avird-2026-eda/requirements.txt` — append `lightgbm>=4.5` and `shap>=0.46` after install succeeds, for reproducibility.
- Fallback path (sidecar): Create `~/claude_code_repos/my-uv-envs/avird-2026-eda-target/.venv/` (via `uv venv --python 3.12 --prompt avird-2026-eda-target`) and `~/claude_code_repos/my-uv-envs/avird-2026-eda-target/requirements.txt` (copied from the main env's `requirements.txt`, then `lightgbm>=4.5` / `shap>=0.46` appended).

**Approach:**

*Primary path — main env (Python 3.14):*
- Activate the main env: `source ~/claude_code_repos/my-uv-envs/avird-2026-eda/.venv/Scripts/activate`.
- `uv pip install lightgbm shap`. uv resolves into the active env; no need to re-install from `requirements.txt`, which would churn the pinned numpy / pandas / sklearn lines.
- Verify both packages import: `python -c "import lightgbm as lgb; import shap; print(lgb.__version__, shap.__version__)"`.
- On success, append `lightgbm>=4.5` and `shap>=0.46` to the main env's `requirements.txt` as a record of what landed. Use lower-bound pins consistent with the existing embeddings-track entries.

*Fallback path — Python 3.12 sidecar (`avird-2026-eda-target`):*
- Trigger this path when the main-env install fails because `lightgbm` or `shap` lacks a Python 3.14 wheel, OR resolves to a version below the minimum API floor (LightGBM >=4.0, SHAP >=0.45). Do NOT downgrade the main env's numpy / pandas / sklearn pins to force a 3.14 install.
- Mirror the `avird-2026-eda-spacy` sidecar pattern from `docs/plans/2026-05-20-001-feat-spacy-narrative-eda-plan.md` (U1 there).
- From `~/claude_code_repos/my-uv-envs/avird-2026-eda-target/`: `uv venv --python 3.12 --prompt avird-2026-eda-target`.
- Copy `~/claude_code_repos/my-uv-envs/avird-2026-eda/requirements.txt` verbatim into the new sidecar, then append `lightgbm>=4.5` and `shap>=0.46`. If a main-env pin (e.g., numpy / pandas) refuses to resolve on 3.12, relax that single line with an inline `#` comment explaining why — do not blanket-downgrade.
- Activate and install: `source ~/claude_code_repos/my-uv-envs/avird-2026-eda-target/.venv/Scripts/activate`, then `uv pip install -r requirements.txt`.
- Update `eda/ADS_to_2026_03_16/06_eda_target_injury_2026.ipynb`'s Section 0 markdown cell (U10) so the activation command points at the sidecar env, not the main one.

*API floor (both paths):*
- LightGBM `>=4.0` for `is_unbalance` + `boosting_type='rf'` + native pandas `category`-dtype handling via `categorical_feature='auto'`.
- SHAP `>=0.45` for `TreeExplainer(model)` returning explanations whose `.values` array carries the documented shape contract used in U6.
- If either floor is missed, surface explicitly — U5/U6 are written against these APIs.

**Patterns to follow:**
- Existing env layout at `~/claude_code_repos/my-uv-envs/avird-2026-eda/` and `~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/` (requirements.txt at root, `.venv` sibling).
- The spaCy sidecar plan's U1 (`docs/plans/2026-05-20-001-feat-spacy-narrative-eda-plan.md`) for the Python 3.12 fallback recipe.

**Test scenarios:**
- Happy path (main env): `uv pip install lightgbm shap` succeeds in the activated `avird-2026-eda` env without source-build fallbacks; both packages import; `numpy / pandas / sklearn __version__` still reports `2.4.4 / 3.0.2 / 1.8.0`.
- Happy path (sidecar fallback): If main-env install fails, the new 3.12 sidecar installs cleanly, both packages import, and `nlp = lightgbm.LGBMClassifier(); shap.TreeExplainer` resolve.
- Edge case: A main-env pin refuses to resolve on 3.12 — relax that one pin inline with a `#` comment, do not blanket-downgrade.
- Error path: Both paths fail (no 3.14 wheel AND 3.12 sidecar install errors on a transitive dep) — surface the exact resolution error so the user can decide whether to try a different LightGBM / SHAP version pin or open the loop with the user.

**Verification:**
- Whichever env is chosen, both `lightgbm` and `shap` import cleanly inside the activated env.
- Existing notebooks (e.g., `03_eda_basic_topics_2026.ipynb`) still run their first import cell without regressions.
- The notebook in U10/U11 documents which env to activate in its Section 0 markdown cell.

**Patterns to follow:**
- Existing line-format in the env's `requirements.txt` (one package per line, lower-bound pins for newer entries).

**Test scenarios:**
- Happy path: `python -c "import lightgbm as lgb; import shap; print(lgb.__version__, shap.__version__)"` prints versions cleanly.
- Happy path: `python -c "import numpy, pandas, sklearn; print(numpy.__version__, pandas.__version__, sklearn.__version__)"` still prints the pre-existing versions (2.4.4 / 3.0.2 / 1.8.0).
- Error path: No Python 3.14 wheel available for the chosen `lightgbm` / `shap` version — surface the conflict, pin to the latest version that does have a 3.14 wheel, and add a one-line comment explaining why.

**Verification:**
- Both packages import without warnings inside the activated `avird-2026-eda` env.
- Existing notebooks (e.g., `03_eda_basic_topics_2026.ipynb`) still run their first import cell without regressions.

---

- U2. **Create `eda/eda_utils_target_univariate.py` with feature schema + basic-EDA helpers**

**Goal:** Stand up the file with its module docstring, the shared `default_feature_columns` helper, and the per-target value-counts / describes functions used by the basic-EDA section.

**Requirements:** R1, R3, R9

**Dependencies:** None

**Files:**
- Create: `eda/eda_utils_target_univariate.py`
- Test: `eda/tests/test_eda_utils_target_univariate.py` (added in U4 alongside the ranking functions)

**Approach:**
- Module docstring explains the three function groups (feature schema, basic-EDA-by-target, univariate ranking) and the `(takes DataFrame + target column + feature list, returns DataFrame)` contract.
- `DEFAULT_DROP_COLS`: module-level tuple grouping free-text + ID + always-leakage columns (the static drop-list). Free-text / narrative: `Narrative`, `Narrative - Same Incident ID`, `Narrative - CBI?`, `Weather - Other Text`, `Source - Other Text`. Address / location: `Address`, `City`, `Zip Code`, `Latitude`, `Longitude`. Officer / contact: `Investigating Officer Name`, `Investigating Officer Phone`, `Investigating Officer Email`. Identifiers: `Report ID`, `Report Version`, `VIN`, `VIN Decoded`, `Serial Number`, `Same Vehicle ID`, `Same Incident ID`. Other derived target columns produced by `add_all_targets`: `No Injury Reported`, `Multi Class Injury`, `Binary Airbag Deployed`, `Binary Vehicle Towed`, `Potential Non-Trivial Accident` (the target the user picks for *this* run stays in the frame as the target; the others are dropped to avoid cross-target leakage). Comment the rationale per group inline.
- `TARGET_SOURCE_COLS`: module-level dict mapping each `eda_utils_targets` target-column name to the source column(s) it is computed from (read straight off `eda_utils_targets.INJURY_COL` / `AIRBAG_COLS` / `TOWED_COLS` / `SV_SPEED_COL` / `CRASH_WITH_COL`). For `'Injury Reported'`, the source is `('Highest Injury Severity Alleged',)`. For `'Binary Airbag Deployed'`, the source is `('Any Air Bags Deployed?', 'CP Any Air Bags Deployed?', 'SV Any Air Bags Deployed?')`. The mapping is the single source of truth — when targets gain or lose source columns upstream, this dict updates and every feature-list call inherits the correct drop set.
- `default_feature_columns(df, target_col, drop_cols=DEFAULT_DROP_COLS, extra_drop=())`: returns the eligible feature list as `[c for c in df.columns if c not in (set(drop_cols) | set(TARGET_SOURCE_COLS.get(target_col, ())) | {target_col} | set(extra_drop))]`. This guarantees the columns that *make up the current target* are never in the feature set — directly addressing the obvious leakage. The target column itself is also always dropped.
- The static drop-list above does NOT cover the post-hoc co-observed crash-outcome source columns of *other* derived targets — for the `Injury Reported` run, `TARGET_SOURCE_COLS['Injury Reported']` only drops `Highest Injury Severity Alleged`, leaving `Was Any Vehicle Towed?`, `Any Air Bags Deployed?`, `SV Precrash Speed (MPH)`, etc. eligible as features. Those are NOT columns that make up the `Injury Reported` target (they make up the other derived targets), but they are observed at the same time as the injury severity and may correlate via co-occurrence rather than causation. See `Open Questions → Deferred to Implementation` for the contrast-pass option if the SHAP ranking ends up dominated by them.
- Pre-implementation guard: when `default_feature_columns` is first called inside the notebook, print the schema of `treated_df` to confirm every drop-list entry actually exists in the frame. Columns named in the drop-list but missing from the frame are tolerated silently (defensive), but the print surfaces the column-name drift cheaply so the implementer can fix the drop-list rather than the cell silently doing nothing.
- `default_feature_columns(df, target_col, drop_cols=DEFAULT_DROP_COLS, extra_drop=())`: returns the list of remaining columns. The target column is always dropped even if not in `drop_cols`.
- `value_counts_by_target(df, feature_col, target_col, dropna=False, normalize=False)`: returns a long-form DataFrame `[feature_value, target_value, count, share_within_target]` so the user can read positive-rate by feature value at a glance.
- `describe_by_target(df, feature_col, target_col)`: returns the pandas `describe()` output of `feature_col` segmented by `target_col`, as a tidy DataFrame.
- `basic_eda_to_csvs(df, target_col, feature_cols, out_dir)`: orchestrator that calls the two above for every `feature_col` and writes `out_dir/<feature>__value_counts.csv` and `out_dir/<feature>__describe.csv`. Returns the list of paths written. NaN-safe column names (replace `/` with `__` in filenames). Creates `out_dir` (and any missing parents) via `Path(out_dir).mkdir(parents=True, exist_ok=True)` on entry.
- **Directory-creation convention for every artifact-writing helper in all three new utils files**: each helper that takes an `out_dir` or `out_path` is responsible for ensuring its parent exists (`Path(out_path).parent.mkdir(parents=True, exist_ok=True)` for single-file writers, `Path(out_dir).mkdir(parents=True, exist_ok=True)` for orchestrators). The notebook does NOT pre-create the subfolder tree; helpers own it. This applies to `basic_eda_to_csvs` (U2), `shap_summary_plot` (U6), `pairwise_heatmaps_to_png` (U7), `stub_tree_png` (U8). Stated once here so U6/U7/U8 do not need to restate it.

**Patterns to follow:**
- `eda_utils_basic.py::value_counts_top` for the tidy-DataFrame return shape.
- `eda_utils_targets.py::_safe_col` (lines 81-85) for missing-column tolerance.

**Test scenarios:**
- Happy path: `default_feature_columns(df, 'Injury Reported')` on the treated `treated_df` excludes every name in `DEFAULT_DROP_COLS` that is present, plus the target itself (`'Injury Reported'`), plus every entry in `TARGET_SOURCE_COLS['Injury Reported']` (i.e., `'Highest Injury Severity Alleged'`).
- Happy path: `default_feature_columns(df, 'Binary Airbag Deployed')` excludes the three airbag source columns from `TARGET_SOURCE_COLS['Binary Airbag Deployed']` (`'Any Air Bags Deployed?'`, `'CP Any Air Bags Deployed?'`, `'SV Any Air Bags Deployed?'`) — proves the dynamic source-drop generalizes to the deferred follow-up targets.
- Happy path: For any target name not in `TARGET_SOURCE_COLS`, `default_feature_columns` falls back to just the static drop-list + target column (no crash, no silent extra drops).
- Happy path: `value_counts_by_target` on a categorical feature returns one row per (feature_value, target_value) pair, share-within-target sums to 1.0 per target group within float tolerance.
- Happy path: `describe_by_target` on a numeric feature returns a DataFrame with both `0` and `1` columns (one per target value) and `count`/`mean`/`std`/... rows.
- Edge case: `value_counts_by_target` on a feature with a single distinct value yields a 2-row DataFrame (one per target value) and does not raise.
- Edge case: `default_feature_columns(df, 'Injury Reported', extra_drop=('Make Clean',))` excludes `Make Clean` in addition to the defaults.
- Edge case: `basic_eda_to_csvs` creates `out_dir` if it does not exist.
- Error path: `default_feature_columns(df, target_col='Not A Column')` raises `KeyError` with a clear message naming the missing column.

**Verification:**
- Notebook `import eda_utils_target_univariate as ut; ut.default_feature_columns(treated_df, 'Injury Reported')` returns a list of >50 column names.

---

- U3. **Add univariate ranking helpers (AUC, KS, MI, chi2, correlation) to `eda_utils_target_univariate.py`**

**Goal:** One-call `rank_features(df, target_col, feature_cols=None)` that produces the master ranking DataFrame.

**Requirements:** R1, R4, R9

**Dependencies:** U2

**Files:**
- Modify: `eda/eda_utils_target_univariate.py`

**Approach:**
- Internal helpers:
    - `_score_auc(series, target)`: numeric features only. Coerce via `pd.to_numeric(errors='coerce')`; drop rows where the feature is NaN; compute `raw_auc = sklearn.metrics.roc_auc_score(target_mask, series)`. Returns `(auc_magnitude, auc_direction, n_used)` where `auc_magnitude = max(raw_auc, 1 - raw_auc)` and `auc_direction = +1 if raw_auc >= 0.5 else -1`. Splitting magnitude from direction lets the ranking sort by discrimination strength while keeping the sign recoverable for downstream interpretation.
    - `_score_ks(series, target)`: numeric features only. `scipy.stats.ks_2samp(series[target==1], series[target==0])`. Returns `(ks_stat, n_used)`.
    - `_score_mutual_info(series, target)`: works for both numeric and categorical via `sklearn.feature_selection.mutual_info_classif`. Categorical features get label-encoded with `__MISSING__` sentinel + `pd.Categorical(...).codes`. Returns `(mi, n_used)`.
    - `_score_chi2(series, target)`: categorical features only. Builds a contingency via `pd.crosstab` and calls `scipy.stats.chi2_contingency`. Returns `(p_value, chi2_stat, n_used)`. Skips features with fewer than 2 distinct non-NaN values.
    - `_score_correlation(series, target)`: numeric features only. Spearman rank correlation (robust to skew; the target is 0/1 so this is essentially the point-biserial-as-rank). Returns `(rho, n_used)`.
- `rank_features(df, target_col, feature_cols=None, kind='auto')`: orchestrator. For each feature, decides numeric vs categorical from its dtype (with object/string treated as categorical), runs the applicable scorers, and returns a tidy `[feature, dtype, n_non_null, auc, auc_direction, ks, mutual_info, chi2_p, correlation]` DataFrame sorted by mutual information descending. Column order matches R4.
- All scorers return `np.nan` (not raise) when not applicable to that feature type — the ranking row carries the gap and the reader can see which metrics apply.
- Per-feature debug printouts are NOT included by default (would flood the notebook). A `verbose=False` flag toggles them.

**Patterns to follow:**
- `eda_utils_targets.py::_safe_col` for missing-column tolerance.
- `eda_utils_basic.py::missing_summary` for the "return a tidy DataFrame ranked by a single column" shape.

**Test scenarios:**
- Happy path: `rank_features` on a synthetic frame with one perfectly-correlated numeric feature returns `auc ≈ 1.0`, `correlation ≈ 1.0`, high `mutual_info`, `chi2_p == NaN` for that row.
- Happy path: `rank_features` on a synthetic frame with one perfectly-correlated categorical feature returns `chi2_p ≈ 0`, high `mutual_info`, `auc == NaN`.
- Happy path: `_score_auc` on a numeric feature where the relationship is *inverted* (e.g., higher feature -> lower target rate) returns `auc_magnitude = max(auc, 1 - auc)` AND `auc_direction = -1`. A positively-correlated feature returns the same `auc_magnitude` with `auc_direction = +1`. Categorical-feature rows in `rank_features` carry `auc_direction = NaN`.
- Edge case: A feature with all NaN values produces a row of NaN scores and `n_non_null = 0`, does not raise.
- Edge case: A feature with one distinct value (zero variance) produces NaN AUC / KS / correlation and is flagged with `n_non_null = N` so the reader sees it was checked.
- Edge case: A binary numeric column (e.g., `Source - Telematics` style 0/1) is scored on both numeric (AUC, correlation) and categorical (chi2) tracks. Document this in the docstring.
- Integration: `rank_features(treated_df, 'Injury Reported')` returns a DataFrame with one row per non-dropped column, sorted by `mutual_info` desc, with no all-NaN row that should have scored.
- Error path: `rank_features(df, 'NotATarget')` raises `KeyError` with a clear message.

**Verification:**
- Notebook section produces `artifacts_target_injury/univariate/feature_ranking.csv` with top rows showing recognizable predictors (e.g., contact-area columns, `Crash With`, `master_entity`, `SV Precrash Speed (MPH)`).

---

- U4. **Pytest coverage for `eda_utils_target_univariate.py`**

**Goal:** Lock in the univariate scoring contracts with a small synthetic-frame test suite under `eda/tests/`.

**Requirements:** R10

**Dependencies:** U2, U3

**Files:**
- Create: `eda/tests/test_eda_utils_target_univariate.py`

**Approach:**
- Module-level fixture builds a 100-row synthetic DataFrame with: a perfectly-correlated numeric column, a perfectly-correlated categorical column, an inversely-correlated numeric column, a noise numeric column, an all-NaN column, a single-value column, and the binary target.
- Test the `default_feature_columns` drop-list contract by constructing a frame containing every name in `DEFAULT_DROP_COLS` and asserting all are removed.
- Test each `_score_*` helper individually against the synthetic frame.
- Test `rank_features` end-to-end: row order matches `mutual_info` desc, all expected columns are present, NaN handling matches the documented contract.

**Patterns to follow:**
- `eda/tests/test_eda_utils_keybert.py` for the per-fixture / per-function test style.
- `eda/tests/conftest.py` for any shared synthetic-frame fixtures (extend if useful; otherwise local to this test file).

**Test scenarios:**
- Happy path: All synthetic-frame tests pass on a fresh checkout.
- Edge case: The single-value column produces NaN AUC/KS/correlation without raising, and the test asserts that.
- Edge case: The all-NaN column produces all-NaN scores and `n_non_null == 0`, and the test asserts that.
- Integration: `rank_features` row order is asserted explicitly — the perfectly-correlated columns rank above the noise column.

**Verification:**
- `pytest eda/tests/test_eda_utils_target_univariate.py -q` passes.

---

- U5. **Create `eda/eda_utils_target_models.py` with LightGBM RF + Logistic Regression**

**Goal:** Stand up the modeling utils file with the two simpler model fits (LightGBM RF and sklearn LR) and shared train/test split + evaluation helpers.

**Requirements:** R1, R5, R9

**Dependencies:** U1, U2 (consumes `default_feature_columns`)

**Files:**
- Create: `eda/eda_utils_target_models.py`

**Approach:**
- Module docstring explains the three model fits (RF / LR / GBM+SHAP), the shared evaluation contract, and the imbalance-handling stance (built-in weights, no SMOTE).
- `prepare_modeling_frame(df, target_col, feature_cols=None, categorical_threshold=30)`: returns `(X, y, categorical_cols, numeric_cols)`. Casts object-dtype features to `category` dtype; rare-buckets categories whose support is below `categorical_threshold` distinct values for the LR pathway. Numeric features get NaN -> column-median imputation; categorical features get `__MISSING__` -> sentinel level.
- `stratified_split(X, y, test_size=0.2, random_state=0)`: thin wrapper over `train_test_split(stratify=y)` so every model uses the same split.
- `fit_lgbm_rf(X_train, y_train, categorical_cols, n_estimators=200, num_leaves=15, min_data_in_leaf=20, random_state=0)`: `LGBMClassifier(boosting_type='rf', is_unbalance=True, bagging_fraction=0.8, bagging_freq=1, feature_fraction=0.8, ...)`. Returns the trained model.
- `fit_logistic(X_train, y_train, categorical_cols, numeric_cols, C=1.0, max_iter=2000, random_state=0)`: builds a sklearn `Pipeline` with `ColumnTransformer(OneHotEncoder(handle_unknown='ignore') on categoricals, StandardScaler() on numerics)` + `LogisticRegression(class_weight='balanced')`. Returns the fitted pipeline.
- `evaluate_classifier(model, X_test, y_test, name)`: returns a dict `{name, auc, pr_auc, n_test, n_pos_test}`. Uses `predict_proba(...)[:, 1]`.
- `feature_importance_lgbm(model, feature_cols)`: returns a DataFrame `[feature, gain, split]` sorted by gain desc.
- `feature_importance_logistic(model, feature_cols)`: returns a DataFrame `[feature, coef, abs_coef]` sorted by abs_coef desc, after expanding the one-hot-encoded columns back to their parent feature with a `__<value>` suffix.

**Patterns to follow:**
- `eda_utils_topics.py`'s pattern of returning `(model, eval_df, ...)` so the notebook can hold onto the model object.
- `eda_utils_basic.py::value_counts_top`'s tidy-DataFrame return shape for the importance tables.

**Test scenarios:**
- Happy path: `prepare_modeling_frame` on a synthetic frame returns `X` with all object columns cast to `category`, NaN-filled numerics, and lists `categorical_cols` + `numeric_cols` correctly.
- Happy path: `fit_lgbm_rf` + `evaluate_classifier` on the synthetic frame produces `0 < auc <= 1.0` and the expected dict keys.
- Happy path: `fit_logistic` + `evaluate_classifier` returns AUC > 0.5 on a separable synthetic frame.
- Edge case: A categorical column with cardinality > `categorical_threshold` is rare-bucketed to "other" in the LR path but kept verbatim in the LightGBM path (LightGBM tolerates high-cardinality categoricals natively).
- Edge case: `evaluate_classifier` on a degenerate model that predicts the same probability for every row reports `auc == 0.5` and `pr_auc == base_rate`, no crash.
- Integration: The two model fits use the same train/test split (asserted by reusing the `stratified_split` output).
- Error path: `prepare_modeling_frame(df, target_col='NotATarget')` raises `KeyError`.

**Verification:**
- Notebook section runs the two models end-to-end on `treated_df` + `Injury Reported`, prints holdout AUC + PR-AUC for each.

---

- U6. **Add LightGBM gradient boosting + SHAP to `eda_utils_target_models.py`**

**Goal:** The third model fit (`boosting_type='gbdt'`) plus the SHAP-based importance table and summary plot.

**Requirements:** R1, R5, R9

**Dependencies:** U5

**Files:**
- Modify: `eda/eda_utils_target_models.py`

**Approach:**
- `fit_lgbm_gbm(X_train, y_train, categorical_cols, n_estimators=200, num_leaves=15, learning_rate=0.05, min_data_in_leaf=20, random_state=0)`: `LGBMClassifier(boosting_type='gbdt', is_unbalance=True, ...)`. Returns the trained model.
- `shap_importance(model, X_sample, max_display=20)`: builds a `shap.TreeExplainer(model)`, calls `explainer(X_sample)` (the modern `Explanation`-object API in SHAP >=0.45), then extracts the positive-class slice: for binary classification on a SHAP `Explanation` with `.values` shape `(n_rows, n_features, 2)`, slice `[:, :, 1]`; for the legacy list-of-arrays return (`[shap_neg, shap_pos]`), take the second element. Aggregate `mean_abs_shap = np.abs(positive_class_shap).mean(axis=0)` per feature. Returns a DataFrame `[feature, mean_abs_shap]` sorted desc. `X_sample` defaults to the full holdout in the notebook but the util accepts a downsample for speed. Document explicitly: SHAP for the *positive* class (injury=1); negating signs flip the interpretation.
- `shap_summary_plot(model, X_sample, out_path, plot_type='bar', max_display=20)`: wraps `shap.summary_plot(..., show=False)` then `plt.savefig(out_path)`. Two plot variants supported: `'bar'` (mean |SHAP|) and `'beeswarm'` (per-row distribution).
- Document explicitly in the docstring: SHAP for the gradient-boosting fit only (per R5). RF and LR rely on their own importance tables from U5.

**Patterns to follow:**
- `eda_utils_topics.py`'s shape for the importance table returns.
- `eda_utils_nlp.py::plot_word_cloud` for the "write a PNG and return the path" plotting helper.

**Test scenarios:**
- Happy path: `fit_lgbm_gbm` on the synthetic frame returns a model with `predict_proba` shape `(n_test, 2)`.
- Happy path: `shap_importance(model, X_test)` returns a DataFrame whose total `mean_abs_shap` is positive and whose top feature on the synthetic frame matches the planted-signal column.
- Happy path: `shap_summary_plot(model, X_test, tmp_path / 'shap.png', plot_type='bar')` writes a PNG with non-zero size.
- Edge case: `shap_importance` on a feature that LightGBM never split on (i.e., zero importance) returns `mean_abs_shap == 0.0` for that row.
- Edge case: `X_sample` smaller than the trained-on feature count still works (`shap.TreeExplainer` tolerates downsamples).
- Integration: The SHAP-ranked top-K matches the LightGBM `gain` ranking from U5's `feature_importance_lgbm` on rough order (Spearman correlation between the two rankings is high on the synthetic frame).

**Verification:**
- Notebook section produces `artifacts_target_injury/models/shap_importance.csv` and `artifacts_target_injury/models/shap_summary_bar.png`.

---

- U7. **Create `eda/eda_utils_target_interactions.py` with two-way heatmap helper**

**Goal:** Render a target-rate heatmap over two feature columns with cell counts overlaid.

**Requirements:** R1, R6, R9

**Dependencies:** U2 (consumes `default_feature_columns` indirectly through notebook usage)

**Files:**
- Create: `eda/eda_utils_target_interactions.py`

**Approach:**
- Module docstring explains the two function groups (heatmap, stub tree) and that "two-way" means pairwise.
- `target_rate_pivot(df, feat_a, feat_b, target_col, max_levels=10, fillna='__MISSING__')`: builds a pivot of mean(target) by (feat_a, feat_b). For numeric features, bin into `max_levels` quantile bins (using `pd.qcut(..., duplicates='drop')`). For categorical features, keep the top `max_levels` by frequency and bucket the rest as `__OTHER__`. Returns a tuple `(rate_pivot, count_pivot)`. NaN cells (where the cell has zero count) stay NaN in `rate_pivot` and are rendered as blank in the heatmap.
- `plot_target_rate_heatmap(df, feat_a, feat_b, target_col, ax=None, annot='both', cmap='RdBu_r', max_levels=10)`: calls `target_rate_pivot` then renders via `matplotlib.pyplot.imshow` (no seaborn dependency required since the repo already pins matplotlib). `annot='rate'` shows the percentage in each cell; `annot='count'` shows N; `annot='both'` shows `"rate% (n=count)"`. Returns the `Axes`.
- `pairwise_heatmaps_to_png(df, feature_cols, target_col, out_dir, max_levels=10)`: iterates over all pairs `(i, j)` in `feature_cols` (`i < j`), calls `plot_target_rate_heatmap` for each, saves `out_dir/<feat_a>__x__<feat_b>.png`. Returns the list of paths written. NaN-safe filenames.
- Suppress pairs where the joint count is below a configurable threshold (default 10) to avoid noisy heatmaps.

**Patterns to follow:**
- `eda_utils_basic.py::crosstab_pct` for the pivot-of-percentages shape.
- `eda_utils_basic.py::plot_top_values` for the "matplotlib Axes in, matplotlib Axes out" convention.

**Test scenarios:**
- Happy path: `target_rate_pivot` on a synthetic frame returns a `(rate_pivot, count_pivot)` tuple whose cells sum back to the row count and whose rate is in [0, 1].
- Happy path: `plot_target_rate_heatmap` returns an `Axes` whose `get_title()` mentions both feature names and the target.
- Happy path: `pairwise_heatmaps_to_png(['a', 'b', 'c'], ...)` writes `(3 choose 2) = 3` PNG files.
- Edge case: A pair where every joint cell has count < threshold is skipped (returns no PNG for that pair) and the function logs which pair was skipped.
- Edge case: Numeric features with constant values (zero variance) skip the pair gracefully.
- Edge case: `max_levels=2` on a categorical with 50 distinct values keeps the top 2 and buckets the rest as `__OTHER__`.

**Verification:**
- Notebook section produces `artifacts_target_injury/interactions/pairwise_heatmaps/*.png` for the top-K pairs.

---

- U8. **Add stub decision-tree helper to `eda_utils_target_interactions.py`**

**Goal:** Fit a tiny `DecisionTreeClassifier(max_depth=3)` over the top-K features and render the tree as both text and a PNG.

**Requirements:** R1, R6, R9

**Dependencies:** U7

**Files:**
- Modify: `eda/eda_utils_target_interactions.py`

**Approach:**
- `fit_stub_tree(df, feature_cols, target_col, max_depth=3, min_samples_leaf=20, random_state=0)`: builds `X` from `feature_cols` (object -> `category` codes; numeric -> NaN-filled with median), fits `sklearn.tree.DecisionTreeClassifier(max_depth=max_depth, class_weight='balanced', ...)`, returns `(tree, X_columns)` where `X_columns` matches the column order used for fitting.
- `stub_tree_text(tree, feature_names)`: returns `sklearn.tree.export_text(tree, feature_names=...)` as a string.
- `stub_tree_png(tree, feature_names, out_path, class_names=('no_injury', 'injury'))`: renders via `sklearn.tree.plot_tree` (matplotlib-only, no graphviz dep), saves PNG. Returns the path.
- Document explicitly: this is a stub, not a model — purpose is interaction discovery (which splits beat which), not prediction.

**Patterns to follow:**
- `eda_utils_topics.py`'s `(model, ...)` return shape for the fitted tree.

**Test scenarios:**
- Happy path: `fit_stub_tree` on a synthetic frame returns a fitted `DecisionTreeClassifier` whose `get_depth() <= max_depth`.
- Happy path: `stub_tree_text` returns a non-empty string containing at least one feature name from `feature_cols`.
- Happy path: `stub_tree_png` writes a PNG with non-zero size.
- Edge case: All features constant -> tree fits but `get_depth() == 0`; helpers do not crash.
- Edge case: `max_depth=1` produces a single split that names exactly one feature.
- Integration: The tree's top-1 split feature is also present in the top-3 features by LGBM `gain` (loose assertion on the synthetic frame).

**Verification:**
- Notebook section produces `artifacts_target_injury/interactions/stub_tree.png` + `artifacts_target_injury/interactions/stub_tree.txt`.

---

- U9. **Pytest coverage for `eda_utils_target_interactions.py`**

**Goal:** Lock in the heatmap-pivot and stub-tree contracts with a small synthetic-frame test suite.

**Requirements:** R10

**Dependencies:** U7, U8

**Files:**
- Create: `eda/tests/test_eda_utils_target_interactions.py`

**Approach:**
- Reuse the synthetic-frame fixture style from `test_eda_utils_target_univariate.py` (factor a shared fixture into `eda/tests/conftest.py` only if both files end up using identical frames; otherwise local).
- Test `target_rate_pivot` cell-rate math.
- Test `plot_target_rate_heatmap` `Axes` return.
- Test `pairwise_heatmaps_to_png` file-count.
- Test `fit_stub_tree` depth + non-empty text export.
- No PNG byte-comparison — assert non-zero file size only.

**Patterns to follow:**
- `eda/tests/test_eda_utils_keybert.py` for the per-function test style.

**Test scenarios:**
- Happy path: `target_rate_pivot` returns rate matrix in `[0, 1]`.
- Happy path: `pairwise_heatmaps_to_png(['a', 'b', 'c'], ...)` writes 3 files.
- Happy path: `fit_stub_tree(max_depth=2)` returns a tree with `get_depth() <= 2`.
- Edge case: A pair with all cells below threshold writes 0 files and returns an empty path list (or marks the pair as skipped).

**Verification:**
- `pytest eda/tests/test_eda_utils_target_interactions.py -q` passes.

---

- U10. **Create the notebook `06_eda_target_injury_2026.ipynb` (Sections 0-3: setup, load, basic EDA, univariate)**

**Goal:** First half of the notebook — environment setup, load + treat + targets, basic EDA against `Injury Reported`, univariate ranking.

**Requirements:** R2, R3, R4, R7

**Dependencies:** U2, U3

**Files:**
- Create: `eda/ADS_to_2026_03_16/06_eda_target_injury_2026.ipynb`
- Create: `eda/ADS_to_2026_03_16/artifacts_target_injury/` (directory created at runtime)

**Approach:**
- Section 0 — Setup: `sys.path.append('..')`, `%load_ext autoreload`, `%autoreload 2`, imports including `eda_utils_target_univariate` (and downstream sections will add `eda_utils_target_models`, `eda_utils_target_interactions`). Markdown cell pointing at the env activation command from `eda/CLAUDE.md`.
- Section 1 — Load & treat data: copy the preamble from `04_eda_target_exploration.ipynb` cells 36464cee → e412b197 verbatim. Call `eda_utils_targets.add_all_targets(treated_df, sv_speed_threshold=15)` then set `TARGET_COL = 'Injury Reported'` and verify positive rate (~9.5%) and row count (~2344) with a printout.
- Section 2 — Define the feature schema: call `feature_cols = ut.default_feature_columns(treated_df, TARGET_COL)`. Print the length and head of the list so the reader can sanity-check what's in / what's out. Save the list to `artifacts_target_injury/feature_cols.txt`.
- Section 3 — Basic EDA: call `ut.basic_eda_to_csvs(treated_df, TARGET_COL, feature_cols, out_dir='artifacts_target_injury/basic_eda')`. Display a few sample value-counts + describes inline for spot-checking (e.g., for `master_entity`, `Crash With`, `SV Precrash Speed (MPH)`).
- Section 4 — Univariate ranking: call `ranking = ut.rank_features(treated_df, TARGET_COL, feature_cols)`. Display the full table (top-by-MI). Save to `artifacts_target_injury/univariate/feature_ranking.csv`. Display the top-20 by each metric (AUC, KS, MI, chi2_p, |correlation|) as quick side-by-side comparison.

**Patterns to follow:**
- `03_eda_basic_topics_2026.ipynb` cell structure (imports + autoreload + load/treat preamble + per-section markdown headings).
- `04_eda_target_exploration.ipynb` for the load/treat/target preamble specifically.

**Test scenarios:**
- Test expectation: none — notebooks are exercised by running end-to-end, matching the spaCy plan's convention.

**Verification:**
- Section 1 prints `len(treated_df) == 2344` and `treated_df[TARGET_COL].mean() ≈ 0.095`.
- Section 4 produces `artifacts_target_injury/univariate/feature_ranking.csv` with one row per feature.

---

- U11. **Extend the notebook with Sections 5-7 (models + interactions)**

**Goal:** Second half of the notebook — modeling, SHAP, two-way interactions.

**Requirements:** R2, R5, R6, R7

**Dependencies:** U5, U6, U7, U8, U10

**Files:**
- Modify: `eda/ADS_to_2026_03_16/06_eda_target_injury_2026.ipynb`

**Approach:**
- Section 5 — Modeling prep: call `prepare_modeling_frame(treated_df, TARGET_COL, feature_cols)` → `(X, y, cat_cols, num_cols)`. Print cardinality of every categorical column. Call `stratified_split(X, y)`.
- Section 6 — Three model fits: fit + evaluate LightGBM RF (U5), LR (U5), LightGBM GBM (U6). Stack the three eval dicts into a single comparison DataFrame. Save `artifacts_target_injury/models/eval_summary.csv`. Save per-model importance tables — LightGBM RF `gain`, LR `abs_coef`, LightGBM GBM `gain`. SHAP only for the GBM fit: save `shap_importance.csv` + `shap_summary_bar.png`.
- Section 7 — Two-way interactions: pick the top-K (K=8) features by SHAP `mean_abs_shap`. Call `pairwise_heatmaps_to_png(treated_df, top_k_features, TARGET_COL, out_dir='artifacts_target_injury/interactions/pairwise_heatmaps')`. Fit + render the stub tree: `fit_stub_tree(treated_df, top_k_features, TARGET_COL, max_depth=3)`. Save `stub_tree.png` + `stub_tree.txt`.
- Closing markdown — Notes: brief recap of (a) top SHAP features, (b) any interaction pairs that surprised, (c) backlog items observed during the run (mirrors the `## Notes` cell at the bottom of `03_eda_basic_topics_2026.ipynb`). Optional: a one-line "next target to mirror this on" note pointing at the deferred `SV Speed >= 15` follow-up.

**Patterns to follow:**
- `03_eda_basic_topics_2026.ipynb`'s `## Notes` closing markdown cell.
- The spaCy plan's per-section artifact-saving convention.

**Test scenarios:**
- Test expectation: none — notebook end-to-end run is the verification.

**Verification:**
- All three model AUCs print in Section 6 and are written to `eval_summary.csv`.
- `artifacts_target_injury/interactions/` contains the heatmap PNGs and the stub-tree artifacts.

---

- U12. **Tick off `eda_to_do.md` and document the artifact tree**

**Goal:** Mark the relevant items done in `eda/ADS_to_2026_03_16/eda_to_do.md` and capture the artifact layout where future-me will look.

**Requirements:** R7 (artifact-tree visibility)

**Dependencies:** U10, U11

**Files:**
- Modify: `eda/ADS_to_2026_03_16/eda_to_do.md`

**Approach:**
- Tick the "against target (displays, percents), univariate (AUC, KS, mutual information, chi2, overall score, correlation), quick RF / LR / lightbm test (with SHAP), maybe interactions (heatmap & 2 stub tree), brainstowrm some more" item (line 60) as DONE for the `Injury Reported` target. Leave the `SV Speed >= 15` part flagged as remaining.
- Add a one-paragraph pointer below the ticked item naming the three util files and the notebook path, plus the artifact subfolder structure.
- Do not refactor anything else in the to-do file; leave existing items intact.

**Patterns to follow:**
- Existing DONE-marker convention in `eda_to_do.md` (e.g., lines 9-26 use `* DONE` prefix).

**Test scenarios:**
- Test expectation: none — documentation-only change.

**Verification:**
- `git diff eda/ADS_to_2026_03_16/eda_to_do.md` shows the ticked items and the pointer paragraph.

---

## System-Wide Impact

- **Interaction graph:** Reads `treated_df` from the existing `eda_utils_sgo` + `eda_utils_dedupe` + `eda_utils_treatment` pipeline and the candidate-target columns from `eda_utils_targets.add_all_targets`. No changes to those modules. Adds three new utils files in `eda/`, two new test files in `eda/tests/`, one new notebook in `eda/ADS_to_2026_03_16/`, and one new artifact directory in the same place.
- **Error propagation:** Failures in `lightgbm` / `shap` install (U1) surface in the first notebook import cell. Failures in `default_feature_columns` (missing target column) surface as `KeyError`. Failures in any single feature's univariate scoring fall through to `NaN` in the ranking row rather than aborting the whole run — documented behavior.
- **State lifecycle risks:** No persistent state. Artifacts overwrite on re-run (deliberate — the notebook is the source of truth, not a checkpoint). The univariate ranking + model fits are deterministic given `random_state=0`.
- **API surface parity:** All three new files match the existing `eda_utils_*.py` convention — top-level functions, pandas-Series / DataFrame inputs, DataFrame / Axes / dict outputs, no class hierarchy. No new convention introduced.
- **Integration coverage:** The cross-layer scenario worth surfacing is the SHAP-importance → top-K → interactions handoff. U11 codifies this in the notebook (top-K is read from the SHAP table produced in U6, not invented). Universe of test scenarios in U6 includes a loose-but-explicit "SHAP ranking and LGBM gain ranking should agree on the top features" check.
- **Unchanged invariants:** `eda_utils_targets.py` is read-only. `eda_utils_targets.add_all_targets` still appends the same seven target columns under the same names. Existing notebooks (01-05) continue to run.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `lightgbm` or `shap` has no Python 3.14 wheel as of 2026-05-22. | U1 documents the explicit fallback: pin to the latest version that does have a 3.14 wheel and add a one-line comment. Do not downgrade numpy / pandas / sklearn — verify the existing pins still resolve via the U1 "still imports" test scenario. |
| The 222 positives + 2344-row dataset is small enough that holdout AUC is noisy. | Document explicitly in the notebook: single 80/20 stratified split with `random_state=0` is "quick eval, not a deployment claim." Cross-validation is a backlog item (see Deferred to Follow-Up Work). |
| High-cardinality categoricals (`master_entity` ~60 levels, `Make Clean` ~30+) blow up one-hot encoding for LR. | `prepare_modeling_frame` rare-buckets to `__OTHER__` for any categorical with cardinality > `categorical_threshold` (default 30) on the LR pathway. LightGBM gets the full cardinality natively. |
| Target leakage from the other candidate-target columns or `Highest Injury Severity Alleged`. | Hardcoded in `DEFAULT_DROP_COLS` (U2). Notebook spot-checks the post-drop feature list and prints it as Section 2 artifact. |
| Free-text + ID columns inflate the feature schema and crash univariate metrics. | Same `DEFAULT_DROP_COLS` covers narrative + redaction + identifier columns. U4's drop-list assertion test guards against regressions. |
| SHAP's `TreeExplainer` is sensitive to LightGBM version pinning. | U6 uses the documented `TreeExplainer` recipe and asserts `mean_abs_shap > 0` on a synthetic positive-signal frame. If the SHAP API breaks on the chosen LightGBM version, U1's pin-fallback path covers it. |
| Pairwise heatmaps (K=8 -> 28 pairs) clutter the artifact directory. | U7's `pairwise_heatmaps_to_png` skips low-count pairs and the notebook keeps K=8 as the default — adjustable. Filenames encode the pair, so post-hoc filtering is easy. |
| Pinning `lightgbm` differently in the main env breaks one of the existing embeddings / spaCy tracks. | The existing tracks use the sidecar `avird-2026-eda-spacy` env for spaCy; the embeddings track is in the same main env but does not import lightgbm. The U1 test scenario "existing notebooks still run" guards against this. |
| Per-file synthetic-frame tests pass but the notebook fails at runtime on a real-data integration issue (e.g., a top-K SHAP feature is a datetime that `pairwise_heatmaps_to_png` can't qcut). | U11 verification is the integration check: notebook runs end-to-end on `treated_df` before commit, and `artifacts_target_injury/` is inspected for the expected file tree. If runtime issues recur, add a small smoke-test (in `eda/tests/test_eda_utils_target_integration.py`) that loads a 200-row slice of `treated_df`, runs the full pipeline, and asserts no exceptions + expected output shapes — backlog item if not needed at v1. |

---

## Documentation / Operational Notes

- The notebook itself is the documentation. Each section opens with a markdown cell describing what the section does and where its artifacts land.
- `eda/CLAUDE.md` already covers the "one function per `eda_utils_x.py`" rule — no edits needed.
- Update `eda/ADS_to_2026_03_16/eda_to_do.md` (U12) so future-me sees the work landed and what's next (`SV Speed >= 15` follow-up).
- No CHANGELOG / repo-root README updates required.

---

## Sources & References

- **Origin document:** [docs/brainstorms/nhtsa-crash-project-requirements.md](../brainstorms/nhtsa-crash-project-requirements.md) (R14 — severity classification with tabular baseline)
- Origin EDA notebook: `eda/ADS_to_2026_03_16/04_eda_target_exploration.ipynb`
- Target construction: `eda/eda_utils_targets.py` (`make_injury_reported_target`, `add_all_targets`)
- Load + treat pipeline: `eda/eda_utils_sgo.py`, `eda/eda_utils_dedupe.py`, `eda/eda_utils_treatment.py`
- Pattern references: `eda/eda_utils_basic.py`, `eda/eda_utils_topics.py`, `eda/eda_utils_spacy.py`
- Sibling plan: `docs/plans/2026-05-20-001-feat-spacy-narrative-eda-plan.md`
- Backlog source: `eda/ADS_to_2026_03_16/eda_to_do.md` (lines 56-62 — "against target ... quick RF / LR / lightgbm ... maybe interactions (heatmap & 2 stub tree)")
- LightGBM docs: https://lightgbm.readthedocs.io/en/stable/Python-API.html, https://lightgbm.readthedocs.io/en/stable/Advanced-Topics.html#categorical-feature-support
- SHAP docs: https://shap.readthedocs.io/en/latest/example_notebooks/tabular_examples/tree_based_models/Census%20income%20classification%20with%20LightGBM.html
- scikit-learn univariate: `sklearn.feature_selection.mutual_info_classif`, `sklearn.feature_selection.chi2`, `sklearn.metrics.roc_auc_score`
- KS statistic: `scipy.stats.ks_2samp`
