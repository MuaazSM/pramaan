"""Canonical JSON + content-hash ID determinism tests."""

from __future__ import annotations

import hashlib
import json

from pramaan_core.ids import canonical_json, content_hash, content_id


def test_canonical_json_sorts_keys_and_is_compact() -> None:
    obj = {"b": 1, "a": [3, 2, 1], "c": {"y": 1, "x": 2}}
    out = canonical_json(obj)
    assert out == b'{"a":[3,2,1],"b":1,"c":{"x":2,"y":1}}'
    assert json.loads(out) == obj


def test_content_hash_is_deterministic_and_order_independent() -> None:
    h1 = content_hash({"a": 1, "b": 2})
    h2 = content_hash({"b": 2, "a": 1})
    assert h1 == h2
    assert h1 == hashlib.sha256(b'{"a":1,"b":2}').hexdigest()


def test_content_hash_differs_for_different_content() -> None:
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_content_id_format_and_determinism() -> None:
    payload = {"image_id": "img_x", "channel": 1, "start": 0, "offset": 512}
    id1 = content_id("rec", payload)
    id2 = content_id("rec", dict(reversed(list(payload.items()))))
    assert id1 == id2
    assert id1.startswith("rec_")
    assert len(id1) == len("rec_") + 16


def test_content_id_custom_length() -> None:
    id_ = content_id("frame", {"payload": "x"}, length=24)
    assert len(id_) == len("frame_") + 24
