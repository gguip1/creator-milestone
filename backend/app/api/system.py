"""Rate card, demo reset, the P1 webhook placeholder, and health."""

import asyncio
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.rules import reconcile
from app.api.deps import DbDep, PayPalDep, SettingsDep, ViewerDep, get_commission
from app.api.presenters import project_out
from app.errors import AppError, conflict, invalid
from app.models import Commission, RateCardItem
from app.models.enums import CommissionStatus
from app.schemas import api as schemas
from app.services.demo_jump import run_jump
from app.services.paypal_errors import PAYPAL_FAILURES
from app.services.seed import (
    FOLLOW_UP_MESSAGE,
    INTAKE_MESSAGE,
    ensure_seller,
    reset_demo,
    seed_demo_project,
    suggested_recipient,
)

router = APIRouter()

TOKEN_CHECK_TIMEOUT_SECONDS = 5


def _rate_card(db: Session, seller_id: str) -> schemas.RateCardOut:
    items = db.scalars(
        select(RateCardItem)
        .where(RateCardItem.seller_id == seller_id)
        .order_by(RateCardItem.unit_price_minor_units.desc())
    )
    return schemas.RateCardOut(
        items=[
            schemas.RateCardItemOut(
                code=item.code,
                name=item.name,
                unit_price_minor_units=item.unit_price_minor_units,
                unit=item.unit,
                active=item.active,
            )
            for item in items
        ]
    )


@router.get("/settings/rate-card", response_model=schemas.RateCardOut)
async def get_rate_card(db: DbDep, viewer: ViewerDep) -> schemas.RateCardOut:
    seller = ensure_seller(db, viewer.id)
    db.commit()
    return _rate_card(db, seller.id)


@router.put("/settings/rate-card", response_model=schemas.RateCardOut)
async def put_rate_card(
    body: schemas.RateCardIn, db: DbDep, viewer: ViewerDep
) -> schemas.RateCardOut:
    """Upsert by code. Codes left out are deactivated, because old change orders refer to them."""
    codes = [item.code for item in body.items]
    if len(codes) != len(set(codes)):
        raise invalid("DUPLICATE_RATE_CARD_CODE", "Each rate-card code can appear only once.")
    seller = ensure_seller(db, viewer.id)
    existing = {
        item.code: item
        for item in db.scalars(select(RateCardItem).where(RateCardItem.seller_id == seller.id))
    }
    for entry in body.items:
        item = existing.get(entry.code)
        if item is None:
            item = RateCardItem(seller_id=seller.id, code=entry.code)
            db.add(item)
        item.name = entry.name
        item.unit_price_minor_units = entry.unit_price_minor_units
        item.unit = entry.unit
        item.active = entry.active
    for code, item in existing.items():
        if code not in codes:
            item.active = False
    db.commit()
    return _rate_card(db, seller.id)


def _demo_start(db: Session, commission: Commission, settings) -> schemas.DemoResetOut:
    return schemas.DemoResetOut(
        project=project_out(db, commission, settings),
        suggested_client_email=suggested_recipient(settings),
        example_messages=schemas.ExampleMessages(
            intake=INTAKE_MESSAGE, follow_up=FOLLOW_UP_MESSAGE
        ),
    )


@router.post("/demo/reset", response_model=schemas.DemoResetOut)
async def demo_reset(db: DbDep, settings: SettingsDep, viewer: ViewerDep) -> schemas.DemoResetOut:
    """Wipes and reseeds this visitor's project only."""
    commission = reset_demo(db, visitor_id=viewer.id)
    db.commit()
    return _demo_start(db, commission, settings)


@router.get("/demo/session", response_model=schemas.DemoResetOut)
async def demo_session(db: DbDep, settings: SettingsDep, viewer: ViewerDep) -> schemas.DemoResetOut:
    """The visitor's latest project, seeded on demand when a restart or a new cookie left none."""
    query = select(Commission).order_by(Commission.created_at.desc()).limit(1)
    query = query.where(
        Commission.visitor_id.is_(None) if viewer.id is None else Commission.visitor_id == viewer.id
    )
    commission = db.scalar(query)
    if commission is None:
        commission = seed_demo_project(db, visitor_id=viewer.id)
        db.commit()
    return _demo_start(db, commission, settings)


@router.get("/demo/status", response_model=schemas.DemoStatusOut)
async def demo_status(db: DbDep, viewer: ViewerDep) -> schemas.DemoStatusOut:
    """Read-only: never seeds or wipes. Lets the landing page warn before Start over."""
    query = select(Commission).order_by(Commission.created_at.desc()).limit(1)
    query = query.where(
        Commission.visitor_id.is_(None) if viewer.id is None else Commission.visitor_id == viewer.id
    )
    commission = db.scalar(query)
    if commission is None:
        return schemas.DemoStatusOut(has_project=False)
    at_paypal = [i for i in commission.invoices if i.paypal_invoice_id]
    paid = [i for i in at_paypal if i.paypal_status == "PAID"]
    return schemas.DemoStatusOut(
        has_project=True,
        project_id=commission.id,
        title=commission.title,
        status=commission.status,
        has_progress=bool(
            at_paypal
            or commission.title
            or commission.messages
            or commission.status != CommissionStatus.DRAFT
        ),
        invoices_at_paypal=len(at_paypal),
        invoices_paid=len(paid),
    )


@router.get("/demo/info", response_model=schemas.DemoInfoOut)
async def demo_info(settings: SettingsDep) -> schemas.DemoInfoOut:
    """What the sandbox banner shows. The buyer login is display-only and comes from settings."""
    return schemas.DemoInfoOut(
        judge_mode=settings.judge_mode,
        buyer_login=schemas.BuyerLoginOut(**settings.demo_buyer_login),
        paid_invoice_configured=bool(settings.demo_paid_invoice_id),
    )


@router.post("/demo/jump", response_model=schemas.DemoJumpOut)
async def demo_jump(
    body: schemas.DemoJumpIn,
    db: DbDep,
    paypal: PayPalDep,
    settings: SettingsDep,
    viewer: ViewerDep,
) -> schemas.DemoJumpOut:
    if not settings.judge_mode:
        raise conflict("NOT_JUDGE_MODE", "Shortcuts exist only in Judge Mode.")
    commission = get_commission(db, body.project_id, viewer)
    result = await run_jump(db, commission, body.target, paypal, settings)
    reconcile(db, commission, settings)
    db.commit()
    return schemas.DemoJumpOut(
        applied=result.applied,
        message=result.message,
        project=project_out(db, commission, settings),
    )


@router.post("/webhooks/paypal", status_code=501)
async def paypal_webhook() -> None:
    raise AppError(501, "NOT_IMPLEMENTED", "Webhooks are not enabled yet; status comes by polling.")


@router.get("/health")
async def health(settings: SettingsDep, paypal: PayPalDep) -> dict[str, Any]:
    """Liveness stays ok when PayPal is down. token_ok is null when no credentials are set."""
    token_ok: bool | None = None
    if paypal is not None:
        try:
            await asyncio.wait_for(paypal.get_access_token(), TOKEN_CHECK_TIMEOUT_SECONDS)
            token_ok = True
        except (*PAYPAL_FAILURES, TimeoutError):
            token_ok = False
    return {
        "status": "ok",
        "paypal": {
            "environment": settings.paypal_environment,
            "configured": settings.paypal_configured,
            "token_ok": token_ok,
        },
        "judge_mode": settings.judge_mode,
    }
