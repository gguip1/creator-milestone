"""Seller routes for a project: analyze, scope, plan, acceptance, messages, delivery."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.rules import propose_change_order, propose_next_step, reconcile
from app.api.deps import (
    LLM_FAILURES,
    DbDep,
    IntakeDep,
    LlmGateDep,
    ScopeGuardDep,
    SettingsDep,
    TodayDep,
    ViewerDep,
    get_commission,
    get_milestone,
    llm_unavailable,
)
from app.api.presenters import (
    change_order_out,
    project_out,
    project_summary,
    proposal_out,
)
from app.errors import conflict
from app.models import ClientMessage, Commission, ExtractionField
from app.models.enums import Actor, CommissionStatus, MessageKind
from app.schemas import api as schemas
from app.schemas.ai import ExtractedField, IntakeAnalysis
from app.services.activity import log_activity
from app.services.change_orders import (
    create_change_order,
    ensure_message_not_billed,
    rate_card_entries,
    record_message,
    sanitize_guard_result,
)
from app.services.invoice_sync import mark_viewed
from app.services.limits import rate_limited
from app.services.milestones import PlanEntry, deliver_milestone
from app.services.scope import (
    FIELD_COLUMNS,
    accept_as_seller,
    edit_plan,
    edit_scope,
    scope_context,
)
from app.services.seed import ensure_seller, new_commission
from app.services.state_machines import set_commission_status

router = APIRouter()

ACTIVE_STATUSES = (CommissionStatus.AGREED, CommissionStatus.IN_PROGRESS)


def _store_intake(db: Session, commission: Commission, record: schemas.IntakeRecord) -> None:
    """Keep what the seller reviewed. These rows are records only; nothing bills from them."""
    analysis: IntakeAnalysis = record.analysis
    message = ClientMessage(
        commission_id=commission.id,
        body=record.message,
        language=analysis.source_language,
        analysis_json=analysis.model_dump(mode="json"),
        kind=MessageKind.INTAKE,
    )
    db.add(message)
    db.flush()

    fields: list[tuple[str, ExtractedField]] = [
        ("title", analysis.title),
        ("deadline", analysis.deadline),
        ("revisions", analysis.revisions),
        ("usage_rights", analysis.usage_rights),
        ("budget", analysis.budget),
        ("client_email", analysis.client_email),
        ("sketch_review_requested", analysis.sketch_review_requested),
        *(("deliverables", f) for f in analysis.deliverables),
        *(("file_formats", f) for f in analysis.file_formats),
    ]
    db.add_all(
        ExtractionField(
            commission_id=commission.id,
            message_id=message.id,
            field_name=name,
            value_json=field.value,
            source_quote=field.quote,
            quote_verified=field.quote_verified,
            provenance=field.provenance,
            reviewer_confirmed=not field.needs_confirmation,
            model_id=analysis.model_id,
        )
        for name, field in fields
    )
    log_activity(db, commission, Actor.AGENT, "intake_analyzed", source=analysis.source)


def _scope_changes(body: schemas.ScopeFields) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True, exclude={"intake"})


@router.post("/analyze", response_model=schemas.IntakeAnalysis)
async def analyze(
    body: schemas.AnalyzeIn, analyzer: IntakeDep, today: TodayDep, gate: LlmGateDep
) -> IntakeAnalysis:
    try:
        return await gate.intake(analyzer, body.message, today=body.today or today)
    except LLM_FAILURES as exc:
        raise llm_unavailable() from exc


@router.get("/projects", response_model=list[schemas.ProjectSummaryOut])
async def list_projects(db: DbDep, viewer: ViewerDep) -> list[schemas.ProjectSummaryOut]:
    query = select(Commission).order_by(Commission.created_at.desc())
    if viewer.scoped:
        query = query.where(Commission.visitor_id == viewer.id)
    return [project_summary(c) for c in db.scalars(query)]


@router.post("/projects", response_model=schemas.ProjectOut, status_code=201)
async def create_project(
    body: schemas.ProjectCreate, db: DbDep, settings: SettingsDep, viewer: ViewerDep
) -> schemas.ProjectOut:
    if viewer.scoped:
        owned = db.scalar(
            select(func.count()).select_from(Commission).where(Commission.visitor_id == viewer.id)
        )
        if owned >= settings.limit_projects_per_visitor:
            raise rate_limited(
                "This demo keeps a few projects per visitor. Reset the demo to start over.", 3600
            )
    seller = ensure_seller(db, viewer.id)
    fields = {
        FIELD_COLUMNS.get(name, name): value
        for name, value in _scope_changes(body).items()
        if value is not None
    }
    commission = new_commission(db, seller, visitor_id=viewer.id, **fields)
    if body.intake:
        _store_intake(db, commission, body.intake)
    db.commit()
    return project_out(db, commission, settings)


@router.get("/projects/{project_id}", response_model=schemas.ProjectOut)
async def get_project(
    project_id: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> schemas.ProjectOut:
    commission = get_commission(db, project_id, viewer)
    mark_viewed(commission.id)
    return project_out(db, commission, settings)


@router.patch("/projects/{project_id}", response_model=schemas.ProjectOut)
async def patch_project(
    project_id: str, viewer: ViewerDep, body: schemas.ProjectPatch, db: DbDep, settings: SettingsDep
) -> schemas.ProjectOut:
    commission = get_commission(db, project_id, viewer)
    edit_scope(db, commission, _scope_changes(body))
    if body.intake:
        _store_intake(db, commission, body.intake)
    reconcile(db, commission, settings)
    db.commit()
    return project_out(db, commission, settings)


@router.put("/projects/{project_id}/milestones", response_model=schemas.ProjectOut)
async def put_milestones(
    project_id: str,
    viewer: ViewerDep,
    body: schemas.MilestonePlanIn,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.ProjectOut:
    commission = get_commission(db, project_id, viewer)
    edit_plan(
        db,
        commission,
        [PlanEntry(m.title, m.basis_points, m.billing_trigger) for m in body.milestones],
    )
    reconcile(db, commission, settings)
    db.commit()
    return project_out(db, commission, settings)


@router.post("/projects/{project_id}/accept", response_model=schemas.ProjectOut)
async def accept_project(
    project_id: str,
    viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    body: schemas.SellerAcceptIn | None = None,
) -> schemas.ProjectOut:
    commission = get_commission(db, project_id, viewer)
    accept_as_seller(db, commission, body.scope_version if body else None)
    reconcile(db, commission, settings)
    db.commit()
    return project_out(db, commission, settings)


@router.post("/projects/{project_id}/cancel", response_model=schemas.ProjectOut)
async def cancel_project(
    project_id: str, viewer: ViewerDep, db: DbDep, settings: SettingsDep
) -> schemas.ProjectOut:
    commission = get_commission(db, project_id, viewer)
    if any(i.is_active and i.sent_at and not i.paid_seen_at for i in commission.invoices):
        raise conflict(
            "OPEN_INVOICE_EXISTS", "Cancel the unpaid invoice first, then cancel the commission."
        )
    set_commission_status(commission, CommissionStatus.CANCELLED)
    log_activity(db, commission, Actor.SELLER, "commission_cancelled")
    reconcile(db, commission, settings)
    db.commit()
    return project_out(db, commission, settings)


@router.post("/projects/{project_id}/revisions", response_model=schemas.ProjectOut)
async def log_revision(
    project_id: str,
    viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    body: schemas.RevisionIn | None = None,
) -> schemas.ProjectOut:
    commission = get_commission(db, project_id, viewer)
    if commission.status not in ACTIVE_STATUSES:
        raise conflict("COMMISSION_NOT_ACTIVE", f"The commission is {commission.status}.")
    commission.revisions_used += body.count if body else 1
    log_activity(
        db,
        commission,
        Actor.SELLER,
        "revision_logged",
        revisions_used=commission.revisions_used,
        revisions_included=commission.revisions_included,
    )
    reconcile(db, commission, settings)
    db.commit()
    return project_out(db, commission, settings)


@router.post("/projects/{project_id}/messages", response_model=schemas.FollowUpOut, status_code=201)
async def post_message(
    project_id: str,
    viewer: ViewerDep,
    body: schemas.FollowUpIn,
    db: DbDep,
    settings: SettingsDep,
    guard: ScopeGuardDep,
    today: TodayDep,
    gate: LlmGateDep,
) -> schemas.FollowUpOut:
    commission = get_commission(db, project_id, viewer)
    if commission.status not in ACTIVE_STATUSES:
        raise conflict(
            "COMMISSION_NOT_ACTIVE",
            f"Scope Guard needs an agreed scope; the commission is {commission.status}.",
        )
    ensure_message_not_billed(db, commission, body.body)
    version = commission.scope_version
    scope = scope_context(commission)
    rate_card = rate_card_entries(db, commission.seller_id)
    db.commit()

    try:
        raw_result = await gate.guard(
            guard, body.body, scope=scope, rate_card=rate_card, today=today
        )
    except LLM_FAILURES as exc:
        raise llm_unavailable() from exc

    # The world may have moved during the model call; recheck before writing anything.
    if commission.scope_version != version:
        raise conflict(
            "SCOPE_VERSION_MISMATCH",
            "The scope changed while this message was being checked. Run it again.",
            {"current_version": commission.scope_version},
        )
    ensure_message_not_billed(db, commission, body.body)

    result = sanitize_guard_result(raw_result, body.body, rate_card)
    message = record_message(
        db, commission, body.body, body.language, result.model_dump(mode="json")
    )
    log_activity(
        db,
        commission,
        Actor.AGENT,
        "scope_guard_checked",
        items=len(result.items),
        billable=sum(1 for item in result.items if item.billable),
        source=result.source,
    )
    change_order = create_change_order(db, commission, message, result)
    proposal = propose_change_order(db, commission, change_order, result) if change_order else None
    reconcile(db, commission, settings)
    db.commit()
    return schemas.FollowUpOut(
        message_id=message.id,
        scope_guard=result,
        change_order=change_order_out(change_order) if change_order else None,
        proposal=proposal_out(db, proposal, settings) if proposal else None,
        project=project_out(db, commission, settings),
    )


@router.post("/milestones/{milestone_id}/deliver", response_model=schemas.ProjectOut)
async def deliver(
    milestone_id: str,
    viewer: ViewerDep,
    db: DbDep,
    settings: SettingsDep,
    body: schemas.DeliverIn | None = None,
) -> schemas.ProjectOut:
    milestone = get_milestone(db, milestone_id, viewer)
    commission = milestone.commission
    deliver_milestone(
        db, milestone, body.evidence_url if body else None, body.note if body else None
    )
    reconcile(db, commission, settings)
    db.commit()
    return project_out(db, commission, settings)


@router.post(
    "/milestones/{milestone_id}/propose-bill",
    response_model=schemas.ProposalOut,
    status_code=201,
)
async def propose_bill_again(
    milestone_id: str, db: DbDep, settings: SettingsDep, viewer: ViewerDep
) -> schemas.ProposalOut:
    """Bring back a billing card after the seller dismissed it. It still needs approval."""
    milestone = get_milestone(db, milestone_id, viewer)
    proposal = propose_next_step(db, milestone.commission, milestone)
    db.commit()
    return proposal_out(db, proposal, settings)
