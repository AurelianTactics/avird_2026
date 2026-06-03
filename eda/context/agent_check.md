# Agent Context Check

A lightweight, judgment-based verification set. In a **fresh session scoped to
`eda/`**, an agent (or the author) should be able to answer every question below
using only `eda/CLAUDE.md` and the linked `eda/context/` files — **without**
opening the source PDF (`data/nhtsa/SGO-2021-01_Data_Element_Definitions.pdf`)
or any notebook. This is a qualitative pass/fail, not an automated gate. Any
question that forces a PDF/notebook read is a gap to fix in `findings.md` (or the
relevant context file).

1. The dataset comes from two CSVs. **Why can't you assume a given column exists
   in every row**, and what defensive pattern does the codebase use? _(schema
   split across time; `_safe_col` returns all-NaN for missing columns)_

2. The "air bags deployed" and "vehicle towed" fields look different between the
   two files. **How do they differ, and how does target logic reconcile them?**
   _(compound single column in new schema vs split CP/SV Yes/No in old;
   case-insensitive substring match on "yes")_

3. **How are duplicate reports for the same physical incident collapsed** —
   what's the grouping key and which report wins? _(Same Incident ID, else
   composite fallback key; most recent by submission date / version / id;
   narratives concatenated latest-first)_

4. There's a string that **breaks sentence segmentation** in the NLP work. What
   is it and where does it come from? _(`--- next report ---` narrative join
   separator from dedupe)_

5. **What is `master_entity`, why does it exist, and should you group on it or on
   the raw entity columns?** _(canonical rollup of Operating + Reporting Entity;
   group on it — raw fields have duplicate IDs / text noise)_

6. **Which targets did the phase keep, and how should you evaluate the injury
   target** given its class balance? _(`Injury Reported` + `SV Speed >= 15`;
   imbalanced → AUC + PR-AUC on a stratified holdout, not accuracy)_

7. When building a feature set for `Injury Reported`, **which columns must you
   drop to avoid leakage, and why is a hand-maintained drop-list dangerous?**
   _(source col `Highest Injury Severity Alleged` + other derived targets;
   derive from the target-name source of truth — a static list drifted and
   leaked `SV Speed >= 15`)_

8. **Which columns are "co-observed crash outcomes" rather than pre-incident
   signal**, and how should they be handled? _(towed / airbags / precrash speed;
   run a pre-incident-only contrast pass)_

9. **Who redacts narratives, and what markers indicate redaction?** _(a few
   entities — defunct Cruise/Argo/Motional near 100%, plus Tesla as the active
   redactor; Waymo low; markers `[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS
   INFORMATION]` / `XXX` / `CBI`, via `is_redacted`)_

10. **Which env do you need for LightGBM/SHAP work vs spaCy work**, and what
    happens if you stay on the main env? _(target sidecar 3.12 / spaCy sidecar
    3.12; main env is 3.14 and lazy imports fail late with a cryptic
    ImportError)_

11. **Where do point-in-time numbers, charts, and the full "what was and wasn't
    tried" coverage log live** — and why aren't they in `findings.md`? _(the
    dated HTML report; findings.md excludes volatile stats so agents aren't
    anchored to numbers that move on refresh)_
