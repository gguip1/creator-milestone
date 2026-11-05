"""Service-level checks that do not need the HTTP layer."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.agent.executor import approve_proposal, recover_interrupted
from app.agent.rules import reconcile
from app.config import Settings
from app.db import make_session_factory
from app.errors import AppError
from app.models import Commission, Proposal
from app.models.enums import (
    ChangeOrderStatus,
    CommissionStatus,
    MilestoneState,
    ProposalKind,
    ProposalStatus,
)
from app.services import state_machines as sm
from app.services.scope import accept_as_client, accept_as_seller, edit_scope, write_snapshot
from app.services.seed import ensure_seller, new_commission, reset_demo, seed_demo_project
from tests.fake_paypal import FakePayPal


@pytest.fixture
def db(tmp_path: Path):
    factory = make_session_factory(f"sqlite:///{tmp_path / 'domain.db'}")
    with factory() as session:
        yield session


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, paypal_client_id="", judge_mode=False, recipient_allowlist=[])


def agreed_commission(db: Session, settings: Settings) -> Commission:
    seller = ensure_seller(db)
    commission = new_commission(
        db,
        seller,
        title="Illustration",
        client_email="buyer@example.com",
        deliverables_json=["One full-body illustration"],
        revisions_included=2,
        deadline_date=date(2026, 11, 25),
        usage_rights="Personal streaming",
        total_minor_units=30000,
    )
    write_snapshot(db, commission, "initial")
    accept_as_seller(db, commission, None)
    accept_as_client(db, commission, commission.scope_version)
    reconcile(db, commission, settings)
    db.commit()
    return commission


def test_seed_creates_rate_card_and_intake_project(db):
    commission = seed_demo_project(db)
    db.commit()
    assert commission.status == CommissionStatus.DRAFT
    assert [m.percentage_basis_points for m in commission.milestones] == [3000, 3000, 4000]
    assert commission.snapshots[0].reason == "initial"
    assert commission.visitor_id is None


def test_reset_replaces_projects_including_billed_ones(db, settings):
    old = agreed_commission(db, settings)
    old_id = old.id
    fresh = reset_demo(db)
    db.commit()
    assert db.get(Commission, old_id) is None
    assert fresh.id != old_id


async def test_agreement_proposes_deposit_and_approval_creates_one_draft(db, settings):
    commission = agreed_commission(db, settings)
    assert commission.status == CommissionStatus.AGREED
    assert commission.milestones[0].workflow_state == MilestoneState.READY_TO_BILL
    assert commission.milestones[1].workflow_state == MilestoneState.LOCKED
    [bill] = commission.proposals
    assert bill.kind == ProposalKind.BILL_MILESTONE
    assert bill.payload_json["amount_minor_units"] == 9000

    fake = FakePayPal()
    await approve_proposal(db, bill, fake.client(), settings)
    assert bill.status == ProposalStatus.EXECUTED
    assert fake.count("create") == 1
    assert [p.kind for p in commission.proposals if p.status == ProposalStatus.PENDING] == [
        ProposalKind.SEND_INVOICE
    ]


def test_edit_after_agreement_goes_stale_and_relocks(db, settings):
    commission = agreed_commission(db, settings)
    [bill] = commission.proposals
    assert edit_scope(db, commission, {"total_minor_units": 10001})
    reconcile(db, commission, settings)
    db.commit()
    assert bill.status == ProposalStatus.STALE
    assert commission.scope_version == 2
    assert commission.status == CommissionStatus.DRAFT
    assert commission.seller_accepted_version is None
    assert commission.milestones[0].workflow_state == MilestoneState.LOCKED
    assert [m.amount_minor_units for m in commission.milestones] == [3000, 3000, 4001]


def test_edit_before_any_acceptance_keeps_the_version(db):
    commission = seed_demo_project(db)
    assert edit_scope(db, commission, {"title": "First"})
    assert edit_scope(db, commission, {"title": "Second"})
    assert commission.scope_version == 1
    assert commission.snapshots[0].snapshot_json["title"] == "Second"
    assert edit_scope(db, commission, {"title": "Second"}) is False


def test_recover_interrupted_makes_approved_retryable(db, settings):
    commission = agreed_commission(db, settings)
    bill: Proposal = commission.proposals[0]
    bill.status = ProposalStatus.APPROVED
    db.commit()
    assert recover_interrupted(db) == 1
    db.refresh(bill)
    assert bill.status == ProposalStatus.FAILED
    assert bill.error_code == "INTERRUPTED"


@pytest.mark.parametrize(
    ("setter", "entity_attr", "start", "target"),
    [
        (sm.set_commission_status, "status", CommissionStatus.DRAFT, CommissionStatus.AGREED),
        (sm.set_commission_status, "status", CommissionStatus.COMPLETED, CommissionStatus.DRAFT),
        (
            sm.set_milestone_state,
            "workflow_state",
            MilestoneState.LOCKED,
            MilestoneState.DELIVERED,
        ),
        (
            sm.set_milestone_state,
            "workflow_state",
            MilestoneState.READY_TO_BILL,
            MilestoneState.SETTLED,
        ),
        (sm.set_milestone_state, "workflow_state", MilestoneState.SETTLED, MilestoneState.BILLED),
        (
            sm.set_change_order_status,
            "status",
            ChangeOrderStatus.DRAFT,
            ChangeOrderStatus.CLIENT_APPROVED,
        ),
        (sm.set_proposal_status, "status", ProposalStatus.EXECUTED, ProposalStatus.APPROVED),
        (sm.set_proposal_status, "status", ProposalStatus.STALE, ProposalStatus.APPROVED),
        (sm.set_proposal_status, "status", ProposalStatus.PENDING, ProposalStatus.EXECUTED),
    ],
)
def test_forbidden_transitions_raise_409(setter, entity_attr, start, target):
    entity = type("Entity", (), {entity_attr: start})()
    with pytest.raises(AppError) as caught:
        setter(entity, target)
    assert caught.value.status_code == 409
    assert caught.value.code == "FORBIDDEN_TRANSITION"
    assert getattr(entity, entity_attr) == start
