"""Judge Mode: per-visitor isolation, abuse and cost limits, and the skip-ahead shortcuts."""

import pytest

from app.agent.cached import load_cached_intake
from app.services.seed import FOLLOW_UP_MESSAGE, INTAKE_MESSAGE
from tests.conftest import BUYER, pending


@pytest.fixture(autouse=True)
def judge(settings):
    settings.judge_mode = True
    settings.recipient_allowlist = [BUYER]
    settings.paypal_sandbox_buyer_email = BUYER


async def start(api):
    return (await api.post("/api/demo/reset"))["project"]


async def agree(api, project):
    await api.patch(
        f"/api/projects/{project['id']}",
        {
            "title": "T",
            "deliverables": ["One full-body illustration"],
            "revisions_included": 2,
            "deadline_date": "2026-11-25",
            "usage_rights": "Personal streaming",
            "total_minor_units": 30000,
            "client_email": BUYER,
        },
    )
    project = await api.post(f"/api/projects/{project['id']}/accept")
    await api.post(
        f"/api/c/{project['share_token']}/accept", {"scope_version": project["scope_version"]}
    )
    return await api.get(f"/api/projects/{project['id']}")


# --- cookie ---


async def test_cookie_is_signed_httponly_and_lax(api):
    response = await api.client.post("/api/demo/reset", headers={"Idempotency-Key": "k1"})
    cookie = response.headers["set-cookie"].lower()
    assert "cm_visitor=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


async def test_tampered_cookie_is_a_new_visitor(api, new_visitor):
    project = await start(api)
    forger = new_visitor()
    forger.client.cookies.set("cm_visitor", "someone.deadbeef")
    await forger.get(f"/api/projects/{project['id']}", expect=404)


# --- isolation ---


async def test_visitors_cannot_read_or_write_each_others_projects(
    api, new_visitor, make_agreed, fake_paypal
):
    alice, bob = api, new_visitor()
    a_project = await agree(alice, await start(alice))
    await start(bob)
    pid, mid = a_project["id"], a_project["milestones"][0]["id"]
    card = pending(a_project, "BILL_MILESTONE")

    await bob.get(f"/api/projects/{pid}", expect=404)
    await bob.patch(f"/api/projects/{pid}", {"title": "hijack"}, expect=404)
    await bob.put(f"/api/projects/{pid}/milestones", {"milestones": []}, expect=422)
    await bob.post(f"/api/projects/{pid}/accept", expect=404)
    await bob.post(f"/api/projects/{pid}/cancel", expect=404)
    await bob.post(f"/api/projects/{pid}/revisions", expect=404)
    await bob.post(f"/api/projects/{pid}/messages", {"body": FOLLOW_UP_MESSAGE}, expect=404)
    await bob.post(f"/api/milestones/{mid}/deliver", expect=404)
    await bob.post(f"/api/milestones/{mid}/propose-bill", expect=404)
    await bob.post(f"/api/proposals/{card['id']}/approve", expect=404)
    await bob.post(f"/api/proposals/{card['id']}/dismiss", expect=404)
    await bob.patch(f"/api/proposals/{card['id']}", {"note": "x"}, expect=404)
    await bob.post("/api/invoices/abc/refresh", expect=404)
    await bob.post("/api/invoices/abc/cancel", expect=404)
    await bob.post("/api/demo/jump", {"project_id": pid, "target": "deposit_paid"}, expect=404)

    assert fake_paypal.calls == []
    assert await bob.get("/api/projects") != await alice.get("/api/projects")
    assert [p["id"] for p in await bob.get("/api/projects")] != [pid]
    untouched = await alice.get(f"/api/projects/{pid}")
    assert untouched["title"] == "T"
    assert pending(untouched, "BILL_MILESTONE")["id"] == card["id"]


async def test_put_milestones_of_another_visitor_is_404(api, new_visitor):
    alice, bob = api, new_visitor()
    project = await start(alice)
    await start(bob)
    plan = {
        "milestones": [{"title": "All", "basis_points": 10000, "billing_trigger": "ON_AGREEMENT"}]
    }
    await bob.put(f"/api/projects/{project['id']}/milestones", plan, expect=404)


