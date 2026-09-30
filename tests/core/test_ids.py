"""Canonical JSON + content-hash ID determinism tests."""

from __future__ import annotations

import hashlib
import json

from pramaan_core.ids import canonical_json, content_hash, content_id
from pramaan_core.ids import frame_id as make_frame_id


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


# --- FIX-3: frame ids must be unique per physical frame, not per payload ---


def test_frame_id_differs_for_identical_payload_at_different_offsets() -> None:
    """Two distinct physical frames (e.g. a carved duplicate) that happen to
    share identical payload bytes must not collapse onto the same id
    (docs/progress/QD.md's finding: pre-FIX-3, frame_id was a pure hash of
    the payload, so this case silently merged unrelated frames anywhere a
    caller keyed a dict/set by frame_id)."""
    same_payload_sha256 = hashlib.sha256(b"identical-frame-bytes").hexdigest()
    id_a = make_frame_id("img_" + "a" * 16, offset=1000, payload_sha256=same_payload_sha256)
    id_b = make_frame_id("img_" + "a" * 16, offset=2000, payload_sha256=same_payload_sha256)
    assert id_a != id_b


def test_frame_id_is_deterministic_across_runs() -> None:
    """The same physical frame (same image, same offset, same bytes) must
    always re-derive the same id (CLAUDE.md rule 5: determinism)."""
    payload_sha256 = hashlib.sha256(b"some frame payload").hexdigest()
    id1 = make_frame_id("img_" + "b" * 16, offset=4096, payload_sha256=payload_sha256)
    id2 = make_frame_id("img_" + "b" * 16, offset=4096, payload_sha256=payload_sha256)
    assert id1 == id2


def test_frame_id_differs_for_different_image() -> None:
    """Same offset and bytes on two different images must not collide
    either — the id is scoped per-image, not just per-offset."""
    payload_sha256 = hashlib.sha256(b"shared bytes").hexdigest()
    id_a = make_frame_id("img_" + "a" * 16, offset=512, payload_sha256=payload_sha256)
    id_b = make_frame_id("img_" + "b" * 16, offset=512, payload_sha256=payload_sha256)
    assert id_a != id_b


def test_frame_id_format() -> None:
    payload_sha256 = hashlib.sha256(b"x").hexdigest()
    id_ = make_frame_id("img_" + "a" * 16, offset=0, payload_sha256=payload_sha256)
    assert id_.startswith("frm_")
    assert len(id_) == len("frm_") + 24
