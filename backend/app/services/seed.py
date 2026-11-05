"""Seeded demo data (PRD §5): seller Jiwoo, her rate card, and a project waiting at intake."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Commission, RateCardItem, Seller
from app.models.enums import Actor
from app.services.activity import log_activity
from app.services.milestones import DEFAULT_PLAN, set_plan
from app.services.scope import write_snapshot

SELLER_NAME = "Jiwoo"

RATE_CARD = (
    ("full_body_base", "Full-body illustration", 30000),
    ("extra_outfit", "Extra outfit", 8000),
    ("extra_revision", "Extra revision", 2000),
    ("commercial_license", "Commercial license add-on", 10000),
)

INTAKE_MESSAGE = (
    "Hi! I need a full-body illustration of my original character for my VTuber debut, "
    "transparent PNG plus layered PSD, around November 25. I'd like a sketch review before "
    "coloring. My budget is USD 300. Maybe two rounds of revisions? Please let me know how "
    "payment works."
)

FOLLOW_UP_MESSAGE = (
    "Love the sketch!! Could you also add a second outfit, maybe a casual hoodie version? "
    "And can we do one more pass on the face? Also I might use it on merch later."
)


def ensure_seller(db: Session) -> Seller:
    """The one demo seller. Her rate card is seeded only when she is first created."""
    seller = db.scalar(select(Seller).where(Seller.display_name == SELLER_NAME))
    if seller is not None:
        return seller
    seller = Seller(display_name=SELLER_NAME)
    db.add(seller)
    db.flush()
    _write_rate_card(db, seller)
    return seller


def _write_rate_card(db: Session, seller: Seller) -> None:
    db.add_all(
        RateCardItem(seller_id=seller.id, code=code, name=name, unit_price_minor_units=price)
        for code, name, price in RATE_CARD
    )
    db.flush()


def new_commission(db: Session, seller: Seller, **fields) -> Commission:
    """A DRAFT commission with the default 30/30/40 plan and its first snapshot."""
    defaults = {"deliverables_json": [], "file_formats_json": []}
    commission = Commission(
        seller_id=seller.id, seller_display_name=seller.display_name, **{**defaults, **fields}
    )
    db.add(commission)
    db.flush()
    set_plan(db, commission, list(DEFAULT_PLAN))
    write_snapshot(db, commission, "initial")
    log_activity(db, commission, Actor.SYSTEM, "project_created")
    return commission


def seed_demo_project(db: Session, *, visitor_id: str | None = None) -> Commission:
    """A fresh project at intake. Terms are empty because the demo starts by analyzing message 1."""
    seller = ensure_seller(db)
    return new_commission(db, seller, client_display_name="Demo client", visitor_id=visitor_id)


def suggested_recipient(settings: Settings) -> str | None:
    """Judge Mode presets the recipient to our sandbox buyer (PRD §15.3)."""
    if settings.paypal_sandbox_buyer_email:
        return settings.paypal_sandbox_buyer_email
    return settings.recipient_allowlist[0] if settings.recipient_allowlist else None


def reset_demo(db: Session, *, visitor_id: str | None = None) -> Commission:
    """Wipe this visitor's projects (all of them until Judge Mode scoping exists) and reseed.

    Invoices already at PayPal are left alone. They cannot collide with the new project's because
    invoice numbers are built from random ids.
    """
    seller = ensure_seller(db)
    commissions = db.scalars(
        select(Commission).where(
            Commission.visitor_id.is_(None)
            if visitor_id is None
            else Commission.visitor_id == visitor_id
        )
    ).all()
    for commission in commissions:
        db.delete(commission)
    db.flush()
    db.execute(delete(RateCardItem).where(RateCardItem.seller_id == seller.id))
    _write_rate_card(db, seller)
    seller.billing_disabled_code = None
    return seed_demo_project(db, visitor_id=visitor_id)
