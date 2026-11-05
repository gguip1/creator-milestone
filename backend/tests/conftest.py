"""Every test runs against a temp SQLite file, a fake PayPal, and fake AI functions.

Settings skip backend/.env on purpose, so no test can read real credentials or reach PayPal.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_intake_analyzer, get_paypal_client, get_scope_guard, get_today
from app.config import Settings, get_settings
from app.db import make_session_factory
from app.main import app
from app.schemas.ai import (
    ExtractedField,
    IntakeAnalysis,
    RateCardEntry,
    ScopeContext,
    ScopeGuardItem,
    ScopeGuardResult,
)
from app.services.seed import ensure_seller
from tests.fake_paypal import FakePayPal

BUYER = "buyer@example.com"
TODAY = date(2026, 11, 5)


def message_two_result() -> ScopeGuardResult:
    """The PRD §5 classification of message 2."""
    return ScopeGuardResult(
        items=[
            ScopeGuardItem(
                request_summary="Second outfit (casual hoodie version)",
                quote="add a second outfit, maybe a casual hoodie version",
                classification="out_of_scope",
                clause_ref="deliverables",
                clause_text="One full-body illustration",
                rate_card_code="extra_outfit",
                billable=True,
            ),
            ScopeGuardItem(
                request_summary="One more pass on the face",
                quote="one more pass on the face",
                classification="exceeds_limit",
                clause_ref="revisions",
                clause_text="2 revisions included",
                rate_card_code="extra_revision",
                billable=True,
            ),
            ScopeGuardItem(
                request_summary="Merch use later",
                quote="I might use it on merch later",
                classification="question",
                clause_ref="usage_rights",
                clause_text="Personal streaming",
                rate_card_code="commercial_license",
                billable=False,
            ),
        ],
        reply_draft_client="Thanks! Here is what is included and what the extras cost.",
        reply_draft_seller_translation="(translated reply)",
        source="live",
        model_id="fake-model",
    )


def empty_field(value: str | None = None) -> ExtractedField:
    return ExtractedField(value=value, provenance="unknown" if value is None else "explicit")


def intake_result() -> IntakeAnalysis:
    return IntakeAnalysis(
        source_language="en",
        title=empty_field("Full-body illustration"),
        deliverables=[empty_field("One full-body illustration")],
        file_formats=[empty_field("PNG"), empty_field("PSD")],
        deadline=empty_field("2026-11-25"),
        revisions=empty_field(),
        usage_rights=empty_field(),
        budget=empty_field("USD 300"),
        budget_minor_units=30000,
        currency_code="USD",
        client_email=empty_field(),
        sketch_review_requested=empty_field("yes"),
        questions=["How many revisions?"],
        reply_draft_client="Thanks for reaching out!",
        reply_draft_seller_translation="(translated reply)",
        source="live",
        model_id="fake-model",
    )


@dataclass
class FakeAI:
    guard_result: ScopeGuardResult = field(default_factory=message_two_result)
    guard_error: Exception | None = None
    intake_error: Exception | None = None
    guard_calls: list[dict[str, Any]] = field(default_factory=list)

    async def analyze(self, message: str, *, today: date) -> IntakeAnalysis:
        if self.intake_error:
            raise self.intake_error
        return intake_result()

    async def guard(
        self,
        message: str,
        *,
        scope: ScopeContext,
        rate_card: list[RateCardEntry],
        today: date,
    ) -> ScopeGuardResult:
        self.guard_calls.append({"message": message, "scope": scope, "rate_card": rate_card})
        if self.guard_error:
            raise self.guard_error
        return self.guard_result


class Api:
    """HTTP helper: asserts the status and adds a fresh Idempotency-Key to each write."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def request(
        self, method: str, path: str, *, json: Any = None, expect: int | None = None, key=None
    ) -> Any:
        headers = {"Idempotency-Key": key or uuid4().hex} if method != "GET" else {}
        response = await self.client.request(method, path, json=json, headers=headers)
        if expect is not None:
            assert response.status_code == expect, response.text
        return response.json()

    async def get(self, path: str, *, expect: int = 200) -> Any:
        return await self.request("GET", path, expect=expect)

    async def post(self, path: str, json: Any = None, *, expect: int = 200, key=None) -> Any:
        return await self.request("POST", path, json=json, expect=expect, key=key)

    async def patch(self, path: str, json: Any, *, expect: int = 200) -> Any:
        return await self.request("PATCH", path, json=json, expect=expect)

    async def put(self, path: str, json: Any, *, expect: int = 200) -> Any:
        return await self.request("PUT", path, json=json, expect=expect)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        paypal_client_id="",
        paypal_invoicer_email="",
        paypal_sandbox_buyer_email="",
        judge_mode=False,
        recipient_allowlist=[],
        reminder_threshold_minutes=60,
    )


