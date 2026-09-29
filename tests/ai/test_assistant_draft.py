"""API-level tests for ``POST /cases/{cid}/assistant/draft`` and
``POST /cases/{cid}/assistant/explain`` (docs/03-AI-TIMELINE.md
§8.3.2/§8.3.3/§9), through the real FastAPI app with the default ``fixture``
provider — offline, no network.

See ``test_assistant_query.py`` for why this file builds its own
LLM-enabled test client rather than sharing one from ``tests/backend``.
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


def test_draft_returns_a_validated_sentence_for_a_matching_fact(
    llm_client: TestClient, case_id: str
) -> None:
    # The checked-in draft fixture cites "fact_1" — matching it here proves
    # the validator accepted a real (fixture) model response end-to-end.
    resp = llm_client.post(
        f"/api/cases/{case_id}/assistant/draft",
        json={
            "facts": [
                {"id": "fact_1", "text": "Recording gap on CH2 from 20:00 to 09:00."}
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    sentences = resp.json()
    assert len(sentences) == 1
    assert sentences[0]["evidence_ids"] == ["fact_1"]
    assert "20:00" in sentences[0]["text"]


def test_draft_drops_sentences_citing_facts_the_request_did_not_send(
    llm_client: TestClient, case_id: str
) -> None:
    # The fixture always cites "fact_1"; if the caller's facts don't
    # include that id, the validator must reject it and the response is an
    # empty (but still schema-valid) list — never a fabricated citation.
    resp = llm_client.post(
        f"/api/cases/{case_id}/assistant/draft",
        json={"facts": [{"id": "fact_other", "text": "Something else entirely."}]},
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_draft_404s_for_unknown_case(llm_client: TestClient) -> None:
    resp = llm_client.post(
        "/api/cases/case_does_not_exist/assistant/draft", json={"facts": []}
    )
    assert resp.status_code == 404


def test_draft_is_disabled_by_default(case_id: str) -> None:
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "examiner", "password": "demo"})
        resp = client.post(f"/api/cases/{case_id}/assistant/draft", json={"facts": []})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "llm_disabled"



# The inference explainer (docs/03-AI-TIMELINE.md §8.3.3) is not wired to an
# HTTP route (see apps/api/pramaan_api/routers/assistant.py's module
# docstring for why) — it's tested directly at the library level in
# tests/ai/test_llm_assistant.py::test_explain_inference_*.
