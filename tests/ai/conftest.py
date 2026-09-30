"""Fixtures for real (non-fixture) mode AI tests (task A2).

Mirrors ``tests/backend/conftest.py``'s ``real_evidence_dir``/``real_settings``
/``real_client`` fixtures (a task B1 own file this task must not edit — see
CLAUDE.md's "stay inside your owned paths"), duplicated here so ``tests/ai``
stays self-contained: each real-mode test gets its own ``tmp_path`` data dir
and evidence root, never the fixture dataset and never a developer's real
``$PRAMAAN_DATA``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pramaan_api.deps import get_settings
from pramaan_api.main import app
from pramaan_api.settings import Settings

CORPUS_IMAGES = Path(__file__).resolve().parents[2] / "corpus" / "images"
CORPUS_TRUTH = Path(__file__).resolve().parents[2] / "corpus" / "truth"


def corpus_image(name: str) -> Path | None:
    path = CORPUS_IMAGES / name
    return path if path.is_file() else None


def _login(client: TestClient, username: str, password: str = "demo") -> TestClient:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture
def real_evidence_dir(tmp_path: Path) -> Path:
    d = tmp_path / "evidence"
    d.mkdir()
    return d


@pytest.fixture
def real_settings(tmp_path: Path, real_evidence_dir: Path) -> Settings:
    return Settings(
        stub_mode=False,
        data_dir=str(tmp_path / "data"),
        evidence_roots=(str(real_evidence_dir),),
    )


def _real_client(settings: Settings, username: str) -> Iterator[TestClient]:
    def _settings() -> Settings:
        return settings

    app.dependency_overrides[get_settings] = _settings
    try:
        with TestClient(app) as c:
            _login(c, username)
            csrf_token = c.cookies.get(settings.csrf_cookie_name)
            assert csrf_token, "login did not set the CSRF cookie"
            c.headers[settings.csrf_header_name] = csrf_token
            yield c
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def real_client(real_settings: Settings) -> Iterator[TestClient]:
    yield from _real_client(real_settings, "examiner")
