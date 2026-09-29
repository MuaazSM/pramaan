"""Session-cookie auth with seeded demo users (docs/02-BACKEND.md §4, §11).

Wave 0 scope: a signed, HttpOnly session cookie (via ``itsdangerous``) around
three seeded users, one per role. Password hashing (argon2) and CSRF tokens
are full-B1 concerns (02 §11) and are noted as known gaps in
``docs/progress/W0.3.md`` — this stub compares plaintext passwords against an
in-memory seed so WEB can build the login screen tonight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

Role = Literal["examiner", "reviewer", "admin"]


@dataclass(frozen=True)
class User:
    username: str
    role: Role
    display_name: str


# Seeded users (CLAUDE.md / W0.3 task): examiner/demo, reviewer/demo, admin/demo.
_SEED_USERS: dict[str, tuple[str, User]] = {
    "examiner": ("demo", User("examiner", "examiner", "Examiner Demo")),
    "reviewer": ("demo", User("reviewer", "reviewer", "Reviewer Demo")),
    "admin": ("demo", User("admin", "admin", "Admin Demo")),
}


def authenticate(username: str, password: str) -> User | None:
    """Check a login attempt against the seeded users. ``None`` on failure."""
    entry = _SEED_USERS.get(username)
    if entry is None:
        return None
    expected_password, user = entry
    if password != expected_password:
        return None
    return user


def get_user(username: str) -> User | None:
    entry = _SEED_USERS.get(username)
    return entry[1] if entry else None


class SessionCodec:
    """Signs/verifies the session cookie payload ``{"u": username}``."""

    def __init__(self, secret: str, max_age_s: int) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt="pramaan.session")
        self._max_age_s = max_age_s

    def encode(self, username: str) -> str:
        value = self._serializer.dumps({"u": username})
        assert isinstance(value, str)
        return value

    def decode(self, token: str) -> str | None:
        try:
            data = self._serializer.loads(token, max_age=self._max_age_s)
        except (BadSignature, SignatureExpired):
            return None
        username = data.get("u")
        return username if isinstance(username, str) else None
