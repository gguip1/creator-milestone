"""Scope edits, versioned snapshots, and two-party acceptance (PRD §4, §10, §13)."""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import conflict, invalid
from app.models import Commission, ScopeSnapshot
from app.models.enums import (
    Actor,
    ChangeOrderStatus,
    CommissionStatus,
    MilestoneKind,
    MilestoneState,
)
from app.schemas.ai import ScopeContext
from app.services.activity import log_activity
from app.services.milestones import (
    PlanEntry,
    plan_milestones,
    recompute_plan_amounts,
    set_plan,
    unlock_next_plan_milestone,
)
from app.services.money import CURRENCY_EXPONENTS
from app.services.state_machines import set_commission_status, set_milestone_state

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

EDITABLE_STATUSES = (
    CommissionStatus.DRAFT,
    CommissionStatus.AWAITING_ACCEPTANCE,
    CommissionStatus.AGREED,
)

# API field -> column, for fields whose column name differs.
FIELD_COLUMNS = {"deliverables": "deliverables_json", "file_formats": "file_formats_json"}
# A cleared value on these columns means "empty", because the columns are not nullable.
EMPTY_VALUES: dict[str, Any] = {
    "title": "",
    "description": "",
    "usage_rights": "",
    "client_display_name": "",
    "source_language": "en",
    "currency_code": "USD",
    "deliverables_json": [],
    "file_formats_json": [],
}


def is_valid_email(value: str | None) -> bool:
    return bool(value and EMAIL_PATTERN.match(value))


def missing_fields(commission: Commission) -> list[str]:
    """Mandatory terms that still block agreement."""
    missing = []
    if not commission.title.strip():
        missing.append("title")
    if not commission.deliverables_json:
        missing.append("deliverables")
    if commission.deadline_date is None:
        missing.append("deadline_date")
    if commission.revisions_included is None:
        missing.append("revisions_included")
    if not commission.usage_rights.strip():
        missing.append("usage_rights")
    if not commission.total_minor_units or commission.total_minor_units < 1:
        missing.append("total_minor_units")
    if commission.currency_code not in CURRENCY_EXPONENTS:
        missing.append("currency_code")
    if not is_valid_email(commission.client_email):
        missing.append("client_email")
    if not plan_milestones(commission):
        missing.append("milestones")
    return missing


def snapshot_data(commission: Commission) -> dict[str, Any]:
    """Everything both parties agree to at one version. Invoice terms are built from this."""
    return {
        "version": commission.scope_version,
        "title": commission.title,
        "description": commission.description,
        "deliverables": list(commission.deliverables_json),
        "file_formats": list(commission.file_formats_json),
        "revisions_included": commission.revisions_included,
        "deadline_date": commission.deadline_date.isoformat() if commission.deadline_date else None,
        "usage_rights": commission.usage_rights,
        "total_minor_units": commission.total_minor_units,
        "currency_code": commission.currency_code,
        "plan": [
            {
                "title": m.title,
                "basis_points": m.percentage_basis_points,
                "amount_minor_units": m.amount_minor_units,
                "billing_trigger": m.billing_trigger,
            }
            for m in plan_milestones(commission)
        ],
        "change_orders": [
            {"number": co.number, "total_minor_units": co.total_minor_units, "lines": co.items_json}
            for co in commission.change_orders
            if co.status == ChangeOrderStatus.CLIENT_APPROVED
        ],
    }


def get_snapshot(db: Session, commission: Commission, version: int) -> ScopeSnapshot | None:
    return db.scalar(
        select(ScopeSnapshot).where(
            ScopeSnapshot.commission_id == commission.id, ScopeSnapshot.version == version
        )
    )


def write_snapshot(db: Session, commission: Commission, reason: str) -> ScopeSnapshot:
    """Create the snapshot for the current version, or refresh it if nobody has accepted it yet."""
    db.flush()
    snapshot = get_snapshot(db, commission, commission.scope_version)
    if snapshot is None:
        snapshot = ScopeSnapshot(
            commission_id=commission.id,
            version=commission.scope_version,
            snapshot_json=snapshot_data(commission),
            reason=reason,
        )
        db.add(snapshot)
    else:
        snapshot.snapshot_json = snapshot_data(commission)
    db.flush()
    return snapshot


