from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pramaan_api.deps import get_settings
from pramaan_api.fixtures import store
from pramaan_api.main import app
from pramaan_api.settings import Settings


def _login(client: TestClient, username: str, password: str = "demo") -> TestClient:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture
def anon_client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def examiner_client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield _login(c, "examiner")


@pytest.fixture
def reviewer_client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield _login(c, "reviewer")


@pytest.fixture
def admin_client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield _login(c, "admin")


@pytest.fixture
def llm_client() -> Iterator[TestClient]:
    """An examiner-authenticated client with LLM_ENABLED overridden to True,
    for exercising the assistant/llm-usage routes' documented success shape
    (the Wave 0 default is disabled — see test_assistant.py for that path).
    """

    def _llm_enabled_settings() -> Settings:
        return Settings(llm_enabled=True)

    app.dependency_overrides[get_settings] = _llm_enabled_settings
    try:
        with TestClient(app) as c:
            yield _login(c, "examiner")
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def case_id() -> str:
    return store.DATA.case.id


@pytest.fixture
def evidence_id() -> str:
    return next(iter(store.DATA.evidence))


@pytest.fixture
def secondary_evidence_id() -> str:
    ids = list(store.DATA.evidence)
    return ids[1]


@pytest.fixture
def recording_id() -> str:
    return store.DATA.recordings[0].id


@pytest.fixture
def frame_id() -> str:
    return store.DATA.frames[0].frame_id


@pytest.fixture
def clip_id() -> str:
    return store.DATA.clips[0].id


@pytest.fixture
def job_id() -> str:
    return next(iter(store.DATA.jobs))


@pytest.fixture
def report_id() -> str:
    return store.DATA.reports[0].id


@pytest.fixture
def export_id() -> str:
    return store.DATA.exports[0].id


@pytest.fixture
def inferred_layout_id() -> str:
    return next(iter(store.DATA.inferred_layouts))


@pytest.fixture
def clock_model_id() -> str:
    return store.DATA.clock_models[0].id
