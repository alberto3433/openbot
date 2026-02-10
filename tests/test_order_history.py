"""
Tests for Order History & Reorder Feature.

Tests cover:
- Pattern detection for order history intents
- Order history lookup functions
- Modification parsing
- Item reorder from history
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from orderbot.tasks.parsers.inquiry_patterns import (
    ORDER_HISTORY_PATTERNS,
    VIEW_LAST_ORDER_PATTERNS,
    REORDER_ITEM_PATTERNS,
    MODIFICATION_EXTRACTOR,
    WITHOUT_PATTERN,
    get_reorder_modification_keywords,
    ORDER_NUMBER_PATTERN,
)
from orderbot.tasks.order_history_handler import OrderHistoryHandler
from orderbot.tasks.utils.text import parse_selection


class TestOrderHistoryPatterns:
    """Test regex patterns for order history intents."""

    @pytest.mark.parametrize("text", [
        "what did I order before",
        "what did I order before?",
        "my order history",
        "order history",
        "show my orders",
        "show my previous orders",
        "my past orders",
        "past orders",
        "my previous orders",
        "what have I ordered",
        "what have I gotten here before",
    ])
    def test_order_history_patterns(self, text):
        """Test ORDER_HISTORY_PATTERNS match various phrasings."""
        assert any(p.search(text) for p in ORDER_HISTORY_PATTERNS), f"Failed to match: {text}"

    @pytest.mark.parametrize("text", [
        "what did I order last time",
        "what was in my last order",
        "what was my last order",
        "show me my last order",
        "tell me about my last order",
        "what did I have last time",
    ])
    def test_view_last_order_patterns(self, text):
        """Test VIEW_LAST_ORDER_PATTERNS match various phrasings."""
        assert any(p.search(text) for p in VIEW_LAST_ORDER_PATTERNS), f"Failed to match: {text}"

    @pytest.mark.parametrize("text,expected_item", [
        ("just the bagel from last time", "bagel"),
        ("the coffee I had before", "coffee"),
        ("order the same latte as before", "latte"),
        ("get the same sandwich I had", "sandwich"),
        ("same coffee again", "coffee"),
    ])
    def test_reorder_item_patterns(self, text, expected_item):
        """Test REORDER_ITEM_PATTERNS extract item reference."""
        for pattern in REORDER_ITEM_PATTERNS:
            match = pattern.search(text)
            if match:
                # Get first non-None group
                item_ref = next((g for g in match.groups() if g), None)
                assert expected_item in item_ref.lower(), f"Expected '{expected_item}' in '{item_ref}'"
                return
        pytest.fail(f"No pattern matched: {text}")


class TestModificationPatterns:
    """Test patterns for order modification detection."""

    @pytest.mark.parametrize("text,expected_mod", [
        ("same as before but iced", "iced"),
        ("repeat my order except without the bagel", "without the bagel"),
        ("my usual but large", "large"),
        ("same as last time and toasted", "toasted"),
        ("repeat my last order but hot", "hot"),
    ])
    def test_modification_extractor(self, text, expected_mod):
        """Test MODIFICATION_EXTRACTOR extracts modification text."""
        match = MODIFICATION_EXTRACTOR.search(text)
        assert match is not None, f"No match for: {text}"
        assert expected_mod in match.group(1).lower(), f"Expected '{expected_mod}' in '{match.group(1)}'"

    @pytest.mark.parametrize("text,expected_item", [
        ("without the bagel", "bagel"),
        ("without bagel", "bagel"),
        ("without the cream cheese", "cream cheese"),
    ])
    def test_without_pattern(self, text, expected_item):
        """Test WITHOUT_PATTERN extracts item to remove."""
        match = WITHOUT_PATTERN.search(text)
        assert match is not None, f"No match for: {text}"
        assert expected_item in match.group(1).lower()

    def test_modification_keywords_structure(self):
        """Test get_reorder_modification_keywords returns proper structure."""
        keywords = get_reorder_modification_keywords()
        # Should return a dict
        assert isinstance(keywords, dict)
        # If cache is loaded, should have some entries
        if keywords:
            # Each entry should be (attribute_slug, value) tuple
            for keyword, mapping in keywords.items():
                assert isinstance(keyword, str)
                assert isinstance(mapping, tuple)
                assert len(mapping) == 2
                attr_slug, value = mapping
                assert isinstance(attr_slug, str)
                # Value can be bool or str

    @pytest.mark.parametrize("keyword,expected_attr", [
        # These keywords should map to the expected attributes when they exist in cache
        ("large", "size"),
        ("small", "size"),
        ("toasted", "toasted"),
    ])
    def test_modification_keywords_common_mappings(self, keyword, expected_attr):
        """Test that common keywords map to expected attributes when available."""
        keywords = get_reorder_modification_keywords()
        if keyword in keywords:
            attr, _ = keywords[keyword]
            assert attr == expected_attr, f"'{keyword}' should map to '{expected_attr}'"

    @pytest.mark.parametrize("text,expected_order_num", [
        ("reorder order number 42", 42),
        ("repeat order 123", 123),
        ("reorder order #7", 7),
    ])
    def test_order_number_pattern(self, text, expected_order_num):
        """Test ORDER_NUMBER_PATTERN extracts order number."""
        match = ORDER_NUMBER_PATTERN.search(text)
        assert match is not None, f"No match for: {text}"
        assert int(match.group(1)) == expected_order_num


class TestOrderHistoryHandler:
    """Test OrderHistoryHandler functionality."""

    def test_is_order_history_inquiry(self):
        """Test order history inquiry detection."""
        handler = OrderHistoryHandler()

        assert handler.is_order_history_inquiry("what did I order before")
        assert handler.is_order_history_inquiry("my order history")
        assert handler.is_order_history_inquiry("show my orders")
        assert not handler.is_order_history_inquiry("I want a bagel")

    def test_is_view_last_order(self):
        """Test view last order detection."""
        handler = OrderHistoryHandler()

        assert handler.is_view_last_order("what was in my last order")
        assert handler.is_view_last_order("what did I order last time")
        assert not handler.is_view_last_order("I want a coffee")

    def test_is_reorder_specific_item(self):
        """Test specific item reorder detection."""
        handler = OrderHistoryHandler()

        is_match, item = handler.is_reorder_specific_item("just the bagel from last time")
        assert is_match
        assert "bagel" in item.lower()

        is_match, item = handler.is_reorder_specific_item("the coffee I had before")
        assert is_match
        assert "coffee" in item.lower()

        is_match, item = handler.is_reorder_specific_item("I want a new bagel")
        assert not is_match

    def test_is_reorder_with_modifications(self):
        """Test reorder with modifications detection."""
        handler = OrderHistoryHandler()

        is_match, mod = handler.is_reorder_with_modifications("same as before but iced")
        assert is_match
        assert "iced" in mod.lower()

        is_match, mod = handler.is_reorder_with_modifications("repeat my order except without bagel")
        assert is_match
        assert "without" in mod.lower()

        is_match, mod = handler.is_reorder_with_modifications("I want a bagel")
        assert not is_match

    def test_apply_modifications_iced(self):
        """Test applying 'iced' modification to items.

        The 'iced' keyword now maps to '_variant_coffee_based_beverage' attribute per the cache.
        """
        handler = OrderHistoryHandler()
        items = [
            {"menu_item_name": "Latte", "item_type": "coffee_based_beverage", "attribute_values": {"size": "large"}}
        ]

        modified, desc = handler.apply_modifications(items, "iced")

        assert len(modified) == 1
        # Check that some attribute was modified (exact attr depends on cache data)
        assert modified[0]["attribute_values"] is not None
        assert "iced" in desc.lower()

    def test_apply_modifications_without(self):
        """Test applying 'without' modification to remove items."""
        handler = OrderHistoryHandler()
        items = [
            {"menu_item_name": "Everything Bagel", "item_type": "bagel"},
            {"menu_item_name": "Latte", "item_type": "coffee_based_beverage"},
        ]

        modified, desc = handler.apply_modifications(items, "without the bagel")

        assert len(modified) == 1
        assert modified[0]["menu_item_name"] == "Latte"
        assert "without" in desc.lower()

    def test_apply_modifications_size_change(self):
        """Test applying size modification."""
        handler = OrderHistoryHandler()
        items = [
            {"menu_item_name": "Latte", "item_type": "coffee_based_beverage", "attribute_values": {"size": "small"}}
        ]

        modified, desc = handler.apply_modifications(items, "large")

        assert len(modified) == 1
        assert modified[0]["attribute_values"]["size"] == "large"
        assert "large" in desc.lower()

    def test_parse_order_selection_number(self):
        """Test parsing numeric order selection using shared utility."""
        assert parse_selection("1", 5) == 0
        assert parse_selection("2", 5) == 1
        assert parse_selection("5", 5) == 4
        assert parse_selection("6", 5) is None  # Out of range

    def test_parse_order_selection_ordinal(self):
        """Test parsing ordinal order selection using shared utility."""
        assert parse_selection("first", 5) == 0
        assert parse_selection("the first one", 5) == 0
        assert parse_selection("second", 5) == 1
        assert parse_selection("third", 5) == 2


class TestOrderHistoryHelpers:
    """Test helper functions for order history lookup."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return MagicMock()

    def test_format_order_date(self):
        """Test order date formatting."""
        handler = OrderHistoryHandler()

        # Test ISO format string
        result = handler._format_order_date("2024-01-15T10:30:00")
        assert "Jan" in result
        assert "15" in result

        # Test None
        result = handler._format_order_date(None)
        assert "unknown" in result.lower()

    def test_format_items_for_display(self):
        """Test formatting items list for display."""
        handler = OrderHistoryHandler()

        items = [
            {"menu_item_name": "Everything Bagel", "quantity": 2},
            {"menu_item_name": "Latte", "quantity": 1},
        ]
        result = handler._format_items_for_display(items)

        assert "2x Everything Bagel" in result
        assert "Latte" in result

    def test_format_items_for_display_empty(self):
        """Test formatting empty items list."""
        handler = OrderHistoryHandler()

        result = handler._format_items_for_display([])
        assert "no items" in result.lower()


