"""SQLAlchemy models for PRD §10. Money columns are integer minor units."""

import secrets
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, new_id, utcnow
from app.models.enums import (
    ChangeOrderStatus,
    CommissionStatus,
    MilestoneKind,
    MilestoneState,
    ProposalStatus,
)


def new_share_token() -> str:
    return secrets.token_urlsafe(24)


class Seller(Base):
    __tablename__ = "seller"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(120))
    # Set when PayPal answers 403; PayPal writes stay blocked until a retry succeeds.
    billing_disabled_code: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class RateCardItem(Base):
    __tablename__ = "rate_card_item"
    __table_args__ = (UniqueConstraint("seller_id", "code"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    seller_id: Mapped[str] = mapped_column(ForeignKey("seller.id"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    unit_price_minor_units: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(32), default="each")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Commission(Base):
    __tablename__ = "commission"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    seller_id: Mapped[str] = mapped_column(ForeignKey("seller.id"))
    # Reserved for Judge Mode cookie scoping.
    visitor_id: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    share_token: Mapped[str] = mapped_column(String(64), unique=True, default=new_share_token)
    seller_display_name: Mapped[str] = mapped_column(String(120))
    client_display_name: Mapped[str] = mapped_column(String(120), default="")
    client_email: Mapped[str | None] = mapped_column(String(254), default=None)
    source_language: Mapped[str] = mapped_column(String(16), default="en")
    currency_code: Mapped[str] = mapped_column(String(3), default="USD")
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    deliverables_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    file_formats_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    revisions_included: Mapped[int | None] = mapped_column(Integer, default=None)
    revisions_used: Mapped[int] = mapped_column(Integer, default=0)
    deadline_date: Mapped[date | None] = mapped_column(Date, default=None)
    usage_rights: Mapped[str] = mapped_column(Text, default="")
    # Agreed plan total. Change orders bill on top of it through their own milestones.
    total_minor_units: Mapped[int | None] = mapped_column(Integer, default=None)
    scope_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default=CommissionStatus.DRAFT)
    seller_accepted_version: Mapped[int | None] = mapped_column(Integer, default=None)
    client_accepted_version: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    seller: Mapped[Seller] = relationship()
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="commission", cascade="all, delete-orphan", order_by="Milestone.position"
    )
    invoices: Mapped[list["PaypalInvoice"]] = relationship(
        back_populates="commission",
        cascade="all, delete-orphan",
        order_by="PaypalInvoice.created_at",
    )
    proposals: Mapped[list["Proposal"]] = relationship(
        back_populates="commission", cascade="all, delete-orphan", order_by="Proposal.created_at"
    )
    change_orders: Mapped[list["ChangeOrder"]] = relationship(
        back_populates="commission", cascade="all, delete-orphan", order_by="ChangeOrder.number"
    )
    messages: Mapped[list["ClientMessage"]] = relationship(
        back_populates="commission",
        cascade="all, delete-orphan",
        order_by="ClientMessage.received_at",
    )
    snapshots: Mapped[list["ScopeSnapshot"]] = relationship(
        back_populates="commission", cascade="all, delete-orphan", order_by="ScopeSnapshot.version"
    )
    extraction_fields: Mapped[list["ExtractionField"]] = relationship(cascade="all, delete-orphan")
    activity: Mapped[list["ActivityLog"]] = relationship(
        back_populates="commission", cascade="all, delete-orphan", order_by="ActivityLog.created_at"
    )


class ScopeSnapshot(Base):
    __tablename__ = "scope_snapshot"
    __table_args__ = (UniqueConstraint("commission_id", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    commission: Mapped[Commission] = relationship(back_populates="snapshots")


class ClientMessage(Base):
    __tablename__ = "client_message"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16), default=None)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    analysis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    kind: Mapped[str] = mapped_column(String(16))

    commission: Mapped[Commission] = relationship(back_populates="messages")


class ExtractionField(Base):
    __tablename__ = "extraction_field"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    message_id: Mapped[str] = mapped_column(ForeignKey("client_message.id"))
    field_name: Mapped[str] = mapped_column(String(64))
    value_json: Mapped[Any] = mapped_column(JSON, default=None)
    source_quote: Mapped[str] = mapped_column(Text, default="")
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[str] = mapped_column(String(16))
    reviewer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    model_id: Mapped[str | None] = mapped_column(String(64), default=None)


class ChangeOrder(Base):
    __tablename__ = "change_order"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    message_id: Mapped[str] = mapped_column(ForeignKey("client_message.id"))
    # Shown to people as "Change order #1"; unique per commission.
    number: Mapped[int] = mapped_column(Integer)
    # Billable lines only. Each becomes one invoice line.
    items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    total_minor_units: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=ChangeOrderStatus.DRAFT)
    base_scope_version: Mapped[int] = mapped_column(Integer)
    resulting_scope_version: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    commission: Mapped[Commission] = relationship(back_populates="change_orders")
    message: Mapped[ClientMessage] = relationship()


