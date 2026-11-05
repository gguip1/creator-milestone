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
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "Some fields are missing or invalid.",
            {"errors": errors},
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
