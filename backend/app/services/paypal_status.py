"""Mapping of raw PayPal invoice statuses to UI meaning (PRD §11.3)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StatusInfo:
    label: str
    settles_milestone: bool
    needs_attention: bool = False


STATUS_MAP: dict[str, StatusInfo] = {
    "DRAFT": StatusInfo("Draft (not sent)", False),
    "SCHEDULED": StatusInfo("Scheduled", False),
    "SENT": StatusInfo("Sent — awaiting payment", False),
    "UNPAID": StatusInfo("Sent — awaiting payment", False),
    "PAYMENT_PENDING": StatusInfo("Payment pending", False),
    # Partial payment is disabled on our invoices, so this is unexpected.
    "PARTIALLY_PAID": StatusInfo("Partially paid", False, needs_attention=True),
    "PAID": StatusInfo("Paid via PayPal", True),
    # Recorded outside PayPal; never treated as a PayPal payment without seller confirmation.
    "MARKED_AS_PAID": StatusInfo("Marked paid (outside PayPal)", False, needs_attention=True),
    "CANCELLED": StatusInfo("Cancelled", False),
    "REFUNDED": StatusInfo("Refunded", False, needs_attention=True),
    "PARTIALLY_REFUNDED": StatusInfo("Partially refunded", False, needs_attention=True),
    "MARKED_AS_REFUNDED": StatusInfo(
        "Marked refunded (outside PayPal)", False, needs_attention=True
    ),
}


def describe_status(raw_status: str | None) -> StatusInfo:
    if raw_status in STATUS_MAP:
        return STATUS_MAP[raw_status]
    return StatusInfo(f"Unknown status ({raw_status})", False, needs_attention=True)
