-- fault_analysis: one LLM "insurance adjuster" verdict per
-- (report_id, fault_version). Precomputed offline by fault/judge_batch.py and
-- read back read-only by the api (no LLM deps on the read path). The unique
-- (report_id, fault_version) key makes a re-run of the same version an UPSERT
-- (no duplicate verdicts) while a new version appends a fresh set of rows.
--
-- All three verdict columns are NULLABLE on purpose: a parse failure stores an
-- explicit error sentinel (NULL verdict + NULL percentage + an error string in
-- short_explanation_of_decision), never a guessed value. The 0..1 CHECK passes
-- on NULL (standard SQL), so the sentinel row is legal.
--
-- created_at is an ISO-8601 TEXT timestamp written by the batch, matching the
-- ingest_batches convention (portable across sqlite + Postgres, orderable
-- lexicographically).
CREATE TABLE IF NOT EXISTS fault_analysis (
    "report_id"                     TEXT NOT NULL,
    "fault_version"                 TEXT NOT NULL,
    "is_av_at_fault"                BOOLEAN,
    "av_fault_percentage"           NUMERIC(5,4)
        CHECK ("av_fault_percentage" >= 0 AND "av_fault_percentage" <= 1),
    "short_explanation_of_decision" TEXT,
    "model"                         TEXT,
    "created_at"                    TEXT NOT NULL,
    UNIQUE ("report_id", "fault_version")
);
