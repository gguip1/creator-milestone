"""PayPal invoice lifecycle: create, send, remind, cancel, and status reconciliation.

Rules verified against the sandbox (docs/paypal-test-log.md):
- A repeated create returns 422 DUPLICATE_INVOICE_NUMBER and does not replay, so the invoice number
  is the duplicate guard and recovery looks the invoice up by that number.
- Send returns one link object {href, rel: "payer-view", method}.
- Cancel only works on sent invoices.
"""

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError, conflict
from app.models import Commission, Milestone, PaypalInvoice, utcnow
from app.models.enums import Actor, CommissionStatus, MilestoneKind, MilestoneState
from app.services.activity import log_activity
from app.services.milestones import complete_if_all_settled, unlock_next_plan_milestone
from app.services.money import MoneyError, from_paypal_value, to_paypal_value
from app.services.paypal_client import InvoiceLine, PayPalClient, PayPalError, build_invoice_payload
from app.services.paypal_errors import DUPLICATE_INVOICE_NUMBER, has_issue
from app.services.paypal_status import describe_status
from app.services.scope import get_snapshot, snapshot_data
from app.services.state_machines import set_commission_status, set_milestone_state

ITEM_NAME_LIMIT = 200
ITEM_DESCRIPTION_LIMIT = 1000
NOTE_LIMIT = 4000

AWAITING_PAYMENT_STATUSES = ("SENT", "UNPAID")
# Worth polling: the buyer can still move these along.
OPEN_STATUSES = ("SENT", "UNPAID", "PAYMENT_PENDING", "PARTIALLY_PAID")


def active_invoice(milestone: Milestone) -> PaypalInvoice | None:
    return next((i for i in milestone.invoices if i.is_active), None)


def next_attempt(milestone: Milestone) -> int:
    return max((i.attempt for i in milestone.invoices if not i.is_active), default=0) + 1


def invoice_lines(milestone: Milestone) -> list[InvoiceLine]:
    """Amounts always come from our rows. Change orders get one line per change-order line."""
    if milestone.kind != MilestoneKind.CHANGE_ORDER:
        return [InvoiceLine(milestone.title[:ITEM_NAME_LIMIT], milestone.amount_minor_units)]
    return [
        InvoiceLine(
            name=line["name"][:ITEM_NAME_LIMIT],
            unit_amount_minor_units=line["unit_price_minor_units"],
            quantity=line["quantity"],
            description=(line.get("request_summary") or "")[:ITEM_DESCRIPTION_LIMIT] or None,
        )
        for line in milestone.change_order.items_json
    ]


def lines_total(lines: list[InvoiceLine]) -> int:
    return sum(line.unit_amount_minor_units * line.quantity for line in lines)


def invoice_note(commission: Commission, milestone: Milestone) -> str:
    what = f"{milestone.title} for {commission.title}"
    if milestone.kind == MilestoneKind.CHANGE_ORDER:
        summary = ", ".join(
            f"{line['name']} x {line['quantity']}" for line in milestone.change_order.items_json
        )
        what = f"{what}: {summary}"
    return f"{what}. Billed under agreed scope v{commission.scope_version}."[:NOTE_LIMIT]


def invoice_terms(snapshot: dict[str, Any]) -> str:
    """Terms of one agreed version, so they travel with the PayPal invoice."""
    parts = [f"Agreed scope v{snapshot['version']}: {snapshot['title']}."]
    if snapshot.get("deliverables"):
        parts.append(f"Deliverables: {'; '.join(snapshot['deliverables'])}.")
    if snapshot.get("file_formats"):
        parts.append(f"File formats: {', '.join(snapshot['file_formats'])}.")
    if snapshot.get("revisions_included") is not None:
        parts.append(f"Revisions included: {snapshot['revisions_included']}.")
    if snapshot.get("usage_rights"):
        parts.append(f"Usage rights: {snapshot['usage_rights']}.")
    if snapshot.get("deadline_date"):
        parts.append(f"Delivery by: {snapshot['deadline_date']}.")
    return " ".join(parts)[:NOTE_LIMIT]


def terms_for_current_version(db: Session, commission: Commission) -> str:
    snapshot = get_snapshot(db, commission, commission.scope_version)
    return invoice_terms(snapshot.snapshot_json if snapshot else snapshot_data(commission))


def start_attempt(db: Session, commission: Commission, milestone: Milestone) -> PaypalInvoice:
    """Reuse the active row while no PayPal invoice is known, so its number survives retries."""
    invoice = active_invoice(milestone)
    if invoice is not None:
        return invoice
    attempt = next_attempt(milestone)
    invoice = PaypalInvoice(
        commission=commission,
        milestone=milestone,
        attempt=attempt,
        billed_scope_version=commission.scope_version,
        amount_minor_units=milestone.amount_minor_units,
        currency_code=commission.currency_code,
        # PayPal caps invoice numbers at 25 characters; this format stays at or under 22.
        invoice_number=f"CM-{commission.id[:8]}-{milestone.id[:6]}-{attempt}",
    )
    db.add(invoice)
    db.flush()
    return invoice


