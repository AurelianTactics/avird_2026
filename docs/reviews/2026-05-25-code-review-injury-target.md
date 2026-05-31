# Code Review — Injury Target Analysis (commit 8d82840)

- **Scope:** last commit `8d82840` vs `f7c227b` (HEAD~1). 3 new utils, 2 test files, 1 notebook (4514 lines), `.gitignore` + `eda_to_do.md`.
- **Plan:** `docs/plans/2026-05-22-001-feat-injury-target-analysis-plan.md` (explicit).
- **Mode:** report-only. Findings written for triage; no fixes applied.
- **Reviewers (6):** correctness, adversarial, testing, maintainability, project-standards, performance.
- **Verdict:** **Ready with fixes.** One P1 (cross-target leakage already present in the committed rankings/SHAP) should be fixed before the rankings are trusted. Everything else is P2/P3 polish.

Per-reviewer raw JSON: `/tmp/compound-engineering/ce-code-review/20260525-628600d5/`.

---

## P1 — High

| # | File:line | Issue | Reviewers | Conf | Route |
|---|-----------|-------|-----------|------|-------|
| 1 | `eda/eda_utils_target_univariate.py:75` | **`SV Speed >= 15` derived target leaks into the `Injury Reported` feature set.** `DEFAULT_DROP_COLS` lists only 5 of the 6 other derived-target columns — the SV-speed target is missing. The inline comment claims "the other six are dropped here," and the notebook markdown (cell ~269) repeats "the other six generated target columns," but the code drops five. Confirmed in committed notebook output: `SV Speed >= 15` appears in `feature_cols` (cell ~291), in the univariate ranking (`feature_ranking`, row 48), **and in the SHAP importance table at 0.126 / rank ~17** (cell ~4063). It's a binarization of `SV Precrash Speed (MPH)` (which is also a feature), so it's a redundant engineered column polluting the signal ranking that the design explicitly intended to exclude. | correctness (100), maintainability | 100 | gated_auto → human |

