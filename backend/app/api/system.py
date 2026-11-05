"""Rate card, demo reset, the P1 webhook placeholder, and health."""

import asyncio
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbDep, PayPalDep, SettingsDep
from app.api.presenters import project_out
from app.errors import AppError, invalid
from app.models import RateCardItem
from app.schemas import api as schemas
from app.services.paypal_errors import PAYPAL_FAILURES
from app.services.seed import (
    FOLLOW_UP_MESSAGE,
    INTAKE_MESSAGE,
    ensure_seller,
    reset_demo,
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
async def get_rate_card(db: DbDep) -> schemas.RateCardOut:
    seller = ensure_seller(db)
    db.commit()
    return _rate_card(db, seller.id)


@router.put("/settings/rate-card", response_model=schemas.RateCardOut)
async def put_rate_card(body: schemas.RateCardIn, db: DbDep) -> schemas.RateCardOut:
    """Upsert by code. Codes left out are deactivated, because old change orders refer to them."""
    codes = [item.code for item in body.items]
    if len(codes) != len(set(codes)):
        raise invalid("DUPLICATE_RATE_CARD_CODE", "Each rate-card code can appear only once.")
    seller = ensure_seller(db)
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


@router.post("/demo/reset", response_model=schemas.DemoResetOut)
async def demo_reset(db: DbDep, settings: SettingsDep) -> schemas.DemoResetOut:
    commission = reset_demo(db)
    db.commit()
    return schemas.DemoResetOut(
        project=project_out(db, commission, settings),
        suggested_client_email=suggested_recipient(settings),
        example_messages=schemas.ExampleMessages(
            intake=INTAKE_MESSAGE, follow_up=FOLLOW_UP_MESSAGE
        ),
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
