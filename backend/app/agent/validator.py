"""Deterministic checks every proposal passes before it can run (PRD §7).

Nothing here trusts the proposal payload or any model output: amounts and the recipient are
compared against our own rows, so a proposal cannot bill anything the backend did not compute.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ChangeOrder, Commission, Milestone, PaypalInvoice, Proposal
from app.models.enums import (
    ChangeOrderStatus,
    CommissionStatus,
    MilestoneKind,
    MilestoneState,
    ProposalKind,
)
from app.services.invoices import (
    AWAITING_PAYMENT_STATUSES,
    active_invoice,
    invoice_lines,
    lines_total,
)
from app.services.milestones import plan_milestones
from app.services.money import CURRENCY_EXPONENTS
from app.services.scope import is_valid_email, missing_fields

AWAITING_PAYMENT = "AWAITING_PAYMENT"
MISSING = "MISSING"
MAX_LINE_QUANTITY = 100
BILLABLE_COMMISSION_STATUSES = (CommissionStatus.AGREED, CommissionStatus.IN_PROGRESS)
PAYPAL_KINDS = (
    ProposalKind.BILL_MILESTONE,
    ProposalKind.SEND_INVOICE,
    ProposalKind.SEND_REMINDER,
    ProposalKind.CANCEL_INVOICE,
)


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str


@dataclass
class Verdict:
    stale_reason: str | None = None
    blockers: list[Blocker] = field(default_factory=list)


def invoice_state(invoice: PaypalInvoice) -> str:
    if not invoice.is_active:
        return "INACTIVE"
    if invoice.paypal_status in AWAITING_PAYMENT_STATUSES:
        return AWAITING_PAYMENT
    return invoice.paypal_status or "NOT_CREATED"


def resolve_target(db: Session, target_ref: str):
    entity, _, entity_id = target_ref.partition(":")
    model = {"milestone": Milestone, "invoice": PaypalInvoice, "change_order": ChangeOrder}[entity]
    return db.get(model, entity_id)


def target_state_of(target: Milestone | PaypalInvoice | ChangeOrder | None) -> str:
    if target is None:
        return MISSING
    if isinstance(target, Milestone):
        return target.workflow_state
    if isinstance(target, PaypalInvoice):
        return invoice_state(target)
    return target.status


def stale_reason(db: Session, proposal: Proposal, commission: Commission) -> str | None:
    if commission.status in (CommissionStatus.CANCELLED, CommissionStatus.COMPLETED):
        return f"The commission is {commission.status}."
    if proposal.scope_version != commission.scope_version:
        return (
            f"The scope moved from v{proposal.scope_version} to v{commission.scope_version} "
            "after this was proposed."
        )
    current = target_state_of(resolve_target(db, proposal.target_ref))
    if current != proposal.target_state:
        return f"The target changed from {proposal.target_state} to {current}."
    return None


def _recipient_blockers(email: str | None, settings: Settings) -> list[Blocker]:
    if not email:
        return [Blocker("MISSING_CLIENT_EMAIL", "Add the client's PayPal email first.")]
    if not is_valid_email(email):
        return [Blocker("INVALID_CLIENT_EMAIL", "The client's email address is not valid.")]
    allowed = {address.casefold() for address in settings.recipient_allowlist}
    if settings.judge_mode and email.casefold() not in allowed:
        return [Blocker("RECIPIENT_NOT_ALLOWED", "Judge Mode only bills the demo sandbox buyers.")]
    return []


def _shown_recipient_blockers(proposal: Proposal, commission: Commission) -> list[Blocker]:
    if proposal.payload_json.get("recipient_email") != commission.client_email:
        return [
            Blocker("RECIPIENT_MISMATCH", "This card's recipient is not the agreed client email.")
        ]
    return []


def _check_change_order_lines(change_order: ChangeOrder) -> list[Blocker]:
    lines = change_order.items_json
    if not lines:
        return [Blocker("NO_BILLABLE_LINES", "This change order has no billable lines.")]
    blockers = []
    if any(line.get("needs_price") or not line.get("unit_price_minor_units") for line in lines):
        blockers.append(Blocker("NEEDS_PRICE", "Enter a price for every line without one."))
    elif any(
        line["amount_minor_units"] != line["unit_price_minor_units"] * line["quantity"]
        for line in lines
    ) or change_order.total_minor_units != sum(line["amount_minor_units"] for line in lines):
        blockers.append(Blocker("SUM_MISMATCH", "The change-order lines do not add up."))
    if any(not 1 <= line["quantity"] <= MAX_LINE_QUANTITY for line in lines):
        blockers.append(
            Blocker("INVALID_QUANTITY", f"Quantities must be 1 to {MAX_LINE_QUANTITY}.")
        )
    return blockers


def _check_bill(
    proposal: Proposal, commission: Commission, milestone: Milestone, settings: Settings
) -> list[Blocker]:
    blockers = _recipient_blockers(commission.client_email, settings)
    blockers += _shown_recipient_blockers(proposal, commission)
    if commission.currency_code not in CURRENCY_EXPONENTS:
        blockers.append(Blocker("UNSUPPORTED_CURRENCY", "This currency is not supported."))
    if commission.status not in BILLABLE_COMMISSION_STATUSES:
        blockers.append(Blocker("COMMISSION_NOT_BILLABLE", "Both parties must agree first."))
    if missing_fields(commission):
        blockers.append(Blocker("SCOPE_INCOMPLETE", "Some required terms are missing."))
    if milestone.workflow_state != MilestoneState.READY_TO_BILL:
        blockers.append(Blocker("MILESTONE_NOT_READY", "This milestone is not ready to bill."))
    if milestone.amount_minor_units < 1:
        blockers.append(Blocker("INVALID_AMOUNT", "The amount must be positive."))

    existing = active_invoice(milestone)
    if existing is not None and existing.paypal_invoice_id:
        blockers.append(
            Blocker("DUPLICATE_ACTIVE_INVOICE", "This milestone already has an active invoice.")
        )

    if milestone.kind == MilestoneKind.CHANGE_ORDER:
        change_order = milestone.change_order
        if change_order is None or change_order.status != ChangeOrderStatus.CLIENT_APPROVED:
            blockers.append(
                Blocker("CHANGE_ORDER_NOT_APPROVED", "The client has not approved this change.")
            )
        else:
            blockers += _check_change_order_lines(change_order)
            if change_order.total_minor_units != milestone.amount_minor_units:
                blockers.append(Blocker("SUM_MISMATCH", "The change-order total does not match."))
    elif commission.total_minor_units != sum(
        m.amount_minor_units for m in plan_milestones(commission)
    ):
        blockers.append(Blocker("SUM_MISMATCH", "Plan amounts do not add up to the total."))

    unreliable = ("SUM_MISMATCH", "NEEDS_PRICE", "CHANGE_ORDER_NOT_APPROVED", "NO_BILLABLE_LINES")
    if not any(b.code in unreliable for b in blockers):
        computed = lines_total(invoice_lines(milestone))
        if (
            computed != milestone.amount_minor_units
            or proposal.payload_json.get("amount_minor_units") != computed
        ):
            blockers.append(Blocker("AMOUNT_MISMATCH", "The amount differs from our own math."))
    return blockers


def _check_invoice_action(
    proposal: Proposal, commission: Commission, invoice: PaypalInvoice, settings: Settings
) -> list[Blocker]:
    blockers = []
    if not invoice.paypal_invoice_id:
        blockers.append(Blocker("INVOICE_NOT_CREATED", "No PayPal draft exists yet."))
    if proposal.kind == ProposalKind.SEND_INVOICE:
        blockers += _recipient_blockers(commission.client_email, settings)
        blockers += _shown_recipient_blockers(proposal, commission)
        if invoice.paypal_status != "DRAFT":
            blockers.append(Blocker("INVOICE_NOT_DRAFT", "Only a draft can be sent."))
    elif invoice.paypal_status not in AWAITING_PAYMENT_STATUSES:
        blockers.append(Blocker("INVOICE_NOT_OPEN", "This only applies to a sent, unpaid invoice."))
    return blockers


def validate_proposal(
    db: Session, proposal: Proposal, commission: Commission, settings: Settings
) -> Verdict:
    reason = stale_reason(db, proposal, commission)
    if reason:
        return Verdict(stale_reason=reason)

    target = resolve_target(db, proposal.target_ref)
    blockers: list[Blocker] = []
    if proposal.kind == ProposalKind.BILL_MILESTONE:
        blockers += _check_bill(proposal, commission, target, settings)
    elif proposal.kind == ProposalKind.CHANGE_ORDER:
        blockers += _check_change_order_lines(target)
    else:
        blockers += _check_invoice_action(proposal, commission, target, settings)

    if proposal.kind in PAYPAL_KINDS:
        disabled = commission.seller.billing_disabled_code
        # Retrying the card that hit the 403 is how the seller re-checks the permission.
        if disabled and proposal.error_code != disabled:
            blockers.append(
                Blocker("BILLING_DISABLED", "PayPal refused an earlier action; billing is paused.")
            )
    return Verdict(blockers=blockers)
