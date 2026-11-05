import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.agent.executor import recover_interrupted
from app.api import api_router
from app.api.deps import paypal_client_for
from app.api.errors import register_error_handlers
from app.api.middleware import request_context
from app.config import get_settings
from app.db import session_factory_for
from app.services.invoice_sync import poll_forever
from app.services.seed import ensure_seller

# Built frontend (vite build output). Served from the same origin as the API in production.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    session_factory = session_factory_for(app)
    with session_factory() as db:
        ensure_seller(db)
        db.commit()
        recover_interrupted(db)

    paypal = paypal_client_for(app, settings)
    poller = None
    if paypal is not None and settings.poll_interval_seconds > 0:
        poller = asyncio.create_task(poll_forever(session_factory, paypal, settings))
    yield
    if poller is not None:
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller
    if paypal is not None:
        await paypal.aclose()


app = FastAPI(title="CreatorMilestone", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)
app.add_middleware(BaseHTTPMiddleware, dispatch=request_context)
app.include_router(api_router)


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = FRONTEND_DIST / path
        if path and candidate.is_file() and FRONTEND_DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
