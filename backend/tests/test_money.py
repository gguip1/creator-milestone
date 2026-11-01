import pytest

from app.services.money import (
    MoneyError,
    from_paypal_value,
    split_by_basis_points,
    to_paypal_value,
)


def test_default_split_of_300_dollars():
    assert split_by_basis_points(30_000, [3000, 3000, 4000]) == [9000, 9000, 12_000]


def test_remainder_goes_to_last_share():
    assert split_by_basis_points(10_001, [3000, 3000, 4000]) == [3000, 3000, 4001]


@pytest.mark.parametrize("total", [1_00, 3_33, 10_001, 99_999, 123_457])
def test_split_always_sums_to_total(total):
    assert sum(split_by_basis_points(total, [3333, 3333, 3334])) == total


@pytest.mark.parametrize(
    "total,shares",
    [
        (0, [10_000]),
        (100, []),
        (100, [5000, 4000]),
        (100, [10_000, 0]),
        (2, [3000, 3000, 4000]),
    ],
)
def test_invalid_splits_are_rejected(total, shares):
    with pytest.raises(MoneyError):
        split_by_basis_points(total, shares)


@pytest.mark.parametrize(
    "minor,expected", [(9000, "90.00"), (4001, "40.01"), (5, "0.05"), (0, "0.00")]
)
def test_to_paypal_value(minor, expected):
    assert to_paypal_value(minor, "USD") == expected


@pytest.mark.parametrize(
    "value,expected", [("90.00", 9000), ("40.01", 4001), ("7", 700), ("0.5", 50)]
)
def test_from_paypal_value(value, expected):
    assert from_paypal_value(value, "USD") == expected


@pytest.mark.parametrize("value", ["-1.00", "1.001", "abc", "1e3", ""])
def test_from_paypal_value_rejects_bad_input(value):
    with pytest.raises(MoneyError):
        from_paypal_value(value, "USD")


def test_unknown_currency_is_rejected():
    with pytest.raises(MoneyError):
        to_paypal_value(100, "JPY")
