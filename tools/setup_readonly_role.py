"""Provision the read-only Postgres role the text-to-SQL agent connects as.

The open-ended SQL agent (plan P1) authors free-form ``SELECT`` and runs it as a
role that *structurally* cannot do anything else (KTD-1). This script applies the
idempotent grant in ``db/roles/readonly_role.sql`` to the local seeded DB.

The role name, password, and database are all read from ``READONLY_DATABASE_URL``
(the role's own connection string), so the secret only ever lives in that env
var — never in this file or the committed ``.sql``. The DDL itself runs over the
admin ``DATABASE_URL`` connection (creating a role needs admin rights).

Idempotent, mirroring ``tools/local_db_setup.py``: a second run reports the role
already exists, re-asserts the grants, and exits 0. It also prints the server
version it connected to (the machine runs both PG 17 on :5432 and PG 18 on :5433
— confirm the port you targeted).

Usage::

    python tools/setup_readonly_role.py
    python tools/setup_readonly_role.py \
        --database-url postgresql://postgres:pw@localhost:5432/avird_dev \
        --readonly-database-url postgresql://avird_readonly:ro@localhost:5432/avird_dev

Both URLs are read from the environment or a gitignored repo-root ``.env`` when
the flags are omitted. See ``.env.example`` for the shape.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # optional: load repo-root .env, mirroring db/connection.py
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:  # pragma: no cover - dotenv is in the env, guard anyway
    pass

DATABASE_URL_ENV = "DATABASE_URL"
READONLY_DATABASE_URL_ENV = "READONLY_DATABASE_URL"

STATEMENT_TIMEOUT = "5s"
WORK_MEM = "32MB"
TABLE = "treated_incident_reports"


@dataclass(frozen=True)
class RoleSpec:
    """The role identity derived from a ``READONLY_DATABASE_URL``."""

    role: str
    password: str
    dbname: str


def _normalize_scheme(url: str) -> str:
    """Route SQLAlchemy-style or bare schemes to what urlsplit/psycopg accept."""
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def parse_readonly_url(url: str) -> RoleSpec:
    """Extract the role name, password, and database from a connection URL.

    The username/password may be percent-encoded in a URL, so they are decoded
    here — the role is created with the *decoded* values, which is what psycopg
    will send when the agent later connects with the same URL.
    """
    parts = urlsplit(_normalize_scheme(url))
    role = unquote(parts.username or "")
    password = unquote(parts.password or "")
    dbname = parts.path.lstrip("/")
    if not role:
        raise ValueError(f"{READONLY_DATABASE_URL_ENV} has no role (username) in it")
    if not password:
        raise ValueError(f"{READONLY_DATABASE_URL_ENV} has no password in it")
    if not dbname:
        raise ValueError(f"{READONLY_DATABASE_URL_ENV} has no database name in its path")
    return RoleSpec(role=role, password=password, dbname=dbname)


def grant_statements(spec: RoleSpec) -> list[sql.Composed]:
    """The idempotent least-privilege DDL, mirroring ``db/roles/readonly_role.sql``.

    Built with ``psycopg.sql`` so the role/db identifiers and the password
    literal are quoted by the driver, never string-interpolated. The first
    statement creates-or-alters the role; the rest strip ambient grants and add
    back only CONNECT + schema USAGE + SELECT on the one treated table.
    """
    role = sql.Identifier(spec.role)
    dbname = sql.Identifier(spec.dbname)
    role_lit = sql.Literal(spec.role)
    pw_lit = sql.Literal(spec.password)
    table = sql.Identifier(TABLE)
    return [
        sql.SQL(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {role_lit}) THEN "
            "EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', {role_lit}, {pw_lit}); "
            "ELSE "
            "EXECUTE format('ALTER ROLE %I LOGIN PASSWORD %L', {role_lit}, {pw_lit}); "
            "END IF; END $$;"
        ).format(role_lit=role_lit, pw_lit=pw_lit),
        sql.SQL("REVOKE ALL ON DATABASE {db} FROM {role}").format(db=dbname, role=role),
        sql.SQL("GRANT CONNECT ON DATABASE {db} TO {role}").format(db=dbname, role=role),
        sql.SQL("REVOKE ALL ON SCHEMA public FROM {role}").format(role=role),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {role}").format(role=role),
        sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}").format(role=role),
        sql.SQL("GRANT SELECT ON {table} TO {role}").format(table=table, role=role),
        sql.SQL("ALTER ROLE {role} SET statement_timeout = {v}").format(
            role=role, v=sql.Literal(STATEMENT_TIMEOUT)
        ),
        sql.SQL("ALTER ROLE {role} SET work_mem = {v}").format(role=role, v=sql.Literal(WORK_MEM)),
    ]


def _resolve_urls(args: argparse.Namespace) -> tuple[str, str] | None:
    admin = (args.database_url or os.environ.get(DATABASE_URL_ENV) or "").strip()
    readonly = (
        args.readonly_database_url or os.environ.get(READONLY_DATABASE_URL_ENV) or ""
    ).strip()
    if not admin:
        print(
            f"[setup_readonly_role] {DATABASE_URL_ENV} is not set. Put it in a repo-root "
            f".env (gitignored) or pass --database-url. This is the *admin* URL used to "
            f"create the role.",
            file=sys.stderr,
        )
        return None
    if not readonly:
        print(
            f"[setup_readonly_role] {READONLY_DATABASE_URL_ENV} is not set. Put it in a "
            f"repo-root .env (gitignored) or pass --readonly-database-url, e.g.\n"
            f"  {READONLY_DATABASE_URL_ENV}=postgresql://avird_readonly:<password>"
            f"@localhost:5432/avird_dev\n"
            f"The agent connects as this role; this script creates it.",
            file=sys.stderr,
        )
        return None
    return admin, readonly


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", help="Admin URL used to create the role.")
    parser.add_argument(
        "--readonly-database-url",
        help="The read-only role's own URL; role/password/db are derived from it.",
    )
    args = parser.parse_args(argv)

    urls = _resolve_urls(args)
    if urls is None:
        return 2
    admin_url, readonly_url = urls

    try:
        spec = parse_readonly_url(readonly_url)
    except ValueError as exc:
        print(f"[setup_readonly_role] {exc}", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(_normalize_scheme(admin_url), autocommit=True) as conn:
            server_version = conn.execute("SELECT version()").fetchone()[0]
            print(f"[ok] connected: {server_version}")

            existed = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (spec.role,)
            ).fetchone()
            for statement in grant_statements(spec):
                conn.execute(statement)
            if existed:
                print(f"[ok] role '{spec.role}' exists — grants re-asserted")
            else:
                print(f"[ok] role '{spec.role}' created with SELECT-only on {TABLE}")
    except psycopg.OperationalError as exc:
        print(
            f"[setup_readonly_role] could not connect with the admin URL: {exc}\n"
            f"  Check the Postgres service is running and DATABASE_URL is right.",
            file=sys.stderr,
        )
        return 2

    print()
    print(f"verify (SELECT-only): psql '{readonly_url}' -c 'SELECT count(*) FROM {TABLE};'")
    print("  an INSERT/UPDATE/DROP as this role must raise a permission error.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
