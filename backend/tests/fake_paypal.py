"""In-memory PayPal Invoicing v2, matching behavior verified in docs/paypal-test-log.md."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.money import from_paypal_value, to_paypal_value
from app.services.paypal_client import PayPalClient

BASE_URL = "https://api-m.sandbox.paypal.com"


def error_response(status: int, name: str, issue: str | None = None) -> httpx.Response:
    body: dict[str, Any] = {"name": name, "message": f"{name} (fake)", "debug_id": "fake-debug"}
    if issue:
        body["details"] = [{"issue": issue, "description": f"{issue} (fake)"}]
    return httpx.Response(status, json=body)


@dataclass
class Fault:
    """What to do on the next call of one operation."""

    response: httpx.Response | None = None
    # Lets a timeout fire after the write landed, the case recovery exists for.
    apply_first: bool = False
    timeout: bool = False


@dataclass
class FakePayPal:
    invoices: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    faults: dict[str, list[Fault]] = field(default_factory=dict)
    create_delay: float = 0.0
    korean_buyer: bool = False
    requests: list[httpx.Request] = field(default_factory=list)

    def count(self, operation: str) -> int:
        return self.calls.count(operation)

    def write_calls(self) -> list[str]:
        return [c for c in self.calls if c in ("create", "send", "remind", "cancel")]

    def fail_next(self, operation: str, status: int, name: str, issue: str | None = None) -> None:
        self.faults.setdefault(operation, []).append(
            Fault(response=error_response(status, name, issue))
        )

    def timeout_next(self, operation: str, *, apply_first: bool = False) -> None:
        self.faults.setdefault(operation, []).append(Fault(timeout=True, apply_first=apply_first))

    def miss_search_next(self) -> None:
        """Search answers empty once even if the invoice exists, like an index that lags."""
        self.faults.setdefault("search", []).append(
            Fault(response=httpx.Response(200, json={"items": []}))
        )

    def buyer_pays(self, invoice_id: str) -> None:
        self.invoices[invoice_id]["status"] = "PAID"

    def set_status(self, invoice_id: str, status: str) -> None:
        self.invoices[invoice_id]["status"] = status

    def by_number(self, invoice_number: str) -> dict[str, Any] | None:
        for invoice in self.invoices.values():
            if invoice["detail"]["invoice_number"] == invoice_number:
                return invoice
        return None

    def add_foreign_invoice(self, invoice_number: str, value: str, email: str) -> dict[str, Any]:
        """An invoice already at PayPal that we did not create in this run."""
        invoice = self._build(
            {
                "detail": {"invoice_number": invoice_number, "currency_code": "USD"},
                "primary_recipients": [{"billing_info": {"email_address": email}}],
                "items": [
                    {
                        "name": "Other",
                        "quantity": "1",
                        "unit_amount": {"currency_code": "USD", "value": value},
                    }
                ],
            }
        )
        return invoice

    def client(self) -> PayPalClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return PayPalClient(BASE_URL, "fake-client-id", "fake-value", http=http)

    def _build(self, payload: dict[str, Any]) -> dict[str, Any]:
        currency = payload["detail"]["currency_code"]
        total = sum(
            from_paypal_value(item["unit_amount"]["value"], currency) * int(item["quantity"])
            for item in payload["items"]
        )
        invoice_id = f"INV2-FAKE-{len(self.invoices) + 1:04d}"
        invoice = {
            **payload,
            "id": invoice_id,
            "status": "DRAFT",
            "amount": {"currency_code": currency, "value": to_paypal_value(total, currency)},
            "links": [{"rel": "self", "href": f"{BASE_URL}/v2/invoicing/invoices/{invoice_id}"}],
        }
        self.invoices[invoice_id] = invoice
        return invoice

    def _create(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if self.by_number(payload["detail"]["invoice_number"]) is not None:
            # Verified: a repeat does not replay, even with the same PayPal-Request-Id.
            return error_response(422, "UNPROCESSABLE_ENTITY", "DUPLICATE_INVOICE_NUMBER")
        return httpx.Response(201, json=self._build(payload))

    def _send(self, invoice: dict[str, Any]) -> httpx.Response:
        if self.korean_buyer:
            return error_response(
                406, "MEDIA_TYPE_NOT_ACCEPTABLE", "KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED"
            )
        invoice["status"] = "SENT"
        return httpx.Response(
            200,
            json={
                "href": f"https://www.sandbox.paypal.com/invoice/p/#{invoice['id']}",
                "rel": "payer-view",
                "method": "GET",
            },
        )

    def _cancel(self, invoice: dict[str, Any]) -> httpx.Response:
        if invoice["status"] == "DRAFT":
            return error_response(422, "UNPROCESSABLE_ENTITY", "CANNOT_CANCEL_DRAFT_INVOICE")
        invoice["status"] = "CANCELLED"
        return httpx.Response(204)

    def _operation(self, request: httpx.Request) -> tuple[str, dict[str, Any] | None]:
        path = request.url.path
        if path == "/v2/invoicing/search-invoices":
            return "search", None
        if path == "/v2/invoicing/invoices":
            return "create", None
        parts = path.removeprefix("/v2/invoicing/invoices/").split("/")
        invoice = self.invoices.get(parts[0])
        if len(parts) == 1:
            return "get", invoice
        return parts[1], invoice

    def _perform(
        self, operation: str, invoice: dict[str, Any] | None, request: httpx.Request
    ) -> httpx.Response:
        if operation == "create":
            return self._create(request)
        if operation == "search":
            number = json.loads(request.content)["invoice_number"]
            found = self.by_number(number)
            return httpx.Response(200, json={"items": [found] if found else []})
        if invoice is None:
            return error_response(404, "RESOURCE_NOT_FOUND")
        if operation == "get":
            return httpx.Response(200, json=invoice)
        if operation == "send":
            return self._send(invoice)
        if operation == "remind":
            return httpx.Response(204)
        if operation == "cancel":
            return self._cancel(invoice)
        return error_response(404, "RESOURCE_NOT_FOUND")

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "fake-token", "expires_in": 32400})

        operation, invoice = self._operation(request)
        self.calls.append(operation)
        if operation == "create" and self.create_delay:
            # Yields to the event loop, so concurrent approvals really overlap here.
            await asyncio.sleep(self.create_delay)

        queue = self.faults.get(operation)
        if queue:
            fault = queue.pop(0)
            if fault.timeout:
                if fault.apply_first:
                    self._perform(operation, invoice, request)
                raise httpx.ReadTimeout("fake timeout", request=request)
            return fault.response
        return self._perform(operation, invoice, request)
