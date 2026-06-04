'''SQLAlchemy engine + connectivity helpers.

The engine is built from the ``DATABASE_URL`` environment variable -- Railway
Postgres in production, a sqlite URL in tests. A local ``.env`` (gitignored) is
loaded if present so the secret never has to live in the shell profile.

Railway hands out URLs with the bare ``postgres://`` / ``postgresql://`` scheme,
which SQLAlchemy would route to the (uninstalled) psycopg2 driver. We rewrite
those to ``postgresql+psycopg://`` so the installed psycopg v3 driver is used.
'''
import os

from sqlalchemy import create_engine, text

try:  # optional: load .env if python-dotenv is available
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover - dotenv is in the env, guard anyway
    pass

DATABASE_URL_ENV = 'DATABASE_URL'


def _normalize_url(url):
    '''Route bare Postgres schemes to the installed psycopg v3 driver.'''
    if url.startswith('postgres://'):
        return 'postgresql+psycopg://' + url[len('postgres://'):]
    if url.startswith('postgresql://'):
        return 'postgresql+psycopg://' + url[len('postgresql://'):]
    return url


def get_database_url():
    '''Return DATABASE_URL or raise a descriptive error if it is unset.'''
    url = os.environ.get(DATABASE_URL_ENV)
    if not url or not url.strip():
        raise RuntimeError(
            f'{DATABASE_URL_ENV} is not set. Put it in a .env file (gitignored) '
            f'or export it, e.g.\n'
            f'  {DATABASE_URL_ENV}=postgresql://user:pass@host:port/dbname'
        )
    return url.strip()


def get_engine(url=None, **kwargs):
    '''Build a SQLAlchemy engine from DATABASE_URL (or an explicit ``url``).'''
    url = _normalize_url(url or get_database_url())
    return create_engine(url, **kwargs)


def ping(engine=None):
    '''Run ``SELECT 1``; return True on success. Builds an engine if none given.'''
    engine = engine or get_engine()
    with engine.connect() as conn:
        return conn.execute(text('SELECT 1')).scalar() == 1
