"""Turn PayPal failures into plain-language API errors. Only sanitized details leave this module."""

import httpx

from app.errors import AppError
from app.services.paypal_client import PayPalError

DUPLICATE_INVOICE_NUMBER = "DUPLICATE_INVOICE_NUMBER"
KOREAN_RESTRICTED = "KOREAN_MERCHANT_KOREAN_PAYER_RESTRICTED"
CANNOT_CANCEL_DRAFT = "CANNOT_CANCEL_DRAFT_INVOICE"
NOT_AUTHORIZED = "PAYPAL_NOT_AUTHORIZED"

# Everything the PayPal client can raise for a failed call.
PAYPAL_FAILURES = (PayPalError, httpx.TransportError)


def has_issue(error: PayPalError, issue: str) -> bool:
    """PayPal puts the specific code in details[].issue; the top-level name is often generic."""
    return error.name == issue or any(detail.get("issue") == issue for detail in error.details)


def map_paypal_error(error: Exception) -> AppError:
    if isinstance(error, httpx.TimeoutException):
        return AppError(
            504, "PAYPAL_TIMEOUT", "PayPal did not answer in time. Nothing is lost; try again."
        )
    if isinstance(error, httpx.TransportError):
        return AppError(
            502, "PAYPAL_UNREACHABLE", "Could not reach PayPal. Nothing is lost; try again."
        )
    if not isinstance(error, PayPalError):
        raise TypeError(f"Not a PayPal failure: {type(error).__name__}")

    details = {"paypal_status": error.status_code, "debug_id": error.debug_id}
    if has_issue(error, KOREAN_RESTRICTED):
        return AppError(
            422,
            KOREAN_RESTRICTED,
            "PayPal does not let a Korean seller account bill a Korean PayPal account. "
            "Your draft invoice is kept. Ask the client for a PayPal email registered outside "
            "Korea.",
            details,
        )
    if has_issue(error, CANNOT_CANCEL_DRAFT):
        return AppError(
            409,
            CANNOT_CANCEL_DRAFT,
            "PayPal can only cancel an invoice that has been sent. This one is still a draft.",
            details,
        )
    if error.status_code == 403:
        return AppError(
            403,
            NOT_AUTHORIZED,
            "PayPal refused this action, so billing is paused. Check that Invoicing is enabled "
            "on the PayPal app, then retry.",
            details,
        )
    if error.status_code == 401:
        return AppError(
            502,
            "PAYPAL_AUTH_FAILED",
            "PayPal rejected our credentials. Check the sandbox app settings.",
            details,
        )
    if error.status_code == 422:
        return AppError(
            422,
            "PAYPAL_VALIDATION_ERROR",
            "PayPal rejected this invoice. Review the details and retry.",
            {**details, "issues": error.details},
        )
    return AppError(502, "PAYPAL_ERROR", "PayPal returned an error. Try again.", details)
