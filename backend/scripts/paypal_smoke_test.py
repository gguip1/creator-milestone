"""Gate A smoke test against the PayPal sandbox (PRD §18, §21).

Exercises: OAuth token -> draft with note/terms -> idempotent re-create -> GET -> send -> GET
-> multi-line change-order invoice + remind -> cancel a sent invoice
-> optional wait for the sandbox buyer to pay.

Usage (from backend/):
    uv run python -m scripts.paypal_smoke_test
    uv run python -m scripts.paypal_smoke_test --wait-for-payment 600 --write-log

Output is sanitized: no tokens, emails masked.
Raw (masked) responses go to smoke-results/ (gitignored).
"""

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.paypal_client import (
    InvoiceLine,
    PayPalClient,
    PayPalError,
    build_invoice_payload,
    find_link,
)
from app.services.paypal_status import describe_status

BACKEND_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BACKEND_DIR / "smoke-results"
TEST_LOG = BACKEND_DIR.parent / "docs" / "paypal-test-log.md"
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+)")

DEPOSIT_NOTE = "Deposit (30%) for: full-body character illustration. Billed under scope v1."
DEPOSIT_TERMS = (
    "Scope v1: one full-body illustration; transparent PNG + layered PSD; "
    "2 revisions included; personal streaming use only; target delivery 2026-11-25."
)


def mask(value: Any) -> Any:
    if isinstance(value, str):
        return EMAIL_RE.sub(r"\1***@\2", value)
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


@dataclass
class Step:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


class SmokeRun:
    def __init__(self) -> None:
        self.steps: list[Step] = []
        self.raw: dict[str, Any] = {}

    def record(self, name: str, ok: bool, detail: str, **data: Any) -> None:
        step = Step(name, ok, detail, data)
        self.steps.append(step)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    def record_error(self, name: str, exc: Exception) -> None:
        if isinstance(exc, PayPalError):
            issues = "; ".join(
                f"{d.get('field', '')} {d.get('issue', '')}".strip() for d in exc.details
            )
            detail = f"HTTP {exc.status_code} {exc.name}: {exc.message}"
            if issues:
                detail += f" [{issues}]"
            self.record(name, False, mask(detail), debug_id=exc.debug_id)
        else:
            self.record(name, False, f"{type(exc).__name__}: {mask(str(exc))}")


def invoice_summary(invoice: dict[str, Any]) -> dict[str, Any]:
    detail = invoice.get("detail", {})
    return {
        "id": invoice.get("id"),
        "status": invoice.get("status"),
        "status_label": describe_status(invoice.get("status")).label,
        "invoice_number": detail.get("invoice_number"),
        "amount": invoice.get("amount", {}).get("value"),
        "note_present": bool(detail.get("note")),
        "terms_present": bool(detail.get("terms_and_conditions")),
        "top_level_keys": sorted(invoice.keys()),
        "detail_keys": sorted(detail.keys()),
        "links": [link.get("rel") for link in invoice.get("links", [])],
    }


async def create(
    client: PayPalClient,
    run: SmokeRun,
    label: str,
    payload: dict[str, Any],
    request_id: str,
) -> dict[str, Any] | None:
    try:
        invoice = await client.create_draft_invoice(payload, request_id=request_id)
    except Exception as exc:  # noqa: BLE001 - report every failure kind
        run.record_error(f"create {label}", exc)
        return None
    run.raw[f"create_{label}"] = mask(invoice)
    summary = invoice_summary(invoice)
    run.record(f"create {label}", True, f"id={summary['id']} status={summary['status']}", **summary)
    return invoice


async def send(
    client: PayPalClient, run: SmokeRun, label: str, invoice_id: str
) -> tuple[bool, str | None]:
    """Returns (sent, payer_link)."""
    try:
        result = await client.send_invoice(
            invoice_id,
            request_id=str(uuid.uuid4()),
            subject="CreatorMilestone sandbox test invoice",
            note="Sandbox test only. No real money.",
        )
    except Exception as exc:  # noqa: BLE001
        run.record_error(f"send {label}", exc)
        return False, None
    run.raw[f"send_{label}"] = mask(result)
    payer_link = find_link(result, "payer-view") or result.get("href")
    run.record(
        f"send {label}",
        True,
        f"payer link {'returned' if payer_link else 'not returned'}",
        response_keys=sorted(result.keys()),
        links=[link.get("rel") for link in result.get("links", [])],
    )
    return True, payer_link


