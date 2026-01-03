"""
Tax calculation utilities.

This module provides centralized tax calculation functions to avoid
duplication across adapter.py and order_utils_handler.py.
"""

from dataclasses import dataclass
from typing import Any


def round_money(amount: float) -> float:
    """Round to 2 decimal places for currency."""
    return round(amount, 2)


@dataclass
class TaxBreakdown:
    """Tax breakdown with city and state components."""

    city_tax: float
    state_tax: float

    @property
    def total(self) -> float:
        """Total tax amount (city + state), rounded to 2 decimals."""
        return round_money(self.city_tax + self.state_tax)


def calculate_taxes(subtotal: float, store_info: dict[str, Any] | None) -> TaxBreakdown:
    """
    Calculate taxes for a given subtotal using store tax rates.

    Args:
        subtotal: Order subtotal before tax
        store_info: Store configuration with tax rates

    Returns:
        TaxBreakdown with city_tax and state_tax amounts
    """
    if not store_info:
        return TaxBreakdown(city_tax=0.0, state_tax=0.0)

    city_rate = store_info.get("city_tax_rate", 0.0) or 0.0
    state_rate = store_info.get("state_tax_rate", 0.0) or 0.0

    return TaxBreakdown(
        city_tax=round_money(subtotal * city_rate),
        state_tax=round_money(subtotal * state_rate),
    )


def calculate_order_total(
    subtotal: float,
    store_info: dict[str, Any] | None,
    is_delivery: bool = False,
) -> dict[str, float]:
    """
    Calculate full order total with taxes and delivery fee.

    Args:
        subtotal: Order subtotal before tax
        store_info: Store configuration with tax rates and delivery fee
        is_delivery: Whether this is a delivery order

    Returns:
        Dictionary with subtotal, city_tax, state_tax, tax, delivery_fee, and total
    """
    taxes = calculate_taxes(subtotal, store_info)

    delivery_fee = 0.0
    if is_delivery and store_info:
        delivery_fee = store_info.get("delivery_fee", 2.99) or 0.0

    return {
        "subtotal": round_money(subtotal),
        "city_tax": taxes.city_tax,
        "state_tax": taxes.state_tax,
        "tax": taxes.total,
        "delivery_fee": round_money(delivery_fee),
        "total": round_money(subtotal + taxes.total + delivery_fee),
    }
