"""In-process status polling (PRD §11.2). PayPal owns payment truth; this keeps our copy current."""

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.rules import reconcile
from app.config import Settings
from app.models import Commission, PaypalInvoice
from app.models.enums import CommissionStatus
from app.services.invoices import OPEN_STATUSES, fetch_and_apply
from app.services.paypal_client import PayPalClient
from app.services.paypal_errors import PAYPAL_FAILURES, map_paypal_error

logger = logging.getLogger(__name__)

# A project counts as open this long after its last page load.
VIEW_WINDOW_SECONDS = 120
# Projects nobody is looking at still need their reminders and PAID updates, just less often.
FULL_SWEEP_SECONDS = 300

_last_viewed: dict[str, float] = {}


def mark_viewed(commission_id: str) -> None:
    _last_viewed[commission_id] = time.monotonic()


def recently_viewed() -> set[str]:
    cutoff = time.monotonic() - VIEW_WINDOW_SECONDS
    for commission_id, viewed_at in list(_last_viewed.items()):
        if viewed_at < cutoff:
            del _last_viewed[commission_id]
    return set(_last_viewed)


async def refresh_invoice(
    db: Session, invoice: PaypalInvoice, paypal: PayPalClient, settings: Settings
) -> None:
    commission = invoice.commission
    await fetch_and_apply(db, commission, invoice, paypal)
    reconcile(db, commission, settings)
    db.commit()


async def poll_once(
    db: Session,
    paypal: PayPalClient,
    settings: Settings,
    *,
    only_commissions: set[str] | None = None,
) -> int:
    """Refresh every open invoice, or only those of the given projects. One failure stays local."""
    query = select(PaypalInvoice.id).where(
        PaypalInvoice.is_active,
        PaypalInvoice.paypal_invoice_id.is_not(None),
        PaypalInvoice.paypal_status.in_(OPEN_STATUSES),
    )
    if only_commissions is not None:
        query = query.where(PaypalInvoice.commission_id.in_(only_commissions))
    invoice_ids = list(db.scalars(query))
    db.commit()

    refreshed = 0
    for invoice_id in invoice_ids:
        invoice = db.get(PaypalInvoice, invoice_id)
        if invoice is None or not invoice.is_active:
            continue
        try:
            await refresh_invoice(db, invoice, paypal, settings)
            refreshed += 1
        except PAYPAL_FAILURES as exc:
            db.rollback()
            error = map_paypal_error(exc)
            invoice = db.get(PaypalInvoice, invoice_id)
            if invoice is not None:
                invoice.last_error_code = error.code
            db.commit()
            logger.warning("Status poll failed for invoice %s: %s", invoice_id, error.code)
    return refreshed


def reconcile_active(db: Session, settings: Settings) -> None:
    """Time-based proposals (reminders) can come due without any invoice changing."""
    commissions = db.scalars(
        select(Commission).where(Commission.status == CommissionStatus.IN_PROGRESS)
    ).all()
    for commission in commissions:
        reconcile(db, commission, settings)
    db.commit()


async def poll_forever(
    session_factory: sessionmaker[Session], paypal: PayPalClient, settings: Settings
) -> None:
    last_sweep = float("-inf")
    while True:
        await asyncio.sleep(settings.poll_interval_seconds)
        now = time.monotonic()
        full_sweep = now - last_sweep >= FULL_SWEEP_SECONDS
        try:
            with session_factory() as db:
                only = None if full_sweep else recently_viewed()
                if only is None or only:
                    await poll_once(db, paypal, settings, only_commissions=only)
                if full_sweep:
                    reconcile_active(db, settings)
            if full_sweep:
                last_sweep = now
        except Exception as exc:
            # The loop must outlive any single bad cycle. Log the type only: no PII or payloads.
            logger.error("Invoice poll cycle failed: %s", type(exc).__name__)
