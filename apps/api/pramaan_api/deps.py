"""FastAPI dependencies: settings, session codec, current user, role guards."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import lru_cache

from fastapi import Depends, Request

from pramaan_api.errors import forbidden, unauthenticated
from pramaan_api.security import Role, SessionCodec, User, get_user
from pramaan_api.settings import Settings, get_settings


@lru_cache
def get_session_codec() -> SessionCodec:
    settings = get_settings()
    return SessionCodec(settings.session_secret, settings.session_max_age_s)


def get_current_user_optional(
    request: Request,
    settings: Settings = Depends(get_settings),
    codec: SessionCodec = Depends(get_session_codec),
) -> User | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    username = codec.decode(token)
    if username is None:
        return None
    return get_user(username)


def get_current_user(user: User | None = Depends(get_current_user_optional)) -> User:
    if user is None:
        raise unauthenticated()
    return user


def require_role(*roles: Role) -> Callable[[User], User]:
    """Dependency factory: 403s unless the current user has one of ``roles``."""

    allowed: Iterable[Role] = roles

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            msg = f"Role '{user.role}' cannot perform this action (requires {sorted(allowed)})."
            raise forbidden(msg)
        return user

    return _check


# Module-level singletons for the common "examiner or admin" mutating-route
# guard (docs/02-BACKEND.md §11: "reviewers cannot run scans"), so route
# signatures can write `Depends(require_examiner_or_admin)` instead of
# calling `require_role(...)` inline in an argument default (ruff B008).
require_examiner_or_admin = require_role("examiner", "admin")
