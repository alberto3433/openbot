"""Tests for the Toast GUID resolver."""

from unittest.mock import MagicMock, patch

import pytest

from orderbot.toast.guid_resolver import GuidResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mapping(entity_type, local_id, toast_guid, store_id=None):
    """Create a mock ToastGuidMap row."""
    m = MagicMock()
    m.entity_type = entity_type
    m.local_id = local_id
    m.toast_guid = toast_guid
    m.store_id = store_id
    return m


class TestGuidResolver:
    """Tests for GuidResolver lookups."""

    def test_mapped_item_resolves(self):
        """A mapped menu item returns its Toast GUID."""
        mapping = _make_mapping("menu_item", 10, "toast-guid-abc")

        db = MagicMock()
        # First query (store-specific) returns None, second (global) returns mapping
        db.query.return_value.filter.return_value.first.side_effect = [None, mapping]

        resolver = GuidResolver(db, store_id="store_1")
        result = resolver.resolve_menu_item(10)

        assert result == "toast-guid-abc"

    def test_unmapped_item_returns_none(self):
        """An unmapped menu item returns None."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        resolver = GuidResolver(db)
        result = resolver.resolve_menu_item(999)

        assert result is None

    def test_cache_prevents_duplicate_queries(self):
        """Second lookup for same entity uses cache, no extra DB query."""
        mapping = _make_mapping("menu_item", 10, "toast-guid-abc")

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mapping

        resolver = GuidResolver(db)
        result1 = resolver.resolve_menu_item(10)
        result2 = resolver.resolve_menu_item(10)

        assert result1 == result2 == "toast-guid-abc"
        # Only one DB query chain should have been initiated
        assert db.query.call_count == 1

    def test_store_specific_overrides_global(self):
        """Store-specific mapping takes priority over global."""
        store_mapping = _make_mapping("menu_item", 10, "toast-store-guid", "store_1")

        db = MagicMock()
        # Store-specific query returns a mapping on the first call
        db.query.return_value.filter.return_value.first.return_value = store_mapping

        resolver = GuidResolver(db, store_id="store_1")
        result = resolver.resolve_menu_item(10)

        assert result == "toast-store-guid"

    def test_ingredient_resolution(self):
        """Ingredient entities resolve correctly."""
        mapping = _make_mapping("ingredient", 50, "toast-ingredient-guid")

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mapping

        resolver = GuidResolver(db)
        result = resolver.resolve_ingredient(50)

        assert result == "toast-ingredient-guid"

    def test_dining_option_resolution(self):
        """Dining option entities resolve correctly."""
        mapping = _make_mapping("dining_option", 1, "toast-pickup-guid")

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mapping

        resolver = GuidResolver(db)
        result = resolver.resolve_dining_option(1)

        assert result == "toast-pickup-guid"


class TestGetUnmappedItems:
    """Tests for get_unmapped_items diagnostic method."""

    def test_identifies_unmapped_items(self):
        """Items without GUID mappings are reported."""
        db = MagicMock()
        # All resolve calls return None (nothing mapped)
        db.query.return_value.filter.return_value.first.return_value = None

        resolver = GuidResolver(db)
        order_state = {
            "items": [
                {"menu_item_id": 10, "menu_item_name": "Plain Bagel"},
                {"menu_item_id": 20, "display_name": "Iced Latte"},
            ]
        }

        unmapped = resolver.get_unmapped_items(order_state)
        assert len(unmapped) == 2
        assert "Plain Bagel" in unmapped
        assert "Iced Latte" in unmapped

    def test_mapped_items_not_reported(self):
        """Mapped items are not included in unmapped list."""
        mapping = _make_mapping("menu_item", 10, "toast-guid")

        db = MagicMock()
        # First item mapped, second not
        db.query.return_value.filter.return_value.first.side_effect = [mapping, None]

        resolver = GuidResolver(db)
        order_state = {
            "items": [
                {"menu_item_id": 10, "menu_item_name": "Plain Bagel"},
                {"menu_item_id": 20, "menu_item_name": "Coffee"},
            ]
        }

        unmapped = resolver.get_unmapped_items(order_state)
        assert len(unmapped) == 1
        assert "Coffee" in unmapped