class Milestone(Base):
    __tablename__ = "milestone"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default=MilestoneKind.PLAN)
    change_order_id: Mapped[str | None] = mapped_column(ForeignKey("change_order.id"), default=None)
    percentage_basis_points: Mapped[int | None] = mapped_column(Integer, default=None)
    amount_minor_units: Mapped[int] = mapped_column(Integer, default=0)
    billing_trigger: Mapped[str] = mapped_column(String(32))
    workflow_state: Mapped[str] = mapped_column(String(32), default=MilestoneState.LOCKED)
    evidence_url: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_note: Mapped[str | None] = mapped_column(Text, default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    commission: Mapped[Commission] = relationship(back_populates="milestones")
    change_order: Mapped[ChangeOrder | None] = relationship()
    invoices: Mapped[list["PaypalInvoice"]] = relationship(
        back_populates="milestone", cascade="all, delete-orphan", order_by="PaypalInvoice.attempt"
    )


class PaypalInvoice(Base):
    __tablename__ = "paypal_invoice"
    __table_args__ = (
        Index(
            "uq_active_invoice_per_milestone",
            "milestone_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    milestone_id: Mapped[str] = mapped_column(ForeignKey("milestone.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    billed_scope_version: Mapped[int] = mapped_column(Integer)
    amount_minor_units: Mapped[int] = mapped_column(Integer)
    currency_code: Mapped[str] = mapped_column(String(3))
    paypal_invoice_id: Mapped[str | None] = mapped_column(String(64), unique=True, default=None)
    # Stable per attempt: it is the duplicate guard for retried creates.
    invoice_number: Mapped[str] = mapped_column(String(32), unique=True)
    create_request_id: Mapped[str] = mapped_column(String(64), default=new_id)
    send_request_id: Mapped[str] = mapped_column(String(64), default=new_id)
    # Raw PayPal value. Kept apart from workflow_state on purpose.
    paypal_status: Mapped[str | None] = mapped_column(String(32), default=None)
    payer_link: Mapped[str | None] = mapped_column(Text, default=None)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    create_attempted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    send_attempted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # Our clock, not PayPal's: payments.transactions[].payment_date_time is not reliable UTC.
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    paid_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    last_reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    commission: Mapped[Commission] = relationship(back_populates="invoices")
    milestone: Mapped[Milestone] = relationship(back_populates="invoices")


class Proposal(Base):
    __tablename__ = "proposal"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    kind: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    scope_version: Mapped[int] = mapped_column(Integer)
    # "<entity>:<id>", plus the state that entity had when the proposal was made.
    target_ref: Mapped[str] = mapped_column(String(64))
    target_state: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default=ProposalStatus.PENDING)
    # Null means rule-generated.
    model_id: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    error_code: Mapped[str | None] = mapped_column(String(64), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    commission: Mapped[Commission] = relationship(back_populates="proposals")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    commission_id: Mapped[str] = mapped_column(ForeignKey("commission.id"))
    actor: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    commission: Mapped[Commission] = relationship(back_populates="activity")


class WebhookEvent(Base):
    """P1: verified PayPal webhooks. The table exists so the feature needs no data migration."""

    __tablename__ = "webhook_event"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paypal_event_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    paypal_invoice_id: Mapped[str | None] = mapped_column(String(64), default=None)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    status: Mapped[str] = mapped_column(String(16), default="RECEIVED")


class IdempotencyRecord(Base):
    """Stored response for one Idempotency-Key. status_code is null while the request runs."""

    __tablename__ = "idempotency_record"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    response_body: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
