"""System health (docs/02-BACKEND.md §4). Public — no auth required, so the
frontend's boot screen and uptime checks work before login.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pramaan_api.fixtures import store
from pramaan_api.schemas import HealthStatus
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["system"])


@router.get("/system/health", response_model=HealthStatus)
def health(settings: Settings = Depends(get_settings)) -> HealthStatus:
    result = store.system_health(llm_enabled=settings.llm_enabled, stub_mode=settings.stub_mode)
    if settings.stub_mode:
        return result
    # Real mode (task B3): report whether a PDF backend (WeasyPrint, or the
    # Playwright/Chromium fallback) is actually usable in this process, and
    # that the Fabric anchor backend is, as documented, not implemented
    # (docs/progress/B1.md "Decisions" — LocalAnchor only).
    from pramaan_reporting.pdf import pdf_backend_available

    return result.model_copy(update={"weasyprint": pdf_backend_available() is not None})
