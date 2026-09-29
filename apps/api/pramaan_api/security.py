"""Session-cookie auth with seeded demo users (docs/02-BACKEND.md §4, §11).

B1: passwords are argon2-hashed (``argon2-cffi``) rather than compared as
plaintext (the W0.3 stub) — the three seeded users' passwords are still
``demo``, but the check now goes through a real KDF/verify. A signed,
HttpOnly session cookie (``itsdangerous``) is set on login as before. CSRF
(double-submit cookie) is layered on top in ``deps.require_csrf`` and
enforced for mutating routes once ``STUB_MODE=0`` — see that module's
docstring for why it isn't enforced in the Wave-0 stub-mode demo path too.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

Role = Literal["examiner", "reviewer", "admin"]


@dataclass(frozen=True)
class User:
    username: str
    role: Role
    display_name: str


_hasher = PasswordHasher()

# Seeded users (CLAUDE.md / W0.3 task): examiner/demo, reviewer/demo, admin/demo.
# Hashed once at import time (argon2 is deliberately slow; the seed set is
# fixed and tiny, so this costs one hash per role at process start, not per
# login attempt).
_SEED_USERS: dict[str, tuple[str, User]] = {
    "examiner": (_hasher.hash("demo"), User("examiner", "examiner", "Examiner Demo")),
    "reviewer": (_hasher.hash("demo"), User("reviewer", "reviewer", "Reviewer Demo")),
    "admin": (_hasher.hash("demo"), User("admin", "admin", "Admin Demo")),
}


def authenticate(username: str, password: str) -> User | None:
    """Check a login attempt against the seeded users' argon2 hashes.
    ``None`` on failure (unknown user or wrong password).
    """
    entry = _SEED_USERS.get(username)
    if entry is None:
        return None
    password_hash, user = entry
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return None
    return user


def new_csrf_token() -> str:
    """A fresh random CSRF token (double-submit cookie; see
    ``deps.require_csrf``)."""
    return secrets.token_urlsafe(32)


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