async def test_reset_affects_only_the_caller(api, new_visitor):
    alice, bob = api, new_visitor()
    a_project = await start(alice)
    b_project = await start(bob)
    b_again = await start(bob)
    assert b_again["id"] != b_project["id"]
    await bob.get(f"/api/projects/{b_project['id']}", expect=404)
    assert (await alice.get(f"/api/projects/{a_project['id']}"))["id"] == a_project["id"]


async def test_rate_card_edits_are_per_visitor(api, new_visitor):
    alice, bob = api, new_visitor()
    await start(alice)
    await start(bob)
    items = (await alice.get("/api/settings/rate-card"))["items"]
    items[0]["unit_price_minor_units"] = 99999
    await alice.put("/api/settings/rate-card", {"items": items})
    bob_items = (await bob.get("/api/settings/rate-card"))["items"]
    assert 99999 not in {i["unit_price_minor_units"] for i in bob_items}
    assert {i["code"] for i in bob_items} == {i["code"] for i in items}
    assert {i["name"] for i in bob_items} == {i["name"] for i in items}


async def test_client_page_works_by_token_without_a_cookie(api, new_visitor):
    project = await start(api)
    stranger = new_visitor()
    view = await stranger.get(f"/api/c/{project['share_token']}")
    assert view["seller_display_name"] == "Jiwoo"
    await stranger.get("/api/c/not-a-token", expect=404)


async def test_session_seeds_on_demand_and_resumes(api):
    first = await api.get("/api/demo/session")
    again = await api.get("/api/demo/session")
    assert first["project"]["id"] == again["project"]["id"]
    assert first["suggested_client_email"] == BUYER


async def test_project_count_per_visitor_is_capped(api, settings):
    settings.limit_projects_per_visitor = 2
    await api.post("/api/projects", {"title": "a"}, expect=201)
    await api.post("/api/projects", {"title": "b"}, expect=201)
    error = await api.post("/api/projects", {"title": "c"}, expect=429)
    assert error["code"] == "RATE_LIMITED" and "request_id" in error


async def test_demo_info_shows_login_only_from_settings(api, settings):
    info = await api.get("/api/demo/info")
    assert info["buyer_login"] == {"email": None, "password": None}
    settings.demo_buyer_email = "b@example.com"
    settings.demo_buyer_password = type(settings.demo_buyer_password)("pw-from-env")
    info = await api.get("/api/demo/info")
    assert info["buyer_login"] == {"email": "b@example.com", "password": "pw-from-env"}


# --- limits ---


async def test_write_rate_limit_is_per_visitor_with_the_uniform_error(api, new_visitor, settings):
    settings.limit_writes_per_minute_visitor = 3
    # The first request has no cookie yet, so only the IP limit counts it.
    for _ in range(4):
        await api.post("/api/demo/reset")
    error = await api.post("/api/demo/reset", expect=429)
    assert set(error) >= {"code", "message", "request_id"} and error["code"] == "RATE_LIMITED"
    other = new_visitor()
    await other.post("/api/demo/reset")  # A different visitor is unaffected.


async def test_spoofed_forwarded_for_does_not_dodge_the_ip_limit(api, new_visitor, settings):
    settings.limit_writes_per_minute_ip = 2
    statuses = []
    for i in range(4):
        visitor = new_visitor()
        response = await visitor.client.post(
            "/api/demo/reset",
            headers={"Idempotency-Key": f"k{i}", "X-Forwarded-For": f"9.9.9.{i}, 10.0.0.1"},
        )
        statuses.append(response.status_code)
    assert statuses == [200, 200, 429, 429]


async def test_oversized_body_is_refused(api):
    response = await api.client.post(
        "/api/analyze", json={"message": "x" * 5000, "pad": "y" * 70000}, headers={}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/analyze", {"message": "x" * 5001}),
        ("post", "/api/projects", {"description": "x" * 4001}),
        ("post", "/api/projects", {"usage_rights": "x" * 2001}),
        ("post", "/api/projects", {"deliverables": ["x" * 301]}),
        ("post", "/api/projects", {"title": "x" * 201}),
    ],
)
async def test_text_inputs_have_length_limits(api, method, path, body):
    error = await getattr(api, method)(path, body, expect=422)
    assert error["code"] == "VALIDATION_ERROR"


