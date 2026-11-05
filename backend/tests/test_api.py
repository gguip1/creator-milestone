"""HTTP contract: uniform errors, Idempotency-Key, state conflicts, scope, settings, demo reset."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.api.deps import get_paypal_client
from app.main import app
from app.models import ExtractionField, IdempotencyRecord, Proposal
from app.schemas.ai import LLMUnavailableError
from app.services.seed import FOLLOW_UP_MESSAGE, INTAKE_MESSAGE, seed_demo_project
from tests.conftest import bill_and_send, pending

# --- Uniform errors ---


async def test_not_found_is_uniform(api):
    body = await api.get("/api/projects/nope", expect=404)
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "NOT_FOUND"


async def test_unknown_route_and_wrong_method_are_uniform(api):
    assert (await api.get("/api/no-such-route", expect=404))["code"] == "NOT_FOUND"
    response = await api.client.delete("/api/health", headers={"Idempotency-Key": "k"})
    assert response.status_code == 405
    assert response.json()["code"] == "METHOD_NOT_ALLOWED"


async def test_validation_error_is_uniform_and_does_not_echo_input(api):
    body = await api.post(
        "/api/projects", {"client_email": "secret-person@example.com", "bogus": 1}, expect=422
    )
    assert body["code"] == "VALIDATION_ERROR"
    assert body["request_id"]
    assert body["details"]["errors"][0]["loc"][-1] == "bogus"
    assert "secret-person" not in str(body)


async def test_request_id_header_matches_error_body(api):
    response = await api.client.get("/api/projects/nope")
    assert response.headers["X-Request-Id"] == response.json()["request_id"]


async def test_unexpected_exception_is_a_uniform_500(api):
    from app.api.deps import get_today

    def boom():
        raise RuntimeError("private detail")

    app.dependency_overrides[get_today] = boom
    response = await api.client.post("/api/analyze", json={"message": "hi"})
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "private" not in response.text


# --- Idempotency-Key ---


async def test_writes_require_a_key(api):
    response = await api.client.post("/api/projects", json={"title": "x"})
    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.parametrize("path", ["/api/analyze"])
async def test_stateless_routes_need_no_key(api, path):
    response = await api.client.post(path, json={"message": "Hello"})
    assert response.status_code == 200


async def test_same_key_replays_without_running_again(api):
    first = await api.client.post(
        "/api/projects", json={"title": "x"}, headers={"Idempotency-Key": "abc"}
    )
    second = await api.client.post(
        "/api/projects", json={"title": "x"}, headers={"Idempotency-Key": "abc"}
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert len(await api.get("/api/projects")) == 1


async def test_same_key_with_different_body_is_refused(api):
    await api.post("/api/projects", {"title": "x"}, key="abc", expect=201)
    body = await api.post("/api/projects", {"title": "y"}, key="abc", expect=422)
    assert body["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_server_side_failure_releases_the_key(api, fake_ai, make_agreed, session_factory):
    project = await make_agreed()
    fake_ai.guard_error = LLMUnavailableError("down")
    path = f"/api/projects/{project['id']}/messages"
    await api.post(path, {"body": FOLLOW_UP_MESSAGE}, key="retry-me", expect=503)
    with session_factory() as db:
        assert db.get(IdempotencyRecord, "retry-me") is None

    fake_ai.guard_error = None
    posted = await api.post(path, {"body": FOLLOW_UP_MESSAGE}, key="retry-me", expect=201)
    assert posted["change_order"]["total_minor_units"] == 10000


async def test_paypal_failure_lets_the_same_key_retry(api, fake_paypal, make_agreed):
    project = await make_agreed()
    bill = pending(project, "BILL_MILESTONE")
    fake_paypal.fail_next("create", 500, "INTERNAL_SERVER_ERROR")
    path = f"/api/proposals/{bill['id']}/approve"
    await api.post(path, key="click-1", expect=502)
    assert (await api.post(path, key="click-1"))["status"] == "EXECUTED"


# --- Forbidden transitions over HTTP ---


async def test_client_cannot_accept_before_the_seller(api, make_project):
    project = await make_project()
    error = await api.post(
        f"/api/c/{project['share_token']}/accept", {"scope_version": 1}, expect=409
    )
    assert error["code"] == "SELLER_ACCEPTANCE_REQUIRED"


async def test_client_must_accept_the_current_version(api, make_project):
    project = await make_project()
    await api.post(f"/api/projects/{project['id']}/accept")
    error = await api.post(
        f"/api/c/{project['share_token']}/accept", {"scope_version": 7}, expect=409
    )
    assert error["code"] == "SCOPE_VERSION_MISMATCH"
    assert error["details"]["current_version"] == 1


async def test_seller_accept_checks_the_version_when_sent(api, make_project):
    project = await make_project()
    await api.post(f"/api/projects/{project['id']}/accept", {"scope_version": 9}, expect=409)
    assert (await api.post(f"/api/projects/{project['id']}/accept", {"scope_version": 1}))[
        "status"
    ] == "AWAITING_ACCEPTANCE"


async def test_accepting_twice_is_harmless(api, make_agreed):
    project = await make_agreed()
    again = await api.post(f"/api/projects/{project['id']}/accept")
    assert again["status"] == "AGREED"
    view = await api.post(f"/api/c/{project['share_token']}/accept", {"scope_version": 1})
    assert view["status"] == "AGREED"


async def test_deliver_on_a_locked_milestone_is_409(api, make_agreed):
    project = await make_agreed()
    sketch = project["milestones"][1]
    error = await api.post(f"/api/milestones/{sketch['id']}/deliver", expect=409)
    assert error["code"] == "FORBIDDEN_TRANSITION"
    assert error["details"] == {"entity": "milestone", "from": "LOCKED", "to": "DELIVERED"}


async def test_client_cannot_approve_an_undelivered_milestone(api, make_agreed):
    project = await make_agreed()
    token = project["share_token"]
    sketch = project["milestones"][1]
    await api.post(f"/api/c/{token}/milestones/{sketch['id']}/approve", expect=409)


async def test_deliver_twice_is_409(api, fake_paypal, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    [invoice] = project["invoices"]
    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    sketch = project["milestones"][1]
    await api.post(f"/api/milestones/{sketch['id']}/deliver")
    await api.post(f"/api/milestones/{sketch['id']}/deliver", expect=409)


async def test_evidence_must_be_a_web_link(api, make_agreed):
    project = await make_agreed()
    await api.post(
        f"/api/milestones/{project['milestones'][1]['id']}/deliver",
        {"evidence_url": "javascript:alert(1)"},
        expect=422,
    )


async def test_client_token_cannot_reach_another_projects_milestone(api, make_agreed):
    first = await make_agreed()
    second = await make_agreed()
    other = second["milestones"][0]
    await api.post(f"/api/c/{first['share_token']}/milestones/{other['id']}/approve", expect=404)
    await api.get("/api/c/not-a-token", expect=404)


async def test_cancelled_commission_cannot_move(api, make_project):
    project = await make_project()
    cancelled = await api.post(f"/api/projects/{project['id']}/cancel")
    assert cancelled["status"] == "CANCELLED"
    await api.post(f"/api/projects/{project['id']}/accept", expect=409)
    await api.patch(f"/api/projects/{project['id']}", {"title": "x"}, expect=409)


async def test_cancel_commission_refuses_while_an_invoice_is_open(api, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    error = await api.post(f"/api/projects/{project['id']}/cancel", expect=409)
    assert error["code"] == "OPEN_INVOICE_EXISTS"


async def test_cancelling_commission_stales_cards(api, make_agreed):
    project = await make_agreed()
    cancelled = await api.post(f"/api/projects/{project['id']}/cancel")
    assert [p["status"] for p in cancelled["proposals"]] == ["STALE"]


# --- Scope and plan ---


async def test_scope_is_locked_once_an_invoice_went_out(api, make_agreed):
    project = await bill_and_send(api, (await make_agreed())["id"])
    error = await api.patch(f"/api/projects/{project['id']}", {"title": "New"}, expect=409)
    assert error["code"] == "SCOPE_LOCKED"
    await api.put(
        f"/api/projects/{project['id']}/milestones",
        {
            "milestones": [
                {"title": "All", "basis_points": 10000, "billing_trigger": "ON_AGREEMENT"}
            ]
        },
        expect=409,
    )


async def test_edit_before_acceptance_refines_v1_after_acceptance_bumps(api, make_project):
    project = await make_project()
    edited = await api.patch(f"/api/projects/{project['id']}", {"title": "Refined"})
    assert edited["scope_version"] == 1
    await api.post(f"/api/projects/{project['id']}/accept")
    edited = await api.patch(f"/api/projects/{project['id']}", {"title": "Changed"})
    assert edited["scope_version"] == 2
    assert edited["status"] == "DRAFT"
    assert edited["seller_accepted_version"] is None


async def test_noop_patch_keeps_acceptance(api, make_project, scope):
    project = await make_project()
    await api.post(f"/api/projects/{project['id']}/accept")
    unchanged = await api.patch(f"/api/projects/{project['id']}", {"title": scope["title"]})
    assert unchanged["seller_accepted_version"] == 1
    assert unchanged["scope_version"] == 1


async def test_exact_split_and_price_edit_recalculates(api, make_project):
    project = await make_project(total_minor_units=30000)
    assert [m["amount_minor_units"] for m in project["milestones"]] == [9000, 9000, 12000]
    edited = await api.patch(f"/api/projects/{project['id']}", {"total_minor_units": 10001})
    assert [m["amount_minor_units"] for m in edited["milestones"]] == [3000, 3000, 4001]


@pytest.mark.parametrize("bad", [100.5, "300", 0, -5])
async def test_total_must_be_a_positive_integer(api, make_project, bad):
    project = await make_project()
    await api.patch(f"/api/projects/{project['id']}", {"total_minor_units": bad}, expect=422)


async def test_put_plan_replaces_the_split(api, make_project):
    project = await make_project()
    updated = await api.put(
        f"/api/projects/{project['id']}/milestones",
        {
            "milestones": [
                {"title": "Half up front", "basis_points": 5000, "billing_trigger": "ON_AGREEMENT"},
                {
                    "title": "Rest on delivery",
                    "basis_points": 5000,
                    "billing_trigger": "ON_DELIVERY_APPROVED",
                },
            ]
        },
    )
    assert [m["amount_minor_units"] for m in updated["milestones"]] == [15000, 15000]
    assert [m["position"] for m in updated["milestones"]] == [1, 2]


async def test_put_plan_must_sum_to_ten_thousand(api, make_project):
    project = await make_project()
    error = await api.put(
        f"/api/projects/{project['id']}/milestones",
        {"milestones": [{"title": "A", "basis_points": 5000, "billing_trigger": "ON_AGREEMENT"}]},
        expect=422,
    )
    assert error["code"] == "INVALID_PLAN"


async def test_plan_edit_after_a_draft_keeps_things_consistent(api, fake_paypal, make_agreed):
    project = await make_agreed()
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    updated = await api.put(
        f"/api/projects/{project['id']}/milestones",
        {
            "milestones": [
                {"title": "All", "basis_points": 10000, "billing_trigger": "ON_AGREEMENT"},
            ]
        },
    )
    assert updated["status"] == "DRAFT"
    assert updated["scope_version"] == 2
    assert updated["invoices"] == []
    assert [m["amount_minor_units"] for m in updated["milestones"]] == [30000]
    assert all(p["status"] in ("EXECUTED", "STALE") for p in updated["proposals"])

    await api.post(f"/api/projects/{project['id']}/accept")
    await api.post(f"/api/c/{project['share_token']}/accept", {"scope_version": 2})
    project = await api.get(f"/api/projects/{project['id']}")
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    numbers = {i["detail"]["invoice_number"] for i in fake_paypal.invoices.values()}
    assert len(numbers) == 2


async def test_revisions_only_count_once_agreed(api, make_project, make_agreed):
    draft = await make_project()
    await api.post(f"/api/projects/{draft['id']}/revisions", expect=409)
    project = await make_agreed()
    logged = await api.post(f"/api/projects/{project['id']}/revisions")
    assert logged["revisions_used"] == 1
    logged = await api.post(f"/api/projects/{project['id']}/revisions", {"count": 2})
    assert logged["revisions_used"] == 3
    assert logged["scope_version"] == project["scope_version"]


async def test_intake_is_stored_with_provenance(api, make_project, session_factory):
    analysis = await api.post("/api/analyze", {"message": INTAKE_MESSAGE})
    project = await make_project(intake={"message": INTAKE_MESSAGE, "analysis": analysis})
    assert project["messages"][0]["analysis"]["budget_minor_units"] == 30000
    with session_factory() as db:
        rows = db.query(ExtractionField).filter_by(commission_id=project["id"]).all()
        by_name = {r.field_name: r for r in rows if r.field_name == "usage_rights"}
        assert by_name["usage_rights"].provenance == "unknown"
        assert {r.field_name for r in rows} >= {"title", "deliverables", "file_formats", "budget"}


# --- Analyze ---


@pytest.mark.parametrize("error", [LLMUnavailableError("down"), NotImplementedError()])
async def test_analyze_llm_failure_is_503(api, fake_ai, error):
    fake_ai.intake_error = error
    body = await api.post("/api/analyze", {"message": "hi"}, expect=503)
    assert body["code"] == "LLM_UNAVAILABLE"


async def test_analyze_caps_input_length(api):
    await api.post("/api/analyze", {"message": "x" * 5001}, expect=422)


async def test_unavailable_ai_surfaces_as_503_not_500(api):
    from app.api.deps import get_intake_analyzer
    from app.schemas.ai import LLMUnavailableError

    async def unavailable(message, *, today):
        raise LLMUnavailableError("every model failed")

    app.dependency_overrides[get_intake_analyzer] = lambda: unavailable
    await api.post("/api/analyze", {"message": "hi"}, expect=503)


# --- Rate card ---


async def test_seeded_rate_card_matches_the_prd(api):
    card = await api.get("/api/settings/rate-card")
    assert card["currency_code"] == "USD"
    assert {i["code"]: i["unit_price_minor_units"] for i in card["items"]} == {
        "full_body_base": 30000,
        "extra_outfit": 8000,
        "extra_revision": 2000,
        "commercial_license": 10000,
    }


async def test_rate_card_edit_changes_new_change_orders(api, make_agreed):
    await api.put(
        "/api/settings/rate-card",
        {
            "items": [
                {"code": "extra_outfit", "name": "Extra outfit", "unit_price_minor_units": 9500},
                {"code": "extra_revision", "name": "Extra pass", "unit_price_minor_units": 2500},
            ]
        },
    )
    card = await api.get("/api/settings/rate-card")
    active = {i["code"]: i["active"] for i in card["items"]}
    assert active["extra_outfit"] is True
    assert active["commercial_license"] is False

    project = await make_agreed()
    posted = await api.post(
        f"/api/projects/{project['id']}/messages", {"body": FOLLOW_UP_MESSAGE}, expect=201
    )
    assert posted["change_order"]["total_minor_units"] == 12000


@pytest.mark.parametrize(
    "items",
    [
        [{"code": "a", "name": "A", "unit_price_minor_units": 80.5}],
        [{"code": "a", "name": "A", "unit_price_minor_units": 0}],
    ],
)
async def test_rate_card_prices_are_positive_integers(api, items):
    await api.put("/api/settings/rate-card", {"items": items}, expect=422)


async def test_rate_card_codes_must_be_unique(api):
    item = {"code": "a", "name": "A", "unit_price_minor_units": 100}
    error = await api.put("/api/settings/rate-card", {"items": [item, item]}, expect=422)
    assert error["code"] == "DUPLICATE_RATE_CARD_CODE"


# --- Demo, webhook, health ---


async def test_demo_reset_wipes_and_reseeds(api, fake_paypal, make_agreed, settings):
    settings.paypal_sandbox_buyer_email = "sandbox-buyer@example.com"
    await bill_and_send(api, (await make_agreed())["id"])
    await api.put(
        "/api/settings/rate-card",
        {"items": [{"code": "x", "name": "X", "unit_price_minor_units": 1}]},
    )

    reset = await api.post("/api/demo/reset")

    assert reset["suggested_client_email"] == "sandbox-buyer@example.com"
    assert reset["project"]["seller_display_name"] == "Jiwoo"
    assert reset["project"]["status"] == "DRAFT"
    assert [p["id"] for p in await api.get("/api/projects")] == [reset["project"]["id"]]
    codes = {i["code"] for i in (await api.get("/api/settings/rate-card"))["items"]}
    assert codes == {"full_body_base", "extra_outfit", "extra_revision", "commercial_license"}


async def test_billing_a_reset_project_never_adopts_an_old_invoice(api, fake_paypal, make_agreed):
    """Ids restart on a fresh DB in autoincrement schemes; ours must not reuse invoice numbers."""
    first = await make_agreed()
    await api.post(f"/api/proposals/{pending(first, 'BILL_MILESTONE')['id']}/approve")
    await api.post("/api/demo/reset")
    second = await make_agreed()
    await api.post(f"/api/proposals/{pending(second, 'BILL_MILESTONE')['id']}/approve")
    assert fake_paypal.count("create") == 2
    assert fake_paypal.count("search") == 0
    assert len(fake_paypal.invoices) == 2


async def test_webhook_is_a_documented_placeholder(api):
    response = await api.client.post("/api/webhooks/paypal", json={})
    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"


async def test_health_without_credentials_skips_the_token_check(api):
    app.dependency_overrides[get_paypal_client] = lambda: None
    body = await api.get("/api/health")
    assert body["status"] == "ok"
    assert body["paypal"] == {"environment": "SANDBOX", "configured": False, "token_ok": None}


async def test_health_reports_a_working_token_and_no_secrets(api, fake_paypal):
    body = await api.get("/api/health")
    assert body["paypal"]["token_ok"] is True
    assert "secret" not in str(body).lower()
    assert "fake-token" not in str(body)


async def test_health_stays_ok_when_paypal_is_down(api):
    class Down:
        async def get_access_token(self):
            raise httpx.ConnectError("down")

    app.dependency_overrides[get_paypal_client] = Down
    body = await api.get("/api/health")
    assert body["status"] == "ok"
    assert body["paypal"]["token_ok"] is False


def test_startup_seeds_recovers_and_stops_cleanly(session_factory, settings):
    settings.paypal_client_id = "configured-for-this-test"
    settings.paypal_client_secret = SecretStr("configured-for-this-test")
    settings.poll_interval_seconds = 3600
    with session_factory() as db:
        project = seed_demo_project(db)
        project_id = project.id
        db.add(
            Proposal(
                commission_id=project_id,
                kind="BILL_MILESTONE",
                payload_json={},
                rationale="stuck",
                scope_version=1,
                target_ref=f"milestone:{project.milestones[0].id}",
                target_state="READY_TO_BILL",
                idempotency_key="stuck",
                status="APPROVED",
            )
        )
        db.commit()

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

    with session_factory() as db:
        card = db.scalar(select(Proposal).where(Proposal.idempotency_key == "stuck"))
        assert card.status == "FAILED"
        assert card.error_code == "INTERRUPTED"
    assert app.state.paypal_client is None


async def test_client_view_hides_seller_data(api, make_agreed):
    project = await make_agreed()
    view = await api.get(f"/api/c/{project['share_token']}")
    for hidden in ("proposals", "activity", "messages", "share_token", "billing_disabled_code"):
        assert hidden not in view


async def test_client_sees_invoice_only_after_it_is_sent(api, make_agreed):
    project = await make_agreed()
    token = project["share_token"]
    await api.post(f"/api/proposals/{pending(project, 'BILL_MILESTONE')['id']}/approve")
    assert (await api.get(f"/api/c/{token}"))["milestones"][0]["invoice"] is None
    project = await api.get(f"/api/projects/{project['id']}")
    await api.post(f"/api/proposals/{pending(project, 'SEND_INVOICE')['id']}/approve")
    invoice = (await api.get(f"/api/c/{token}"))["milestones"][0]["invoice"]
    assert invoice["payer_link"].startswith("https://")
    assert invoice["amount_minor_units"] == 9000
    assert invoice["status_label"] == "Sent — awaiting payment"


async def test_over_length_message_names_the_limit(api):
    body = await api.post("/api/analyze", {"message": "x" * 5001}, expect=422)
    assert body["code"] == "VALIDATION_ERROR"
    assert "5,000 characters" in body["message"]
    assert body["details"]["max_length"] == 5000
    assert "xxxx" not in str(body)  # the rejected input is never echoed


async def test_other_validation_errors_stay_generic(api):
    body = await api.post("/api/analyze", {}, expect=422)
    assert body["message"] == "Some fields are missing or invalid."
