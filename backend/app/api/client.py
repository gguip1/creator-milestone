"""Client page routes. The share token is the only credential (demo-only, labeled in the README)."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.rules import reconcile
from app.api.deps import DbDep, SettingsDep, get_change_order, get_milestone
from app.api.presenters import client_view
from app.errors import not_found
from app.models import Commission
from app.schemas import api as schemas
from app.services.change_orders import client_approve, client_decline
from app.services.invoice_sync import mark_viewed
from app.services.milestones import approve_delivery
from app.services.scope import accept_as_client
from app.services.visitors import UNSCOPED

router = APIRouter(prefix="/c")


def _commission_for(db: Session, token: str) -> Commission:
    commission = db.scalar(select(Commission).where(Commission.share_token == token))
    if commission is None:
        raise not_found("Project")
    return commission


@router.get("/{token}", response_model=schemas.ClientViewOut)
async def get_client_view(token: str, db: DbDep) -> schemas.ClientViewOut:
    commission = _commission_for(db, token)
    mark_viewed(commission.id)
    return client_view(commission)


@router.post("/{token}/accept", response_model=schemas.ClientViewOut)
async def accept_scope(
    token: str, body: schemas.ClientAcceptIn, db: DbDep, settings: SettingsDep
) -> schemas.ClientViewOut:
    commission = _commission_for(db, token)
    accept_as_client(db, commission, body.scope_version)
    reconcile(db, commission, settings)
    db.commit()
    return client_view(commission)


@router.post("/{token}/milestones/{milestone_id}/approve", response_model=schemas.ClientViewOut)
async def approve_milestone(
    token: str, milestone_id: str, db: DbDep, settings: SettingsDep
) -> schemas.ClientViewOut:
    commission = _commission_for(db, token)
    milestone = get_milestone(db, milestone_id, UNSCOPED)
    if milestone.commission_id != commission.id:
        raise not_found("Milestone")
    approve_delivery(db, milestone)
    reconcile(db, commission, settings)
    db.commit()
    return client_view(commission)


@router.post(
    "/{token}/change-orders/{change_order_id}/approve", response_model=schemas.ClientViewOut
)
async def approve_change_order(
    token: str, change_order_id: str, db: DbDep, settings: SettingsDep
) -> schemas.ClientViewOut:
    commission = _commission_for(db, token)
    client_approve(db, commission, get_change_order(db, commission, change_order_id))
    reconcile(db, commission, settings)
    db.commit()
    return client_view(commission)


@router.post(
    "/{token}/change-orders/{change_order_id}/decline", response_model=schemas.ClientViewOut
)
async def decline_change_order(
    token: str, change_order_id: str, db: DbDep, settings: SettingsDep
) -> schemas.ClientViewOut:
    commission = _commission_for(db, token)
    client_decline(db, commission, get_change_order(db, commission, change_order_id))
    reconcile(db, commission, settings)
    db.commit()
    return client_view(commission)