async def test_note_and_evidence_limits(api, make_agreed):
    project = await make_agreed()
    milestone = project["milestones"][0]["id"]
    await api.post(f"/api/milestones/{milestone}/deliver", {"note": "x" * 2001}, expect=422)
    await api.post(f"/api/projects/{project['id']}/messages", {"body": "x" * 5001}, expect=422)


async def test_llm_per_minute_limit_answers_429(api, settings):
    settings.limit_llm_per_minute_visitor = 2
    await api.post("/api/analyze", {"message": "hello"})
    await api.post("/api/analyze", {"message": "hello"})
    error = await api.post("/api/analyze", {"message": "hello"}, expect=429)
    assert error["code"] == "RATE_LIMITED"


async def test_global_llm_cap_serves_cached_demo_message_else_503(api, settings, fake_ai):
    settings.limit_llm_per_day_global = 1
    await api.post("/api/analyze", {"message": "first uses the budget"})
    calls_before = len(fake_ai.guard_calls)

    cached = await api.post("/api/analyze", {"message": INTAKE_MESSAGE})
    assert cached["source"] == "cached"
    assert cached == load_cached_intake(INTAKE_MESSAGE).model_dump(mode="json") | {}

    error = await api.post("/api/analyze", {"message": "something new"}, expect=503)
    assert error["code"] == "LLM_DAILY_CAP" and "request_id" in error
    assert len(fake_ai.guard_calls) == calls_before


async def test_global_cap_applies_to_follow_up_messages(api, settings, fake_ai):
    project = await agree(api, await start(api))
    settings.limit_llm_per_day_global = 0
    done = await api.post(
        f"/api/projects/{project['id']}/messages", {"body": FOLLOW_UP_MESSAGE}, expect=201
    )
    assert done["scope_guard"]["source"] == "cached"
    assert fake_ai.guard_calls == []
    error = await api.post(
        f"/api/projects/{project['id']}/messages", {"body": "A brand new question?"}, expect=503
    )
    assert error["code"] == "LLM_DAILY_CAP"


async def test_visitor_daily_llm_cap_is_429(api, settings):
    settings.limit_llm_per_day_visitor = 1
    await api.post("/api/analyze", {"message": "one"})
    await api.post("/api/analyze", {"message": "two"}, expect=429)


async def test_invoice_creation_is_capped_per_visitor_hour_and_globally(
    api, new_visitor, settings, fake_paypal
):
    settings.limit_invoices_per_hour_visitor = 1
    project = await agree(api, await start(api))
    card = pending(project, "BILL_MILESTONE")
    await api.post(f"/api/proposals/{card['id']}/approve")
    assert fake_paypal.count("create") == 1
    # A repeat of the executed card does not use another slot, and the cap holds for new cards.
    await api.post(f"/api/proposals/{card['id']}/approve")

    settings.limit_invoices_per_hour_visitor = 6
    settings.limit_invoices_per_day_global = 1
    bob = new_visitor()
    b_project = await agree(bob, await start(bob))
    error = await bob.post(
        f"/api/proposals/{pending(b_project, 'BILL_MILESTONE')['id']}/approve", expect=429
    )
    assert error["code"] == "RATE_LIMITED"
    assert fake_paypal.count("create") == 1


async def test_invoice_hour_cap_blocks_the_second_card_of_one_visitor(api, settings, fake_paypal):
    settings.limit_invoices_per_hour_visitor = 1
    a = await agree(api, await start(api))
    await api.post(f"/api/proposals/{pending(a, 'BILL_MILESTONE')['id']}/approve")
    b = await agree(api, await start(api))
    await api.post(f"/api/proposals/{pending(b, 'BILL_MILESTONE')['id']}/approve", expect=429)
    assert fake_paypal.count("create") == 1


# --- shortcuts ---


def paid_invoice(fake_paypal, value="90.00", status="PAID"):
    invoice = fake_paypal.add_foreign_invoice("PRIOR-RUN-1", value, BUYER)
    fake_paypal.set_status(invoice["id"], status)
    return invoice["id"]


