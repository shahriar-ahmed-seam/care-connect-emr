"""Consistent error envelope and exception handlers.

Every error response uses the envelope shape:

    { "error": { "code": str, "message": str, "field"?: str } }

``code`` is a stable machine-readable identifier (e.g. ``validation-error``,
``authentication-required``, ``authorization-error``, ``not-found``,
``internal-error``). ``field`` is included only when an error refers to a
specific input field (Requirements 1.3, 1.4, 10.4, etc.).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

class AppError(Exception):
    """Domain error that maps directly onto the error envelope.

    Raise this from service/route code to return a controlled error response.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        field: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field

def error_payload(
    code: str, message: str, field: Optional[str] = None
) -> dict[str, Any]:
    """Build the error-envelope body."""
    error: dict[str, Any] = {"code": code, "message": message}
    if field is not None:
        error["field"] = field
    return {"error": error}

def _envelope_response(
    status_code: int, code: str, message: str, field: Optional[str] = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(code, message, field),
    )

_STATUS_CODE_MAP: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad-request",
    status.HTTP_401_UNAUTHORIZED: "authentication-required",
    status.HTTP_403_FORBIDDEN: "authorization-error",
    status.HTTP_404_NOT_FOUND: "not-found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "validation-error",
}

def register_error_handlers(app: FastAPI) -> None:
    """Attach the envelope-producing exception handlers to the app."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope_response(exc.status_code, exc.code, exc.message, exc.field)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _STATUS_CODE_MAP.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _envelope_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:

        first = exc.errors()[0] if exc.errors() else None
        field = None
        message = "Invalid request"
        if first:
            loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query")]
            field = ".".join(loc) if loc else None
            message = first.get("msg", message)
        return _envelope_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation-error",
            message,
            field,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        return _envelope_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal-error",
            "An unexpected error occurred",
        )
