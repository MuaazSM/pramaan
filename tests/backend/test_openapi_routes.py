"""Acceptance test (docs/PROMPTBOOK.md W0.3): walks every route in
``apps/api/openapi.json`` and validates the response against its declared
JSON schema.

Binary/multipart endpoints (thumbnails, clip streaming, PDFs, export
upload/download) don't have a JSON response schema to validate against —
those are smoke-tested for status code + content type instead, and are
listed explicitly in ``_NON_JSON_PATHS`` so a route can't silently skip
schema validation by accident.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi.testclient import TestClient
from jsonschema import RefResolver
from pramaan_api.fixtures import store

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "apps" / "api" / "openapi.json"


def _spec() -> dict[str, Any]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def _resolver(spec: dict[str, Any]) -> RefResolver:
    return RefResolver.from_schema(spec)


# path template -> (media_type, "binary" | "pdf") for routes with no JSON body.
_NON_JSON_PATHS: dict[tuple[str, str], str] = {
    ("get", "/api/frames/{fid}/thumb"): "image/jpeg",
    ("get", "/api/clips/{clip_id}/stream"): "video/mp4",
    ("get", "/api/reports/{rid}/pdf"): "application/pdf",
    ("get", "/api/reports/{rid}/certificate.pdf"): "application/pdf",
    ("get", "/api/exports/{xid}/file"): "video/mp4",
}

# Routes exercised through their own dedicated test module instead of the
# generic walker: assistant/llm routes 404 by default (LLM_ENABLED=false —
# see test_assistant.py), and the multipart verify endpoint needs a file
# upload rather than a JSON body.
_SKIP_PATHS: set[tuple[str, str]] = {
    ("post", "/api/exports/verify"),
}
_LLM_PATHS: set[tuple[str, str]] = {
    ("post", "/api/cases/{cid}/assistant/query"),
    ("post", "/api/cases/{cid}/assistant/draft"),
    ("get", "/api/llm/usage"),
}


def _path_params(template: str) -> dict[str, str]:
    data = store.DATA
    params = {
        "cid": data.case.id,
        "eid": next(iter(data.evidence)),
        "fid": data.frames[0].frame_id,
        "clip_id": data.clips[0].id,
        "jid": next(iter(data.jobs)),
        "xid": data.exports[0].id,
        "lid": next(iter(data.inferred_layouts)),
        "id": data.clock_models[0].id,
    }
    # "{rid}" means two different things depending on the route
    # (docs/02-BACKEND.md §4: `/recordings/{rid}` vs `/reports/{rid}/...`).
    if template.startswith("/api/recordings/"):
        params["rid"] = data.recordings[0].id
    elif template.startswith("/api/reports/"):
        params["rid"] = data.reports[0].id
    return params


def _fill_path(template: str, params: dict[str, str]) -> str:
    path = template
    for key, value in params.items():
        path = path.replace("{" + key + "}", value)
    return path


# Request bodies for POST/PATCH routes, keyed by (method, path template).
def _request_bodies() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        ("post", "/api/auth/login"): {"username": "examiner", "password": "demo"},
        ("post", "/api/cases/{cid}/assistant/query"): {"question": "what happened on CH2?"},
        ("post", "/api/cases/{cid}/assistant/draft"): {
            "facts": [{"id": "fact_1", "text": "Recording gap on CH2 from 20:00 to 09:00."}]
        },
        ("post", "/api/cases"): {
            "case_number": "CR-2026-0412",
            "title": "Shopfront burglary, Andheri",
        },
        ("patch", "/api/cases/{cid}"): {"title": "Shopfront burglary, Andheri (updated)"},
        ("post", "/api/cases/{cid}/evidence"): {
            "path": "/evidence/new_device.img",
            "label": "Test device",
            "intake": {
                "seized_at_local": "2026-03-12T16:40:00+05:30",
                "dvr_displayed_time": "2026-03-12T16:45:12",
                "reference_time": "2026-03-12T16:40:00+05:30",
                "reference_source": "NTP phone clock",
                "timezone": "Asia/Kolkata",
            },
        },
        ("post", "/api/evidence/{eid}/scan"): {},
        ("post", "/api/cases/{cid}/reports"): {},
        ("post", "/api/cases/{cid}/exports"): {"channel": 1},
        ("post", "/api/cases/{cid}/anchors"): {},
        ("post", "/api/inferred-layouts/{lid}/confirm"): {},
        ("post", "/api/clock-models/{id}/override"): {"reason": "test override"},
        ("post", "/api/cases/{cid}/analytics/run"): {},
    }


def _success_status(operation: dict[str, Any]) -> str:
    for status_code in operation["responses"]:
        if status_code.startswith("2"):
            return status_code
    raise AssertionError(f"No 2xx response documented: {operation}")


@pytest.mark.parametrize(
    "method,template",
    [
        (method, template)
        for template, item in _spec()["paths"].items()
        for method in item
        if method in ("get", "post", "patch", "put", "delete")
    ],
)
def test_route_matches_schema(
    method: str, template: str, examiner_client: TestClient, llm_client: TestClient
) -> None:
    key = (method, template)
    if key in _SKIP_PATHS:
        pytest.skip("exercised in its own test module")

    spec = _spec()
    resolver = _resolver(spec)
    operation = spec["paths"][template][method]

    params = _path_params(template)
    if template == "/api/evidence/{eid}/inferred-layout":
        # Only the secondary (Tier B) evidence image has an inferred layout.
        params = {**params, "eid": store.list_evidence(store.DATA.case.id)[1].id}
    path = _fill_path(template, params)

    client = llm_client if key in _LLM_PATHS else examiner_client
    body = _request_bodies().get(key)
    kwargs: dict[str, Any] = {}
    if body is not None:
        kwargs["json"] = body

    response = client.request(method, path, **kwargs)
    expected_status = _success_status(operation)
    assert response.status_code == int(expected_status), response.text

    if key in _NON_JSON_PATHS:
        assert response.headers["content-type"].startswith(_NON_JSON_PATHS[key])
        return

    response_spec = operation["responses"][expected_status]
    if "content" not in response_spec:
        # e.g. 204 No Content (auth/logout)
        assert response.status_code == 204
        return
    schema = response_spec["content"]["application/json"]["schema"]
    jsonschema.validate(instance=response.json(), schema=schema, resolver=resolver)
