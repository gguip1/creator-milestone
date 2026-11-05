import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    # Random ids: invoice numbers are built from them, and a recycled autoincrement id would
    # collide with an invoice from an earlier run in the same PayPal sandbox account.
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator):
    """Stores UTC and always returns aware datetimes (SQLite drops the offset)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass
