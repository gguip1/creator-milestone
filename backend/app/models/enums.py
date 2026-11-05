from enum import StrEnum


class CommissionStatus(StrEnum):
    DRAFT = "DRAFT"
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    AGREED = "AGREED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MilestoneState(StrEnum):
    LOCKED = "LOCKED"
    AWAITING_DELIVERY = "AWAITING_DELIVERY"
    DELIVERED = "DELIVERED"
    APPROVED = "APPROVED"
    READY_TO_BILL = "READY_TO_BILL"
    BILLED = "BILLED"
    SETTLED = "SETTLED"


class MilestoneKind(StrEnum):
    PLAN = "plan"
    CHANGE_ORDER = "change_order"


class BillingTrigger(StrEnum):
    ON_AGREEMENT = "ON_AGREEMENT"
    ON_DELIVERY_APPROVED = "ON_DELIVERY_APPROVED"
    ON_CHANGE_ORDER_APPROVED = "ON_CHANGE_ORDER_APPROVED"


class ChangeOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    SELLER_APPROVED = "SELLER_APPROVED"
    CLIENT_APPROVED = "CLIENT_APPROVED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"


class ProposalKind(StrEnum):
    BILL_MILESTONE = "BILL_MILESTONE"
    SEND_INVOICE = "SEND_INVOICE"
    SEND_REMINDER = "SEND_REMINDER"
    CHANGE_ORDER = "CHANGE_ORDER"
    CANCEL_INVOICE = "CANCEL_INVOICE"


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    DISMISSED = "DISMISSED"
    STALE = "STALE"


class MessageKind(StrEnum):
    INTAKE = "intake"
    FOLLOW_UP = "follow_up"


class Actor(StrEnum):
    AGENT = "agent"
    SELLER = "seller"
    CLIENT = "client"
    PAYPAL = "paypal"
    SYSTEM = "system"
