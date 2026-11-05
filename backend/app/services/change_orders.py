"""Change orders: from a Scope Guard result to scope vN+1 and a billable milestone.

The model only maps requests to rate-card codes and quantities. Everything here that touches money
is recomputed from our own rate card, whatever the Scope Guard returned.
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import conflict
from app.models import ChangeOrder, ClientMessage, Commission, Milestone, RateCardItem
from app.models.enums import (
    Actor,
    BillingTrigger,
    ChangeOrderStatus,
    CommissionStatus,
    MessageKind,
    MilestoneKind,
    MilestoneState,
)
from app.schemas.ai import RateCardEntry, ScopeGuardItem, ScopeGuardResult
from app.services.activity import log_activity
from app.services.scope import write_snapshot
from app.services.state_machines import set_change_order_status

BILLABLE_CLASSIFICATIONS = ("out_of_scope", "exceeds_limit")
OPEN_STATUSES = (ChangeOrderStatus.DRAFT, ChangeOrderStatus.SELLER_APPROVED)
# Seeded rate-card codes whose effect on the agreed scope is known. Other lines add a deliverable.
EXTRA_REVISION_CODE = "extra_revision"
COMMERCIAL_LICENSE_CODE = "commercial_license"


def rate_card_entries(db: Session, seller_id: str) -> list[RateCardEntry]:
    items = db.scalars(
        select(RateCardItem)
        .where(RateCardItem.seller_id == seller_id, RateCardItem.active)
        .order_by(RateCardItem.unit_price_minor_units.desc())
    )
    return [
        RateCardEntry(
            code=item.code,
            name=item.name,
            unit_price_minor_units=item.unit_price_minor_units,
            unit=item.unit,
        )
        for item in items
    ]


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_message(quote: str, message: str) -> bool:
    needle = _normalized(quote)
    return bool(needle) and needle in _normalized(message)


def sanitize_guard_result(
    result: ScopeGuardResult, message: str, rate_card: list[RateCardEntry]
) -> ScopeGuardResult:
    """The trust boundary: amounts, billability, and quote checks are decided here, not upstream."""
    prices = {entry.code: entry for entry in rate_card}
    items = []
    total = 0
    for item in result.items:
        verified = quote_in_message(item.quote, message)
        billable = item.billable and item.classification in BILLABLE_CLASSIFICATIONS and verified
        entry = prices.get(item.rate_card_code) if item.rate_card_code else None
        unit_price = entry.unit_price_minor_units if entry else None
        amount = unit_price * item.quantity if billable and unit_price is not None else None
        total += amount or 0
        items.append(
            item.model_copy(
                update={
                    "quote_verified": verified,
                    "billable": billable,
                    "unit_price_minor_units": unit_price,
                    "amount_minor_units": amount,
                    "needs_price": billable and entry is None,
                }
            )
        )
    return result.model_copy(update={"items": items, "total_minor_units": total})


def _line_from_item(
    index: int, item: ScopeGuardItem, prices: dict[str, RateCardEntry]
) -> dict[str, Any]:
    entry = prices.get(item.rate_card_code) if item.rate_card_code else None
    return {
        "id": f"l{index}",
        "request_summary": item.request_summary,
        "quote": item.quote,
        "classification": item.classification,
        "clause_ref": item.clause_ref,
        "clause_text": item.clause_text,
        "rate_card_code": entry.code if entry else None,
        "name": entry.name if entry else item.request_summary,
        "quantity": item.quantity,
        "unit_price_minor_units": item.unit_price_minor_units,
        "amount_minor_units": item.amount_minor_units,
        "needs_price": item.needs_price,
        "price_source": "rate_card" if entry else None,
    }


def lines_total(lines: list[dict[str, Any]]) -> int:
    return sum(line["amount_minor_units"] or 0 for line in lines)


def ensure_message_not_billed(db: Session, commission: Commission, body: str) -> None:
    """Pasting a message whose extras were already approved must not bill them a second time."""
    existing = db.scalars(
        select(ChangeOrder)
        .join(ClientMessage, ChangeOrder.message_id == ClientMessage.id)
        .where(
            ChangeOrder.commission_id == commission.id,
            ChangeOrder.status == ChangeOrderStatus.CLIENT_APPROVED,
            ClientMessage.body == body,
        )
    ).first()
    if existing is not None:
        raise conflict(
            "MESSAGE_ALREADY_BILLED",
            f"Change order #{existing.number} already covers this message.",
            {"change_order_id": existing.id},
        )


def record_message(
    db: Session, commission: Commission, body: str, language: str | None, analysis: dict[str, Any]
) -> ClientMessage:
    """Re-pasting a follow-up reuses its row, so a new change order can supersede the old one."""
    message = db.scalar(
        select(ClientMessage).where(
            ClientMessage.commission_id == commission.id,
            ClientMessage.kind == MessageKind.FOLLOW_UP,
            ClientMessage.body == body,
        )
    )
    if message is None:
        message = ClientMessage(
            commission_id=commission.id, body=body, language=language, kind=MessageKind.FOLLOW_UP
        )
        db.add(message)
    message.analysis_json = analysis
    db.flush()
    return message


def create_change_order(
    db: Session, commission: Commission, message: ClientMessage, result: ScopeGuardResult
) -> ChangeOrder | None:
    """Create a DRAFT from a sanitized result. Billable lines only; questions are never billed."""
    for older in commission.change_orders:
        if older.message_id == message.id and older.status in OPEN_STATUSES:
            set_change_order_status(older, ChangeOrderStatus.SUPERSEDED)

    billable = [item for item in result.items if item.billable]
    if not billable:
        return None

    prices = {entry.code: entry for entry in rate_card_entries(db, commission.seller_id)}
    lines = [_line_from_item(i, item, prices) for i, item in enumerate(billable, start=1)]
    change_order = ChangeOrder(
        commission_id=commission.id,
        message_id=message.id,
        number=max((co.number for co in commission.change_orders), default=0) + 1,
        items_json=lines,
        total_minor_units=lines_total(lines),
        base_scope_version=commission.scope_version,
    )
    commission.change_orders.append(change_order)
    db.flush()
    log_activity(
        db,
        commission,
        Actor.AGENT,
        "change_order_proposed",
        number=change_order.number,
        total_minor_units=change_order.total_minor_units,
    )
    return change_order


def supersede_outdated(db: Session, commission: Commission) -> None:
    """An open change order priced against an older scope no longer applies."""
    for change_order in commission.change_orders:
        if (
            change_order.status in OPEN_STATUSES
            and change_order.base_scope_version != commission.scope_version
        ):
            set_change_order_status(change_order, ChangeOrderStatus.SUPERSEDED)
            log_activity(
                db,
                commission,
                Actor.SYSTEM,
                "change_order_superseded",
                number=change_order.number,
            )


def seller_approve(db: Session, commission: Commission, change_order: ChangeOrder) -> None:
    set_change_order_status(change_order, ChangeOrderStatus.SELLER_APPROVED)
    log_activity(db, commission, Actor.SELLER, "change_order_approved", number=change_order.number)


def _apply_to_scope(commission: Commission, change_order: ChangeOrder) -> None:
    for line in change_order.items_json:
        code = line.get("rate_card_code")
        if code == EXTRA_REVISION_CODE:
            commission.revisions_included = (commission.revisions_included or 0) + line["quantity"]
        elif code == COMMERCIAL_LICENSE_CODE:
            commission.usage_rights = f"{commission.usage_rights}; commercial license".strip("; ")
        else:
            # The rate-card name, never the model's prose, becomes part of the agreed terms.
            label = line["name"] if line["quantity"] == 1 else f"{line['name']} x{line['quantity']}"
            commission.deliverables_json = [*commission.deliverables_json, label]


def client_approve(db: Session, commission: Commission, change_order: ChangeOrder) -> Milestone:
    """Scope vN+1, a new snapshot, and a change-order milestone ready to bill."""
    if commission.status not in (CommissionStatus.AGREED, CommissionStatus.IN_PROGRESS):
        raise conflict(
            "COMMISSION_NOT_ACTIVE", f"The commission is {commission.status}, not in progress."
        )
    if change_order.base_scope_version != commission.scope_version:
        raise conflict(
            "SCOPE_VERSION_MISMATCH",
            "The scope changed after this change order was prepared.",
            {"current_version": commission.scope_version},
        )
    set_change_order_status(change_order, ChangeOrderStatus.CLIENT_APPROVED)
    _apply_to_scope(commission, change_order)
    commission.scope_version += 1
    # Both parties just approved this exact change, so the new version counts as accepted.
    commission.seller_accepted_version = commission.scope_version
    commission.client_accepted_version = commission.scope_version
    change_order.resulting_scope_version = commission.scope_version
    write_snapshot(db, commission, f"change_order:{change_order.id}")

    milestone = Milestone(
        position=max((m.position for m in commission.milestones), default=0) + 1,
        title=f"Change order #{change_order.number}",
        kind=MilestoneKind.CHANGE_ORDER,
        change_order_id=change_order.id,
        amount_minor_units=change_order.total_minor_units,
        billing_trigger=BillingTrigger.ON_CHANGE_ORDER_APPROVED,
        workflow_state=MilestoneState.READY_TO_BILL,
    )
    commission.milestones.append(milestone)
    db.flush()
    log_activity(
        db,
        commission,
        Actor.CLIENT,
        "change_order_approved",
        number=change_order.number,
        scope_version=commission.scope_version,
    )
    return milestone


def client_decline(db: Session, commission: Commission, change_order: ChangeOrder) -> None:
    set_change_order_status(change_order, ChangeOrderStatus.DECLINED)
    log_activity(db, commission, Actor.CLIENT, "change_order_declined", number=change_order.number)
