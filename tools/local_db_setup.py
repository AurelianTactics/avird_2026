"""One-time bootstrap: create the local avird_dev database if absent.

PostgreSQL has no CREATE DATABASE IF NOT EXISTS, so this script connects to
the maintenance database (``postgres``) on the same server with the same
credentials as ``DATABASE_URL``, checks ``pg_database`` for the target name,
and creates it only when missing. Idempotent: a second run reports "exists"
and changes nothing.

Prints the server version it connected to — the machine runs both PG 17 and
PG 18 services, so confirm the port you targeted is the instance you meant.

Seeding is a separate (also idempotent) step, run after this:

    python db/run_pipeline.py

Usage:
    python tools/local_db_setup.py
    python tools/local_db_setup.py --database-url postgresql://postgres:pw@localhost:5432/avird_dev

``DATABASE_URL`` is read from the environment or a gitignored repo-root
``.env`` (same file db/connection.py loads). See .env.example for the shape.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]

try:  # optional: load repo-root .env, mirroring db/connection.py
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:  # pragma: no cover - dotenv is in the env, guard anyway
    pass

DATABASE_URL_ENV = "DATABASE_URL"


def _normalize_scheme(url: str) -> str:
    """Route SQLAlchemy-style or bare schemes to what psycopg.connect accepts."""
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def split_target_url(url: str) -> tuple[str, str]:
    """Return (target_dbname, maintenance_url) from a DATABASE_URL.

    The maintenance URL is the same server/credentials with the path swapped
    to the ``postgres`` database, which always exists.
    """
    parts = urlsplit(_normalize_scheme(url))
    dbname = parts.path.lstrip("/")
    if not dbname:
        raise ValueError("DATABASE_URL has no database name in its path")
    return dbname, urlunsplit(parts._replace(path="/postgres"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url",
        help="Override DATABASE_URL for this run (target db, not the maintenance db).",
    )
    args = parser.parse_args(argv)

    url = (args.database_url or os.environ.get(DATABASE_URL_ENV) or "").strip()
    if not url:
        print(
            f"[local_db_setup] {DATABASE_URL_ENV} is not set. Put it in a repo-root "
            f".env (gitignored) or pass --database-url, e.g.\n"
            f"  {DATABASE_URL_ENV}=postgresql://postgres:<password>@localhost:5432/avird_dev",
            file=sys.stderr,
        )
        return 2

    try:
        dbname, maintenance_url = split_target_url(url)
    except ValueError as exc:
        print(f"[local_db_setup] {exc}", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(maintenance_url, autocommit=True) as conn:
            server_version = conn.execute("SELECT version()").fetchone()[0]
            print(f"[ok] connected: {server_version}")

            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
            ).fetchone()
            if exists:
                print(f"[ok] database '{dbname}' exists — nothing to do")
            else:
                # CREATE DATABASE cannot be parameterized; quote the identifier.
                conn.execute(f'CREATE DATABASE "{dbname}"')
                print(f"[ok] database '{dbname}' created")
    except psycopg.OperationalError as exc:
        print(
            f"[local_db_setup] could not connect to the maintenance db: {exc}\n"
            f"  Check the Postgres service is running and the credentials in .env are right.",
            file=sys.stderr,
        )
        return 2

    print()
    print("next steps:")
    print("  1. ensure apps/api/.env carries the same DATABASE_URL value")
    print("  2. seed (idempotent): python db/run_pipeline.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
