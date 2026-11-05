"""HTTP request and response shapes. Money is always integer minor units; dates are ISO-8601 UTC."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.schemas.ai import IntakeAnalysis, ScopeGuardResult

MAX_MESSAGE_CHARS = 5000

# Strict: 80.5 and "80" are rejected rather than coerced. No floats for money.
MinorUnits = Annotated[StrictInt, Field(ge=1)]
Quantity = Annotated[StrictInt, Field(ge=1)]
MessageBody = Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]


class InputModel(BaseModel):
    # Unknown fields are errors, so "amount" or "recipient" cannot be slipped into an edit.
    model_config = ConfigDict(extra="forbid")


class ErrorOut(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


# --- Requests ---


class AnalyzeIn(InputModel):
    message: MessageBody
    today: date | None = None


class IntakeRecord(InputModel):
    """Stores what /api/analyze returned, since that route keeps nothing."""

    message: MessageBody
    analysis: IntakeAnalysis


class ScopeFields(InputModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    client_display_name: str | None = Field(default=None, max_length=120)
    client_email: str | None = Field(default=None, max_length=254)
    source_language: str | None = Field(default=None, max_length=16)
    currency_code: str | None = Field(default=None, max_length=3)
    deliverables: list[str] | None = None
    file_formats: list[str] | None = None
    revisions_included: Annotated[StrictInt, Field(ge=0)] | None = None
    deadline_date: date | None = None
    usage_rights: str | None = None
    total_minor_units: MinorUnits | None = None


class ProjectCreate(ScopeFields):
    intake: IntakeRecord | None = None


class ProjectPatch(ScopeFields):
    intake: IntakeRecord | None = None


class MilestonePlanEntry(InputModel):
    title: str = Field(min_length=1, max_length=200)
    basis_points: Annotated[StrictInt, Field(ge=1)]
    billing_trigger: Literal["ON_AGREEMENT", "ON_DELIVERY_APPROVED"]


class MilestonePlanIn(InputModel):
    milestones: list[MilestonePlanEntry] = Field(min_length=1)


class SellerAcceptIn(InputModel):
    scope_version: int | None = None


class ClientAcceptIn(InputModel):
    scope_version: int


class FollowUpIn(InputModel):
    body: MessageBody
    language: str | None = Field(default=None, max_length=16)


class RevisionIn(InputModel):
    count: Annotated[StrictInt, Field(ge=1, le=20)] = 1


class DeliverIn(InputModel):
    evidence_url: str | None = None
    note: str | None = None

    @field_validator("evidence_url")
    @classmethod
    def _web_links_only(cls, value: str | None) -> str | None:
        # The client page renders this as a link, so other schemes are an XSS risk.
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("Evidence must be an http or https link")
        return value


class ChangeOrderLineEdit(InputModel):
    id: str
    quantity: Quantity | None = None
    unit_price_minor_units: MinorUnits | None = None


class ProposalPatch(InputModel):
    """note/subject for invoice cards; lines/remove_line_ids for change-order cards."""

    note: str | None = Field(default=None, max_length=4000)
    subject: str | None = Field(default=None, max_length=200)
    lines: list[ChangeOrderLineEdit] | None = None
    remove_line_ids: list[str] | None = None


class RateCardItemIn(InputModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    unit_price_minor_units: MinorUnits
    unit: str = Field(default="each", max_length=32)
    active: bool = True


class RateCardIn(InputModel):
    items: list[RateCardItemIn]


# --- Responses ---


class RateCardItemOut(BaseModel):
    code: str
    name: str
    unit_price_minor_units: int
    unit: str
    active: bool


class RateCardOut(BaseModel):
    currency_code: str = "USD"
    items: list[RateCardItemOut]


class InvoiceOut(BaseModel):
    id: str
    milestone_id: str
    is_active: bool
    attempt: int
    invoice_number: str
    paypal_invoice_id: str | None
    amount_minor_units: int
    currency_code: str
    billed_scope_version: int
    paypal_status: str | None
    status_label: str
    settles_milestone: bool
    needs_attention: bool
    payer_link: str | None
    last_synced_at: datetime | None
    last_error_code: str | None
    reminders_sent: int
    sent_at: datetime | None
    paid_seen_at: datetime | None


class MilestoneOut(BaseModel):
    id: str
    position: int
    title: str
    kind: str
    change_order_id: str | None
    percentage_basis_points: int | None
    amount_minor_units: int
    billing_trigger: str
    workflow_state: str
    evidence_url: str | None
    evidence_note: str | None
    delivered_at: datetime | None
    approved_at: datetime | None
    active_invoice_id: str | None
    # A refund or other PayPal status on its invoice needs the seller's attention.
    flagged: bool


class ChangeOrderLineOut(BaseModel):
    id: str
    request_summary: str | None = None
    quote: str | None = None
    classification: str | None = None
    clause_ref: str | None = None
    clause_text: str | None = None
    rate_card_code: str | None = None
    name: str
    quantity: int
    unit_price_minor_units: int | None = None
    amount_minor_units: int | None = None
    needs_price: bool = False
    price_source: str | None = None


class ChangeOrderOut(BaseModel):
    id: str
    number: int
    message_id: str
    status: str
    lines: list[ChangeOrderLineOut]
    total_minor_units: int
    base_scope_version: int
    resulting_scope_version: int | None
    created_at: datetime


class BlockerOut(BaseModel):
    code: str
    message: str


class ProposalOut(BaseModel):
    id: str
    project_id: str
    kind: str
    status: str
    payload: dict[str, Any]
    rationale: str
    evidence: list[dict[str, Any]]
    scope_version: int
    target_ref: str
    target_state: str
    idempotency_key: str
    # Null means rule-generated.
    model_id: str | None
    blockers: list[BlockerOut]
    can_approve: bool
    error_code: str | None
    error_message: str | None
    created_at: datetime
    decided_at: datetime | None
    executed_at: datetime | None


class ActivityOut(BaseModel):
    id: str
    actor: str
    action: str
    details: dict[str, Any]
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    kind: str
    body: str
    language: str | None
    received_at: datetime
    analysis: dict[str, Any] | None


class ProjectSummaryOut(BaseModel):
    id: str
    title: str
    status: str
    scope_version: int
    client_display_name: str
    total_minor_units: int | None
    currency_code: str
    updated_at: datetime


class ScopeOut(BaseModel):
    id: str
    title: str
    description: str
    client_display_name: str
    client_email: str | None
    seller_display_name: str
    source_language: str
    currency_code: str
    deliverables: list[str]
    file_formats: list[str]
    revisions_included: int | None
    revisions_used: int
    deadline_date: date | None
    usage_rights: str
    # The plan total. Change orders are on top, in change_order_total_minor_units.
    total_minor_units: int | None
    change_order_total_minor_units: int
    scope_version: int
    status: str
    seller_accepted_version: int | None
    client_accepted_version: int | None
    created_at: datetime
    updated_at: datetime


class ProjectOut(ScopeOut):
    share_token: str
    client_path: str
    missing_fields: list[str]
    billing_disabled_code: str | None
    milestones: list[MilestoneOut]
    invoices: list[InvoiceOut]
    proposals: list[ProposalOut]
    change_orders: list[ChangeOrderOut]
    messages: list[MessageOut]
    activity: list[ActivityOut]


class FollowUpOut(BaseModel):
    message_id: str
    scope_guard: ScopeGuardResult
    # Null when nothing in the message is billable.
    change_order: ChangeOrderOut | None
    proposal: ProposalOut | None
    project: ProjectOut


class ClientInvoiceOut(BaseModel):
    invoice_number: str
    amount_minor_units: int
    currency_code: str
    paypal_status: str | None
    status_label: str
    payer_link: str | None


class ClientMilestoneOut(BaseModel):
    id: str
    position: int
    title: str
    kind: str
    amount_minor_units: int
    workflow_state: str
    evidence_url: str | None
    evidence_note: str | None
    delivered_at: datetime | None
    approved_at: datetime | None
    invoice: ClientInvoiceOut | None
    can_approve: bool


class ClientChangeOrderOut(BaseModel):
    id: str
    number: int
    status: str
    lines: list[ChangeOrderLineOut]
    total_minor_units: int
    can_decide: bool


class ClientViewOut(ScopeOut):
    seller_accepted: bool
    client_accepted: bool
    can_accept: bool
    milestones: list[ClientMilestoneOut]
    change_orders: list[ClientChangeOrderOut]


class ExampleMessages(BaseModel):
    intake: str
    follow_up: str


class DemoResetOut(BaseModel):
    project: ProjectOut
    suggested_client_email: str | None
    example_messages: ExampleMessages
