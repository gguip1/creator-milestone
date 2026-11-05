"""Judge Mode shortcuts. They replay real steps (terms, both acceptances) without waiting for
typing, and they never invent PayPal state.

"Paid" is adopted only from a real sandbox invoice named by DEMO_PAID_INVOICE_ID: PayPal is asked
live, and the milestone settles only if PayPal answers PAID with the amount this deposit expects.
Otherwise the project stays in its plain, usable state and says why.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.agent.rules import reconcile
from app.config import Settings
from app.errors import conflict
from app.models import Commission, Milestone, PaypalInvoice
from app.models.enums import (
    Actor,
    CommissionStatus,
    MilestoneState,
    ProposalKind,
    ProposalStatus,
)
from app.services.activity import log_activity
from app.services.invoices import apply_remote_status
from app.services.milestones import deliver_milestone, plan_milestones
from app.services.money import MoneyError, from_paypal_value
from app.services.paypal_client import PayPalClient
from app.services.paypal_errors import PAYPAL_FAILURES
from app.services.scope import accept_as_client, accept_as_seller, edit_scope, missing_fields
from app.services.seed import suggested_recipient
from app.services.state_machines import set_proposal_status

DEMO_TERMS = {
    "title": "Full-body illustration for VTuber debut",
    "deliverables": ["Full-body illustration"],
    "file_formats": ["PNG (transparent)", "PSD (layered)"],
    "revisions_included": 2,
    "deadline_date": date(2026, 11, 25),
    "usage_rights": "Personal use",
    "total_minor_units": 30000,
}


@dataclass(frozen=True)
class JumpResult:
    applied: bool
    message: str


def _not_applied(message: str) -> JumpResult:
    return JumpResult(False, message)


def _agree(db: Session, commission: Commission, recipient: str) -> None:
    if commission.status == CommissionStatus.AGREED:
        return
    changes = {name: DEMO_TERMS[name] for name in missing_fields(commission) if name in DEMO_TERMS}
    if not commission.file_formats_json:
        changes["file_formats"] = DEMO_TERMS["file_formats"]
    if "client_email" in missing_fields(commission):
        changes["client_email"] = recipient
    edit_scope(db, commission, changes)
    accept_as_seller(db, commission, commission.scope_version)
    accept_as_client(db, commission, commission.scope_version)
    log_activity(db, commission, Actor.SYSTEM, "demo_jump_agreed")


async def _adopt_paid_deposit(
    db: Session,
    commission: Commission,
    deposit: Milestone,
    paypal: PayPalClient | None,
    settings: Settings,
) -> JumpResult | None:
    """None on success; otherwise why nothing was marked paid."""
    invoice_id = settings.demo_paid_invoice_id
    if not invoice_id or paypal is None:
        return _not_applied(
            "No previously paid sandbox invoice is configured here, so nothing was marked paid. "
            "Bill the deposit with the card below and pay it as the sandbox buyer."
        )
    db.commit()
    try:
        remote = await paypal.get_invoice(invoice_id)
    except PAYPAL_FAILURES:
        return _not_applied(
            "PayPal could not confirm the saved sandbox invoice just now, so nothing was marked "
            "paid. Bill the deposit with the card below instead."
        )
    amount = remote.get("amount") or {}
    try:
        paid_amount = from_paypal_value(amount.get("value", ""), amount.get("currency_code", ""))
    except MoneyError:  # A malformed answer is simply "not confirmed".
        paid_amount = None
    if (
        remote.get("status") != "PAID"
        or amount.get("currency_code") != commission.currency_code
        or paid_amount != deposit.amount_minor_units
    ):
        return _not_applied(
            "PayPal does not show the saved sandbox invoice as paid for this deposit amount, so "
            "nothing was marked paid. Bill the deposit with the card below instead."
        )
    invoice = PaypalInvoice(
        commission=commission,
        milestone=deposit,
        attempt=1,
        billed_scope_version=commission.scope_version,
        amount_minor_units=deposit.amount_minor_units,
        currency_code=commission.currency_code,
        paypal_invoice_id=invoice_id,
        adopted=True,
        invoice_number=f"CM-{commission.id[:8]}-{deposit.id[:6]}-1",
    )
    db.add(invoice)
    db.flush()
    log_activity(
        db, commission, Actor.SYSTEM, "demo_paid_invoice_adopted", paypal_invoice_id=invoice_id
    )
    # The billing card is moot now that PayPal confirmed this deposit as paid.
    for card in commission.proposals:
        if card.kind == ProposalKind.BILL_MILESTONE and card.status == ProposalStatus.PENDING:
            set_proposal_status(card, ProposalStatus.DISMISSED)
    apply_remote_status(db, commission, invoice, remote)
    return None


async def run_jump(
    db: Session,
    commission: Commission,
    target: str,
    paypal: PayPalClient | None,
    settings: Settings,
) -> JumpResult:
    recipient = suggested_recipient(settings)
    if recipient is None:
        raise conflict("DEMO_RECIPIENT_MISSING", "No sandbox buyer is configured for this demo.")
    if commission.invoices or commission.status not in (
        CommissionStatus.DRAFT,
        CommissionStatus.AWAITING_ACCEPTANCE,
        CommissionStatus.AGREED,
    ):
        raise conflict(
            "DEMO_JUMP_UNAVAILABLE", "Shortcuts only work on a fresh project. Reset the demo first."
        )
    _agree(db, commission, recipient)
    reconcile(db, commission, settings)

    deposit = plan_milestones(commission)[0]
    if deposit.workflow_state != MilestoneState.READY_TO_BILL:
        return _not_applied("The scope is agreed. The deposit is ready to bill.")
    failure = await _adopt_paid_deposit(db, commission, deposit, paypal, settings)
    if failure is not None:
        return failure
    message = "Deposit paid via a previously paid sandbox invoice, confirmed with PayPal just now."
    if target == "sketch_shared":
        sketch = plan_milestones(commission)[1]
        if sketch.workflow_state == MilestoneState.AWAITING_DELIVERY:
            deliver_milestone(db, sketch, None, "Sketch shared (demo shortcut)")
            message += " The sketch is logged as shared, so the client can approve it."
            # The demo story: both included revisions were used in the sketch round. Recorded
            # openly in the activity log so Scope Guard prices the next request from real state.
            used = commission.revisions_included or 0
            if commission.revisions_used < used:
                commission.revisions_used = used
                log_activity(
                    db,
                    commission,
                    Actor.SYSTEM,
                    "demo_revisions_logged",
                    revisions_used=used,
                    revisions_included=used,
                )
                message += (
                    f" It also records {used} of {used} revisions as used in the sketch round."
                )
    return JumpResult(True, message)
