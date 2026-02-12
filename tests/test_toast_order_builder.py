"""Tests for Toast order payload builder."""

from unittest.mock import MagicMock, patch

import pytest

from orderbot.toast.order_builder import (
    build_toast_order,
    _build_customer,
    _build_dining_option,
    _build_selections,
)
from orderbot.toast.guid_resolver import GuidResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_resolver(menu_map=None, ingredient_map=None, dining_map=None):
    """Create a GuidResolver mock with predefined mappings."""
    resolver = MagicMock(spec=GuidResolver)

    menu_map = menu_map or {}
    ingredient_map = ingredient_map or {}
    dining_map = dining_map or {}

    resolver.resolve_menu_item.side_effect = lambda mid: menu_map.get(mid)
    resolver.resolve_ingredient.side_effect = lambda iid: ingredient_map.get(iid)
    resolver.resolve_dining_option.side_effect = lambda did: dining_map.get(did)
    resolver.get_unmapped_items.return_value = []

    return resolver


# ---------------------------------------------------------------------------
# Single item order
# ---------------------------------------------------------------------------

class TestSingleItemOrder:
    """Tests for single-item order payload."""

    def test_basic_structure(self):
        """A single mapped item produces correct Toast JSON structure."""
        db = MagicMock()
        resolver = _mock_resolver(menu_map={10: "toast-guid-bagel"})

        order_state = {
            "db_order_id": 1,
            "items": [
                {
                    "menu_item_id": 10,
                    "menu_item_name": "Plain Bagel",
                    "quantity": 1,
                    "item_config": {},
                }
            ],
            "customer": {"name": "John Doe", "phone": "+15551234567"},
            "order_type": "pickup",
        }

        with patch("orderbot.toast.order_builder.GuidResolver", return_value=resolver):
            payload = build_toast_order(db, order_state)

        assert payload is not None
        assert payload["entityType"] == "Order"
        assert len(payload["checks"]) == 1

        check = payload["checks"][0]
        assert check["entityType"] == "Check"
        assert len(check["selections"]) == 1

        sel = check["selections"][0]
        assert sel["item"]["guid"] == "toast-guid-bagel"
        assert sel["quantity"] == 1


# ---------------------------------------------------------------------------
# Multi-item with modifiers
# ---------------------------------------------------------------------------

class TestMultiItemWithModifiers:
    """Tests for multi-item orders with modifier selections."""

    def test_two_items_with_modifiers(self):
        """Two items, one with modifiers, produce nested selections."""
        db = MagicMock()
        resolver = _mock_resolver(
            menu_map={10: "toast-bagel", 20: "toast-coffee"},
            ingredient_map={100: "toast-cream-cheese"},
        )

        order_state = {
            "db_order_id": 2,
            "items": [
                {
                    "menu_item_id": 10,
                    "menu_item_name": "Plain Bagel",
                    "quantity": 1,
                    "item_config": {
                        "modifiers": [
                            {"ingredient_id": 100, "slug": "cream_cheese", "quantity": 1}
                        ]
                    },
                },
                {
                    "menu_item_id": 20,
                    "menu_item_name": "Iced Latte",
                    "quantity": 2,
                    "item_config": {},
                },
            ],
            "customer": {"name": "Jane"},
            "order_type": "pickup",
        }

        with patch("orderbot.toast.order_builder.GuidResolver", return_value=resolver):
            payload = build_toast_order(db, order_state)

        assert payload is not None
        selections = payload["checks"][0]["selections"]
        assert len(selections) == 2

        # First item has modifier
        bagel_sel = selections[0]
        assert len(bagel_sel["modifiers"]) == 1
        assert bagel_sel["modifiers"][0]["item"]["guid"] == "toast-cream-cheese"

        # Second item has no modifiers
        coffee_sel = selections[1]
        assert coffee_sel["quantity"] == 2
        assert len(coffee_sel["modifiers"]) == 0


