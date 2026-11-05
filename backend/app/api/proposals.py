"""Proposal cards and the invoice actions next to them."""

from fastapi import APIRouter, Request

from app.agent.executor import approve_proposal, dismiss_proposal, edit_proposal
from app.agent.rules import propose_cancel
from app.api.deps import (
    DbDep,
    PayPalDep,
    SettingsDep,
    ViewerDep,
    get_invoice,
    get_proposal,
    require_paypal,
    take_invoice_slot,
)
from app.api.presenters import invoice_out, proposal_out
from app.errors import invalid
from app.models.enums import ProposalKind, ProposalStatus
from app.schemas import api as schemas
from app.services.invoice_sync import refresh_invoice
from app.services.paypal_errors import PAYPAL_FAILURES, map_paypal_error

router = APIRouter()


@router.post("/proposals/{proposal_id}/approve", response_model=schemas.ProposalOut)
async def approve(
    proposal_id: str,
    request: Request,
    db: DbDep,
    paypal: PayPalDep,
    settings: SettingsDep,
    viewer: ViewerDep,
) -> schemas.ProposalOut:
    """Repeats return the current state. status APPROVED means another request is still running."""
    card = get_proposal(db, proposal_id, viewer)
    if card.kind == ProposalKind.BILL_MILESTONE and card.status in (
        ProposalStatus.PENDING,
        ProposalStatus.FAILED,
    ):
        take_invoice_slot(request, settings, viewer)
    proposal = await approve_proposal(db, card, paypal, settings)
    return proposal_out(db, proposal, settings)


@router.post("/proposals/{proposal_id}/dismiss", response_model=schemas.ProposalOut)
async def dismiss(
    proposal_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep
) -> schemas.ProposalOut:
    proposal = dismiss_proposal(db, get_proposal(db, proposal_id, viewer), settings)
    return proposal_out(db, proposal, settings)


@router.patch("/proposals/{proposal_id}", response_model=schemas.ProposalOut)
async def patch_proposal(
    proposal_id: str,
    body: schemas.ProposalPatch,
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
) -> schemas.ProposalOut:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise invalid("NOTHING_TO_EDIT", "Send at least one field to edit.")
    proposal = edit_proposal(db, get_proposal(db, proposal_id, viewer), changes, settings)
    return proposal_out(db, proposal, settings)


@router.post("/invoices/{invoice_id}/refresh", response_model=schemas.InvoiceOut)
async def refresh(
    invoice_id: str, db: DbDep, paypal: PayPalDep, settings: SettingsDep, viewer: ViewerDep
) -> schemas.InvoiceOut:
    invoice = get_invoice(db, invoice_id, viewer)
    if not invoice.paypal_invoice_id:
        raise invalid("INVOICE_NOT_CREATED", "This invoice does not exist at PayPal yet.")
    try:
        await refresh_invoice(db, invoice, require_paypal(paypal), settings)
    except PAYPAL_FAILURES as exc:
        raise map_paypal_error(exc) from exc
    return invoice_out(invoice)


@router.post("/invoices/{invoice_id}/cancel", response_model=schemas.ProposalOut, status_code=201)
async def propose_invoice_cancel(
    invoice_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep
) -> schemas.ProposalOut:
    """Creates a CANCEL_INVOICE card. PayPal is only called once that card is approved."""
    invoice = get_invoice(db, invoice_id, viewer)
    proposal = propose_cancel(db, invoice.commission, invoice)
    db.commit()
    return proposal_out(db, proposal, settings)