**Suggested fix (addresses root cause):** derive the drop-list from the upstream source of truth instead of hand-maintaining names. `eda_utils_targets.TARGET_COL_NAMES` already enumerates every derived target; build the drop set as the formatted target names (handling the `SV Speed >= {threshold}` template with the run's threshold) minus the active `target_col`. A `'SV Speed >= '` prefix match also closes the threshold-variant gap (10/15/20). This is the same fragility maintainability flagged separately: the static list will keep drifting from `add_all_targets`.

---

## P2 — Moderate

| # | File:line | Issue | Reviewers | Conf | Route |
|---|-----------|-------|-----------|------|-------|
| 2 | `eda/eda_utils_target_univariate.py:483` | **`rank_features` sorts by a single `mutual_info` column computed across incompatible dtype tracks.** Discrete MI (label-encoded categoricals) and continuous MI are not comparable, and high-cardinality / near-unique columns get inflated discrete MI — a 60-level `master_entity` or a near-unique **datetime/date-string column outranks real numeric signal** (adversarial reproduced a noise datetime scoring MI ≈ 0.69). SGO date columns are **not** in `DEFAULT_DROP_COLS`, so they enter scoring on the categorical track. | adversarial (100) | 100 | advisory → human |
| 3 | `eda/eda_utils_target_models.py:173,402,123` | **Pure-logic helpers in the models file are untested and can regress silently.** R10 deliberately leaves *model fitting* to notebook-exercise, but `_positive_class_shap_values` (SHAP return-shape dispatch — a wrong slice silently inverts class interpretation on a SHAP version bump), `_sanitize_lgbm_columns` collision-disambiguation, and `RareBucketer` unseen-category mapping are dep-free (numpy/pandas/sklearn only) and cheap to unit-test without lightgbm/shap installed. | testing (100), project-standards (75), maintainability | 100 | advisory → human |
| 4 | multiple | **Dead-code / cleanup cluster (safe deletions, behavior-preserving):** `value_counts_by_target` `normalize` param accepted but never read (`univariate.py:150`); `target_rate_pivot` `fillna` param unused (`interactions.py:67`); `feature_importance_logistic` `feature_cols` param unused (`models.py:342`); `_safe_filename` duplicated verbatim across univariate + interactions; `_MISSING_SENTINEL`/`_MISSING_LABEL` = `'__MISSING__'` defined 3× under 2 names; `shap_summary_plot` creates `plt.figure(...)` then immediately overwrites with `plt.gcf()` (leaks an orphan figure, `models.py:467`); `evaluate_classifier` redundant `hasattr` guard inconsistent with sibling call sites (`models.py:299`). | maintainability (100), testing, performance | 100 | safe_auto → review-fixer |
| 5 | `eda/eda_utils_target_interactions.py:53` | **`_bucketize_for_pivot` qcut single-bin collapse.** A near-constant numeric passes the `nunique() >= 2` guard but `pd.qcut(..., duplicates='drop')` collapses to one bin, producing a degenerate 1×N pivot / misleading heatmap with no warning. | adversarial (100) | 100 | advisory → human |

`normalize` (in #4) was independently flagged by both testing and maintainability — a caller passing `normalize=True` silently gets un-normalized output, so either wire it or delete it.

---

## P3 — Low

| # | File:line | Issue | Reviewers | Conf | Route |
|---|-----------|-------|-----------|------|-------|
| 6 | `eda/eda_utils_target_interactions.py:91` | `target_rate_pivot` count (`aggfunc='size'`) and rate (`aggfunc='mean'`) use divergent denominators when the target has NaN, so the `"rate% (n=count)"` annotation lies. **Not triggered for `Injury Reported`** (always 0/1). Latent. Fix: `aggfunc='count'` or assert a non-null 0/1 target. | correctness, adversarial (75) | 75 | advisory → human |
| 7 | `eda/eda_utils_target_models.py:106,254` | `categorical_threshold` is smuggled from `prepare_modeling_frame` to `fit_logistic` via `X.attrs`. **Verified to survive `train_test_split` in the pinned pandas 3.0.2**, but `.attrs` propagation is best-effort — a pandas upgrade, a slice, or a concat silently reverts `rare_threshold` to 30. Prefer passing the threshold explicitly. | correctness, adversarial, maintainability | 75 | advisory → human |
| 8 | `eda/eda_utils_target_models.py:419,448` / `interactions.py:184` | Minor perf, proportionate to N=2344: `shap_importance` + two `shap_summary_plot` calls each rebuild `TreeExplainer` and recompute SHAP (~5s of avoidable work, repeated for the `gbm_pre` contrast pass); `pairwise_heatmaps_to_png` computes `target_rate_pivot` twice per non-skipped pair. Both scale poorly if K grows past ~15. | performance | 100 | advisory → human |
| 9 | `eda/eda_utils_target_models.py:123` | `RareBucketer` is a class, against eda/CLAUDE.md's function-preference. **Likely justified** — a stateful sklearn transformer is the correct idiom for fit/transform inside a `ColumnTransformer` (prevents train/test bucketing leakage). Recommend documenting the exception rather than removing it. | maintainability, project-standards (50) | 50 | advisory → human |
| 10 | `eda/CLAUDE.md:5` | The work runs on a Python 3.12 sidecar env `avird-2026-eda-target` (per `eda_to_do.md`), but `eda/CLAUDE.md` documents only the main `avird-2026-eda` env. `lightgbm`/`shap` are lazy-imported inside functions, so an agent on the main env fails late with a cryptic ImportError. Add a sidecar block to `eda/CLAUDE.md`. | project-standards (75) | 75 | manual → human |

---

## Requirements completeness (plan: explicit)

| Req | Status | Note |
|-----|--------|------|
| R1 three utils at eda/ base, importable | ✅ | |
| R2 notebook load/treat/targets → Injury Reported | ✅ | |
| R3 basic-EDA value-counts/describe CSVs | ✅ | |
| R4 univariate tidy ranking + auc_direction | ⚠️ | Columns/contract met, but see #1 (leaked target col in the ranking) and #2 (cross-dtype MI sort). The plan's own institutional learning (line 75) said drop all six other target columns — partially unmet. |
| R5 three models + SHAP, imbalance weights | ✅ | |
| R6 heatmap + stub tree, top-K passed in | ✅ | |
| R7 artifacts to `<section>/` subfolders | ✅ | gitignored (`artifacts_target_injury/*`) |
| R8 lightgbm/shap install | ⚠️ | Sidecar fallback taken; `requirements.txt` lives outside the repo — not reviewable here. |
| R9 function contracts (no class hierarchy) | ✅ | one documented exception: `RareBucketer` (#9) |
| R10 pytest for univariate + interactions; models notebook-exercised | ✅ | as planned; see #3 for the dep-free helper gap |

---

## Coverage notes

- **Could not execute:** `lightgbm` / `shap` are not in the review venv, so the sanitize → importance → SHAP round-trip and `_positive_class_shap_values` shape dispatch were verified by static trace only (alignment looks correct; SHAP wrong-class slice remains an unverified residual risk — see #3).
- **Skipped reviewers (not applicable):** security (no auth/endpoints/user input), api-contract, data-migration, reliability, frontend/swift, deployment-verification. agent-native (no UI/agent-tool surface) and learnings-researcher (one unrelated doc in `docs/solutions/`) handled inline.
- **Testing gaps appendix (P3, not in table):** untested branches incl. `describe_by_target` object path, `dropna=True`, `_safe_filename` char substitution, `basic_eda_to_csvs` skip-missing branch, `_score_mutual_info` discrete single-value early-return, `rank_features(feature_cols=None)`, `pairwise_heatmaps_to_png` pivot-error catch, `_bucketize_for_pivot` qcut ValueError fallback, `evaluate_classifier` single-class NaN path. Full lists in the per-reviewer JSON.

## Suggested triage order

1. **#1** — fix the leakage at the drop-list source (root-cause via `TARGET_COL_NAMES`), then re-run the notebook so the ranking/SHAP no longer include `SV Speed >= 15`.
2. **#4** — apply the safe cleanup batch (deletions only, behavior-preserving).
3. **#2 / #5** — decide ranking methodology: drop/parse datetime columns, and consider not using cross-dtype MI as the sole sort key.
4. **#3** — add the dep-free unit tests for the three models-file helpers.
5. **#6–#10** — at your discretion.
