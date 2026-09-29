"""API-level tests for ``POST /cases/{cid}/assistant/query`` and
``GET /llm/usage`` (docs/03-AI-TIMELINE.md §8.3.1/§9), exercised through the
real FastAPI app with the default ``fixture`` provider — offline, no
network, no ``ANTHROPIC_API_KEY`` required.

This file (plus ``test_assistant_draft.py``) is the AI workstream's own
copy of an "LLM enabled" test client — it cannot share
``tests/backend/conftest.py`` (a different, sibling test tree owned by
BACKEND) so it builds one locally instead.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pramaan_api.deps import get_settings
from pramaan_api.fixtures import store
from pramaan_api.main import app
from pramaan_api.settings import Settings


@pytest.fixture
def llm_client() -> Iterator[TestClient]:
    def _llm_enabled_settings() -> Settings:
        return Settings(llm_enabled=True)

    app.dependency_overrides[get_settings] = _llm_enabled_settings
    try:
        with TestClient(app) as client:
            resp = client.post("/api/auth/login", json={"username": "examiner", "password": "demo"})
            assert resp.status_code == 200, resp.text
            yield client
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def case_id() -> str:
    return store.DATA.case.id


def test_query_returns_a_filter_and_results(llm_client: TestClient, case_id: str) -> None:
    resp = llm_client.post(
        f"/api/cases/{case_id}/assistant/query", json={"question": "what happened on CH2?"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"filter", "result_count", "results"}
    assert isinstance(body["results"], list)
    assert body["result_count"] == len(body["results"])
    # The checked-in fixture's canned tool call is {"channels": [2]}.
    assert body["filter"]["channels"] == [2]


def test_query_filter_rejects_unknown_fields(llm_client: TestClient, case_id: str) -> None:
    # The returned filter is EvidenceSearchFilter (extra="forbid") — a
    # regression here would mean the router stopped validating tool input.
    resp = llm_client.post(
        f"/api/cases/{case_id}/assistant/query", json={"question": "anything"}
    )
    assert resp.status_code == 200
    allowed = {
        "channels",
        "from_ist",
        "to_ist",
        "source",
        "deleted_only",
        "motion_min",
        "detection_class",
        "log_kind",
        "text",
    }
    assert set(resp.json()["filter"].keys()) <= allowed


def test_query_404s_for_unknown_case(llm_client: TestClient) -> None:
    resp = llm_client.post(
        "/api/cases/case_does_not_exist/assistant/query", json={"question": "x"}
    )
    assert resp.status_code == 404


def test_query_is_disabled_by_default(case_id: str) -> None:
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "examiner", "password": "demo"})
        resp = client.post(
            f"/api/cases/{case_id}/assistant/query", json={"question": "x"}
        )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "llm_disabled"


def test_llm_usage_grows_after_a_query_call(llm_client: TestClient, case_id: str) -> None:
    before = llm_client.get("/api/llm/usage")
    assert before.status_code == 200
    before_count = len(before.json())

    resp = llm_client.post(
        f"/api/cases/{case_id}/assistant/query", json={"question": "what happened on CH2?"}
    )
    assert resp.status_code == 200

    after = llm_client.get("/api/llm/usage")
    assert after.status_code == 200
    after_body = after.json()
    assert len(after_body) == before_count + 1
    entry = after_body[-1]
    assert set(entry.keys()) == {
        "id",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "prompt_sha256",
        "response_sha256",
        "created_utc",
    }
    assert entry["model"] == "claude-haiku-4-5-20251001"
    assert entry["input_tokens"] > 0


def test_query_is_blocked_once_the_per_case_budget_cap_is_reached(
    llm_client: TestClient, case_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRAMAAN_LLM_BUDGET_USD_PER_CASE", "0.0000000001")
    resp = llm_client.post(
        f"/api/cases/{case_id}/assistant/query", json={"question": "what happened on CH2?"}
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "llm_budget_exceeded"
