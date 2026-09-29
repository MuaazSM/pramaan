"""Session auth (docs/02-BACKEND.md §4): ``POST /auth/login``, ``POST
/auth/logout``, ``GET /me``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from pramaan_api.deps import get_current_user, get_session_codec
from pramaan_api.errors import bad_request
from pramaan_api.schemas import LoginRequest, Me
from pramaan_api.security import SessionCodec, User, authenticate, new_csrf_token
from pramaan_api.settings import Settings, get_settings

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=Me)
def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings),
    codec: SessionCodec = Depends(get_session_codec),
) -> Me:
    user = authenticate(body.username, body.password)
    if user is None:
        raise bad_request("Invalid username or password.", {"field": "password"})
    token = codec.encode(user.username)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_max_age_s,
        httponly=True,
        samesite="strict",
        secure=False,  # dev/demo over http; flip on behind TLS in deployment
    )
    # Double-submit CSRF cookie (docs/02-BACKEND.md §11) — readable by JS
    # (not HttpOnly) so the frontend can echo it in X-CSRF-Token. Enforced
    # only in real mode; see pramaan_api.deps.require_csrf.
    response.set_cookie(
        settings.csrf_cookie_name,
        new_csrf_token(),
        max_age=settings.session_max_age_s,
        httponly=False,
        samesite="strict",
        secure=False,
    )
    return Me(username=user.username, role=user.role, display_name=user.display_name)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, settings: Settings = Depends(get_settings)) -> None:
    response.delete_cookie(settings.session_cookie_name)
    response.delete_cookie(settings.csrf_cookie_name)


@router.get("/me", response_model=Me)
def me(user: User = Depends(get_current_user)) -> Me:
    return Me(username=user.username, role=user.role, display_name=user.display_name)