def _store_invoice(db: Session, invoice: PaypalInvoice, remote: dict[str, Any]) -> None:
    invoice.paypal_invoice_id = remote["id"]
    invoice.paypal_status = remote.get("status")
    invoice.last_synced_at = utcnow()
    invoice.last_error_code = None
    db.flush()


def _adoption_mismatch(
    invoice: PaypalInvoice, recipient: str, remote: dict[str, Any]
) -> str | None:
    """A found invoice is only ours if it bills the same person the same amount."""
    recipients = remote.get("primary_recipients") or []
    emails = [r.get("billing_info", {}).get("email_address") for r in recipients]
    if emails and recipient.casefold() not in {str(e).casefold() for e in emails}:
        return "recipient"
    amount = remote.get("amount") or {}
    if amount.get("value") is not None:
        try:
            found = from_paypal_value(str(amount["value"]), invoice.currency_code)
        except MoneyError:
            return "amount"
        if found != invoice.amount_minor_units:
            return "amount"
    return None


async def _find_existing(
    invoice: PaypalInvoice, recipient: str, paypal: PayPalClient
) -> dict[str, Any] | None:
    matches = await paypal.find_invoices_by_number(invoice.invoice_number)
    match = next(
        (
            m
            for m in matches
            if m.get("detail", {}).get("invoice_number", invoice.invoice_number)
            == invoice.invoice_number
        ),
        None,
    )
    if match is None:
        return None
    remote = await paypal.get_invoice(match["id"])
    mismatch = _adoption_mismatch(invoice, recipient, remote)
    if mismatch:
        raise conflict(
            "INVOICE_NUMBER_CONFLICT",
            f"PayPal already holds invoice {invoice.invoice_number} with a different {mismatch}, "
            "so it was not adopted.",
            {"invoice_number": invoice.invoice_number, "mismatch": mismatch},
        )
    return remote


async def create_draft(
    db: Session,
    commission: Commission,
    milestone: Milestone,
    note: str,
    terms: str,
    paypal: PayPalClient,
    settings: Settings,
) -> PaypalInvoice:
    invoice = start_attempt(db, commission, milestone)
    if invoice.paypal_invoice_id:
        return invoice
    recipient = commission.client_email or ""

    # An earlier attempt may have reached PayPal even though we never saw the answer.
    previously_attempted = invoice.create_attempted_at is not None
    invoice.create_attempted_at = utcnow()
    db.commit()
    remote = await _find_existing(invoice, recipient, paypal) if previously_attempted else None
    adopted = remote is not None

    if remote is None:
        payload = build_invoice_payload(
            invoice_number=invoice.invoice_number,
            currency_code=invoice.currency_code,
            recipient_email=recipient,
            lines=invoice_lines(milestone),
            note=note,
            terms_and_conditions=terms,
            invoicer_email=settings.paypal_invoicer_email or None,
            invoicer_business_name=commission.seller_display_name,
        )
        try:
            remote = await paypal.create_draft_invoice(
                payload, request_id=invoice.create_request_id
            )
        except PayPalError as exc:
            if not has_issue(exc, DUPLICATE_INVOICE_NUMBER):
                raise
            remote = await _find_existing(invoice, recipient, paypal)
            if remote is None:
                raise
            adopted = True
        except httpx.TransportError:
            remote = await _find_existing(invoice, recipient, paypal)
            if remote is None:
                raise
            adopted = True

    if not adopted:
        invoice.billed_scope_version = commission.scope_version
    _store_invoice(db, invoice, remote)
    log_activity(
        db,
        commission,
        Actor.PAYPAL,
        "invoice_adopted" if adopted else "invoice_draft_created",
        invoice_number=invoice.invoice_number,
        paypal_invoice_id=invoice.paypal_invoice_id,
        amount_minor_units=invoice.amount_minor_units,
    )
    apply_remote_status(db, commission, invoice, remote)
    return invoice


def _payer_link(body: dict[str, Any]) -> str | None:
    if body.get("rel") == "payer-view" and body.get("href"):
        return body["href"]
    for link in body.get("links", []):
        if link.get("rel") == "payer-view":
            return link.get("href")
    return body.get("detail", {}).get("metadata", {}).get("recipient_view_url")


