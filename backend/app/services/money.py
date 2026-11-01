"""Integer money helpers. Amounts are always minor units (cents); never floats."""

from collections.abc import Sequence

BASIS_POINTS_TOTAL = 10_000

# Minor-unit exponent per supported currency. Extend only with a verified ISO 4217 scale.
CURRENCY_EXPONENTS = {"USD": 2}


class MoneyError(ValueError):
    pass


def currency_exponent(currency_code: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency_code]
    except KeyError as exc:
        raise MoneyError(f"Unsupported currency: {currency_code}") from exc


def split_by_basis_points(total_minor_units: int, basis_points: Sequence[int]) -> list[int]:
    """Split a total by basis points; the last part absorbs the rounding remainder."""
    if total_minor_units < 1:
        raise MoneyError("Total must be at least one minor unit")
    if not basis_points:
        raise MoneyError("At least one share is required")
    if any(bp <= 0 for bp in basis_points):
        raise MoneyError("Each share must be positive")
    if sum(basis_points) != BASIS_POINTS_TOTAL:
        raise MoneyError(f"Shares must sum to {BASIS_POINTS_TOTAL} basis points")

    parts = [total_minor_units * bp // BASIS_POINTS_TOTAL for bp in basis_points[:-1]]
    parts.append(total_minor_units - sum(parts))
    if any(part < 1 for part in parts):
        raise MoneyError("Every share must be at least one minor unit")
    return parts


def to_paypal_value(amount_minor_units: int, currency_code: str) -> str:
    """Format minor units as the decimal string PayPal expects, e.g. 9000 -> "90.00"."""
    if amount_minor_units < 0:
        raise MoneyError("Amount must not be negative")
    exponent = currency_exponent(currency_code)
    if exponent == 0:
        return str(amount_minor_units)
    major, minor = divmod(amount_minor_units, 10**exponent)
    return f"{major}.{minor:0{exponent}d}"


def from_paypal_value(value: str, currency_code: str) -> int:
    """Parse a PayPal decimal string into minor units without going through float."""
    exponent = currency_exponent(currency_code)
    whole, _, fraction = value.strip().partition(".")
    if not whole.isdigit() or (fraction and not fraction.isdigit()) or len(fraction) > exponent:
        raise MoneyError(f"Invalid amount for {currency_code}: {value!r}")
    return int(whole) * 10**exponent + int(fraction.ljust(exponent, "0") or 0)
