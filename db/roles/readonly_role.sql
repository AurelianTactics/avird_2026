-- Read-only login role for the open-ended text-to-SQL agent (plan P1, U1).
--
-- KTD-1: open-ended *model-authored* SQL is only defensible because it runs as
-- a Postgres role that can do exactly one thing — SELECT from the single
-- treated table. Even a perfect prompt injection that slips past the static
-- validator (statement-type + allow-list + EXPLAIN) cannot mutate data or read
-- another table, because this role was never granted the privilege. The
-- structural boundary is the floor; the validator is defense-in-depth on top.
--
-- Idempotent: re-running only (re)sets the password and re-asserts the grants.
-- The role name + password are supplied as psql variables so the secret never
-- lives in this committed file:
--
--   psql "$DATABASE_URL" \
--     -v role=avird_readonly -v password="$RO_PASSWORD" -v dbname=avird_dev \
--     -f db/roles/readonly_role.sql
--
-- For the local seeded DB, prefer the idempotent applier, which derives all
-- three values from READONLY_DATABASE_URL so you never hand-type them:
--
--   python tools/setup_readonly_role.py
--
-- Railway (prod): run this once against the prod DB with the prod role +
-- password, then set READONLY_DATABASE_URL on the api service. Documented in
-- docs/conventions/stack.md.

\set ON_ERROR_STOP on

-- 1. Create the LOGIN role if absent; otherwise (re)set its password so the
--    script is safe to re-run after a credential rotation.
--
--    \gexec, not a DO block: psql never interpolates :'role' / :'password'
--    inside a dollar-quoted body (interpolation stops at any quoting), so a DO
--    block would fail with `syntax error at or near ":"`. Here the variables
--    are substituted in plain SQL, format() builds the DDL string, and \gexec
--    executes each returned row as a statement.
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role', :'password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'role', :'password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role')
\gexec

-- 2. Least privilege. Strip the ambient grants this role inherits, then add
--    back only: CONNECT to this database, USAGE on the public schema, and
--    SELECT on the one treated table. No INSERT/UPDATE/DELETE/DDL anywhere,
--    and no SELECT on any other table (e.g. the spend ledgers).
REVOKE ALL ON DATABASE :"dbname" FROM :"role";
GRANT CONNECT ON DATABASE :"dbname" TO :"role";
REVOKE ALL ON SCHEMA public FROM :"role";
GRANT USAGE ON SCHEMA public TO :"role";
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM :"role";
GRANT SELECT ON treated_incident_reports TO :"role";

-- 3. Role-level guardrails so a runaway generated query can't pin the server:
--    a hard statement timeout and a conservative per-sort/hash work_mem.
ALTER ROLE :"role" SET statement_timeout = '5s';
ALTER ROLE :"role" SET work_mem = '32MB';