async def send_invoice(
    db: Session,
    commission: Commission,
    invoice: PaypalInvoice,
    paypal: PayPalClient,
    *,
    subject: str | None = None,
    note: str | None = None,
) -> None:
    remote_id = invoice.paypal_invoice_id
    previously_attempted = invoice.send_attempted_at is not None
    invoice.send_attempted_at = utcnow()
    db.commit()

    if previously_attempted:
        # The last send may have landed without us seeing the answer.
        remote = await paypal.get_invoice(remote_id)
        if remote.get("status") != "DRAFT":
            _finish_send(db, commission, invoice, remote)
            return

    try:
        body = await paypal.send_invoice(
            remote_id, request_id=invoice.send_request_id, subject=subject, note=note
        )
    except httpx.TransportError:
        remote = await paypal.get_invoice(remote_id)
        if remote.get("status") == "DRAFT":
            raise
        _finish_send(db, commission, invoice, remote)
        return

    link = _payer_link(body)
    if link:
        # Keep it before verifying: a failed GET must not lose the only copy of the link.
        invoice.payer_link = link
        db.commit()

    remote = await paypal.get_invoice(remote_id)
    if remote.get("status") == "DRAFT":
        raise AppError(
            502, "INVOICE_NOT_SENT", "PayPal accepted the send, but the invoice is still a draft."
        )
    _finish_send(db, commission, invoice, remote)


def _finish_send(
    db: Session, commission: Commission, invoice: PaypalInvoice, remote: dict[str, Any]
) -> None:
    invoice.payer_link = invoice.payer_link or _payer_link(remote)
    apply_remote_status(db, commission, invoice, remote)


async def remind_invoice(
    db: Session,
    commission: Commission,
    invoice: PaypalInvoice,
    paypal: PayPalClient,
    *,
    subject: str | None = None,
    note: str | None = None,
) -> None:
    db.commit()
    await paypal.remind_invoice(invoice.paypal_invoice_id, subject=subject, note=note)
    invoice.reminders_sent += 1
    invoice.last_reminded_at = utcnow()
    invoice.last_error_code = None
    log_activity(
        db,
        commission,
        Actor.PAYPAL,
        "invoice_reminder_sent",
        invoice_number=invoice.invoice_number,
        reminders_sent=invoice.reminders_sent,
    )


async def cancel_invoice(
    db: Session,
    commission: Commission,
    invoice: PaypalInvoice,
    paypal: PayPalClient,
    *,
    note: str | None = None,
) -> None:
    remote_id = invoice.paypal_invoice_id
    db.commit()
    # Look first: a retry after a lost answer must not cancel twice.
    remote = await paypal.get_invoice(remote_id)
    if remote.get("status") != "CANCELLED":
        await paypal.cancel_invoice(remote_id, note=note)
        remote = await paypal.get_invoice(remote_id)
    apply_remote_status(db, commission, invoice, remote)


def apply_remote_status(
    db: Session, commission: Commission, invoice: PaypalInvoice, remote: dict[str, Any]
) -> None:
    """Record PayPal's status and move the workflow. Only PAID settles a milestone."""
    raw = remote.get("status")
    previous = invoice.paypal_status
    now = utcnow()
    invoice.paypal_status = raw
    invoice.last_synced_at = now
    invoice.last_error_code = None
    if raw != previous and previous is not None:
        log_activity(
            db,
            commission,
            Actor.PAYPAL,
            "invoice_status_changed",
            invoice_number=invoice.invoice_number,
            status=raw,
            label=describe_status(raw).label,
        )
    if not invoice.is_active:
        return

    milestone = invoice.milestone
    leaves_draft = raw not in (None, "DRAFT", "SCHEDULED", "CANCELLED")
    if leaves_draft and invoice.sent_at is None:
        invoice.sent_at = now
    if leaves_draft and milestone.workflow_state == MilestoneState.READY_TO_BILL:
        set_milestone_state(milestone, MilestoneState.BILLED)
        if commission.status == CommissionStatus.AGREED:
            set_commission_status(commission, CommissionStatus.IN_PROGRESS)
        log_activity(
            db,
            commission,
            Actor.SYSTEM,
            "milestone_billed",
            milestone=milestone.title,
            invoice_number=invoice.invoice_number,
            amount=to_paypal_value(invoice.amount_minor_units, invoice.currency_code),
        )

    if describe_status(raw).settles_milestone and milestone.workflow_state == MilestoneState.BILLED:
        invoice.paid_seen_at = now
        set_milestone_state(milestone, MilestoneState.SETTLED)
        log_activity(db, commission, Actor.PAYPAL, "milestone_settled", milestone=milestone.title)
        unlock_next_plan_milestone(db, commission)
        complete_if_all_settled(db, commission)
    elif raw == "CANCELLED":
        invoice.is_active = False
        if milestone.workflow_state == MilestoneState.BILLED:
            set_milestone_state(milestone, MilestoneState.READY_TO_BILL)
            log_activity(
                db, commission, Actor.SYSTEM, "milestone_reopened", milestone=milestone.title
            )
    db.flush()


async def fetch_and_apply(
    db: Session, commission: Commission, invoice: PaypalInvoice, paypal: PayPalClient
) -> None:
    """On-demand or polled refresh. Drops the answer if our row moved while we were waiting."""
    before = invoice.paypal_status
    remote_id = invoice.paypal_invoice_id
    db.commit()
    remote = await paypal.get_invoice(remote_id)
    db.refresh(invoice)
    if invoice.paypal_status != before:
        return
    apply_remote_status(db, commission, invoice, remote)