def scope_context(commission: Commission) -> ScopeContext:
    return ScopeContext(
        scope_version=commission.scope_version,
        title=commission.title,
        deliverables=list(commission.deliverables_json),
        file_formats=list(commission.file_formats_json),
        revisions_included=commission.revisions_included or 0,
        revisions_used=commission.revisions_used,
        deadline=commission.deadline_date.isoformat() if commission.deadline_date else None,
        usage_rights=commission.usage_rights,
        currency_code=commission.currency_code,
    )


def _require_editable(commission: Commission) -> None:
    if commission.status not in EDITABLE_STATUSES:
        raise conflict(
            "SCOPE_LOCKED",
            f"The scope cannot be edited while the commission is {commission.status}. "
            "Use a change order instead.",
        )


def _record_edit(db: Session, commission: Commission) -> None:
    """Invalidate what was agreed. Only a version someone accepted gets a new number.

    Edits before any acceptance refine the same draft, which is why the demo's agreed scope is v1
    after the seller fills in the gaps (PRD §5).
    """
    was_accepted = commission.scope_version in (
        commission.seller_accepted_version,
        commission.client_accepted_version,
    )
    if was_accepted:
        commission.scope_version += 1
    commission.seller_accepted_version = None
    commission.client_accepted_version = None
    if commission.status != CommissionStatus.DRAFT:
        set_commission_status(commission, CommissionStatus.DRAFT)
    for milestone in commission.milestones:
        if (
            milestone.kind == MilestoneKind.PLAN
            and milestone.workflow_state == MilestoneState.READY_TO_BILL
        ):
            set_milestone_state(milestone, MilestoneState.LOCKED)
    # Editing is only possible before the first send, so these are unsent drafts with old terms.
    for invoice in commission.invoices:
        if invoice.is_active and invoice.sent_at is None:
            invoice.is_active = False
    write_snapshot(db, commission, "edit")
    log_activity(
        db, commission, Actor.SELLER, "scope_edited", scope_version=commission.scope_version
    )


def edit_scope(db: Session, commission: Commission, changes: dict[str, Any]) -> bool:
    """Apply a partial edit. Returns False when nothing actually changed."""
    _require_editable(commission)
    if "client_email" in changes and changes["client_email"] is not None:
        changes["client_email"] = changes["client_email"].strip() or None
    changed = False
    for field_name, value in changes.items():
        column = FIELD_COLUMNS.get(field_name, field_name)
        if value is None and column in EMPTY_VALUES:
            value = EMPTY_VALUES[column]
        if getattr(commission, column) != value:
            setattr(commission, column, value)
            changed = True
    if changed:
        recompute_plan_amounts(commission)
        _record_edit(db, commission)
    return changed


def edit_plan(db: Session, commission: Commission, entries: list[PlanEntry]) -> None:
    _require_editable(commission)
    set_plan(db, commission, entries)
    _record_edit(db, commission)


def _require_current_version(commission: Commission, scope_version: int | None) -> None:
    if scope_version is not None and scope_version != commission.scope_version:
        raise conflict(
            "SCOPE_VERSION_MISMATCH",
            f"This is scope v{commission.scope_version}, not v{scope_version}. Review it again.",
            {"current_version": commission.scope_version},
        )


def _require_complete(commission: Commission) -> None:
    missing = missing_fields(commission)
    if missing:
        raise invalid(
            "SCOPE_INCOMPLETE",
            "Some required terms are missing, so the scope cannot be agreed yet.",
            {"missing_fields": missing},
        )


def accept_as_seller(db: Session, commission: Commission, scope_version: int | None) -> None:
    _require_current_version(commission, scope_version)
    if commission.seller_accepted_version == commission.scope_version:
        return
    _require_complete(commission)
    set_commission_status(commission, CommissionStatus.AWAITING_ACCEPTANCE)
    commission.seller_accepted_version = commission.scope_version
    log_activity(
        db, commission, Actor.SELLER, "scope_accepted", scope_version=commission.scope_version
    )


def accept_as_client(db: Session, commission: Commission, scope_version: int) -> None:
    _require_current_version(commission, scope_version)
    if commission.client_accepted_version == commission.scope_version:
        return
    _require_complete(commission)
    if commission.seller_accepted_version != commission.scope_version:
        raise conflict(
            "SELLER_ACCEPTANCE_REQUIRED", "The seller has not accepted this scope version yet."
        )
    set_commission_status(commission, CommissionStatus.AGREED)
    commission.client_accepted_version = commission.scope_version
    log_activity(
        db, commission, Actor.CLIENT, "scope_accepted", scope_version=commission.scope_version
    )
    unlock_next_plan_milestone(db, commission)