# ---------------------------------------------------------------------------
# Dining option mapping
# ---------------------------------------------------------------------------

class TestDiningOption:
    """Tests for pickup/delivery dining option mapping."""

    def test_pickup_maps_to_id_1(self):
        resolver = _mock_resolver(dining_map={1: "toast-pickup-guid"})
        order_state = {"order_type": "pickup"}

        result = _build_dining_option(order_state, resolver)
        assert result == {"guid": "toast-pickup-guid"}

    def test_delivery_maps_to_id_2(self):
        resolver = _mock_resolver(dining_map={2: "toast-delivery-guid"})
        order_state = {"order_type": "delivery"}

        result = _build_dining_option(order_state, resolver)
        assert result == {"guid": "toast-delivery-guid"}

    def test_unmapped_returns_none(self):
        resolver = _mock_resolver()
        order_state = {"order_type": "pickup"}

        result = _build_dining_option(order_state, resolver)
        assert result is None


# ---------------------------------------------------------------------------
# Unmapped items (partial order)
# ---------------------------------------------------------------------------

class TestUnmappedItems:
    """Tests for handling items without Toast GUIDs."""

    def test_unmapped_items_skipped(self):
        """Items without Toast GUIDs are skipped; mapped ones still included."""
        db = MagicMock()
        # Only item 10 is mapped; item 20 is not
        resolver = _mock_resolver(menu_map={10: "toast-bagel"})
        resolver.get_unmapped_items.return_value = ["Iced Latte"]

        order_state = {
            "db_order_id": 3,
            "items": [
                {"menu_item_id": 10, "menu_item_name": "Plain Bagel", "quantity": 1, "item_config": {}},
                {"menu_item_id": 20, "menu_item_name": "Iced Latte", "quantity": 1, "item_config": {}},
            ],
            "customer": {"name": "Bob"},
            "order_type": "pickup",
        }

        with patch("orderbot.toast.order_builder.GuidResolver", return_value=resolver):
            payload = build_toast_order(db, order_state)

        assert payload is not None
        assert len(payload["checks"][0]["selections"]) == 1

    def test_all_unmapped_returns_none(self):
        """When no items can be mapped, build_toast_order returns None."""
        db = MagicMock()
        resolver = _mock_resolver()  # Nothing mapped
        resolver.get_unmapped_items.return_value = ["Bagel", "Coffee"]

        order_state = {
            "db_order_id": 4,
            "items": [
                {"menu_item_id": 10, "menu_item_name": "Bagel", "quantity": 1, "item_config": {}},
            ],
            "customer": {"name": "Alice"},
            "order_type": "pickup",
        }

        with patch("orderbot.toast.order_builder.GuidResolver", return_value=resolver):
            payload = build_toast_order(db, order_state)

        assert payload is None


# ---------------------------------------------------------------------------
# Customer info
# ---------------------------------------------------------------------------

class TestCustomerInfo:
    """Tests for customer info mapping."""

    def test_name_split(self):
        """Full name is split into firstName and lastName."""
        result = _build_customer({"customer": {"name": "Jane Smith", "phone": "+15551234567"}})
        assert result["firstName"] == "Jane"
        assert result["lastName"] == "Smith"

    def test_single_name(self):
        """Single name goes to firstName, no lastName included."""
        result = _build_customer({"customer": {"name": "Madonna"}})
        assert result["firstName"] == "Madonna"
        assert "lastName" not in result

    def test_with_email(self):
        """Email is included when present."""
        result = _build_customer({
            "customer": {"name": "Test", "email": "test@example.com"}
        })
        assert result["email"] == "test@example.com"

    def test_no_customer_returns_none(self):
        """No customer block returns None."""
        result = _build_customer({})
        assert result is None

    def test_empty_customer_returns_none(self):
        """Empty customer dict returns None."""
        result = _build_customer({"customer": {}})
        assert result is None
