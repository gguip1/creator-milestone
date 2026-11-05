"""Approved proposal -> services. This is the only path to a PayPal write (PRD §7)."""

import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.agent.rules import reconcile
from app.agent.validator import MAX_LINE_QUANTITY, resolve_target, validate_proposal
from app.config import Settings
from app.errors import AppError, conflict, invalid
from app.models import ChangeOrder, Milestone, PaypalInvoice, Proposal, utcnow
from app.models.enums import Actor, ProposalKind, ProposalStatus
from app.services import invoices as invoice_service
from app.services.activity import log_activity
from app.services.change_orders import lines_total, seller_approve
from app.services.paypal_client import PayPalClient
from app.services.paypal_errors import NOT_AUTHORIZED, PAYPAL_FAILURES, map_paypal_error
from app.services.state_machines import set_proposal_status

logger = logging.getLogger(__name__)

# Fields a seller may edit, per kind. Amounts and recipients are never among them.
EDITABLE_FIELDS: dict[str, set[str]] = {
    ProposalKind.BILL_MILESTONE: {"note"},
    ProposalKind.SEND_INVOICE: {"subject", "note"},
    ProposalKind.SEND_REMINDER: {"subject", "note"},
    ProposalKind.CANCEL_INVOICE: {"note"},
    ProposalKind.CHANGE_ORDER: {"lines", "remove_line_ids"},
}
EDITABLE_STATUSES = (ProposalStatus.PENDING, ProposalStatus.FAILED)


def _claim(db: Session, proposal: Proposal) -> bool:
    """Atomically take the proposal. Exactly one concurrent approval wins this update."""
    result = db.execute(
        update(Proposal)
        .where(
            Proposal.id == proposal.id,
            Proposal.status.in_((ProposalStatus.PENDING, ProposalStatus.FAILED)),
        )
        .values(
            status=ProposalStatus.APPROVED,
            decided_at=utcnow(),
            error_code=None,
            error_message=None,
        )
    )
    claimed = result.rowcount == 1
    db.commit()
    return claimed


async def _run(
    db: Session, proposal: Proposal, target: Any, paypal: PayPalClient | None, settings: Settings
) -> None:
    commission = proposal.commission
    payload = proposal.payload_json
    match proposal.kind:
        case ProposalKind.CHANGE_ORDER:
            seller_approve(db, commission, target)
        case ProposalKind.BILL_MILESTONE:
            await invoice_service.create_draft(
                db,
                commission,
                target,
                payload["note"],
                invoice_service.terms_for_current_version(db, commission),
                paypal,
                settings,
            )
        case ProposalKind.SEND_INVOICE:
            await invoice_service.send_invoice(
                db,
                commission,
                target,
                paypal,
                subject=payload.get("subject"),
                note=payload.get("note"),
            )
        case ProposalKind.SEND_REMINDER:
            await invoice_service.remind_invoice(
                db,
                commission,
                target,
                paypal,
                subject=payload.get("subject"),
                note=payload.get("note"),
            )
        case ProposalKind.CANCEL_INVOICE:
            await invoice_service.cancel_invoice(
                db, commission, target, paypal, note=payload.get("note")
            )
        case _:
            raise invalid("UNKNOWN_PROPOSAL_KIND", f"Cannot run a {proposal.kind} proposal.")


def _invoice_of(target: Any) -> PaypalInvoice | None:
    if isinstance(target, PaypalInvoice):
        return target
    if isinstance(target, Milestone):
        return invoice_service.active_invoice(target)
    return None


def _record_failure(db: Session, proposal: Proposal, target: Any, error: AppError) -> None:
    db.rollback()
    db.refresh(proposal)
    set_proposal_status(proposal, ProposalStatus.FAILED)
    proposal.error_code = error.code
    proposal.error_message = error.message
    invoice = _invoice_of(target)
    if invoice is not None:
        invoice.last_error_code = error.code
    commission = proposal.commission
    if error.code == NOT_AUTHORIZED:
        commission.seller.billing_disabled_code = NOT_AUTHORIZED
    log_activity(
        db,
        commission,
        Actor.SYSTEM,
        "proposal_failed",
        kind=proposal.kind,
        error_code=error.code,
    )
    db.commit()


