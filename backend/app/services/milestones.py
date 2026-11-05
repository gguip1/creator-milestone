"""Milestone plan math and workflow steps (PRD §13, §14)."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.errors import invalid
from app.models import Commission, Milestone, utcnow
from app.models.enums import Actor, BillingTrigger, CommissionStatus, MilestoneKind, MilestoneState
from app.services.activity import log_activity
from app.services.money import BASIS_POINTS_TOTAL, MoneyError, split_by_basis_points
from app.services.state_machines import set_commission_status, set_milestone_state


@dataclass(frozen=True)
class PlanEntry:
    title: str
    basis_points: int
    billing_trigger: BillingTrigger


DEFAULT_PLAN = (
    PlanEntry("Deposit", 3000, BillingTrigger.ON_AGREEMENT),
    PlanEntry("Sketch approval", 3000, BillingTrigger.ON_DELIVERY_APPROVED),
    PlanEntry("Final delivery", 4000, BillingTrigger.ON_DELIVERY_APPROVED),
)


def plan_milestones(commission: Commission) -> list[Milestone]:
    plan = [m for m in commission.milestones if m.kind == MilestoneKind.PLAN]
    return sorted(plan, key=lambda m: m.position)


def recompute_plan_amounts(commission: Commission) -> None:
    """Plan amounts always come from the total; the last milestone takes the remainder."""
    plan = plan_milestones(commission)
    if not plan:
        return
    if commission.total_minor_units is None:
        for milestone in plan:
            milestone.amount_minor_units = 0
        return
    try:
        amounts = split_by_basis_points(
            commission.total_minor_units, [m.percentage_basis_points or 0 for m in plan]
        )
    except MoneyError as exc:
        raise invalid("INVALID_PLAN", str(exc)) from exc
    for milestone, amount in zip(plan, amounts, strict=True):
        milestone.amount_minor_units = amount


def validate_plan(entries: list[PlanEntry]) -> None:
    if not entries:
        raise invalid("INVALID_PLAN", "A plan needs at least one milestone.")
    if sum(e.basis_points for e in entries) != BASIS_POINTS_TOTAL:
        raise invalid("INVALID_PLAN", f"Shares must sum to {BASIS_POINTS_TOTAL} basis points.")
    if any(e.billing_trigger == BillingTrigger.ON_CHANGE_ORDER_APPROVED for e in entries):
        raise invalid("INVALID_PLAN", "Change-order billing cannot be part of the plan.")


def set_plan(db: Session, commission: Commission, entries: list[PlanEntry]) -> None:
    """Replace the plan rows. Change-order milestones keep their rows and move after the plan."""
    validate_plan(entries)
    for milestone in plan_milestones(commission):
        for invoice in list(milestone.invoices):
            commission.invoices.remove(invoice)
        commission.milestones.remove(milestone)
    for position, entry in enumerate(entries, start=1):
        commission.milestones.append(
            Milestone(
                position=position,
                title=entry.title,
                kind=MilestoneKind.PLAN,
                percentage_basis_points=entry.basis_points,
                billing_trigger=entry.billing_trigger,
                workflow_state=MilestoneState.LOCKED,
            )
        )
    extras = [m for m in commission.milestones if m.kind == MilestoneKind.CHANGE_ORDER]
    for offset, milestone in enumerate(sorted(extras, key=lambda m: m.position), start=1):
        milestone.position = len(entries) + offset
    db.flush()
    recompute_plan_amounts(commission)


def unlock_next_plan_milestone(db: Session, commission: Commission) -> None:
    """Open the first unsettled plan milestone. Later ones wait for it to settle."""
    if commission.status not in (CommissionStatus.AGREED, CommissionStatus.IN_PROGRESS):
        return
    for milestone in plan_milestones(commission):
        if milestone.workflow_state == MilestoneState.SETTLED:
            continue
        if milestone.workflow_state == MilestoneState.LOCKED:
            target = (
                MilestoneState.READY_TO_BILL
                if milestone.billing_trigger == BillingTrigger.ON_AGREEMENT
                else MilestoneState.AWAITING_DELIVERY
            )
            set_milestone_state(milestone, target)
            log_activity(
                db,
                commission,
                Actor.SYSTEM,
                "milestone_unlocked",
                milestone=milestone.title,
                state=str(target),
            )
        return


def complete_if_all_settled(db: Session, commission: Commission) -> None:
    if commission.status != CommissionStatus.IN_PROGRESS:
        return
    if all(m.workflow_state == MilestoneState.SETTLED for m in commission.milestones):
        set_commission_status(commission, CommissionStatus.COMPLETED)
        log_activity(db, commission, Actor.SYSTEM, "commission_completed")


def deliver_milestone(
    db: Session, milestone: Milestone, evidence_url: str | None, note: str | None
) -> None:
    set_milestone_state(milestone, MilestoneState.DELIVERED)
    milestone.evidence_url = evidence_url
    milestone.evidence_note = note
    milestone.delivered_at = utcnow()
    log_activity(
        db, milestone.commission, Actor.SELLER, "milestone_delivered", milestone=milestone.title
    )


def approve_delivery(db: Session, milestone: Milestone) -> None:
    """Client approval makes the milestone billable straight away (PRD §13)."""
    set_milestone_state(milestone, MilestoneState.APPROVED)
    milestone.approved_at = utcnow()
    set_milestone_state(milestone, MilestoneState.READY_TO_BILL)
    log_activity(
        db, milestone.commission, Actor.CLIENT, "milestone_approved", milestone=milestone.title
    )
