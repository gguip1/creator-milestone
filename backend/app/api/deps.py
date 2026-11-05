"""FastAPI dependencies. Tests override these to inject a fake PayPal and fake AI functions."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy.orm import Session

from app.agent.cached import load_cached_intake
from app.agent.intake import analyze_intake
from app.agent.scope_guard import cached_scope_guard, guard_scope
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AppError, not_found
from app.models import ChangeOrder, Commission, Milestone, PaypalInvoice, Proposal
from app.schemas.ai import IntakeAnalysis, LLMUnavailableError, ScopeGuardResult
from app.services.limits import DAY, HOUR, MINUTE, limits_for, rate_limited
from app.services.paypal_client import PayPalClient
from app.services.visitors import UNSCOPED, Viewer, client_ip, issue_cookie, read_cookie

IntakeAnalyzer = Callable[..., Awaitable[IntakeAnalysis]]
ScopeGuard = Callable[..., Awaitable[ScopeGuardResult]]


def paypal_client_for(app: FastAPI, settings: Settings) -> PayPalClient | None:
    """One shared client, so the OAuth token cache survives between requests."""
    if not settings.paypal_configured:
        return None
    client = getattr(app.state, "paypal_client", None)
    if client is None:
        client = PayPalClient(
            settings.paypal_base_url,
            settings.paypal_client_id,
            settings.paypal_client_secret.get_secret_value(),
        )
        app.state.paypal_client = client
    return client


def get_paypal_client(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> PayPalClient | None:
    return paypal_client_for(request.app, settings)


def get_intake_analyzer() -> IntakeAnalyzer:
    return analyze_intake


def get_scope_guard() -> ScopeGuard:
    return guard_scope


def get_today() -> date:
    """Relative dates in client messages resolve against this explicit "today"."""
    return datetime.now(UTC).date()


DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PayPalDep = Annotated[PayPalClient | None, Depends(get_paypal_client)]
IntakeDep = Annotated[IntakeAnalyzer, Depends(get_intake_analyzer)]
ScopeGuardDep = Annotated[ScopeGuard, Depends(get_scope_guard)]
TodayDep = Annotated[date, Depends(get_today)]

# NotImplementedError covers the AI layer until it is merged: the caller sees the same clear error.
LLM_FAILURES = (LLMUnavailableError, NotImplementedError)


def llm_unavailable() -> AppError:
    return AppError(
        503,
        "LLM_UNAVAILABLE",
        "The AI service is not available right now. Nothing was changed; try again shortly.",
    )


def require_paypal(paypal: PayPalClient | None) -> PayPalClient:
    if paypal is None:
        raise AppError(
            503, "PAYPAL_NOT_CONFIGURED", "PayPal credentials are not configured on this server."
        )
    return paypal


def get_viewer(
    request: Request, response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> Viewer:
    """Judge Mode: the visitor named by the signed cookie, issuing one on first contact."""
    if not settings.judge_mode:
        return UNSCOPED
    visitor_id = read_cookie(request, settings) or issue_cookie(response, settings)
    return Viewer(id=visitor_id, scoped=True)


ViewerDep = Annotated[Viewer, Depends(get_viewer)]


def get_commission(db: Session, project_id: str, viewer: Viewer) -> Commission:
    """Another visitor's project is indistinguishable from one that does not exist."""
    commission = db.get(Commission, project_id)
    if commission is None or not viewer.owns(commission.visitor_id):
        raise not_found("Project")
    return commission


def get_milestone(db: Session, milestone_id: str, viewer: Viewer) -> Milestone:
    milestone = db.get(Milestone, milestone_id)
    if milestone is None or not viewer.owns(milestone.commission.visitor_id):
        raise not_found("Milestone")
    return milestone


def get_invoice(db: Session, invoice_id: str, viewer: Viewer) -> PaypalInvoice:
    invoice = db.get(PaypalInvoice, invoice_id)
    if invoice is None or not viewer.owns(invoice.commission.visitor_id):
        raise not_found("Invoice")
    return invoice


