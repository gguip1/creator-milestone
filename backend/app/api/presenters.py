"""ORM rows -> response schemas. Call after commit, so collections reflect the saved state."""

from typing import Any

from sqlalchemy.orm import Session

from app.agent.validator import validate_proposal
from app.config import Settings
from app.models import ChangeOrder, Commission, Milestone, PaypalInvoice, Proposal
from app.models.enums import (
    ChangeOrderStatus,
    CommissionStatus,
    MilestoneKind,
    MilestoneState,
    ProposalStatus,
)
from app.schemas import api as schemas
from app.services.invoices import active_invoice
from app.services.paypal_status import StatusInfo, describe_status
from app.services.scope import missing_fields

NOT_CREATED = StatusInfo("Not created yet", False)
CLIENT_VISIBLE_CHANGE_ORDERS = (
    ChangeOrderStatus.SELLER_APPROVED,
    ChangeOrderStatus.CLIENT_APPROVED,
    ChangeOrderStatus.DECLINED,
)


def _status_info(invoice: PaypalInvoice) -> StatusInfo:
    return describe_status(invoice.paypal_status) if invoice.paypal_status else NOT_CREATED


def invoice_out(invoice: PaypalInvoice) -> schemas.InvoiceOut:
    info = _status_info(invoice)
    return schemas.InvoiceOut(
        id=invoice.id,
        milestone_id=invoice.milestone_id,
        is_active=invoice.is_active,
        attempt=invoice.attempt,
        invoice_number=invoice.invoice_number,
        paypal_invoice_id=invoice.paypal_invoice_id,
        amount_minor_units=invoice.amount_minor_units,
        currency_code=invoice.currency_code,
        billed_scope_version=invoice.billed_scope_version,
        paypal_status=invoice.paypal_status,
        status_label=info.label,
        settles_milestone=info.settles_milestone,
        needs_attention=info.needs_attention,
        payer_link=invoice.payer_link,
        last_synced_at=invoice.last_synced_at,
        last_error_code=invoice.last_error_code,
        reminders_sent=invoice.reminders_sent,
        sent_at=invoice.sent_at,
        paid_seen_at=invoice.paid_seen_at,
    )


def milestone_out(milestone: Milestone) -> schemas.MilestoneOut:
    invoice = active_invoice(milestone)
    return schemas.MilestoneOut(
        id=milestone.id,
        position=milestone.position,
        title=milestone.title,
        kind=milestone.kind,
        change_order_id=milestone.change_order_id,
        percentage_basis_points=milestone.percentage_basis_points,
        amount_minor_units=milestone.amount_minor_units,
        billing_trigger=milestone.billing_trigger,
        workflow_state=milestone.workflow_state,
        evidence_url=milestone.evidence_url,
        evidence_note=milestone.evidence_note,
        delivered_at=milestone.delivered_at,
        approved_at=milestone.approved_at,
        active_invoice_id=invoice.id if invoice else None,
        flagged=bool(invoice and _status_info(invoice).needs_attention),
    )


def _lines_out(change_order: ChangeOrder) -> list[schemas.ChangeOrderLineOut]:
    return [schemas.ChangeOrderLineOut(**line) for line in change_order.items_json]


def change_order_out(change_order: ChangeOrder) -> schemas.ChangeOrderOut:
    return schemas.ChangeOrderOut(
        id=change_order.id,
        number=change_order.number,
        message_id=change_order.message_id,
        status=change_order.status,
        lines=_lines_out(change_order),
        total_minor_units=change_order.total_minor_units,
        base_scope_version=change_order.base_scope_version,
        resulting_scope_version=change_order.resulting_scope_version,
        created_at=change_order.created_at,
    )


def proposal_out(db: Session, proposal: Proposal, settings: Settings) -> schemas.ProposalOut:
    blockers: list[schemas.BlockerOut] = []
    actionable = proposal.status in (ProposalStatus.PENDING, ProposalStatus.FAILED)
    if actionable:
        verdict = validate_proposal(db, proposal, proposal.commission, settings)
        blockers = [schemas.BlockerOut(code=b.code, message=b.message) for b in verdict.blockers]
        actionable = verdict.stale_reason is None
    return schemas.ProposalOut(
        id=proposal.id,
        project_id=proposal.commission_id,
        kind=proposal.kind,
        status=proposal.status,
        payload=proposal.payload_json,
        rationale=proposal.rationale,
        evidence=proposal.evidence_json,
        scope_version=proposal.scope_version,
        target_ref=proposal.target_ref,
        target_state=proposal.target_state,
        idempotency_key=proposal.idempotency_key,
        model_id=proposal.model_id,
        blockers=blockers,
        can_approve=actionable and not blockers,
        error_code=proposal.error_code,
        error_message=proposal.error_message,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
        executed_at=proposal.executed_at,
    )


