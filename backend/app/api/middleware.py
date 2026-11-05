"""Request ids and Idempotency-Key handling for every write under /api.

Clients send a new key per user action and reuse it only when retrying that same action. Responses
below 500 are stored and replayed; a 5xx releases the key so the retry really runs again. The money
path does not depend on this layer: proposal claims and invoice numbers guard it on their own.
"""

import hashlib
import re
import uuid
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import RequestResponseEndpoint

from app.api.errors import error_response
from app.db import session_factory_for
from app.models import IdempotencyRecord, utcnow
from app.services.limits import MINUTE, limits_for
from app.services.visitors import client_ip, read_cookie, settings_for

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_KEY_LENGTH = 128
# Field limits bound each text input; this bounds the whole body, whatever the endpoint.
MAX_BODY_BYTES = 64 * 1024
# Not limited here: liveness, and PayPal's own signed callbacks.
UNLIMITED_PATHS = ("/api/health", "/api/webhooks/paypal")
# A record still unfinished after this long belongs to a crashed request.
IN_PROGRESS_TTL = timedelta(minutes=5)
# Not writes in the sense of this rule: stateless analysis, and a read-through to PayPal that
# must run again on every call. The webhook is authenticated by signature, not by a key.
EXEMPT_PATHS = (
    re.compile(r"^/api/analyze$"),
    re.compile(r"^/api/invoices/[^/]+/refresh$"),
    re.compile(r"^/api/webhooks/paypal$"),
)


def _requires_key(request: Request) -> bool:
    path = request.url.path
    if request.method not in WRITE_METHODS or not path.startswith("/api/"):
        return False
    return not any(pattern.match(path) for pattern in EXEMPT_PATHS)


def _release(request: Request, key: str) -> None:
    with session_factory_for(request.app)() as db:
        record = db.get(IdempotencyRecord, key)
        if record is not None:
            db.delete(record)
            db.commit()


def _begin(request: Request, key: str, fingerprint: str) -> Response | None:
    """Reserve the key, or return the response that answers this request instead."""
    with session_factory_for(request.app)() as db:
        record = db.get(IdempotencyRecord, key)
        if record is not None:
            if record.fingerprint != fingerprint:
                return error_response(
                    request,
                    422,
                    "IDEMPOTENCY_KEY_REUSED",
                    "This Idempotency-Key was already used for a different request.",
                )
            if record.status_code is not None:
                return Response(
                    content=record.response_body,
                    status_code=record.status_code,
                    media_type="application/json",
                    headers={"Idempotency-Replayed": "true"},
                )
            if utcnow() - record.created_at < IN_PROGRESS_TTL:
                return error_response(
                    request,
                    409,
                    "IDEMPOTENCY_IN_PROGRESS",
                    "The first request with this Idempotency-Key is still running.",
                )
            db.delete(record)
            db.flush()
        db.add(IdempotencyRecord(key=key, fingerprint=fingerprint))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return error_response(
                request,
                409,
                "IDEMPOTENCY_IN_PROGRESS",
                "The first request with this Idempotency-Key is still running.",
            )
    return None


def _store(request: Request, key: str, status_code: int, body: bytes) -> None:
    with session_factory_for(request.app)() as db:
        record = db.get(IdempotencyRecord, key)
        if record is not None:
            record.status_code = status_code
            record.response_body = body.decode()
            db.commit()


async def _run_idempotent(request: Request, call_next: RequestResponseEndpoint) -> Response:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        return error_response(
            request,
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            f"Writes need an Idempotency-Key header of 1 to {MAX_KEY_LENGTH} characters.",
        )
    body = await request.body()
    digest = hashlib.sha256()
    for part in (request.method.encode(), request.url.path.encode(), body):
        digest.update(part + b"\0")
    answer = _begin(request, key, digest.hexdigest())
    if answer is not None:
        return answer

    try:
        response = await call_next(request)
        content = b"".join([chunk async for chunk in response.body_iterator])
    except Exception:
        _release(request, key)
        raise
    if response.status_code < 500:
        _store(request, key, response.status_code, content)
    else:
        _release(request, key)
    return Response(
        content=content,
        status_code=response.status_code,
        headers=dict(response.headers),
    )


def _throttle(request: Request) -> Response | None:
    """Judge Mode request-rate limits, per visitor and per IP. Spend caps live next to the spend."""
    path = request.url.path
    if not path.startswith("/api/") or path in UNLIMITED_PATHS:
        return None
    settings = settings_for(request.app)
    if not settings.judge_mode:
        return None
    limits = limits_for(request.app)
    ip = client_ip(request, settings)
    if request.method in WRITE_METHODS:
        visitor = read_cookie(request, settings)
        allowed = limits.allow(f"w:ip:{ip}", settings.limit_writes_per_minute_ip, MINUTE) and (
            visitor is None
            or limits.allow(f"w:v:{visitor}", settings.limit_writes_per_minute_visitor, MINUTE)
        )
    else:
        allowed = limits.allow(f"r:ip:{ip}", settings.limit_reads_per_minute_ip, MINUTE)
    if allowed:
        return None
    return error_response(
        request,
        429,
        "RATE_LIMITED",
        "Too many requests. Wait a moment and try again.",
        {"retry_after_seconds": 30},
    )


async def _too_large(request: Request) -> Response | None:
    if request.method not in WRITE_METHODS or not request.url.path.startswith("/api/"):
        return None
    declared = request.headers.get("content-length", "")
    if declared.isdigit():
        too_big = int(declared) > MAX_BODY_BYTES
    else:
        too_big = len(await request.body()) > MAX_BODY_BYTES
    if not too_big:
        return None
    return error_response(
        request,
        413,
        "PAYLOAD_TOO_LARGE",
        f"That request is too large. The limit is {MAX_BODY_BYTES // 1024} KB.",
    )


async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
    request.state.request_id = uuid.uuid4().hex
    early = await _too_large(request) or _throttle(request)
    if early is not None:
        early.headers["X-Request-Id"] = request.state.request_id
        return early
    if _requires_key(request):
        response = await _run_idempotent(request, call_next)
    else:
        response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response