async def approve_proposal(
    db: Session, proposal: Proposal, paypal: PayPalClient | None, settings: Settings
) -> Proposal:
    """Run a proposal once. Repeats and concurrent calls get the current state back, no new call."""
    if proposal.status in (ProposalStatus.EXECUTED, ProposalStatus.APPROVED):
        return proposal
    if proposal.status not in EDITABLE_STATUSES:
        raise conflict(
            "PROPOSAL_NOT_ACTIONABLE",
            f"This proposal is {proposal.status} and cannot be approved.",
            {"status": proposal.status},
        )

    commission = proposal.commission
    verdict = validate_proposal(db, proposal, commission, settings)
    if verdict.stale_reason:
        set_proposal_status(proposal, ProposalStatus.STALE)
        log_activity(
            db,
            commission,
            Actor.SYSTEM,
            "proposal_stale",
            kind=proposal.kind,
            reason=verdict.stale_reason,
        )
        reconcile(db, commission, settings)
        db.commit()
        raise conflict("PROPOSAL_STALE", verdict.stale_reason, {"proposal_id": proposal.id})
    if verdict.blockers:
        raise invalid(
            "PROPOSAL_BLOCKED",
            verdict.blockers[0].message,
            {
                "proposal_id": proposal.id,
                "blockers": [{"code": b.code, "message": b.message} for b in verdict.blockers],
            },
        )
    needs_paypal = proposal.kind != ProposalKind.CHANGE_ORDER
    if needs_paypal and paypal is None:
        raise AppError(
            503, "PAYPAL_NOT_CONFIGURED", "PayPal credentials are not configured on this server."
        )

    if not _claim(db, proposal):
        db.refresh(proposal)
        return proposal
    log_activity(db, commission, Actor.SELLER, "proposal_approved", kind=proposal.kind)
    db.commit()

    target = resolve_target(db, proposal.target_ref)
    try:
        await _run(db, proposal, target, paypal, settings)
    except PAYPAL_FAILURES as exc:
        error = map_paypal_error(exc)
        _record_failure(db, proposal, target, error)
        raise AppError(
            error.status_code,
            error.code,
            error.message,
            {**(error.details or {}), "proposal_id": proposal.id, "proposal_status": "FAILED"},
        ) from exc
    except AppError as exc:
        _record_failure(db, proposal, target, exc)
        raise AppError(
            exc.status_code,
            exc.code,
            exc.message,
            {**(exc.details or {}), "proposal_id": proposal.id, "proposal_status": "FAILED"},
        ) from exc

    set_proposal_status(proposal, ProposalStatus.EXECUTED)
    proposal.executed_at = utcnow()
    if needs_paypal:
        commission.seller.billing_disabled_code = None
    log_activity(db, commission, Actor.AGENT, "proposal_executed", kind=proposal.kind)
    reconcile(db, commission, settings)
    db.commit()
    return proposal


def dismiss_proposal(db: Session, proposal: Proposal, settings: Settings) -> Proposal:
    if proposal.status == ProposalStatus.DISMISSED:
        return proposal
    set_proposal_status(proposal, ProposalStatus.DISMISSED)
    proposal.decided_at = utcnow()
    log_activity(db, proposal.commission, Actor.SELLER, "proposal_dismissed", kind=proposal.kind)
    reconcile(db, proposal.commission, settings)
    db.commit()
    return proposal


def _edit_change_order_lines(
    proposal: Proposal,
    change_order: ChangeOrder,
    edits: list[dict[str, Any]],
    remove_ids: list[str],
) -> None:
    lines = [dict(line) for line in change_order.items_json]
    by_id = {line["id"]: line for line in lines}
    unknown = ({edit["id"] for edit in edits} | set(remove_ids)) - set(by_id)
    if unknown:
        raise invalid("UNKNOWN_LINE", "That change-order line does not exist.")
    for edit in edits:
        line = by_id[edit["id"]]
        if edit.get("quantity") is not None:
            if edit["quantity"] > MAX_LINE_QUANTITY:
                raise invalid("INVALID_QUANTITY", f"Quantities must be 1 to {MAX_LINE_QUANTITY}.")
            line["quantity"] = edit["quantity"]
        if edit.get("unit_price_minor_units") is not None:
            line["unit_price_minor_units"] = edit["unit_price_minor_units"]
            line["needs_price"] = False
            line["price_source"] = "seller"
        unit_price = line["unit_price_minor_units"]
        line["amount_minor_units"] = unit_price * line["quantity"] if unit_price else None
    lines = [line for line in lines if line["id"] not in set(remove_ids)]
    change_order.items_json = lines
    change_order.total_minor_units = lines_total(lines)
    proposal.payload_json = {
        **proposal.payload_json,
        "lines": lines,
        "amount_minor_units": change_order.total_minor_units,
    }


def edit_proposal(
    db: Session, proposal: Proposal, changes: dict[str, Any], settings: Settings
) -> Proposal:
    """Seller edits before approval. The result is re-validated when shown and when approved."""
    if proposal.status not in EDITABLE_STATUSES:
        raise conflict(
            "PROPOSAL_NOT_ACTIONABLE",
            f"This proposal is {proposal.status} and cannot be edited.",
            {"status": proposal.status},
        )
    not_editable = set(changes) - EDITABLE_FIELDS.get(proposal.kind, set())
    if not_editable:
        raise invalid(
            "FIELD_NOT_EDITABLE",
            f"{proposal.kind} does not allow editing: {', '.join(sorted(not_editable))}.",
        )
    if proposal.kind == ProposalKind.CHANGE_ORDER:
        target = resolve_target(db, proposal.target_ref)
        _edit_change_order_lines(
            proposal, target, changes.get("lines") or [], changes.get("remove_line_ids") or []
        )
    else:
        proposal.payload_json = {**proposal.payload_json, **changes}
    log_activity(db, proposal.commission, Actor.SELLER, "proposal_edited", kind=proposal.kind)
    reconcile(db, proposal.commission, settings)
    db.commit()
    return proposal


def recover_interrupted(db: Session) -> int:
    """A restart can leave APPROVED rows with nobody running them. Retrying them is safe: the
    executor searches by the stable invoice number and GET-verifies before repeating a write."""
    result = db.execute(
        update(Proposal)
        .where(Proposal.status == ProposalStatus.APPROVED)
        .values(
            status=ProposalStatus.FAILED,
            error_code="INTERRUPTED",
            error_message="The server restarted during this action. Retry it.",
        )
    )
    interrupted = result.rowcount
    db.commit()
    if interrupted:
        logger.warning("Marked %d interrupted proposals as FAILED", interrupted)
    return interrupted
