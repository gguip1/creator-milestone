"""Proposal rules: one execution, staleness, validator blocks, and what a seller may edit."""

import asyncio

from sqlalchemy import select

from app.agent.executor import approve_proposal
from app.models import Commission, Proposal
from tests.conftest import BUYER, pending


async def test_concurrent_approvals_make_one_paypal_create(api, fake_paypal, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.create_delay = 0.05  # Holds the first request open while the rest arrive.

    responses = await asyncio.gather(
        *(api.post(f"/api/proposals/{bill['id']}/approve") for _ in range(8))
    )

    assert fake_paypal.count("create") == 1
    assert len(fake_paypal.invoices) == 1
    # Both states seen means the losers arrived while the winner was still inside PayPal.
    assert {r["status"] for r in responses} == {"APPROVED", "EXECUTED"}
    project = await api.get(f"/api/projects/{project['id']}")
    assert len(project["invoices"]) == 1
    assert pending(project, "SEND_INVOICE")


async def test_atomic_claim_stops_approvals_that_all_read_pending(
    make_agreed, fake_paypal, session_factory, settings
):
    """Models another worker: every session read PENDING before anyone claimed it."""
    project = await make_agreed()
    bill_id = pending(project, "BILL_MILESTONE")["id"]
    sessions = [session_factory() for _ in range(4)]
    try:
        cards = [db.get(Proposal, bill_id) for db in sessions]
        assert {card.status for card in cards} == {"PENDING"}
        fake_paypal.create_delay = 0.05
        client = fake_paypal.client()
        results = await asyncio.gather(
            *(
                approve_proposal(db, card, client, settings)
                for db, card in zip(sessions, cards, strict=True)
            )
        )
        assert fake_paypal.count("create") == 1
        statuses = [r.status for r in results]
        assert statuses.count("EXECUTED") == 1
        assert statuses.count("APPROVED") == 3
    finally:
        for db in sessions:
            db.close()


async def test_concurrent_send_approvals_send_once(api, fake_paypal, make_agreed):
    project = await make_agreed()
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    project = await api.get(f"/api/projects/{project['id']}")
    send = pending(project, "SEND_INVOICE")
    await asyncio.gather(*(api.post(f"/api/proposals/{send['id']}/approve") for _ in range(5)))
    assert fake_paypal.count("send") == 1


async def test_same_key_concurrently_runs_once_and_reports_in_progress(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.create_delay = 0.05
    responses = await asyncio.gather(
        *(
            api.request("POST", f"/api/proposals/{bill['id']}/approve", key="same-click")
            for _ in range(3)
        )
    )
    assert fake_paypal.count("create") == 1
    assert sum(1 for r in responses if r.get("code") == "IDEMPOTENCY_IN_PROGRESS") == 2


async def test_repeat_approval_after_execution_changes_nothing(api, fake_paypal, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    first = await api.post(f"/api/proposals/{bill['id']}/approve")
    second = await api.post(f"/api/proposals/{bill['id']}/approve")
    assert first["status"] == second["status"] == "EXECUTED"
    assert fake_paypal.count("create") == 1


async def test_scope_edit_clears_acceptances_and_stales_pending_cards(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")

    edited = await api.patch(f"/api/projects/{project['id']}", {"total_minor_units": 40000})

    assert edited["scope_version"] == 2
    assert edited["seller_accepted_version"] is None
    assert edited["client_accepted_version"] is None
    assert edited["status"] == "DRAFT"
    assert [m["amount_minor_units"] for m in edited["milestones"]] == [12000, 12000, 16000]
    assert [p["status"] for p in edited["proposals"]] == ["STALE"]

    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=409)
    assert error["code"] == "PROPOSAL_NOT_ACTIONABLE"
    assert fake_paypal.write_calls() == []


async def test_reagreeing_after_an_edit_proposes_at_the_new_version(api, make_agreed):
    project = await make_agreed()
    await api.patch(f"/api/projects/{project['id']}", {"total_minor_units": 40000})
    await api.post(f"/api/projects/{project['id']}/accept")
    await api.post(f"/api/c/{project['share_token']}/accept", {"scope_version": 2})
    project = await api.get(f"/api/projects/{project['id']}")
    bill = pending(project, "BILL_MILESTONE")
    assert bill["scope_version"] == 2
    assert bill["payload"]["amount_minor_units"] == 12000


async def test_edit_with_a_draft_retires_it_and_bills_a_new_attempt(api, fake_paypal, make_agreed):
    project = await make_agreed()
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    project = await api.get(f"/api/projects/{project['id']}")
    send = pending(project, "SEND_INVOICE")

    await api.patch(f"/api/projects/{project['id']}", {"total_minor_units": 40000})
    await api.post(f"/api/proposals/{send['id']}/approve", expect=409)
    assert fake_paypal.count("send") == 0

    await api.post(f"/api/projects/{project['id']}/accept")
    await api.post(f"/api/c/{project['share_token']}/accept", {"scope_version": 2})
    project = await api.get(f"/api/projects/{project['id']}")
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    project = await api.get(f"/api/projects/{project['id']}")
    first, second = project["invoices"]
    assert first["is_active"] is False
    assert second["is_active"] is True
    assert second["attempt"] == 2
    assert first["invoice_number"] != second["invoice_number"]
    assert second["amount_minor_units"] == 12000


async def test_stale_detected_at_approval_is_a_409(api, make_agreed, session_factory):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    # Move the version underneath the card, skipping the code path that reconciles.
    with session_factory() as db:
        db.get(Commission, project["id"]).scope_version = 9
        db.commit()
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=409)
    assert error["code"] == "PROPOSAL_STALE"
    with session_factory() as db:
        assert db.get(Proposal, bill["id"]).status == "STALE"


async def test_dismissed_card_stays_dismissed_and_can_be_brought_back(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    dismissed = await api.post(f"/api/proposals/{bill['id']}/dismiss")
    assert dismissed["status"] == "DISMISSED"
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=409)

    # An unrelated event must not resurrect it.
    project = await api.post(f"/api/projects/{project['id']}/revisions")
    assert all(p["status"] == "DISMISSED" for p in project["proposals"])

    milestone = project["milestones"][0]
    again = await api.post(f"/api/milestones/{milestone['id']}/propose-bill", expect=201)
    assert again["status"] == "PENDING"
    assert again["id"] != bill["id"]
    assert fake_paypal.write_calls() == []


async def test_missing_client_email_blocks_agreement(api, make_project):
    project = await make_project(client_email=None)
    assert project["missing_fields"] == ["client_email"]
    error = await api.post(f"/api/projects/{project['id']}/accept", expect=422)
    assert error["code"] == "SCOPE_INCOMPLETE"
    assert error["details"]["missing_fields"] == ["client_email"]


async def test_missing_client_email_blocks_billing_without_a_paypal_call(
    api, fake_paypal, make_agreed, session_factory
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    with session_factory() as db:
        db.get(Commission, project["id"]).client_email = None
        db.commit()
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert error["code"] == "PROPOSAL_BLOCKED"
    codes = {b["code"] for b in error["details"]["blockers"]}
    assert "MISSING_CLIENT_EMAIL" in codes
    assert fake_paypal.calls == []
    # Blocked is not failed: the card stays open, and the seller can fix the cause.
    project = await api.get(f"/api/projects/{project['id']}")
    card = pending(project, "BILL_MILESTONE")
    assert card["can_approve"] is False
    assert "MISSING_CLIENT_EMAIL" in {b["code"] for b in card["blockers"]}


async def test_invalid_email_and_unknown_currency_block_agreement(api, make_project):
    project = await make_project(client_email="not-an-email", currency_code="XXX")
    assert set(project["missing_fields"]) == {"client_email", "currency_code"}
    await api.post(f"/api/projects/{project['id']}/accept", expect=422)


async def test_unknown_currency_blocks_the_proposal(api, fake_paypal, make_agreed, session_factory):
    project = await make_agreed()
    with session_factory() as db:
        db.get(Commission, project["id"]).currency_code = "XXX"
        db.commit()
    bill = pending(project, "BILL_MILESTONE")
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert "UNSUPPORTED_CURRENCY" in {b["code"] for b in error["details"]["blockers"]}
    assert fake_paypal.calls == []


async def test_tampered_payload_amount_and_recipient_are_blocked(
    api, fake_paypal, make_agreed, session_factory
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    with session_factory() as db:
        row = db.get(Proposal, bill["id"])
        row.payload_json = {**row.payload_json, "amount_minor_units": 0, "recipient_email": "x@y.z"}
        db.commit()
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    codes = {b["code"] for b in error["details"]["blockers"]}
    assert {"AMOUNT_MISMATCH", "RECIPIENT_MISMATCH"} <= codes
    assert fake_paypal.calls == []


async def test_sum_mismatch_is_blocked(api, fake_paypal, make_agreed, session_factory):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    with session_factory() as db:
        db.get(Commission, project["id"]).total_minor_units = 99999
        db.commit()
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert "SUM_MISMATCH" in {b["code"] for b in error["details"]["blockers"]}
    assert fake_paypal.calls == []


async def test_judge_mode_enforces_the_allowlist(api, fake_paypal, make_agreed, settings):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")

    settings.judge_mode = True
    settings.recipient_allowlist = ["other@example.com"]
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert "RECIPIENT_NOT_ALLOWED" in {b["code"] for b in error["details"]["blockers"]}
    assert fake_paypal.calls == []

    settings.recipient_allowlist = [BUYER.upper()]
    executed = await api.post(f"/api/proposals/{bill['id']}/approve")
    assert executed["status"] == "EXECUTED"


async def test_judge_mode_with_an_empty_allowlist_fails_closed(
    api, fake_paypal, make_agreed, settings
):
    project = await make_agreed()
    settings.judge_mode = True
    settings.recipient_allowlist = []
    bill = pending(project, "BILL_MILESTONE")
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert fake_paypal.calls == []


async def test_allowlist_is_ignored_outside_judge_mode(api, make_agreed, settings):
    project = await make_agreed()
    settings.judge_mode = False
    settings.recipient_allowlist = ["other@example.com"]
    bill = pending(project, "BILL_MILESTONE")
    assert (await api.post(f"/api/proposals/{bill['id']}/approve"))["status"] == "EXECUTED"


async def test_money_and_recipient_fields_cannot_be_edited(api, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    for field in ("amount_minor_units", "recipient_email", "currency_code", "terms_and_conditions"):
        error = await api.patch(f"/api/proposals/{bill['id']}", {field: "x"}, expect=422)
        assert error["code"] == "VALIDATION_ERROR"


async def test_seller_can_edit_a_bill_note_and_it_reaches_paypal(api, fake_paypal, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    edited = await api.patch(f"/api/proposals/{bill['id']}", {"note": "Deposit, thank you!"})
    assert edited["payload"]["note"] == "Deposit, thank you!"
    assert edited["payload"]["amount_minor_units"] == 9000
    await api.post(f"/api/proposals/{bill['id']}/approve")
    [remote] = fake_paypal.invoices.values()
    assert remote["detail"]["note"] == "Deposit, thank you!"


async def test_a_field_from_another_card_kind_is_rejected(api, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    error = await api.patch(f"/api/proposals/{bill['id']}", {"lines": []}, expect=422)
    assert error["code"] == "FIELD_NOT_EDITABLE"


async def test_nothing_writes_to_paypal_without_approval(api, fake_paypal, make_agreed):
    project = await make_agreed()
    await api.post(f"/api/projects/{project['id']}/revisions")
    await api.post(f"/api/projects/{project['id']}/messages", {"body": "Hello?"}, expect=201)
    await api.get(f"/api/projects/{project['id']}")
    assert fake_paypal.write_calls() == []


async def test_no_duplicate_active_invoice_per_milestone(
    api, fake_paypal, make_agreed, session_factory
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    await api.post(f"/api/proposals/{bill['id']}/approve")
    # A second card for the same milestone can only appear through a bug; it must still be blocked.
    with session_factory() as db:
        original = db.scalar(select(Proposal).where(Proposal.id == bill["id"]))
        duplicate = Proposal(
            commission_id=original.commission_id,
            kind=original.kind,
            payload_json=original.payload_json,
            rationale="duplicate",
            scope_version=original.scope_version,
            target_ref=original.target_ref,
            target_state=original.target_state,
            idempotency_key="duplicate-card",
        )
        db.add(duplicate)
        db.commit()
        duplicate_id = duplicate.id
    error = await api.post(f"/api/proposals/{duplicate_id}/approve", expect=422)
    assert "DUPLICATE_ACTIVE_INVOICE" in {b["code"] for b in error["details"]["blockers"]}
    assert fake_paypal.count("create") == 1


async def test_dismissed_send_card_can_be_brought_back_without_a_new_draft(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    project = await api.get(f"/api/projects/{project['id']}")
    send = pending(project, "SEND_INVOICE")
    await api.post(f"/api/proposals/{send['id']}/dismiss")

    again = await api.post(
        f"/api/milestones/{project['milestones'][0]['id']}/propose-bill", expect=201
    )
    assert again["kind"] == "SEND_INVOICE"
    assert (await api.post(f"/api/proposals/{again['id']}/approve"))["status"] == "EXECUTED"
    assert fake_paypal.count("create") == 1
    assert fake_paypal.count("send") == 1


async def test_propose_bill_refuses_a_milestone_that_is_not_ready(api, make_agreed):
    project = await make_agreed()
    error = await api.post(
        f"/api/milestones/{project['milestones'][1]['id']}/propose-bill", expect=409
    )
    assert error["code"] == "MILESTONE_NOT_READY"
