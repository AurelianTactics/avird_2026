"""Postgres pool + `SELECT 1` probe.

The pool is lazy-initialized on first use so service startup never
blocks on DB availability. `check_db()` swallows every exception and
returns "down" — `/health` must never raise on transient DB blips.
Errors are logged with a sanitized message; `DATABASE_URL` is never
included in the log output.
"""

from __future__ import annotations

import asyncio
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def _ensure_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            url = os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL is not set")
            _pool = await asyncpg.create_pool(url, min_size=0, max_size=4, command_timeout=5)
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Public accessor for the lazy-initialized pool.

    Wraps the private `_ensure_pool()` so data-access code (see `data.py`)
    never reaches into module internals. Preserves the lazy-init and
    sanitized-failure posture — a missing `DATABASE_URL` raises here, and
    callers decide how to surface it.
    """
    return await _ensure_pool()


async def _drop_pool() -> None:
    global _pool
    if _pool is None:
        return
    try:
        await _pool.close()
    except Exception:  # noqa: BLE001
        pass
    _pool = None


async def check_db() -> str:
    """Run SELECT 1 through the pool. Returns 'ok' or 'down'. Never raises."""
    try:
        pool = await _ensure_pool()
        async with pool.acquire(timeout=5) as conn:
            value = await conn.fetchval("SELECT 1")
            return "ok" if value == 1 else "down"
    except Exception:  # noqa: BLE001
        logger.warning("DB connection failed")
        await _drop_pool()
        return "down"
