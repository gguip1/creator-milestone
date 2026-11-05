"""The PRD §6 video spine, through HTTP, against the fake PayPal."""

from app.services.seed import FOLLOW_UP_MESSAGE, INTAKE_MESSAGE
from tests.conftest import BUYER, bill_and_send, pending


async def test_full_flow_from_intake_to_paid_change_order(api, fake_paypal, scope):
    # 1. Try the demo: a seeded project waits at intake.
    reset = await api.post("/api/demo/reset")
    project = reset["project"]
    project_id = project["id"]
    token = project["share_token"]
    assert project["status"] == "DRAFT"
    assert project["scope_version"] == 1
    assert "client_email" in project["missing_fields"]
    assert reset["example_messages"] == {"intake": INTAKE_MESSAGE, "follow_up": FOLLOW_UP_MESSAGE}
    assert [m["amount_minor_units"] for m in project["milestones"]] == [0, 0, 0]

    # 2. Analyze message 1, statelessly.
    analysis = await api.post("/api/analyze", {"message": INTAKE_MESSAGE})
    assert analysis["budget_minor_units"] == 30000

    # 3. The seller fills the gaps. Agreed scope is still v1, as in PRD §5.
    project = await api.patch(
        f"/api/projects/{project_id}",
        {**scope, "intake": {"message": INTAKE_MESSAGE, "analysis": analysis}},
    )
    assert project["scope_version"] == 1
    assert project["missing_fields"] == []
    assert [m["amount_minor_units"] for m in project["milestones"]] == [9000, 9000, 12000]
    assert [m["kind"] for m in project["messages"]] == ["intake"]
    project = await api.post(f"/api/projects/{project_id}/accept")
    assert project["status"] == "AWAITING_ACCEPTANCE"

    # 4. The client accepts on their page.
    view = await api.get(f"/api/c/{token}")
    assert view["can_accept"] is True
    assert "proposals" not in view
    view = await api.post(f"/api/c/{token}/accept", {"scope_version": 1})
    assert view["status"] == "AGREED"

    # 5. Deposit: bill card -> draft -> send card -> SENT.
    project = await api.get(f"/api/projects/{project_id}")
    bill = pending(project, "BILL_MILESTONE")
    assert bill["payload"]["amount_minor_units"] == 9000
    assert bill["payload"]["recipient_email"] == BUYER
    assert bill["model_id"] is None
    assert bill["can_approve"] is True
    assert fake_paypal.write_calls() == []  # Nothing reaches PayPal before approval.

    await api.post(f"/api/proposals/{bill['id']}/approve")
    project = await api.get(f"/api/projects/{project_id}")
    [invoice] = project["invoices"]
    assert invoice["paypal_status"] == "DRAFT"
    assert project["milestones"][0]["workflow_state"] == "READY_TO_BILL"
    remote = fake_paypal.invoices[invoice["paypal_invoice_id"]]
    assert "scope v1" in remote["detail"]["note"]
    assert "Revisions included: 2" in remote["detail"]["terms_and_conditions"]
    assert "Personal streaming" in remote["detail"]["terms_and_conditions"]
    assert remote["configuration"]["allow_partial_payment"] is False
    assert remote["amount"]["value"] == "90.00"

    send = pending(project, "SEND_INVOICE")
    assert send["payload"]["recipient_email"] == BUYER
    await api.post(f"/api/proposals/{send['id']}/approve")
    project = await api.get(f"/api/projects/{project_id}")
    [invoice] = project["invoices"]
    assert invoice["paypal_status"] == "SENT"
    assert invoice["status_label"] == "Sent — awaiting payment"
    assert invoice["payer_link"].startswith("https://www.sandbox.paypal.com/invoice/p/")
    assert project["status"] == "IN_PROGRESS"
    assert project["milestones"][0]["workflow_state"] == "BILLED"

    # 6. The buyer pays; PAID is read from PayPal and unlocks the sketch milestone.
    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    invoice = await api.post(f"/api/invoices/{invoice['id']}/refresh")
    assert invoice["status_label"] == "Paid via PayPal"
    project = await api.get(f"/api/projects/{project_id}")
    assert project["milestones"][0]["workflow_state"] == "SETTLED"
    assert project["milestones"][1]["workflow_state"] == "AWAITING_DELIVERY"

    # 7. Sketch delivered, client approves, the agent proposes the sketch invoice.
    sketch = project["milestones"][1]
    await api.post(
        f"/api/milestones/{sketch['id']}/deliver",
        {"evidence_url": "https://example.com/sketch.png", "note": "First sketch"},
    )
    view = await api.get(f"/api/c/{token}")
    assert view["milestones"][1]["can_approve"] is True
    assert view["milestones"][1]["evidence_url"] == "https://example.com/sketch.png"
    await api.post(f"/api/c/{token}/milestones/{sketch['id']}/approve")
    project = await api.get(f"/api/projects/{project_id}")
    assert pending(project, "BILL_MILESTONE")["payload"]["amount_minor_units"] == 9000
    await api.post(f"/api/projects/{project_id}/revisions", {"count": 2})

    # 8. Message 2: Scope Guard -> change order card $100 -> seller, then client.
    posted = await api.post(
        f"/api/projects/{project_id}/messages", {"body": FOLLOW_UP_MESSAGE}, expect=201
    )
    classes = {i["rate_card_code"]: i["classification"] for i in posted["scope_guard"]["items"]}
    assert classes == {
        "extra_outfit": "out_of_scope",
        "extra_revision": "exceeds_limit",
        "commercial_license": "question",
    }
    change_order = posted["change_order"]
    assert change_order["total_minor_units"] == 10000
    assert change_order["status"] == "DRAFT"
    assert [line["name"] for line in change_order["lines"]] == ["Extra outfit", "Extra revision"]
    card = posted["proposal"]
    assert card["kind"] == "CHANGE_ORDER"
    assert card["model_id"] == "fake-model"
    assert [item["request_summary"] for item in card["payload"]["not_billed"]] == [
        "Merch use later"
    ]
    # The client does not see it until the seller approves.
    assert (await api.get(f"/api/c/{token}"))["change_orders"] == []

    writes_before = len(fake_paypal.write_calls())
    await api.post(f"/api/proposals/{card['id']}/approve")
    assert len(fake_paypal.write_calls()) == writes_before  # Approval here is not a PayPal write.

    view = await api.get(f"/api/c/{token}")
    assert view["change_orders"][0]["can_decide"] is True
    view = await api.post(f"/api/c/{token}/change-orders/{change_order['id']}/approve")
    assert view["scope_version"] == 2
    assert view["revisions_included"] == 3

    # Scope v2: snapshot, milestone, and a bill card. The old sketch card was re-proposed at v2.
    project = await api.get(f"/api/projects/{project_id}")
    assert project["status"] == "IN_PROGRESS"
    assert project["change_order_total_minor_units"] == 10000
    assert project["total_minor_units"] == 30000
    assert project["seller_accepted_version"] == project["client_accepted_version"] == 2
    extra = project["milestones"][-1]
    assert extra["kind"] == "change_order"
    assert extra["workflow_state"] == "READY_TO_BILL"
    assert extra["billing_trigger"] == "ON_CHANGE_ORDER_APPROVED"
    cards = [
        p
        for p in project["proposals"]
        if p["kind"] == "BILL_MILESTONE" and p["status"] == "PENDING"
    ]
    assert sorted(c["payload"]["milestone_title"] for c in cards) == [
        "Change order #1",
        "Sketch approval",
    ]
    assert all(c["scope_version"] == 2 for c in cards)

    # 9. Bill and send the change order: one invoice line per change-order line.
    bill = next(c for c in cards if c["payload"]["milestone_title"] == "Change order #1")
    await api.post(f"/api/proposals/{bill['id']}/approve")
    project = await api.get(f"/api/projects/{project_id}")
    invoice = next(i for i in project["invoices"] if i["milestone_id"] == extra["id"])
    send = next(
        p
        for p in project["proposals"]
        if p["kind"] == "SEND_INVOICE"
        and p["status"] == "PENDING"
        and p["payload"]["invoice_id"] == invoice["id"]
    )
    await api.post(f"/api/proposals/{send['id']}/approve")

    remote = fake_paypal.invoices[invoice["paypal_invoice_id"]]
    assert [(i["name"], i["quantity"], i["unit_amount"]["value"]) for i in remote["items"]] == [
        ("Extra outfit", "1", "80.00"),
        ("Extra revision", "1", "20.00"),
    ]
    assert remote["amount"]["value"] == "100.00"
    assert remote["status"] == "SENT"
    assert "Extra outfit x 1" in remote["detail"]["note"]
    assert "Agreed scope v2" in remote["detail"]["terms_and_conditions"]
    assert "Revisions included: 3" in remote["detail"]["terms_and_conditions"]
    assert "commercial" not in remote["detail"]["terms_and_conditions"].lower()

    # Paid again.
    fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
    await api.post(f"/api/invoices/{invoice['id']}/refresh")
    project = await api.get(f"/api/projects/{project_id}")
    assert project["milestones"][-1]["workflow_state"] == "SETTLED"

    # The timeline names each actor.
    assert {a["actor"] for a in project["activity"]} >= {"agent", "seller", "client", "paypal"}


async def test_commission_completes_when_every_milestone_settles(api, fake_paypal, make_agreed):
    project = await make_agreed(total_minor_units=10001)
    project_id = project["id"]
    token = project["share_token"]
    assert [m["amount_minor_units"] for m in project["milestones"]] == [3000, 3000, 4001]

    for index in range(3):
        if index:
            milestone = project["milestones"][index]
            await api.post(f"/api/milestones/{milestone['id']}/deliver")
            await api.post(f"/api/c/{token}/milestones/{milestone['id']}/approve")
        project = await bill_and_send(api, project_id)
        invoice = next(i for i in project["invoices"] if i["paypal_status"] == "SENT")
        fake_paypal.buyer_pays(invoice["paypal_invoice_id"])
        await api.post(f"/api/invoices/{invoice['id']}/refresh")
        project = await api.get(f"/api/projects/{project_id}")

    assert project["status"] == "COMPLETED"
    assert all(m["workflow_state"] == "SETTLED" for m in project["milestones"])
    await api.post(f"/api/projects/{project_id}/messages", {"body": "One more?"}, expect=409)