def get_proposal(db: Session, proposal_id: str, viewer: Viewer) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None or not viewer.owns(proposal.commission.visitor_id):
        raise not_found("Proposal")
    return proposal


def get_change_order(db: Session, commission: Commission, change_order_id: str) -> ChangeOrder:
    change_order = db.get(ChangeOrder, change_order_id)
    if change_order is None or change_order.commission_id != commission.id:
        raise not_found("Change order")
    return change_order


def llm_cap_reached() -> AppError:
    return AppError(
        503,
        "LLM_DAILY_CAP",
        "The demo's daily AI budget is used up. Saved analysis still works for the two example "
        "messages; other text can be analyzed again tomorrow.",
    )


class LlmGate:
    """Judge Mode spend control around every LLM-backed request.

    Short windows and the per-visitor daily cap answer 429. The global daily cap falls back to the
    recorded analysis of the demo messages, and otherwise answers a clear 503.
    """

    def __init__(self, request: Request, settings: Settings, viewer: Viewer) -> None:
        self.settings = settings
        self.limits = limits_for(request.app)
        self.visitor = viewer.id or "anon"
        self.ip = client_ip(request, settings)

    def _admit(self) -> str | None:
        """None to go live; "visitor" or "global" when a daily cap says use the cache."""
        s, limits = self.settings, self.limits
        if not s.judge_mode:
            return None
        if limits.full(f"llm-min:v:{self.visitor}", s.limit_llm_per_minute_visitor, MINUTE) or (
            limits.full(f"llm-min:ip:{self.ip}", s.limit_llm_per_minute_ip, MINUTE)
        ):
            raise rate_limited("Too many AI requests in a minute. Wait a moment and retry.", 30)
        if limits.full(f"llm-day:v:{self.visitor}", s.limit_llm_per_day_visitor, DAY):
            return "visitor"
        if limits.full("llm-day:global", s.limit_llm_per_day_global, DAY):
            return "global"
        limits.record(f"llm-min:v:{self.visitor}", MINUTE)
        limits.record(f"llm-min:ip:{self.ip}", MINUTE)
        limits.record(f"llm-day:v:{self.visitor}", DAY)
        limits.record("llm-day:global", DAY)
        return None

    @staticmethod
    def _capped(reason: str) -> AppError:
        if reason == "visitor":
            return rate_limited("You have used today's AI budget for this demo.", 3600)
        return llm_cap_reached()

    async def intake(
        self, analyzer: IntakeAnalyzer, message: str, *, today: date
    ) -> IntakeAnalysis:
        capped = self._admit()
        if capped is None:
            return await analyzer(message, today=today)
        cached = load_cached_intake(message)
        if cached is None:
            raise self._capped(capped)
        return cached

    async def guard(self, guard: ScopeGuard, message: str, **kwargs) -> ScopeGuardResult:
        capped = self._admit()
        if capped is None:
            return await guard(message, **kwargs)
        try:
            return cached_scope_guard(message, **kwargs)
        except LLMUnavailableError:
            raise self._capped(capped) from None


def get_llm_gate(request: Request, settings: SettingsDep, viewer: ViewerDep) -> LlmGate:
    return LlmGate(request, settings, viewer)


LlmGateDep = Annotated[LlmGate, Depends(get_llm_gate)]


def take_invoice_slot(request: Request, settings: Settings, viewer: Viewer) -> None:
    """Judge Mode caps real PayPal invoice creation per visitor per hour and globally per day."""
    if not settings.judge_mode:
        return
    limits = limits_for(request.app)
    visitor = f"inv-hour:v:{viewer.id}"
    if limits.full(visitor, settings.limit_invoices_per_hour_visitor, HOUR):
        raise rate_limited("This demo allows a few invoices per hour. Try again later.", HOUR)
    if limits.full("inv-day:global", settings.limit_invoices_per_day_global, DAY):
        raise rate_limited("The demo reached today's invoice limit. Try again tomorrow.", HOUR)
    limits.record(visitor, HOUR)
    limits.record("inv-day:global", DAY)