def _scope_fields(commission: Commission) -> dict[str, Any]:
    change_order_total = sum(
        m.amount_minor_units for m in commission.milestones if m.kind == MilestoneKind.CHANGE_ORDER
    )
    return {
        "id": commission.id,
        "title": commission.title,
        "description": commission.description,
        "client_display_name": commission.client_display_name,
        "client_email": commission.client_email,
        "seller_display_name": commission.seller_display_name,
        "source_language": commission.source_language,
        "currency_code": commission.currency_code,
        "deliverables": commission.deliverables_json,
        "file_formats": commission.file_formats_json,
        "revisions_included": commission.revisions_included,
        "revisions_used": commission.revisions_used,
        "deadline_date": commission.deadline_date,
        "usage_rights": commission.usage_rights,
        "total_minor_units": commission.total_minor_units,
        "change_order_total_minor_units": change_order_total,
        "scope_version": commission.scope_version,
        "status": commission.status,
        "seller_accepted_version": commission.seller_accepted_version,
        "client_accepted_version": commission.client_accepted_version,
        "created_at": commission.created_at,
        "updated_at": commission.updated_at,
    }


def project_out(db: Session, commission: Commission, settings: Settings) -> schemas.ProjectOut:
    return schemas.ProjectOut(
        **_scope_fields(commission),
        share_token=commission.share_token,
        client_path=f"/c/{commission.share_token}",
        missing_fields=missing_fields(commission),
        billing_disabled_code=commission.seller.billing_disabled_code,
        milestones=[milestone_out(m) for m in commission.milestones],
        invoices=[invoice_out(i) for i in commission.invoices],
        proposals=[proposal_out(db, p, settings) for p in commission.proposals],
        change_orders=[change_order_out(co) for co in commission.change_orders],
        messages=[
            schemas.MessageOut(
                id=m.id,
                kind=m.kind,
                body=m.body,
                language=m.language,
                received_at=m.received_at,
                analysis=m.analysis_json,
            )
            for m in commission.messages
        ],
        activity=[
            schemas.ActivityOut(
                id=a.id,
                actor=a.actor,
                action=a.action,
                details=a.details_json,
                created_at=a.created_at,
            )
            for a in commission.activity
        ],
    )


def project_summary(commission: Commission) -> schemas.ProjectSummaryOut:
    return schemas.ProjectSummaryOut(
        id=commission.id,
        title=commission.title,
        status=commission.status,
        scope_version=commission.scope_version,
        client_display_name=commission.client_display_name,
        total_minor_units=commission.total_minor_units,
        currency_code=commission.currency_code,
        updated_at=commission.updated_at,
    )


def _client_milestone(milestone: Milestone) -> schemas.ClientMilestoneOut:
    # Prefer the active invoice; a settled or cancelled one is still worth showing.
    invoice = active_invoice(milestone) or (milestone.invoices[-1] if milestone.invoices else None)
    # A draft is the seller's work in progress, and has no payer link yet.
    shown = invoice if invoice and invoice.sent_at else None
    return schemas.ClientMilestoneOut(
        id=milestone.id,
        position=milestone.position,
        title=milestone.title,
        kind=milestone.kind,
        amount_minor_units=milestone.amount_minor_units,
        workflow_state=milestone.workflow_state,
        evidence_url=milestone.evidence_url,
        evidence_note=milestone.evidence_note,
        delivered_at=milestone.delivered_at,
        approved_at=milestone.approved_at,
        invoice=schemas.ClientInvoiceOut(
            invoice_number=shown.invoice_number,
            amount_minor_units=shown.amount_minor_units,
            currency_code=shown.currency_code,
            paypal_status=shown.paypal_status,
            status_label=_status_info(shown).label,
            payer_link=shown.payer_link,
        )
        if shown
        else None,
        can_approve=milestone.workflow_state == MilestoneState.DELIVERED,
    )


def client_view(commission: Commission) -> schemas.ClientViewOut:
    version = commission.scope_version
    client_accepted = commission.client_accepted_version == version
    seller_accepted = commission.seller_accepted_version == version
    return schemas.ClientViewOut(
        **_scope_fields(commission),
        seller_accepted=seller_accepted,
        client_accepted=client_accepted,
        can_accept=(
            commission.status == CommissionStatus.AWAITING_ACCEPTANCE
            and seller_accepted
            and not client_accepted
        ),
        milestones=[_client_milestone(m) for m in commission.milestones],
        change_orders=[
            schemas.ClientChangeOrderOut(
                id=co.id,
                number=co.number,
                status=co.status,
                lines=_lines_out(co),
                total_minor_units=co.total_minor_units,
                can_decide=co.status == ChangeOrderStatus.SELLER_APPROVED,
            )
            for co in commission.change_orders
            if co.status in CLIENT_VISIBLE_CHANGE_ORDERS
        ],
    )
