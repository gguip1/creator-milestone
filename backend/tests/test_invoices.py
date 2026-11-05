"""Invoice service against verified PayPal behavior (docs/paypal-test-log.md)."""

import asyncio
from datetime import timedelta

import pytest

from app.models import Commission, PaypalInvoice, Proposal, utcnow
from app.services.invoice_sync import poll_forever, poll_once, reconcile_active
from app.services.paypal_status import STATUS_MAP, describe_status
from tests.conftest import BUYER, bill_and_send, pending


async def approve_bill(api, project):
    bill = pending(project, "BILL_MILESTONE")
    await api.post(f"/api/proposals/{bill['id']}/approve")
    return await api.get(f"/api/projects/{project['id']}")


async def test_invoice_number_format_fits_paypal_limit(api, make_agreed):
    project = await approve_bill(api, await make_agreed())
    [invoice] = project["invoices"]
    parts = invoice["invoice_number"].split("-")
    assert parts[0] == "CM"
    assert parts[1] == project["id"][:8]
    assert parts[2] == project["milestones"][0]["id"][:6]
    assert parts[3] == "1"
    assert len(invoice["invoice_number"]) <= 25


async def test_create_timeout_after_landing_adopts_the_found_invoice(api, fake_paypal, make_agreed):
    project = await make_agreed()
    fake_paypal.timeout_next("create", apply_first=True)
    project = await approve_bill(api, project)
    [invoice] = project["invoices"]
    assert invoice["paypal_status"] == "DRAFT"
    assert invoice["paypal_invoice_id"] in fake_paypal.invoices
    assert len(fake_paypal.invoices) == 1
    assert fake_paypal.count("search") == 1
    assert "invoice_adopted" in {a["action"] for a in project["activity"]}


async def test_create_timeout_without_landing_fails_and_retry_searches_first(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.timeout_next("create")

    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=504)
    assert error["code"] == "PAYPAL_TIMEOUT"
    assert error["details"]["proposal_status"] == "FAILED"
    project = await api.get(f"/api/projects/{project['id']}")
    [card] = project["proposals"]
    assert card["status"] == "FAILED"
    assert card["can_approve"] is True
    number = project["invoices"][0]["invoice_number"]
    assert project["invoices"][0]["last_error_code"] == "PAYPAL_TIMEOUT"

    calls_before = len(fake_paypal.calls)
    retried = await api.post(f"/api/proposals/{bill['id']}/approve")
    assert retried["status"] == "EXECUTED"
    assert fake_paypal.calls[calls_before:] == ["search", "create"]
    project = await api.get(f"/api/projects/{project['id']}")
    assert [i["invoice_number"] for i in project["invoices"]] == [number]
    assert [i["last_error_code"] for i in project["invoices"]] == [None]
    assert next(iter(fake_paypal.invoices.values()))["detail"]["invoice_number"] == number


async def test_duplicate_number_on_retry_adopts_instead_of_double_billing(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    # The first attempt reached PayPal, and the recovery search also failed.
    fake_paypal.timeout_next("create", apply_first=True)
    fake_paypal.timeout_next("search")
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=504)
    assert len(fake_paypal.invoices) == 1

    # The retry's search misses it (index lag), so create gets the verified 422, then adopts.
    fake_paypal.miss_search_next()
    calls_before = len(fake_paypal.calls)
    retried = await api.post(f"/api/proposals/{bill['id']}/approve")

    assert retried["status"] == "EXECUTED"
    assert fake_paypal.calls[calls_before:] == ["search", "create", "search", "get"]
    assert len(fake_paypal.invoices) == 1
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["invoices"][0]["paypal_invoice_id"] in fake_paypal.invoices


async def test_duplicate_with_nothing_found_fails_and_stays_retryable(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 422, "UNPROCESSABLE_ENTITY", "DUPLICATE_INVOICE_NUMBER")
    fake_paypal.miss_search_next()
    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert error["details"]["proposal_status"] == "FAILED"
    assert (await api.post(f"/api/proposals/{bill['id']}/approve"))["status"] == "EXECUTED"


