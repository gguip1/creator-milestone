"""Judge Mode visitor identity: a signed cookie that names the visitor's own demo project.

The cookie holds a random id and an HMAC of it. It carries no data and grants nothing beyond
"you are this visitor", so every seller route checks ownership against it.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response

from app.config import Settings

COOKIE_NAME = "cm_visitor"
COOKIE_MAX_AGE = 60 * 60 * 24 * 45  # Judging runs until Dec 15.

_boot_secret = secrets.token_bytes(32)


@dataclass(frozen=True)
class Viewer:
    """Who is asking. `scoped` is False outside Judge Mode, where nothing is cookie-scoped."""

    id: str | None
    scoped: bool

    def owns(self, visitor_id: str | None) -> bool:
        return not self.scoped or visitor_id == self.id


UNSCOPED = Viewer(id=None, scoped=False)


def _key(settings: Settings) -> bytes:
    configured = settings.session_secret.get_secret_value()
    return configured.encode() if configured else _boot_secret


def _sign(settings: Settings, visitor_id: str) -> str:
    return hmac.new(_key(settings), visitor_id.encode(), hashlib.sha256).hexdigest()[:32]


def read_cookie(request: Request, settings: Settings) -> str | None:
    raw = request.cookies.get(COOKIE_NAME, "")
    visitor_id, _, signature = raw.partition(".")
    if not visitor_id or not signature or len(visitor_id) > 64:
        return None
    return visitor_id if hmac.compare_digest(signature, _sign(settings, visitor_id)) else None


def issue_cookie(response: Response, settings: Settings) -> str:
    visitor_id = secrets.token_hex(16)
    response.set_cookie(
        COOKIE_NAME,
        f"{visitor_id}.{_sign(settings, visitor_id)}",
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        path="/",
    )
    return visitor_id


def client_ip(request: Request, settings: Settings) -> str:
    """The address a trusted proxy saw. Entries a client put at the front of X-Forwarded-For are
    ignored: only the last `trusted_proxy_hops` entries were appended by our own proxy chain.
    The global daily caps remain the backstop if this is still wrong."""
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_hops
    if hops <= 0:
        return peer
    parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return parts[-hops] if len(parts) >= hops else peer


def settings_for(app: FastAPI) -> Settings:
    from app.config import get_settings

    return app.dependency_overrides.get(get_settings, get_settings)()