@pytest.fixture
def fake_paypal() -> FakePayPal:
    return FakePayPal()


@pytest.fixture
def fake_ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    # A file, not :memory:, so concurrent requests get separate connections as in production.
    return make_session_factory(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture(autouse=True)
def wired_app(
    session_factory: sessionmaker[Session],
    settings: Settings,
    fake_paypal: FakePayPal,
    fake_ai: FakeAI,
) -> Iterator[None]:
    client = fake_paypal.client()
    app.state.session_factory = session_factory
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_paypal_client] = lambda: client
    app.dependency_overrides[get_intake_analyzer] = lambda: fake_ai.analyze
    app.dependency_overrides[get_scope_guard] = lambda: fake_ai.guard
    app.dependency_overrides[get_today] = lambda: TODAY
    with session_factory() as db:
        ensure_seller(db)
        db.commit()
    yield
    app.dependency_overrides.clear()
    app.state.session_factory = None


@pytest.fixture
async def api() -> AsyncIterator[Api]:
    # Handled errors become responses; an unhandled one is a 500 the test can assert on.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield Api(client)


SCOPE = {
    "title": "VTuber debut illustration",
    "client_display_name": "Mika",
    "client_email": BUYER,
    "deliverables": ["One full-body illustration"],
    "file_formats": ["PNG", "PSD"],
    "revisions_included": 2,
    "deadline_date": "2026-11-25",
    "usage_rights": "Personal streaming",
    "total_minor_units": 30000,
}


@pytest.fixture
def scope() -> dict[str, Any]:
    return dict(SCOPE)


@pytest.fixture
def make_project(api: Api, scope: dict[str, Any]) -> Callable[..., Any]:
    async def _make(**overrides: Any) -> dict[str, Any]:
        return await api.post("/api/projects", {**scope, **overrides}, expect=201)

    return _make


@pytest.fixture
def make_agreed(api: Api, make_project: Callable[..., Any]) -> Callable[..., Any]:
    """A project both parties accepted. Returns the seller's view."""

    async def _make(**overrides: Any) -> dict[str, Any]:
        project = await make_project(**overrides)
        await api.post(f"/api/projects/{project['id']}/accept")
        await api.post(
            f"/api/c/{project['share_token']}/accept",
            {"scope_version": project["scope_version"]},
        )
        return await api.get(f"/api/projects/{project['id']}")

    return _make


def pending(project: dict[str, Any], kind: str) -> dict[str, Any]:
    matches = [p for p in project["proposals"] if p["kind"] == kind and p["status"] == "PENDING"]
    assert len(matches) == 1, [(p["kind"], p["status"]) for p in project["proposals"]]
    return matches[0]


async def bill_and_send(api: Api, project_id: str) -> dict[str, Any]:
    """Approve the pending bill card, then its send card. Returns the refreshed project."""
    project = await api.get(f"/api/projects/{project_id}")
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    project = await api.get(f"/api/projects/{project_id}")
    await api.post(f"/api/proposals/{pending(project, 'SEND_INVOICE')['id']}/approve")
    return await api.get(f"/api/projects/{project_id}")
