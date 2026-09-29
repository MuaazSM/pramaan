"""FastAPI app factory. Run with:

    uv run uvicorn pramaan_api.main:app --reload --port 8000

See docs/progress/W0.3.md "API summary" for the full route list, auth flow
and WS event types.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from pramaan_api import __version__
from pramaan_api.errors import ApiError, api_error_handler, validation_error_handler
from pramaan_api.routers import (
    analytics,
    anchors,
    assistant,
    audit,
    cases,
    clips,
    deletions,
    evidence,
    exports,
    frames,
    fs,
    jobs,
    logs,
    recordings,
    reports,
    search,
    system,
    timeline,
)
from pramaan_api.routers import auth as auth_router
from pramaan_api.ws import router as ws_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pramaan API",
        version=__version__,
        description="Multi-vendor DVR/NVR forensic platform — API (docs/02-BACKEND.md).",
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    api_prefix = "/api"
    for module in (
        auth_router,
        cases,
        fs,
        evidence,
        jobs,
        recordings,
        frames,
        clips,
        logs,
        deletions,
        reports,
        exports,
        audit,
        anchors,
        search,
        system,
        timeline,
        analytics,
        assistant,
    ):
        app.include_router(module.router, prefix=api_prefix)

    # WS endpoint lives at /api/ws (matches the /api prefix everything else
    # uses; docs/02-BACKEND.md §4 shows it as `/ws?case_id=` relative to
    # that base path).
    app.include_router(ws_router, prefix=api_prefix)

    return app


app = create_app()
