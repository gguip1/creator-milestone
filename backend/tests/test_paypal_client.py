import json

import httpx
import pytest

from app.services.paypal_client import (
    InvoiceLine,
    PayPalClient,
    PayPalError,
    build_invoice_payload,
)
from app.services.paypal_status import describe_status

BASE = "https://api-m.sandbox.paypal.com"


class FakePayPal:
    """Records requests and replies from a per-route queue of responses."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.routes: dict[tuple[str, str], list[httpx.Response]] = {}

    def add(self, method: str, path: str, *responses: httpx.Response) -> None:
        self.routes.setdefault((method, path), []).extend(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            self.token_calls += 1
            return httpx.Response(
                200, json={"access_token": f"token-{self.token_calls}", "expires_in": 32400}
            )
        queue = self.routes.get((request.method, request.url.path))
        if not queue:
            return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "no route"})
        return queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def fake():
    return FakePayPal()


@pytest.fixture
def make_client(fake):
    def _make(**kwargs):
        http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        return PayPalClient(BASE, "client-id", "secret", http=http, **kwargs)

    return _make


def sample_payload():
    return build_invoice_payload(
        invoice_number="CM-1-1-1",
        currency_code="USD",
        recipient_email="buyer@example.com",
        lines=[InvoiceLine("Deposit", 9000)],
        note="Scope v1",
        terms_and_conditions="2 revisions",
    )


def test_payload_uses_string_amounts_and_disables_partial_payment():
    payload = build_invoice_payload(
        invoice_number="CM-1-4-1",
        currency_code="USD",
        recipient_email="buyer@example.com",
        lines=[InvoiceLine("Extra outfit", 8000), InvoiceLine("Extra revision", 2000)],
        note="Change order #1",
    )
    assert [i["unit_amount"]["value"] for i in payload["items"]] == ["80.00", "20.00"]
    assert all(i["quantity"] == "1" for i in payload["items"])
    assert payload["configuration"]["allow_partial_payment"] is False
    assert payload["detail"]["note"] == "Change order #1"
    assert "terms_and_conditions" not in payload["detail"]
    assert "invoicer" not in payload


def test_payload_requires_lines():
    with pytest.raises(ValueError):
        build_invoice_payload(
            invoice_number="x", currency_code="USD", recipient_email="b@example.com", lines=[]
        )


async def test_token_is_cached(fake, make_client):
    fake.add("GET", "/v2/invoicing/invoices/INV2-1", httpx.Response(200, json={"id": "INV2-1"}))
    client = make_client()
    await client.get_invoice("INV2-1")
    await client.get_invoice("INV2-1")
    assert fake.token_calls == 1


async def test_token_refreshes_after_expiry(fake, make_client):
    now = [0.0]
    fake.add("GET", "/v2/invoicing/invoices/INV2-1", httpx.Response(200, json={"id": "INV2-1"}))
    client = make_client(clock=lambda: now[0])
    await client.get_invoice("INV2-1")
    now[0] = 32400.0
    await client.get_invoice("INV2-1")
    assert fake.token_calls == 2


async def test_401_gets_new_token_and_retries_once(fake, make_client):
    fake.add(
        "GET",
        "/v2/invoicing/invoices/INV2-1",
        httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE", "message": "expired"}),
        httpx.Response(200, json={"id": "INV2-1", "status": "SENT"}),
    )
    client = make_client()
    invoice = await client.get_invoice("INV2-1")
    assert invoice["status"] == "SENT"
    assert fake.token_calls == 2
    assert fake.requests[-1].headers["Authorization"] == "Bearer token-2"


async def test_create_sends_request_id_and_returns_representation(fake, make_client):
    fake.add(
        "POST",
        "/v2/invoicing/invoices",
        httpx.Response(201, json={"id": "INV2-AAA", "status": "DRAFT"}),
    )
    client = make_client()
    invoice = await client.create_draft_invoice(sample_payload(), request_id="req-123")
    assert invoice["id"] == "INV2-AAA"
    create_request = fake.requests[-1]
    assert create_request.headers["PayPal-Request-Id"] == "req-123"
    assert create_request.headers["Prefer"] == "return=representation"
    assert json.loads(create_request.content)["detail"]["invoice_number"] == "CM-1-1-1"


async def test_create_follows_self_link_when_response_is_minimal(fake, make_client):
    fake.add(
        "POST",
        "/v2/invoicing/invoices",
        httpx.Response(
            201,
            json={"links": [{"rel": "self", "href": f"{BASE}/v2/invoicing/invoices/INV2-BBB"}]},
        ),
    )
    fake.add(
        "GET",
        "/v2/invoicing/invoices/INV2-BBB",
        httpx.Response(200, json={"id": "INV2-BBB", "status": "DRAFT"}),
    )
    client = make_client()
    invoice = await client.create_draft_invoice(sample_payload(), request_id="req-1")
    assert invoice == {"id": "INV2-BBB", "status": "DRAFT"}


async def test_errors_are_parsed_without_detail_values(fake, make_client):
    fake.add(
        "POST",
        "/v2/invoicing/invoices",
        httpx.Response(
            422,
            headers={"paypal-debug-id": "dbg-1"},
            json={
                "name": "UNPROCESSABLE_ENTITY",
                "message": "The requested action could not be performed.",
                "details": [
                    {
                        "field": "/primary_recipients/0/billing_info/email_address",
                        "issue": "INVALID_EMAIL",
                        "value": "secret@example.com",
                    }
                ],
            },
        ),
    )
    client = make_client()
    with pytest.raises(PayPalError) as info:
        await client.create_draft_invoice(sample_payload(), request_id="req-1")
    err = info.value
    assert err.status_code == 422
    assert err.debug_id == "dbg-1"
    assert err.details == [
        {"field": "/primary_recipients/0/billing_info/email_address", "issue": "INVALID_EMAIL"}
    ]
    assert "secret@example.com" not in str(err)


async def test_send_remind_cancel_paths(fake, make_client):
    fake.add("POST", "/v2/invoicing/invoices/INV2-1/send", httpx.Response(200, json={"href": "x"}))
    fake.add("POST", "/v2/invoicing/invoices/INV2-1/remind", httpx.Response(204))
    fake.add("POST", "/v2/invoicing/invoices/INV2-1/cancel", httpx.Response(204))
    client = make_client()
    assert await client.send_invoice("INV2-1", request_id="send-1") == {"href": "x"}
    await client.remind_invoice("INV2-1")
    await client.cancel_invoice("INV2-1")
    send_request = next(r for r in fake.requests if r.url.path.endswith("/send"))
    assert send_request.headers["PayPal-Request-Id"] == "send-1"
    assert json.loads(send_request.content)["send_to_recipient"] is True


@pytest.mark.parametrize(
    "status,settles",
    [
        ("PAID", True),
        ("SENT", False),
        ("UNPAID", False),
        ("MARKED_AS_PAID", False),
        ("PARTIALLY_PAID", False),
    ],
)
def test_only_paid_settles(status, settles):
    assert describe_status(status).settles_milestone is settles


def test_unknown_status_is_flagged():
    info = describe_status("SOMETHING_NEW")
    assert info.needs_attention and not info.settles_milestone
