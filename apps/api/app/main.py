"""FastAPI app entrypoint.

P0 ships only `/health`. The route is anonymous public access by
design — see Scope Boundaries in the P0 plan. Future P1+ data routes
will live here behind the same Railway-internal-only origin.
"""

from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from . import debate, fault, groupings, incidents
from .db import check_db
from .derived import routes as derived_routes

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="avird-2026 api", version="0.0.0")

# Internal-boundary auth. `api` has no public domain, but that's network
# obscurity, not a trust boundary — anything that reaches it is otherwise
# trusted. When API_SHARED_SECRET is set (production: same value on `web` and
# `api`), every request except the health probe must present a matching
# `x-internal-secret`. When unset (local dev, CI, tests) the check is skipped,
# so the seeded-stack verification loop needs no extra wiring.
SHARED_SECRET_HEADER = "x-internal-secret"


@app.middleware("http")
async def require_internal_secret(request: Request, call_next):
    secret = os.environ.get("API_SHARED_SECRET")
    if secret and request.url.path != "/health":
        if request.headers.get(SHARED_SECRET_HEADER) != secret:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(incidents.router)
app.include_router(groupings.router)
app.include_router(fault.router)
app.include_router(debate.router)
app.include_router(derived_routes.router)


@app.get("/health")
async def health(db: str = Depends(check_db)) -> dict[str, str]:
    return {"status": "ok", "db": db}