async def test_jump_adopts_a_real_paid_invoice_after_a_live_get(api, settings, fake_paypal):
    settings.demo_paid_invoice_id = paid_invoice(fake_paypal)
    project = await start(api)
    done = await api.post("/api/demo/jump", {"project_id": project["id"], "target": "deposit_paid"})
    assert done["applied"] is True
    assert "get" in fake_paypal.calls and fake_paypal.write_calls() == []
    deposit = done["project"]["milestones"][0]
    assert deposit["workflow_state"] == "SETTLED"
    invoice = done["project"]["invoices"][0]
    assert invoice["paypal_status"] == "PAID" and invoice["adopted"] is True
    assert done["project"]["milestones"][1]["workflow_state"] == "AWAITING_DELIVERY"
    assert done["project"]["file_formats"] == ["PNG (transparent)", "PSD (layered)"]
    # No dead billing card is left behind for the deposit PayPal already shows as paid.
    assert not [p for p in done["project"]["proposals"] if p["status"] in ("PENDING", "STALE")]


async def test_two_visitors_can_adopt_the_same_prepaid_invoice(
    api, new_visitor, settings, fake_paypal
):
    settings.demo_paid_invoice_id = paid_invoice(fake_paypal)
    bob = new_visitor()
    for client in (api, bob):
        project = await start(client)
        done = await client.post(
            "/api/demo/jump", {"project_id": project["id"], "target": "deposit_paid"}
        )
        assert done["applied"] is True


async def test_jump_to_sketch_shared_logs_delivery_after_paid(api, settings, fake_paypal):
    settings.demo_paid_invoice_id = paid_invoice(fake_paypal)
    project = await start(api)
    done = await api.post(
        "/api/demo/jump", {"project_id": project["id"], "target": "sketch_shared"}
    )
    assert done["applied"] is True
    assert done["project"]["milestones"][1]["workflow_state"] == "DELIVERED"


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("unconfigured", "No previously paid"),
        ("not_paid", "does not show"),
        ("wrong_amount", "does not show"),
        ("missing", "could not confirm"),
    ],
)
async def test_jump_never_fakes_paid(api, settings, fake_paypal, setup, expected):
    if setup == "not_paid":
        settings.demo_paid_invoice_id = paid_invoice(fake_paypal, status="SENT")
    elif setup == "wrong_amount":
        settings.demo_paid_invoice_id = paid_invoice(fake_paypal, value="10.00")
    elif setup == "missing":
        settings.demo_paid_invoice_id = "INV2-NOPE"
    project = await start(api)
    done = await api.post(
        "/api/demo/jump", {"project_id": project["id"], "target": "sketch_shared"}
    )
    assert done["applied"] is False and expected in done["message"]
    state = done["project"]
    assert state["status"] == "AGREED"
    assert state["invoices"] == []
    assert state["milestones"][0]["workflow_state"] == "READY_TO_BILL"
    # The demo stays usable: the normal billing card is waiting.
    assert pending(state, "BILL_MILESTONE")
    assert fake_paypal.write_calls() == []


async def test_jump_is_refused_outside_judge_mode(api, settings):
    project = await start(api)
    settings.judge_mode = False
    error = await api.post(
        "/api/demo/jump", {"project_id": project["id"], "target": "deposit_paid"}, expect=409
    )
    assert error["code"] == "NOT_JUDGE_MODE"


# --- client page ---


async def test_client_page_lists_not_billed_requests_without_internal_fields(api, make_agreed):
    project = await agree(api, await start(api))
    await api.post(
        f"/api/projects/{project['id']}/messages", {"body": FOLLOW_UP_MESSAGE}, expect=201
    )
    project = await api.get(f"/api/projects/{project['id']}")
    co = project["change_orders"][0]
    await api.post(f"/api/proposals/{pending(project, 'CHANGE_ORDER')['id']}/approve")
    view = await api.get(f"/api/c/{project['share_token']}")
    shown = next(c for c in view["change_orders"] if c["id"] == co["id"])
    assert shown["not_billed"] == [{"request_summary": "Merch use later"}]