async def fetch(client: PayPalClient, run: SmokeRun, label: str, invoice_id: str) -> dict | None:
    try:
        invoice = await client.get_invoice(invoice_id)
    except Exception as exc:  # noqa: BLE001
        run.record_error(f"get {label}", exc)
        return None
    run.raw[f"get_{label}_{len(run.steps)}"] = mask(invoice)
    summary = invoice_summary(invoice)
    run.record(
        f"get {label}",
        True,
        f"status={summary['status']} note={summary['note_present']} "
        f"terms={summary['terms_present']}",
        **summary,
    )
    return invoice


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    missing = [
        name
        for name, value in [
            ("PAYPAL_CLIENT_ID", settings.paypal_client_id),
            ("PAYPAL_CLIENT_SECRET", settings.paypal_client_secret.get_secret_value()),
            ("PAYPAL_SANDBOX_BUYER_EMAIL", settings.paypal_sandbox_buyer_email),
        ]
        if not value
    ]
    if missing:
        print(f"Missing in backend/.env: {', '.join(missing)}", file=sys.stderr)
        return 2

    run = SmokeRun()
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    buyer = settings.paypal_sandbox_buyer_email
    invoicer = settings.paypal_invoicer_email or None
    client = PayPalClient(
        settings.paypal_base_url,
        settings.paypal_client_id,
        settings.paypal_client_secret.get_secret_value(),
    )
    payer_link_a = None
    sent_a = False
    try:
        try:
            await client.get_access_token()
            run.record("oauth token", True, "access token issued (not logged)")
        except Exception as exc:  # noqa: BLE001
            run.record_error("oauth token", exc)
            return finish(run, args, stamp)

        # A: deposit invoice with agreed terms embedded.
        payload_a = build_invoice_payload(
            invoice_number=f"CM-SMOKE-{stamp}-A",
            currency_code="USD",
            recipient_email=buyer,
            invoicer_email=invoicer,
            lines=[InvoiceLine("Deposit (30%) — full-body illustration", 9000)],
            note=DEPOSIT_NOTE,
            terms_and_conditions=DEPOSIT_TERMS,
        )
        request_id_a = str(uuid.uuid4())
        invoice_a = await create(client, run, "A (deposit)", payload_a, request_id_a)

        if invoice_a:
            await check_duplicate_create(client, run, payload_a, request_id_a, invoice_a["id"])
            await fetch(client, run, "A after create", invoice_a["id"])
            sent_a, payer_link_a = await send(client, run, "A", invoice_a["id"])
            await fetch(client, run, "A after send", invoice_a["id"])

        # B: change-order invoice with two lines, then a reminder.
        payload_b = build_invoice_payload(
            invoice_number=f"CM-SMOKE-{stamp}-B",
            currency_code="USD",
            recipient_email=buyer,
            invoicer_email=invoicer,
            lines=[
                InvoiceLine("Change order #1 — extra outfit", 8000),
                InvoiceLine("Change order #1 — extra revision", 2000),
            ],
            note="Change order #1 approved by client. Billed under scope v2.",
            terms_and_conditions="Scope v2 adds: one extra outfit, one extra revision.",
        )
        invoice_b = await create(
            client, run, "B (change order, 2 lines)", payload_b, str(uuid.uuid4())
        )
        sent_b, _ = await send(client, run, "B", invoice_b["id"]) if invoice_b else (False, None)
        if sent_b:
            try:
                await client.remind_invoice(
                    invoice_b["id"], subject="Reminder: sandbox test", note="Sandbox test reminder."
                )
                run.record("remind B", True, "reminder accepted")
            except Exception as exc:  # noqa: BLE001
                run.record_error("remind B", exc)

        # C: send then cancel.
        payload_c = build_invoice_payload(
            invoice_number=f"CM-SMOKE-{stamp}-C",
            currency_code="USD",
            recipient_email=buyer,
            invoicer_email=invoicer,
            lines=[InvoiceLine("Cancellation test", 100)],
        )
        invoice_c = await create(client, run, "C (cancel test)", payload_c, str(uuid.uuid4()))
        sent_c, _ = await send(client, run, "C", invoice_c["id"]) if invoice_c else (False, None)
        if sent_c:
            try:
                await client.cancel_invoice(invoice_c["id"], note="Sandbox cancellation test.")
                run.record("cancel C", True, "cancel accepted")
            except Exception as exc:  # noqa: BLE001
                run.record_error("cancel C", exc)
            await fetch(client, run, "C after cancel", invoice_c["id"])

        if sent_a and args.wait_for_payment > 0:
            await wait_for_payment(
                client, run, invoice_a["id"], payer_link_a, args.wait_for_payment
            )
    finally:
        await client.aclose()

    return finish(run, args, stamp)


