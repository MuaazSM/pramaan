"""Runtime configuration (docs/02-BACKEND.md §3).

Everything is a ``pydantic-settings`` field so it can be overridden by
environment variables (``PRAMAAN_*``) or a ``.env`` file at the repo root.
No secret has a default that looks like a real credential; ``session_secret``
and ``anthropic_api_key`` must come from the environment in any real
deployment (CLAUDE.md: "No secrets in git").
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration, read once and cached (see ``get_settings``)."""

    model_config = SettingsConfigDict(env_prefix="PRAMAAN_", env_file=".env", extra="ignore")

    data_dir: str = "./data"
    job_backend: Literal["inline", "dramatiq"] = "inline"
    redis_url: str = "redis://localhost:6379/0"
    llm_enabled: bool = False
    anthropic_api_key: str | None = None
    anchor_backend: Literal["local", "fabric"] = "local"
    evidence_roots: tuple[str, ...] = ("./data/evidence",)

    # Wave 0 stub-mode switches (docs/PROMPTBOOK.md W0.3):
    # STUB_MODE=1 (default) serves fixture data and a simulated WS job
    # instead of driving the real worker pipeline. BACKEND flips this off
    # once B1 lands the real case pipeline.
    stub_mode: bool = True

    # Session cookie signing key (itsdangerous). Never commit a real value;
    # the fixture default below is clearly a dev-only placeholder.
    session_secret: str = "dev-only-insecure-session-secret-change-me"
    session_cookie_name: str = "pramaan_session"
    session_max_age_s: int = 60 * 60 * 12  # 12h

    # CSRF (double-submit cookie, docs/02-BACKEND.md §11). Issued on every
    # login regardless of mode; enforced on mutating routes only when
    # stub_mode=False (see pramaan_api.deps.require_csrf).
    csrf_cookie_name: str = "pramaan_csrf"
    csrf_header_name: str = "x-csrf-token"


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton (FastAPI dependency-injects this)."""
    return Settings()