async def test_duplicate_error_on_first_create_is_recovered_by_search(
    api, fake_paypal, make_agreed, session_factory
):
    """A number already at PayPal with matching terms is adopted, not recreated."""
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    number = f"CM-{project['id'][:8]}-{project['milestones'][0]['id'][:6]}-1"
    fake_paypal.add_foreign_invoice(number, "90.00", BUYER)

    executed = await api.post(f"/api/proposals/{bill['id']}/approve")

    assert executed["status"] == "EXECUTED"
    assert len(fake_paypal.invoices) == 1
    assert fake_paypal.calls[:3] == ["create", "search", "get"]


@pytest.mark.parametrize(
    ("value", "email", "mismatch"),
    [("55.00", BUYER, "amount"), ("90.00", "someone@else.example", "recipient")],
)
async def test_found_invoice_with_other_terms_is_not_adopted(
    api, fake_paypal, make_agreed, value, email, mismatch
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    number = f"CM-{project['id'][:8]}-{project['milestones'][0]['id'][:6]}-1"
    fake_paypal.add_foreign_invoice(number, value, email)

    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=409)

    assert error["code"] == "INVOICE_NUMBER_CONFLICT"
    assert error["details"]["mismatch"] == mismatch
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["invoices"][0]["paypal_invoice_id"] is None
    assert project["proposals"][0]["status"] == "FAILED"


async def test_paypal_422_marks_failed_and_can_be_retried_with_same_key(
    api, fake_paypal, make_agreed
):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 422, "UNPROCESSABLE_ENTITY", "INVALID_STRING_LENGTH")

    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=422)
    assert error["code"] == "PAYPAL_VALIDATION_ERROR"
    assert error["details"]["issues"][0]["issue"] == "INVALID_STRING_LENGTH"

    project = await api.get(f"/api/projects/{project['id']}")
    [card] = project["proposals"]
    assert card["status"] == "FAILED"
    assert card["error_code"] == "PAYPAL_VALIDATION_ERROR"
    assert card["idempotency_key"] == bill["idempotency_key"]

    retried = await api.post(f"/api/proposals/{bill['id']}/approve")
    assert retried["status"] == "EXECUTED"
    assert retried["idempotency_key"] == bill["idempotency_key"]
    assert fake_paypal.count("create") == 2


async def test_failed_card_can_be_dismissed(api, fake_paypal, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 500, "INTERNAL_SERVER_ERROR")
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=502)
    assert (await api.post(f"/api/proposals/{bill['id']}/dismiss"))["status"] == "DISMISSED"


async def test_korean_restriction_gives_plain_error_and_keeps_the_draft(
    api, fake_paypal, make_agreed
):
    project = await approve_bill(api, await make_agreed())
    send = pending(project, "SEND_INVOICE")
    fake_paypal.korean_buyer = True

    error = await api.post(f"/api/proposals/{send['id']}/approve", expect=422)

    assert error["code"] == "KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED"
    assert "Korean" in error["message"]
    assert "draft invoice is kept" in error["message"]
    project = await api.get(f"/api/projects/{project['id']}")
    [invoice] = project["invoices"]
    assert invoice["is_active"] is True
    assert invoice["paypal_status"] == "DRAFT"
    assert invoice["last_error_code"] == "KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED"
    assert project["milestones"][0]["workflow_state"] == "READY_TO_BILL"
    assert fake_paypal.invoices[invoice["paypal_invoice_id"]]["status"] == "DRAFT"
    card = next(p for p in project["proposals"] if p["id"] == send["id"])
    assert card["status"] == "FAILED"

    # Fixed at PayPal's side: the same card can be retried.
    fake_paypal.korean_buyer = False
    assert (await api.post(f"/api/proposals/{send['id']}/approve"))["status"] == "EXECUTED"


async def test_403_pauses_billing_until_a_retry_succeeds(api, fake_paypal, make_agreed):
    first = await make_agreed()
    second = await make_agreed()
    bill = pending(first, "BILL_MILESTONE")
    other = pending(second, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 403, "NOT_AUTHORIZED")

    error = await api.post(f"/api/proposals/{bill['id']}/approve", expect=403)
    assert error["code"] == "PAYPAL_NOT_AUTHORIZED"

    project = await api.get(f"/api/projects/{first['id']}")
    assert project["billing_disabled_code"] == "PAYPAL_NOT_AUTHORIZED"
    blocked = await api.post(f"/api/proposals/{other['id']}/approve", expect=422)
    assert "BILLING_DISABLED" in {b["code"] for b in blocked["details"]["blockers"]}
    assert fake_paypal.count("create") == 1

    # Retrying the card that hit the 403 is the re-check, and success lifts the pause.
    assert (await api.post(f"/api/proposals/{bill['id']}/approve"))["status"] == "EXECUTED"
    project = await api.get(f"/api/projects/{first['id']}")
    assert project["billing_disabled_code"] is None
    assert (await api.post(f"/api/proposals/{other['id']}/approve"))["status"] == "EXECUTED"


