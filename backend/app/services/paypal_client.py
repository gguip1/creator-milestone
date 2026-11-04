"""Minimal async client for PayPal REST OAuth2 + Invoicing v2 (sandbox only).

Docs: https://developer.paypal.com/api/invoicing/v2/
Field names follow the v2 invoice object; re-check the live reference when changing payloads.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.money import to_paypal_value

INVOICES_PATH = "/v2/invoicing/invoices"


@dataclass
class PayPalError(Exception):
    status_code: int
    name: str
    message: str
    debug_id: str | None = None
    details: list[dict[str, str]] = field(default_factory=list)

    def __str__(self) -> str:
        return f"PayPal {self.status_code} {self.name}: {self.message} (debug_id={self.debug_id})"

    @classmethod
    def from_response(cls, response: httpx.Response) -> "PayPalError":
        try:
            body = response.json()
        except ValueError:
            body = {}
        # Keep only field/issue/description; detail "value" entries can echo customer data.
        details = [
            {k: str(d[k]) for k in ("field", "issue", "description") if k in d}
            for d in body.get("details", [])
            if isinstance(d, dict)
        ]
        return cls(
            status_code=response.status_code,
            name=body.get("name") or body.get("error") or "UNKNOWN_ERROR",
            message=body.get("message") or body.get("error_description") or response.reason_phrase,
            debug_id=body.get("debug_id") or response.headers.get("paypal-debug-id"),
            details=details,
        )


@dataclass(frozen=True)
class InvoiceLine:
    name: str
    unit_amount_minor_units: int
    quantity: int = 1
    description: str | None = None


def build_invoice_payload(
    *,
    invoice_number: str,
    currency_code: str,
    recipient_email: str,
    lines: Sequence[InvoiceLine],
    note: str | None = None,
    terms_and_conditions: str | None = None,
    invoicer_email: str | None = None,
    invoicer_business_name: str | None = None,
) -> dict[str, Any]:
    if not lines:
        raise ValueError("An invoice needs at least one line")

    detail: dict[str, Any] = {"invoice_number": invoice_number, "currency_code": currency_code}
    if note:
        detail["note"] = note
    if terms_and_conditions:
        detail["terms_and_conditions"] = terms_and_conditions

    items = []
    for line in lines:
        item: dict[str, Any] = {
            "name": line.name,
            "quantity": str(line.quantity),
            "unit_amount": {
                "currency_code": currency_code,
                "value": to_paypal_value(line.unit_amount_minor_units, currency_code),
            },
            "unit_of_measure": "QUANTITY",
        }
        if line.description:
            item["description"] = line.description
        items.append(item)

    payload: dict[str, Any] = {
        "detail": detail,
        "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
        "items": items,
        # Each milestone is its own invoice, so partial payment stays off.
        "configuration": {"allow_partial_payment": False},
    }
    invoicer: dict[str, Any] = {}
    if invoicer_email:
        invoicer["email_address"] = invoicer_email
    if invoicer_business_name:
        invoicer["business_name"] = invoicer_business_name
    if invoicer:
        payload["invoicer"] = invoicer
    return payload


def find_link(resource: dict[str, Any], rel: str) -> str | None:
    for link in resource.get("links", []):
        if link.get("rel") == rel:
            return link.get("href")
    return None


class PayPalClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.AsyncClient | None = None,
        token_margin_seconds: int = 120,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        self._token_margin = token_margin_seconds
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        async with self._token_lock:
            if not force_refresh and self._token and self._clock() < self._token_expires_at:
                return self._token
            response = await self._http.post(
                f"{self._base_url}/v1/oauth2/token",
                auth=(self._client_id, self._client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
            if response.status_code != 200:
                raise PayPalError.from_response(response)
            body = response.json()
            self._token = body["access_token"]
            expires_in = int(body.get("expires_in", 0))
            self._token_expires_at = self._clock() + max(expires_in - self._token_margin, 0)
            return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        request_id: str | None = None,
        prefer_representation: bool = False,
    ) -> httpx.Response:
        for attempt in range(2):
            token = await self.get_access_token(force_refresh=attempt > 0)
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            if prefer_representation:
                headers["Prefer"] = "return=representation"
            response = await self._http.request(
                method, f"{self._base_url}{path}", json=json, headers=headers
            )
            # Client-credentials tokens have no refresh token: on 401, fetch a new one once.
            if response.status_code == 401 and attempt == 0:
                continue
            if response.status_code >= 400:
                raise PayPalError.from_response(response)
            return response
        raise AssertionError("unreachable")

    async def create_draft_invoice(self, payload: dict[str, Any], *, request_id: str) -> dict:
        response = await self._request(
            "POST", INVOICES_PATH, json=payload, request_id=request_id, prefer_representation=True
        )
        body = response.json() if response.content else {}
        if body.get("id"):
            return body
        # Minimal responses only carry a HATEOAS link to the new invoice.
        href = find_link(body, "self") or body.get("href")
        if not href:
            raise PayPalError(
                response.status_code, "NO_INVOICE_ID", "Create returned no invoice id"
            )
        return await self.get_invoice(href.rstrip("/").rsplit("/", 1)[-1])

    async def find_invoices_by_number(self, invoice_number: str) -> list[dict]:
        """Recovery lookup: a retried create can fail with DUPLICATE_INVOICE_NUMBER."""
        response = await self._request(
            "POST",
            "/v2/invoicing/search-invoices",
            json={"invoice_number": invoice_number},
        )
        return response.json().get("items", [])

    async def get_invoice(self, invoice_id: str) -> dict:
        response = await self._request("GET", f"{INVOICES_PATH}/{invoice_id}")
        return response.json()

    async def send_invoice(
        self,
        invoice_id: str,
        *,
        request_id: str,
        subject: str | None = None,
        note: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"send_to_invoicer": False, "send_to_recipient": True}
        if subject:
            body["subject"] = subject
        if note:
            body["note"] = note
        response = await self._request(
            "POST", f"{INVOICES_PATH}/{invoice_id}/send", json=body, request_id=request_id
        )
        return response.json() if response.content else {}

    async def remind_invoice(
        self, invoice_id: str, *, subject: str | None = None, note: str | None = None
    ) -> None:
        body: dict[str, Any] = {"send_to_invoicer": False, "send_to_recipient": True}
        if subject:
            body["subject"] = subject
        if note:
            body["note"] = note
        await self._request("POST", f"{INVOICES_PATH}/{invoice_id}/remind", json=body)

    async def cancel_invoice(
        self, invoice_id: str, *, subject: str | None = None, note: str | None = None
    ) -> None:
        body: dict[str, Any] = {"send_to_invoicer": False, "send_to_recipient": True}
        if subject:
            body["subject"] = subject
        if note:
            body["note"] = note
        await self._request("POST", f"{INVOICES_PATH}/{invoice_id}/cancel", json=body)
