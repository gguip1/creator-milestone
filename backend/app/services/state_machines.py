"""Allowed transitions (PRD §13). Anything else raises and becomes a 409."""

from app.errors import conflict
from app.models import ChangeOrder, Commission, Milestone, Proposal
from app.models.enums import ChangeOrderStatus as CO
from app.models.enums import CommissionStatus as CS
from app.models.enums import MilestoneState as MS
from app.models.enums import ProposalStatus as PS

COMMISSION_TRANSITIONS: dict[str, set[str]] = {
    CS.DRAFT: {CS.AWAITING_ACCEPTANCE, CS.CANCELLED},
    # An edit clears both acceptances, so both of these can fall back to DRAFT.
    CS.AWAITING_ACCEPTANCE: {CS.AGREED, CS.DRAFT, CS.CANCELLED},
    CS.AGREED: {CS.IN_PROGRESS, CS.DRAFT, CS.CANCELLED},
    CS.IN_PROGRESS: {CS.COMPLETED, CS.CANCELLED},
    CS.COMPLETED: set(),
    CS.CANCELLED: set(),
}

MILESTONE_TRANSITIONS: dict[str, set[str]] = {
    MS.LOCKED: {MS.READY_TO_BILL, MS.AWAITING_DELIVERY},
    MS.AWAITING_DELIVERY: {MS.DELIVERED},
    MS.DELIVERED: {MS.APPROVED},
    MS.APPROVED: {MS.READY_TO_BILL},
    # READY_TO_BILL -> LOCKED only happens when an agreed scope is edited before any send.
    MS.READY_TO_BILL: {MS.BILLED, MS.LOCKED},
    MS.BILLED: {MS.SETTLED, MS.READY_TO_BILL},
    MS.SETTLED: set(),
}

CHANGE_ORDER_TRANSITIONS: dict[str, set[str]] = {
    CO.DRAFT: {CO.SELLER_APPROVED, CO.SUPERSEDED},
    CO.SELLER_APPROVED: {CO.CLIENT_APPROVED, CO.DECLINED, CO.SUPERSEDED},
    CO.CLIENT_APPROVED: set(),
    CO.DECLINED: set(),
    CO.SUPERSEDED: set(),
}

PROPOSAL_TRANSITIONS: dict[str, set[str]] = {
    PS.PENDING: {PS.APPROVED, PS.DISMISSED, PS.STALE},
    PS.APPROVED: {PS.EXECUTED, PS.FAILED},
    # Retry goes back through APPROVED. A failed card can also be dropped or go out of date.
    PS.FAILED: {PS.APPROVED, PS.DISMISSED, PS.STALE},
    PS.EXECUTED: set(),
    PS.DISMISSED: set(),
    PS.STALE: set(),
}


def check_transition(entity: str, table: dict[str, set[str]], current: str, target: str) -> None:
    if target not in table.get(current, set()):
        raise conflict(
            "FORBIDDEN_TRANSITION",
            f"A {entity} cannot move from {current} to {target}.",
            {"entity": entity, "from": str(current), "to": str(target)},
        )


def set_commission_status(commission: Commission, target: CS) -> None:
    check_transition("commission", COMMISSION_TRANSITIONS, commission.status, target)
    commission.status = target


def set_milestone_state(milestone: Milestone, target: MS) -> None:
    check_transition("milestone", MILESTONE_TRANSITIONS, milestone.workflow_state, target)
    milestone.workflow_state = target


def set_change_order_status(change_order: ChangeOrder, target: CO) -> None:
    check_transition("change order", CHANGE_ORDER_TRANSITIONS, change_order.status, target)
    change_order.status = target


def set_proposal_status(proposal: Proposal, target: PS) -> None:
    check_transition("proposal", PROPOSAL_TRANSITIONS, proposal.status, target)
    proposal.status = target
