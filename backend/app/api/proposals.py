"""Proposal cards and the invoice actions next to them."""

from fastapi import APIRouter

from app.agent.executor import approve_proposal, dismiss_proposal, edit_proposal
from app.agent.rules import propose_cancel
from app.api.deps import DbDep, PayPalDep, SettingsDep, get_invoice, get_proposal, require_paypal
from app.api.presenters import invoice_out, proposal_out
from app.errors import invalid
from app.schemas import api as schemas
from app.services.invoice_sync import refresh_invoice
from app.services.paypal_errors import PAYPAL_FAILURES, map_paypal_error

router = APIRouter()


@router.post("/proposals/{proposal_id}/approve", response_model=schemas.ProposalOut)
async def approve(
    proposal_id: str, db: DbDep, paypal: PayPalDep, settings: SettingsDep
) -> schemas.ProposalOut:
    """Repeats return the current state. status APPROVED means another request is still running."""
    proposal = await approve_proposal(db, get_proposal(db, proposal_id), paypal, settings)
    return proposal_out(db, proposal, settings)


@router.post("/proposals/{proposal_id}/dismiss", response_model=schemas.ProposalOut)
async def dismiss(proposal_id: str, db: DbDep, settings: SettingsDep) -> schemas.ProposalOut:
    proposal = dismiss_proposal(db, get_proposal(db, proposal_id), settings)
    return proposal_out(db, proposal, settings)


@router.patch("/proposals/{proposal_id}", response_model=schemas.ProposalOut)
async def patch_proposal(
    proposal_id: str, body: schemas.ProposalPatch, db: DbDep, settings: SettingsDep
) -> schemas.ProposalOut:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise invalid("NOTHING_TO_EDIT", "Send at least one field to edit.")
    proposal = edit_proposal(db, get_proposal(db, proposal_id), changes, settings)
    return proposal_out(db, proposal, settings)


@router.post("/invoices/{invoice_id}/refresh", response_model=schemas.InvoiceOut)
async def refresh(
    invoice_id: str, db: DbDep, paypal: PayPalDep, settings: SettingsDep
) -> schemas.InvoiceOut:
    invoice = get_invoice(db, invoice_id)
    if not invoice.paypal_invoice_id:
        raise invalid("INVOICE_NOT_CREATED", "This invoice does not exist at PayPal yet.")
    try:
        await refresh_invoice(db, invoice, require_paypal(paypal), settings)
    except PAYPAL_FAILURES as exc:
        raise map_paypal_error(exc) from exc
    return invoice_out(invoice)


@router.post("/invoices/{invoice_id}/cancel", response_model=schemas.ProposalOut, status_code=201)
async def propose_invoice_cancel(
    invoice_id: str, db: DbDep, settings: SettingsDep
) -> schemas.ProposalOut:
    """Creates a CANCEL_INVOICE card. PayPal is only called once that card is approved."""
    invoice = get_invoice(db, invoice_id)
    proposal = propose_cancel(db, invoice.commission, invoice)
    db.commit()
    return proposal_out(db, proposal, settings)