async def test_pause_ends_when_the_card_that_could_lift_it_is_dismissed(
    api, fake_paypal, make_agreed
):
    first = await make_agreed()
    second = await make_agreed()
    bill = pending(first, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 403, "NOT_AUTHORIZED")
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=403)
    await api.post(f"/api/proposals/{bill['id']}/dismiss")

    project = await api.get(f"/api/projects/{second['id']}")
    assert project["billing_disabled_code"] is None
    card = pending(project, "BILL_MILESTONE")
    assert (await api.post(f"/api/proposals/{card['id']}/approve"))["status"] == "EXECUTED"


async def test_send_stores_payer_link_from_the_single_link_object(api, fake_paypal, make_agreed):
    project = await make_agreed()
    project = await bill_and_send(api, project["id"])
    [invoice] = project["invoices"]
    assert invoice["payer_link"] == (
        f"https://www.sandbox.paypal.com/invoice/p/#{invoice['paypal_invoice_id']}"
    )
    assert invoice["sent_at"] is not None
    # Send is verified by a GET afterward.
    send_index = fake_paypal.calls.index("send")
    assert fake_paypal.calls[send_index + 1] == "get"


async def test_send_timeout_after_landing_is_verified_by_get(api, fake_paypal, make_agreed):
    project = await approve_bill(api, await make_agreed())
    send = pending(project, "SEND_INVOICE")
    fake_paypal.timeout_next("send", apply_first=True)
    executed = await api.post(f"/api/proposals/{send['id']}/approve")
    assert executed["status"] == "EXECUTED"
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["invoices"][0]["paypal_status"] == "SENT"
    assert project["milestones"][0]["workflow_state"] == "BILLED"
    assert fake_paypal.count("send") == 1


async def test_send_retry_does_not_send_twice(api, fake_paypal, make_agreed):
    project = await approve_bill(api, await make_agreed())
    send = pending(project, "SEND_INVOICE")
    fake_paypal.timeout_next("send", apply_first=True)
    fake_paypal.timeout_next("get")
    await api.post(f"/api/proposals/{send['id']}/approve", expect=504)

    assert (await api.post(f"/api/proposals/{send['id']}/approve"))["status"] == "EXECUTED"
    assert fake_paypal.count("send") == 1


