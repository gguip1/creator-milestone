"""Runs the Gate A smoke script end to end against an in-memory fake of the PayPal sandbox."""

import argparse
import json

import httpx

from app.config import Settings
from app.services import paypal_client as paypal_module
from scripts import paypal_smoke_test as smoke


class FakeSandbox:
    def __init__(self) -> None:
        self.invoices: dict[str, dict] = {}
        self.by_request_id: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 32400})
        if request.method == "POST" and path == "/v2/invoicing/invoices":
            request_id = request.headers["PayPal-Request-Id"]
            if request_id not in self.by_request_id:
                invoice_id = f"INV2-{len(self.invoices) + 1:04d}"
                body = json.loads(request.content)
                self.invoices[invoice_id] = {"id": invoice_id, "status": "DRAFT", **body}
                self.by_request_id[request_id] = invoice_id
            return httpx.Response(201, json=self.invoices[self.by_request_id[request_id]])
        invoice_id = path.split("/")[4]
        invoice = self.invoices[invoice_id]
        if request.method == "GET":
            return httpx.Response(200, json=invoice)
        action = path.rsplit("/", 1)[-1]
        if action == "send":
            invoice["status"] = "SENT"
            link = {"rel": "payer-view", "href": f"https://sandbox/pay/{invoice_id}"}
            return httpx.Response(200, json={"links": [link]})
        if action == "cancel":
            invoice["status"] = "CANCELLED"
        return httpx.Response(204)


async def test_smoke_script_passes_against_fake_sandbox(monkeypatch, tmp_path):
    sandbox = FakeSandbox()
    real_init = paypal_module.PayPalClient.__init__

    def init_with_fake(self, *args, **kwargs):
        kwargs["http"] = httpx.AsyncClient(transport=httpx.MockTransport(sandbox.handler))
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(paypal_module.PayPalClient, "__init__", init_with_fake)
    monkeypatch.setattr(
        smoke,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            paypal_client_id="id",
            paypal_client_secret="secret",
            paypal_sandbox_buyer_email="buyer@example.com",
        ),
    )
    monkeypatch.setattr(smoke, "RESULTS_DIR", tmp_path)

    exit_code = await smoke.main(argparse.Namespace(wait_for_payment=0, write_log=False))

    assert exit_code == 0
    # A (created once despite two creates with the same request id), B, C.
    assert len(sandbox.invoices) == 3
    statuses = [inv["status"] for inv in sandbox.invoices.values()]
    assert statuses == ["SENT", "SENT", "CANCELLED"]
    results = json.loads(next(tmp_path.glob("smoke-*.json")).read_text())
    assert "buyer@example.com" not in json.dumps(results)
