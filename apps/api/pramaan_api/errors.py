"""Typed error envelope (docs/02-BACKEND.md §4: ``{"error": {...}}``).

Every non-2xx JSON response from this API uses this shape so the frontend
can render one error component everywhere.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    """Raise this from any route/dependency; the handler below serialises it."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

    def to_response(self) -> ErrorResponse:
        detail = ErrorDetail(code=self.code, message=self.message, details=self.details)
        return ErrorResponse(error=detail)


def not_found(kind: str, ident: str) -> ApiError:
    return ApiError(
        status.HTTP_404_NOT_FOUND,
        "not_found",
        f"{kind} '{ident}' was not found.",
        {"kind": kind, "id": ident},
    )


def forbidden(message: str = "You do not have permission to do that.") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def unauthenticated(message: str = "Sign in required.") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "unauthenticated", message)


def bad_request(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, "bad_request", message, details)


def unprocessable(
    message: str, code: str = "unprocessable", details: dict[str, Any] | None = None
) -> ApiError:
    """A well-formed request that the server understood but cannot carry
    out against the current evidence state (task FIX-4) — e.g. a signed
    export request for a recording whose frames can't be stream-copied
    into a valid MP4 (a real, evidence-side gap, not a client input
    error). Distinct from :func:`bad_request` (400: the request itself
    was invalid) so the frontend can tell the two apart.
    """
    return ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, code, message, details)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    body = exc.to_response().model_dump(mode="json")
    return JSONResponse(status_code=exc.status_code, content=body)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    payload = ErrorResponse(
        error=ErrorDetail(
            code="validation_error",
            message="Request did not match the expected schema.",
            details={"errors": jsonable_encoder(exc.errors())},
        )
    )
    body = payload.model_dump(mode="json")
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=body)