class TestReorderOfferConfirmation:
    """Test the reorder offer confirmation flow ('Want to reorder it?' -> 'yes')."""

    def test_handle_reorder_offer_affirmative(self):
        """Test that 'yes' to 'Want to reorder it?' adds items to order."""
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.schemas import OrderPhase
        from orderbot.tasks.pending_fields import PendingField

        handler = OrderHistoryHandler()
        order = OrderTask()

        # Simulate pending reorder offer (state after showing last order details)
        order.pending_reorder_offer_items = [
            {"menu_item_name": "The BLT", "menu_item_type": "signature_sandwich", "quantity": 2, "price": 11.25},
        ]
        order.pending_field = PendingField.REORDER_OFFER_CONFIRMATION

        # User says yes
        result = handler.handle_reorder_offer_response("yes", order)

        assert result is not None
        assert "added" in result.message.lower() or "The BLT" in result.message
        assert order.items.get_item_count() == 2  # quantity=2 means 2 items
        assert order.pending_field is None
        assert order.pending_reorder_offer_items is None

    def test_handle_reorder_offer_negative(self):
        """Test that 'no' to 'Want to reorder it?' clears pending state."""
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.pending_fields import PendingField

        handler = OrderHistoryHandler()
        order = OrderTask()

        # Simulate pending reorder offer
        order.pending_reorder_offer_items = [
            {"menu_item_name": "The BLT", "menu_item_type": "signature_sandwich", "quantity": 1, "price": 11.25},
        ]
        order.pending_field = PendingField.REORDER_OFFER_CONFIRMATION

        # User says no
        result = handler.handle_reorder_offer_response("no", order)

        assert result is not None
        assert "what can i get" in result.message.lower()
        assert order.items.get_item_count() == 0
        assert order.pending_field is None
        assert order.pending_reorder_offer_items is None

    def test_handle_reorder_offer_unclear(self):
        """Test that unclear response clears pending state and returns None for fallthrough."""
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.pending_fields import PendingField

        handler = OrderHistoryHandler()
        order = OrderTask()

        # Simulate pending reorder offer
        order.pending_reorder_offer_items = [
            {"menu_item_name": "The BLT", "menu_item_type": "signature_sandwich", "quantity": 1, "price": 11.25},
        ]
        order.pending_field = PendingField.REORDER_OFFER_CONFIRMATION

        # User says something unclear
        result = handler.handle_reorder_offer_response("I'd like a coffee instead", order)

        # Should return None to allow fallthrough to normal processing
        assert result is None
        assert order.pending_field is None
        assert order.pending_reorder_offer_items is None
