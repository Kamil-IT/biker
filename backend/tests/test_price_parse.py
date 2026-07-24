"""Unit tests for app.price_parse.parse_price (no server, no network).

Run: python -m pytest -m "not llm" -q   (pytest.ini collects tests/ by default)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.price_parse import parse_price  # noqa: E402


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Every literal observed in cache.db (TODO-009 ground-truth block).
        ("2799 zł", 2799.0),
        ("1199.99 zł", 1199.99),
        ("1407,12 zł", 1407.12),
        ("17 386,85 zł", 17386.85),
        ("11 000 zł", 11000.0),
        ("939,99 zł", 939.99),
        # Non-numeric sentinels.
        ("Price on request", None),
        ("Not listed", None),
        ("Not specified", None),
        ("", None),
    ],
)
def test_ground_truth_literals(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Currency tokens and casing.
        ("2799 PLN", 2799.0),
        ("2799 pln", 2799.0),
        ("2799 zl", 2799.0),
        ("2799ZŁ", 2799.0),
        # NBSP and narrow NBSP as thousands separators.
        ("17 386,85 zł", 17386.85),
        ("17 386,85 zł", 17386.85),
        # Lone separator with 3 trailing digits groups thousands.
        ("11.000 zł", 11000.0),
        ("11,000 zł", 11000.0),
        # Both separators present — the last one is the decimal point.
        ("1.234,56 zł", 1234.56),
        ("1,234.56 zł", 1234.56),
        ("17 386.85 zł", 17386.85),
        # Bare numbers.
        ("2799", 2799.0),
        ("0", 0.0),
    ],
)
def test_separator_and_currency_rules(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Regression: a 1-digit tail used to be read as thousands grouping, so
        # '1,5' parsed as 15.0 — a silent 10x error straight past price_max.
        ("1,5", 1.5),
        ("1.5", 1.5),
        ("2,5 zł", 2.5),
        # …without turning real thousands grouping into a decimal.
        ("11.000", 11000.0),
        ("1,234", 1234.0),
        # …and leaving the common 2-digit decimal untouched.
        ("1249,00", 1249.0),
        ("1199.99", 1199.99),
    ],
)
def test_lone_separator_digit_tail(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "zł", "-", ".", ",", "n/a", "—"])
def test_no_digits_is_none(raw):
    assert parse_price(raw) is None


@pytest.mark.parametrize("raw", [None, 123, [], {"price": "1"}, object()])
def test_never_raises_on_junk_input(raw):
    # Cache rows are model output — the parser must degrade to None, not raise.
    assert parse_price(raw) is None