async def test_only_paid_settles_a_milestone(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    remote_id = invoice["paypal_invoice_id"]

    for status in ("UNPAID", "PAYMENT_PENDING", "PARTIALLY_PAID", "MARKED_AS_PAID"):
        fake_paypal.set_status(remote_id, status)
        refreshed = await api.post(f"/api/invoices/{invoice['id']}/refresh")
        assert refreshed["paypal_status"] == status
        project = await api.get(f"/api/projects/{project['id']}")
        assert project["milestones"][0]["workflow_state"] == "BILLED", status
        assert project["milestones"][1]["workflow_state"] == "LOCKED", status

    assert refreshed["status_label"] == "Marked paid (outside PayPal)"
    assert refreshed["settles_milestone"] is False
    assert project["milestones"][0]["flagged"] is True

    fake_paypal.set_status(remote_id, "PAID")
    refreshed = await api.post(f"/api/invoices/{invoice['id']}/refresh")
    assert refreshed["status_label"] == "Paid via PayPal"
    assert refreshed["paid_seen_at"] is not None
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["milestones"][0]["workflow_state"] == "SETTLED"
    assert project["milestones"][1]["workflow_state"] == "AWAITING_DELIVERY"


async def test_refund_flags_a_settled_milestone_without_reversing_it(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    fake_paypal.set_status(invoice["paypal_invoice_id"], "REFUNDED")
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["milestones"][0]["workflow_state"] == "SETTLED"
    assert project["milestones"][0]["flagged"] is True


async def test_paid_arriving_after_a_lost_send_response_still_settles(
    api, fake_paypal, make_agreed
):
    project = await approve_bill(api, await make_agreed())
    send = pending(project, "SEND_INVOICE")
    [invoice] = project["invoices"]
    fake_paypal.timeout_next("send", apply_first=True)
    fake_paypal.timeout_next("get")
    await api.post(f"/api/proposals/{send['id']}/approve", expect=504)

    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["milestones"][0]["workflow_state"] == "SETTLED"
    assert project["status"] == "IN_PROGRESS"


async def test_cancel_is_a_proposal_then_rebill_uses_a_new_number(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]

    card = await api.post(f"/api/invoices/{invoice['id']}/cancel", expect=201)
    assert card["kind"] == "CANCEL_INVOICE"
    assert fake_paypal.count("cancel") == 0  # Asking is not doing.
    again = await api.post(f"/api/invoices/{invoice['id']}/cancel", expect=201)
    assert again["id"] == card["id"]

    await api.post(f"/api/proposals/{card['id']}/approve")
    assert fake_paypal.count("cancel") == 1
    project = await api.get(f"/api/projects/{project['id']}")
    [old] = project["invoices"]
    assert old["paypal_status"] == "CANCELLED"
    assert old["is_active"] is False
    assert project["milestones"][0]["workflow_state"] == "READY_TO_BILL"

    bill = pending(project, "BILL_MILESTONE")
    project = await bill_and_send(api, project["id"])
    assert bill["payload"]["amount_minor_units"] == 9000
    old, new = project["invoices"]
    assert new["attempt"] == 2
    assert new["invoice_number"] != old["invoice_number"]
    assert new["paypal_status"] == "SENT"
    assert project["milestones"][0]["workflow_state"] == "BILLED"


async def test_cancel_refuses_a_draft(api, fake_paypal, make_agreed):
    project = await approve_bill(api, await make_agreed())
    [invoice] = project["invoices"]
    error = await api.post(f"/api/invoices/{invoice['id']}/cancel", expect=409)
    assert error["code"] == "CANNOT_CANCEL_DRAFT_INVOICE"
    assert fake_paypal.count("cancel") == 0


async def test_cancel_retry_after_lost_answer_does_not_cancel_twice(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    card = await api.post(f"/api/invoices/{invoice['id']}/cancel", expect=201)
    fake_paypal.timeout_next("cancel", apply_first=True)
    await api.post(f"/api/proposals/{card['id']}/approve", expect=504)
    assert (await api.post(f"/api/proposals/{card['id']}/approve"))["status"] == "EXECUTED"
    assert fake_paypal.count("cancel") == 1


async def test_cancelled_outside_our_app_reopens_the_milestone(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    fake_paypal.set_status(invoice["paypal_invoice_id"], "CANCELLED")
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["milestones"][0]["workflow_state"] == "READY_TO_BILL"
    assert pending(project, "BILL_MILESTONE")


async def test_refresh_maps_paypal_errors(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    fake_paypal.timeout_next("get")
    error = await api.post(f"/api/invoices/{invoice['id']}/refresh", expect=504)
    assert error["code"] == "PAYPAL_TIMEOUT"


async def test_refresh_needs_an_invoice_that_exists_at_paypal(api, fake_paypal, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 500, "INTERNAL_SERVER_ERROR")
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=502)
    project = await api.get(f"/api/projects/{project['id']}")
    error = await api.post(f"/api/invoices/{project['invoices'][0]['id']}/refresh", expect=422)
    assert error["code"] == "INVOICE_NOT_CREATED"


async def test_refresh_needs_no_idempotency_key(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    response = await api.client.post(f"/api/invoices/{invoice['id']}/refresh")
    assert response.status_code == 200


async def test_payment_timestamp_comes_from_our_clock(api, fake_paypal, make_agreed):
    """PayPal's payment_date_time was seen about 8 hours off, so it must not be used."""
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    remote = fake_paypal.invoices[invoice["paypal_invoice_id"]]
    remote["payments"] = {"transactions": [{"payment_date_time": "2001-01-01T00:00:00Z"}]}
    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    refreshed = await api.post(f"/api/invoices/{invoice['id']}/refresh")
    assert refreshed["paid_seen_at"] == refreshed["last_synced_at"]
    assert not refreshed["paid_seen_at"].startswith("2001")


async def test_poll_updates_open_invoices_and_skips_others(
    api, fake_paypal, make_agreed, session_factory, settings
):
    sent = await bill_and_send(api, (await make_agreed())["id"])
    drafted = await approve_bill(api, await make_agreed())
    [invoice] = sent["invoices"]
    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])

    fake_paypal.calls.clear()
    with session_factory() as db:
        assert await poll_once(db, fake_paypal.client(), settings) == 1
    assert fake_paypal.calls == ["get"]

    project = await api.get(f"/api/projects/{sent['id']}")
    assert project["milestones"][0]["workflow_state"] == "SETTLED"
    drafted = await api.get(f"/api/projects/{drafted['id']}")
    assert drafted["invoices"][0]["paypal_status"] == "DRAFT"

    # Nothing is open anymore except the still-unsent draft, which is not polled.
    fake_paypal.calls.clear()
    with session_factory() as db:
        assert await poll_once(db, fake_paypal.client(), settings) == 0
    assert fake_paypal.calls == []


async def test_poll_can_be_limited_to_viewed_projects(
    api, fake_paypal, make_agreed, session_factory, settings
):
    first = await bill_and_send(api, (await make_agreed())["id"])
    second = await bill_and_send(api, (await make_agreed())["id"])
    with session_factory() as db:
        count = await poll_once(db, fake_paypal.client(), settings, only_commissions={second["id"]})
    assert count == 1
    assert first["id"] != second["id"]


async def test_one_failed_poll_does_not_stop_the_rest(
    api, fake_paypal, make_agreed, session_factory, settings
):
    await bill_and_send(api, (await make_agreed())["id"])
    await bill_and_send(api, (await make_agreed())["id"])
    fake_paypal.timeout_next("get")
    with session_factory() as db:
        assert await poll_once(db, fake_paypal.client(), settings) == 1


async def test_late_poll_answer_is_dropped_when_the_row_moved(
    api, fake_paypal, make_agreed, session_factory
):
    """A GET that started before a cancel must not write the old status back afterward."""
    from app.services.invoices import fetch_and_apply

    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]

    real_get = fake_paypal.client()

    class RacingClient:
        async def get_invoice(self, invoice_id):
            answer = await real_get.get_invoice(invoice_id)
            with session_factory() as other:
                other.get(PaypalInvoice, invoice["id"]).paypal_status = "CANCELLED"
                other.commit()
            return answer

    with session_factory() as db:
        row = db.get(PaypalInvoice, invoice["id"])
        await fetch_and_apply(db, row.commission, row, RacingClient())
        db.commit()
        db.refresh(row)
        assert row.paypal_status == "CANCELLED"


async def test_reminder_appears_after_threshold_and_is_a_proposal(
    api, fake_paypal, make_agreed, session_factory, settings
):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]

    # Not due yet.
    with session_factory() as db:
        await poll_once(db, fake_paypal.client(), settings)
    project = await api.get(f"/api/projects/{project['id']}")
    assert not [p for p in project["proposals"] if p["kind"] == "SEND_REMINDER"]

    with session_factory() as db:
        db.get(PaypalInvoice, invoice["id"]).sent_at = utcnow() - timedelta(minutes=61)
        db.commit()
        reconcile_active(db, settings)
    project = await api.get(f"/api/projects/{project['id']}")
    card = pending(project, "SEND_REMINDER")
    assert "friendly reminder" in card["payload"]["note"]
    assert fake_paypal.count("remind") == 0

    edited = await api.patch(f"/api/proposals/{card['id']}", {"note": "Please pay, thanks!"})
    assert edited["payload"]["note"] == "Please pay, thanks!"
    await api.post(f"/api/proposals/{card['id']}/approve")
    assert fake_paypal.count("remind") == 1
    remind_request = next(r for r in fake_paypal.requests if r.url.path.endswith("/remind"))
    assert b"Please pay, thanks!" in remind_request.content

    project = await api.get(f"/api/projects/{project['id']}")
    assert project["invoices"][0]["reminders_sent"] == 1
    # The clock restarts, so no second card right away.
    assert not [
        p for p in project["proposals"] if p["kind"] == "SEND_REMINDER" and p["status"] == "PENDING"
    ]


async def test_reminder_goes_stale_when_the_invoice_is_paid(
    api, fake_paypal, make_agreed, session_factory, settings
):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    with session_factory() as db:
        db.get(PaypalInvoice, invoice["id"]).sent_at = utcnow() - timedelta(minutes=61)
        db.commit()
        reconcile_active(db, settings)
    project = await api.get(f"/api/projects/{project['id']}")
    card = pending(project, "SEND_REMINDER")

    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    project = await api.get(f"/api/projects/{project['id']}")
    assert next(p for p in project["proposals"] if p["id"] == card["id"])["status"] == "STALE"
    await api.post(f"/api/proposals/{card['id']}/approve", expect=409)
    assert fake_paypal.count("remind") == 0


async def test_interrupted_create_retry_does_not_double_bill(
    api, fake_paypal, make_agreed, session_factory
):
    """Server died after the POST landed: on restart the card is FAILED and the retry adopts."""
    from app.agent.executor import recover_interrupted

    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.timeout_next("create", apply_first=True)
    fake_paypal.timeout_next("search")
    await api.post(f"/api/proposals/{bill['id']}/approve", expect=504)
    with session_factory() as db:
        db.get(Proposal, bill["id"]).status = "APPROVED"
        db.commit()
        assert recover_interrupted(db) == 1
    assert (await api.post(f"/api/proposals/{bill['id']}/approve"))["status"] == "EXECUTED"
    assert len(fake_paypal.invoices) == 1
    assert fake_paypal.count("create") == 1


@pytest.mark.parametrize(
    ("status", "label", "settles"),
    [
        ("DRAFT", "Draft (not sent)", False),
        ("SCHEDULED", "Scheduled", False),
        ("SENT", "Sent — awaiting payment", False),
        ("UNPAID", "Sent — awaiting payment", False),
        ("PAYMENT_PENDING", "Payment pending", False),
        ("PARTIALLY_PAID", "Partially paid", False),
        ("PAID", "Paid via PayPal", True),
        ("MARKED_AS_PAID", "Marked paid (outside PayPal)", False),
        ("CANCELLED", "Cancelled", False),
        ("REFUNDED", "Refunded", False),
        ("PARTIALLY_REFUNDED", "Partially refunded", False),
        ("MARKED_AS_REFUNDED", "Marked refunded (outside PayPal)", False),
    ],
)
def test_status_mapping_covers_every_prd_value(status, label, settles):
    info = describe_status(status)
    assert info.label == label
    assert info.settles_milestone is settles


def test_status_mapping_table_has_nothing_untested_and_unknown_is_shown_raw():
    assert len(STATUS_MAP) == 12
    assert "SOMETHING_NEW" in describe_status("SOMETHING_NEW").label
    assert describe_status("SOMETHING_NEW").settles_milestone is False


async def test_invoices_are_stored_with_commission_links(api, make_agreed, session_factory):
    project = await approve_bill(api, await make_agreed())
    with session_factory() as db:
        commission = db.get(Commission, project["id"])
        assert [i.milestone.title for i in commission.invoices] == ["Deposit"]


async def test_poll_loop_settles_paid_invoices_on_its_own(
    api, fake_paypal, make_agreed, session_factory, settings
):
    project = await bill_and_send(api, (await make_agreed())["id"])
    fake_paypal.buyer_pays(project["invoices"][0]["paypal_invoice_id"])
    settings.poll_interval_seconds = 0

    task = asyncio.create_task(poll_forever(session_factory, fake_paypal.client(), settings))
    try:
        async with asyncio.timeout(5):
            while True:
                await asyncio.sleep(0.01)
                with session_factory() as db:
                    if db.get(PaypalInvoice, project["invoices"][0]["id"]).paid_seen_at:
                        break
    finally:
        task.cancel()
    project = await api.get(f"/api/projects/{project['id']}")
    assert project["milestones"][0]["workflow_state"] == "SETTLED"


async def test_poll_loop_survives_a_bad_cycle(session_factory, fake_paypal, settings, monkeypatch):
    calls = []

    async def exploding_poll(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr("app.services.invoice_sync.poll_once", exploding_poll)
    settings.poll_interval_seconds = 0
    task = asyncio.create_task(poll_forever(session_factory, fake_paypal.client(), settings))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    assert calls
