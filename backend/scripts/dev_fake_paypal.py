"""Dev-only runner: the real app with an in-memory fake PayPal, so the UI can be clicked through
every state (including paid) without credentials. Nothing here runs unless you invoke it:

    uv run python -m scripts.dev_fake_paypal [--port 8000]

It never reads .env, never calls PayPal or the AI provider (the two demo messages return their
cached analyses), and keeps data in a temp SQLite file that is deleted on exit.

Extra dev routes (not part of the product API):
    POST /dev/pay                  mark every sent invoice PAID in the fake
    POST /dev/pay/{paypal_id}      mark one invoice PAID
    POST /dev/status/{paypal_id}/{STATUS}   set any PayPal status (e.g. MARKED_AS_PAID)
    POST /dev/fail-next/{operation}/{status}/{issue}   next create/send/... call fails
"""

import argparse
import shutil
import tempfile
from pathlib import Path

import uvicorn
from fastapi import APIRouter, HTTPException
from pydantic import SecretStr

import app.agent.llm as llm
from app.api.deps import get_paypal_client
from app.config import Settings, get_settings
from app.db import make_session_factory
from app.main import app
from tests.fake_paypal import FakePayPal

dev = APIRouter(prefix="/dev")


def build(fake: FakePayPal, database_url: str) -> Settings:
    # _env_file=None and explicit values: neither the shell nor backend/.env can enable real calls.
    settings = Settings(
        _env_file=None,
        paypal_client_id="fake-client-id",
        paypal_client_secret=SecretStr("fake-value"),
        paypal_invoicer_email="seller@example.com",
        paypal_sandbox_buyer_email="client@example.com",
        llm_provider="",
        llm_model="",
        llm_api_key=SecretStr(""),
        database_url=database_url,
        judge_mode=False,
        recipient_allowlist=[],
        reminder_threshold_minutes=60,
        poll_interval_seconds=5,
    )
    client = fake.client()
    app.state.paypal_client = client  # paypal_client_for() reuses this, so no real client is built
    app.state.session_factory = make_session_factory(database_url)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_paypal_client] = lambda: client
    llm.get_settings = lambda: settings  # the AI layer reads settings directly
    return settings


def register_dev_routes(fake: FakePayPal) -> None:
    @dev.post("/pay")
    def pay_all() -> dict[str, list[str]]:
        paid = [i for i, inv in fake.invoices.items() if inv["status"] in ("SENT", "UNPAID")]
        for invoice_id in paid:
            fake.buyer_pays(invoice_id)
        return {"paid": paid}

    @dev.post("/pay/{paypal_id}")
    def pay_one(paypal_id: str) -> dict[str, str]:
        if paypal_id not in fake.invoices:
            raise HTTPException(404, "No such fake invoice")
        fake.buyer_pays(paypal_id)
        return {"paid": paypal_id}

    @dev.post("/status/{paypal_id}/{status}")
    def set_status(paypal_id: str, status: str) -> dict[str, str]:
        if paypal_id not in fake.invoices:
            raise HTTPException(404, "No such fake invoice")
        fake.set_status(paypal_id, status)
        return {paypal_id: status}

    @dev.post("/fail-next/{operation}/{status}/{issue}")
    def fail_next(operation: str, status: int, issue: str) -> dict[str, str]:
        fake.fail_next(operation, status, "UNPROCESSABLE_ENTITY", issue)
        return {"next": operation, "issue": issue}

    app.include_router(dev)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    fake = FakePayPal()
    workdir = Path(tempfile.mkdtemp(prefix="creatormilestone-fake-"))
    try:
        build(fake, f"sqlite:///{workdir / 'dev.db'}")
        register_dev_routes(fake)
        print(f"Fake PayPal dev server on http://127.0.0.1:{args.port} (data: {workdir})")
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
