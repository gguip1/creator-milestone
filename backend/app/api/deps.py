"""FastAPI dependencies. Tests override these to inject a fake PayPal and fake AI functions."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from sqlalchemy.orm import Session

from app.agent.intake import analyze_intake
from app.agent.scope_guard import guard_scope
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import AppError, not_found
from app.models import ChangeOrder, Commission, Milestone, PaypalInvoice, Proposal
from app.schemas.ai import IntakeAnalysis, LLMUnavailableError, ScopeGuardResult
from app.services.paypal_client import PayPalClient

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


def get_commission(db: Session, project_id: str) -> Commission:
    commission = db.get(Commission, project_id)
    if commission is None:
        raise not_found("Project")
    return commission


def get_milestone(db: Session, milestone_id: str) -> Milestone:
    milestone = db.get(Milestone, milestone_id)
    if milestone is None:
        raise not_found("Milestone")
    return milestone


def get_invoice(db: Session, invoice_id: str) -> PaypalInvoice:
    invoice = db.get(PaypalInvoice, invoice_id)
    if invoice is None:
        raise not_found("Invoice")
    return invoice


def get_proposal(db: Session, proposal_id: str) -> Proposal:
    proposal = db.get(Proposal, proposal_id)
    if proposal is None:
        raise not_found("Proposal")
    return proposal


def get_change_order(db: Session, commission: Commission, change_order_id: str) -> ChangeOrder:
    change_order = db.get(ChangeOrder, change_order_id)
    if change_order is None or change_order.commission_id != commission.id:
        raise not_found("Change order")
    return change_order
