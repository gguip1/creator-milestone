from typing import Any

from sqlalchemy.orm import Session

from app.models import ActivityLog, Commission
from app.models.enums import Actor


def log_activity(
    db: Session, commission: Commission, actor: Actor, action: str, **details: Any
) -> None:
    """Timeline entry. Details are shown to the seller; keep emails and secrets out of them."""
    db.add(
        ActivityLog(commission_id=commission.id, actor=actor, action=action, details_json=details)
    )
