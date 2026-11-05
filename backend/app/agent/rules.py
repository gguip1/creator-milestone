"""Rule-generated proposals (PRD §7). No model is involved in anything here except change orders,
whose lines were already reduced to rate-card math by `sanitize_guard_result`.

`reconcile` is level-triggered: it looks at the current state and makes the proposal list match.
Every mutation calls it, so "a bill proposal appears" and "pending cards go stale" cannot be missed.
Idempotency keys contain the scope version and attempt, so a dismissed card stays dismissed until
something meaningful changes.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.validator import AWAITING_PAYMENT, invoice_state, stale_reason
from app.config import Settings
from app.errors import conflict
from app.models import ChangeOrder, Commission, Milestone, PaypalInvoice, Proposal, new_id, utcnow
from app.models.enums import (
    Actor,
    CommissionStatus,
    MilestoneKind,
    MilestoneState,
    ProposalKind,
    ProposalStatus,
)
from app.schemas.ai import ScopeGuardResult
from app.services.activity import log_activity
from app.services.change_orders import supersede_outdated
from app.services.invoices import (
    AWAITING_PAYMENT_STATUSES,
    active_invoice,
    invoice_lines,
    invoice_note,
    lines_total,
    next_attempt,
    terms_for_current_version,
)
from app.services.money import to_paypal_value
from app.services.state_machines import set_proposal_status

# Proposals in these states block a new card for the same target.
LIVE_STATUSES = (ProposalStatus.PENDING, ProposalStatus.APPROVED, ProposalStatus.FAILED)


def _ensure_proposal(
    db: Session,
    commission: Commission,
    *,
    kind: ProposalKind,
    key: str,
    payload: dict[str, Any],
    rationale: str,
    target_ref: str,
    target_state: str,
    evidence: list[dict[str, Any]] | None = None,
    model_id: str | None = None,
) -> Proposal:
    existing = db.scalar(select(Proposal).where(Proposal.idempotency_key == key))
    if existing is not None:
        return existing
    proposal = Proposal(
        commission_id=commission.id,
        kind=kind,
        payload_json=payload,
        rationale=rationale,
        evidence_json=evidence or [],
        scope_version=commission.scope_version,
        target_ref=target_ref,
        target_state=target_state,
        idempotency_key=key,
        model_id=model_id,
    )
    commission.proposals.append(proposal)
    db.flush()
    log_activity(
        db, commission, Actor.AGENT, "proposal_created", kind=str(kind), rationale=rationale
    )
    return proposal


def _bill_rationale(milestone: Milestone) -> str:
    if milestone.kind == MilestoneKind.CHANGE_ORDER:
        return f"The client approved {milestone.title.lower()}, so it is ready to bill."
    if milestone.approved_at is not None:
        return f"The client approved the delivery for {milestone.title.lower()}."
    return f"The commission is agreed, so {milestone.title.lower()} is ready to bill."


def _bill_evidence(milestone: Milestone, commission: Commission) -> list[dict[str, Any]]:
    if milestone.kind != MilestoneKind.CHANGE_ORDER:
        return [{"type": "clause", "ref": "scope", "text": f"Scope v{commission.scope_version}"}]
    return [_line_evidence(line) for line in milestone.change_order.items_json]


def _line_evidence(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "quote",
        "quote": line.get("quote"),
        "ref": line.get("clause_ref"),
        "text": line.get("clause_text"),
    }


def bill_payload(db: Session, commission: Commission, milestone: Milestone) -> dict[str, Any]:
    lines = invoice_lines(milestone)
    return {
        "milestone_id": milestone.id,
        "milestone_title": milestone.title,
        "recipient_email": commission.client_email,
        "amount_minor_units": lines_total(lines),
        "currency_code": commission.currency_code,
        "scope_version": commission.scope_version,
        "lines": [
            {
                "name": line.name,
                "quantity": line.quantity,
                "unit_amount_minor_units": line.unit_amount_minor_units,
                "amount_minor_units": line.unit_amount_minor_units * line.quantity,
            }
            for line in lines
        ],
        "note": invoice_note(commission, milestone),
        "terms_and_conditions": terms_for_current_version(db, commission),
    }


def propose_bill(
    db: Session, commission: Commission, milestone: Milestone, *, key_suffix: str = ""
) -> Proposal:
    attempt = next_attempt(milestone)
    return _ensure_proposal(
        db,
        commission,
        kind=ProposalKind.BILL_MILESTONE,
        key=f"bill:{milestone.id}:v{commission.scope_version}:a{attempt}{key_suffix}",
        payload=bill_payload(db, commission, milestone),
        rationale=_bill_rationale(milestone),
        evidence=_bill_evidence(milestone, commission),
        target_ref=f"milestone:{milestone.id}",
        target_state=milestone.workflow_state,
    )


def _invoice_payload(commission: Commission, invoice: PaypalInvoice) -> dict[str, Any]:
    return {
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "paypal_invoice_id": invoice.paypal_invoice_id,
        "milestone_id": invoice.milestone_id,
        "milestone_title": invoice.milestone.title,
        "recipient_email": commission.client_email,
        "amount_minor_units": invoice.amount_minor_units,
        "currency_code": invoice.currency_code,
        "billed_scope_version": invoice.billed_scope_version,
    }


def _reminder_text(commission: Commission, invoice: PaypalInvoice) -> dict[str, str]:
    amount = to_paypal_value(invoice.amount_minor_units, invoice.currency_code)
    who = commission.client_display_name or "there"
    return {
        "subject": f"Reminder: invoice {invoice.invoice_number}",
        "note": (
            f"Hi {who}, a friendly reminder that {invoice.milestone.title.lower()} for "
            f"{commission.title} ({invoice.currency_code} {amount}) is still open. "
            f"Thank you! - {commission.seller_display_name}"
        ),
    }


def propose_next_step(db: Session, commission: Commission, milestone: Milestone) -> Proposal:
    """Bring back a card the seller dismissed: send an existing draft, otherwise bill."""
    if commission.status not in (CommissionStatus.AGREED, CommissionStatus.IN_PROGRESS):
        raise conflict("COMMISSION_NOT_ACTIVE", f"The commission is {commission.status}.")
    if milestone.workflow_state != MilestoneState.READY_TO_BILL:
        raise conflict("MILESTONE_NOT_READY", "This milestone is not ready to bill.")
    live = _live_proposal(commission, milestone)
    if live is not None:
        return live
    suffix = f":{new_id()[:8]}"
    invoice = active_invoice(milestone)
    if invoice is not None and invoice.paypal_invoice_id:
        return _propose_send(db, commission, invoice, key_suffix=suffix)
    return propose_bill(db, commission, milestone, key_suffix=suffix)


def propose_cancel(db: Session, commission: Commission, invoice: PaypalInvoice) -> Proposal:
    """Seller-initiated. It still has to be approved like every other PayPal write."""
    if invoice.paypal_status == "DRAFT":
        raise conflict(
            "CANNOT_CANCEL_DRAFT_INVOICE", "PayPal can only cancel an invoice that has been sent."
        )
    if not invoice.is_active or invoice.paypal_status not in AWAITING_PAYMENT_STATUSES:
        raise conflict("INVOICE_NOT_OPEN", "Only a sent, unpaid invoice can be cancelled.")
    ref = f"invoice:{invoice.id}"
    for proposal in commission.proposals:
        if (
            proposal.kind == ProposalKind.CANCEL_INVOICE
            and proposal.target_ref == ref
            and proposal.status in LIVE_STATUSES
        ):
            return proposal
    return _ensure_proposal(
        db,
        commission,
        kind=ProposalKind.CANCEL_INVOICE,
        key=f"cancel:{invoice.id}:{new_id()[:8]}",
        payload=_invoice_payload(commission, invoice),
        rationale="The seller asked to cancel this invoice.",
        target_ref=ref,
        target_state=AWAITING_PAYMENT,
    )


def propose_change_order(
    db: Session,
    commission: Commission,
    change_order: ChangeOrder,
    result: ScopeGuardResult,
) -> Proposal:
    return _ensure_proposal(
        db,
        commission,
        kind=ProposalKind.CHANGE_ORDER,
        key=f"change_order:{change_order.id}",
        payload=change_order_payload(commission, change_order, result),
        rationale=(
            f"The client asked for {len(change_order.items_json)} item(s) beyond the agreed scope."
        ),
        evidence=[_line_evidence(line) for line in change_order.items_json],
        target_ref=f"change_order:{change_order.id}",
        target_state=change_order.status,
        model_id=result.model_id,
    )


def change_order_payload(
    commission: Commission, change_order: ChangeOrder, result: ScopeGuardResult
) -> dict[str, Any]:
    return {
        "change_order_id": change_order.id,
        "number": change_order.number,
        "currency_code": commission.currency_code,
        "lines": change_order.items_json,
        "amount_minor_units": change_order.total_minor_units,
        # Shown for context only. These never reach an invoice.
        "not_billed": [
            {
                "request_summary": item.request_summary,
                "classification": item.classification,
                "quote": item.quote,
                "clause_ref": item.clause_ref,
            }
            for item in result.items
            if not item.billable
        ],
    }


def _live_proposal(commission: Commission, milestone: Milestone) -> Proposal | None:
    """The open bill or send card for this milestone, if there is one."""
    refs = {f"milestone:{milestone.id}", *(f"invoice:{i.id}" for i in milestone.invoices)}
    kinds = (ProposalKind.BILL_MILESTONE, ProposalKind.SEND_INVOICE)
    return next(
        (
            p
            for p in commission.proposals
            if p.kind in kinds and p.target_ref in refs and p.status in LIVE_STATUSES
        ),
        None,
    )


def _ensure_billing_proposals(db: Session, commission: Commission) -> None:
    for milestone in commission.milestones:
        invoice = active_invoice(milestone)
        if (
            milestone.workflow_state == MilestoneState.READY_TO_BILL
            and (invoice is None or not invoice.paypal_invoice_id)
            and milestone.amount_minor_units >= 1
            and _live_proposal(commission, milestone) is None
        ):
            propose_bill(db, commission, milestone)


def _propose_send(
    db: Session, commission: Commission, invoice: PaypalInvoice, *, key_suffix: str = ""
) -> Proposal:
    return _ensure_proposal(
        db,
        commission,
        kind=ProposalKind.SEND_INVOICE,
        key=f"send:{invoice.id}:v{commission.scope_version}{key_suffix}",
        payload=_invoice_payload(commission, invoice),
        rationale=f"The draft for {invoice.milestone.title.lower()} is ready to send.",
        target_ref=f"invoice:{invoice.id}",
        target_state=invoice_state(invoice),
    )


def _ensure_send_proposals(db: Session, commission: Commission) -> None:
    for invoice in commission.invoices:
        if invoice.is_active and invoice.paypal_invoice_id and invoice.paypal_status == "DRAFT":
            _propose_send(db, commission, invoice)


def _ensure_reminder_proposals(db: Session, commission: Commission, settings: Settings) -> None:
    threshold = timedelta(minutes=settings.reminder_threshold_minutes)
    now = utcnow()
    for invoice in commission.invoices:
        if not invoice.is_active or invoice.paypal_status not in AWAITING_PAYMENT_STATUSES:
            continue
        waiting_since = invoice.last_reminded_at or invoice.sent_at
        if waiting_since is None or now - waiting_since < threshold:
            continue
        _ensure_proposal(
            db,
            commission,
            kind=ProposalKind.SEND_REMINDER,
            key=(f"remind:{invoice.id}:{invoice.reminders_sent + 1}:v{commission.scope_version}"),
            payload={
                **_invoice_payload(commission, invoice),
                **_reminder_text(commission, invoice),
            },
            rationale=(
                f"This invoice has been unpaid for over {settings.reminder_threshold_minutes} "
                "minutes."
            ),
            target_ref=f"invoice:{invoice.id}",
            target_state=AWAITING_PAYMENT,
        )


def mark_stale_proposals(db: Session, commission: Commission) -> None:
    db.flush()
    for proposal in commission.proposals:
        if proposal.status not in (ProposalStatus.PENDING, ProposalStatus.FAILED):
            continue
        reason = stale_reason(db, proposal, commission)
        if reason:
            set_proposal_status(proposal, ProposalStatus.STALE)
            log_activity(
                db, commission, Actor.SYSTEM, "proposal_stale", kind=proposal.kind, reason=reason
            )


def reconcile(db: Session, commission: Commission, settings: Settings) -> None:
    """Bring the proposal list in line with the current state. Call after every mutation."""
    db.flush()
    supersede_outdated(db, commission)
    mark_stale_proposals(db, commission)
    if commission.status in (CommissionStatus.AGREED, CommissionStatus.IN_PROGRESS):
        _ensure_billing_proposals(db, commission)
        _ensure_send_proposals(db, commission)
        _ensure_reminder_proposals(db, commission, settings)
    db.flush()
