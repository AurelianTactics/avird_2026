"""FastAPI app entrypoint.

P0 ships only `/health`. The route is anonymous public access by
design — see Scope Boundaries in the P0 plan. Future P1+ data routes
will live here behind the same Railway-internal-only origin.
"""

from __future__ import annotations

import logging

from fastapi import Depends, FastAPI

from . import fault, groupings, incidents
from .db import check_db

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="avird-2026 api", version="0.0.0")

app.include_router(incidents.router)
app.include_router(groupings.router)
app.include_router(fault.router)


@app.get("/health")
async def health(db: str = Depends(check_db)) -> dict[str, str]:
    return {"status": "ok", "db": db}