async def check_duplicate_create(
    client: PayPalClient,
    run: SmokeRun,
    payload: dict[str, Any],
    request_id: str,
    invoice_id: str,
) -> None:
    """A retried create must not produce a second invoice, however PayPal signals it."""
    try:
        again = await client.create_draft_invoice(payload, request_id=request_id)
        same = again.get("id") == invoice_id
        detail = "request id replayed the same invoice" if same else "SECOND invoice created"
        run.record("duplicate create", same, detail)
    except PayPalError as exc:
        if not any(d.get("issue") == "DUPLICATE_INVOICE_NUMBER" for d in exc.details):
            run.record_error("duplicate create", exc)
            return
        run.record("duplicate create", True, "rejected with DUPLICATE_INVOICE_NUMBER")
    try:
        matches = await client.find_invoices_by_number(payload["detail"]["invoice_number"])
    except Exception as exc:  # noqa: BLE001
        run.record_error("search by invoice number", exc)
        return
    found = [m.get("id") for m in matches]
    run.record("search by invoice number", found == [invoice_id], f"{len(found)} match(es)")


async def wait_for_payment(
    client: PayPalClient, run: SmokeRun, invoice_id: str, payer_link: str | None, timeout: int
) -> None:
    print("\nPay invoice A as the sandbox buyer:")
    fallback = "(no payer link returned; open the invoice from the buyer sandbox inbox)"
    print(f"  {payer_link or fallback}")
    print(f"Polling every 10s for up to {timeout}s...")
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        try:
            status = (await client.get_invoice(invoice_id)).get("status")
        except PayPalError as exc:
            run.record_error("poll A", exc)
            return
        if status in {"PAID", "MARKED_AS_PAID", "PAYMENT_PENDING", "CANCELLED"}:
            break
        await asyncio.sleep(10)
    await fetch(client, run, "A after buyer payment", invoice_id)
    run.record("buyer payment", status == "PAID", f"final status={status}")


def finish(run: SmokeRun, args: argparse.Namespace, stamp: str) -> int:
    RESULTS_DIR.mkdir(exist_ok=True)
    result_file = RESULTS_DIR / f"smoke-{stamp}.json"
    result_file.write_text(
        json.dumps(
            {"steps": [s.__dict__ for s in run.steps], "responses": run.raw}, indent=2, default=str
        )
    )
    passed = sum(s.ok for s in run.steps)
    print(f"\n{passed}/{len(run.steps)} steps passed. Masked responses: {result_file}")
    if args.write_log:
        append_log(run, stamp)
        print(f"Appended summary to {TEST_LOG}")
    return 0 if run.steps and all(s.ok for s in run.steps) else 1


def append_log(run: SmokeRun, stamp: str) -> None:
    lines = [
        f"\n## Smoke run {stamp} (UTC)\n",
        "| Step | Result | Detail |",
        "|---|---|---|",
    ]
    for s in run.steps:
        detail = s.detail.replace("|", "\\|")
        if s.data.get("debug_id"):
            detail += f" (debug_id {s.data['debug_id']})"
        lines.append(f"| {s.name} | {'PASS' if s.ok else 'FAIL'} | {detail} |")
    shapes = {
        s.name: s.data.get("top_level_keys") for s in run.steps if s.data.get("top_level_keys")
    }
    if shapes:
        lines.append("\nInvoice object top-level keys observed:\n")
        for name, keys in shapes.items():
            lines.append(f"- {name}: `{', '.join(keys)}`")
    with TEST_LOG.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--wait-for-payment",
        type=int,
        default=0,
        metavar="SECONDS",
        help="after sending invoice A, poll until the sandbox buyer pays (0 = skip)",
    )
    parser.add_argument(
        "--write-log", action="store_true", help="append summary to docs/paypal-test-log.md"
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
