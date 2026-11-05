"""Uniform error body: {code, message, request_id, details?}. Handlers never echo request input."""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.errors import AppError

logger = logging.getLogger(__name__)

HTTP_ERROR_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    headers = {"X-Request-Id": request_id}
    if status_code == 429 and details and "retry_after_seconds" in details:
        headers["Retry-After"] = str(details["retry_after_seconds"])
    return JSONResponse(body, status_code=status_code, headers=headers)


FIELD_NAMES = {
    "message": "The message",
    "body": "The message",
    "title": "The title",
    "description": "The description",
    "usage_rights": "Usage rights",
    "client_email": "The client email",
    "client_display_name": "The client name",
    "note": "The note",
    "subject": "The subject",
    "evidence_url": "The link",
}


def _limit_message(errors: list[dict[str, Any]]) -> str | None:
    """A sentence naming the real limit of the first over-length input. Never the input."""
    for error in errors:
        context = error.get("ctx") or {}
        field = next((str(p) for p in reversed(error["loc"]) if not isinstance(p, int)), "")
        name = FIELD_NAMES.get(field, "That field")
        if error["type"] == "string_too_long" and "max_length" in context:
            return f"{name} is too long. The limit is {context['max_length']:,} characters."
        if error["type"] == "too_long" and "max_length" in context:
            return f"{name} has too many entries. The limit is {context['max_length']:,}."
    return None


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Only location and reason: the rejected input can hold emails or message text.
        errors = [
            {"loc": [str(part) for part in e["loc"]], "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        details: dict[str, Any] = {"errors": errors}
        limit_message = _limit_message(exc.errors())
        if limit_message:
            limits = [
                e["ctx"]["max_length"] for e in exc.errors() if "max_length" in (e.get("ctx") or {})
            ]
            details["max_length"] = limits[0]
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            limit_message or "Some fields are missing or invalid.",
            details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The type only. A traceback's locals or message could carry customer data.
        logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return error_response(
            request, 500, "INTERNAL_ERROR", "Something went wrong on our side. Try again."
        )
