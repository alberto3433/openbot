"""
Tests for the UnrecognizedItemHandler.

Tests the 4-level fallback chain for handling unrecognized menu items:
1. Curated suggestions
2. Fuzzy matching
3. LLM category inference
4. Generic fallback
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from orderbot.tasks.unrecognized_item_handler import UnrecognizedItemHandler
from orderbot.tasks.menu_lookup import MenuLookup
from orderbot.tasks.models import OrderTask, ItemsTask


class TestUnrecognizedItemHandler:
    """Tests for UnrecognizedItemHandler fallback chain."""

    @pytest.fixture
    def mock_menu_lookup(self):
        """Create a mock MenuLookup."""
        lookup = MagicMock(spec=MenuLookup)
        lookup.get_suggestions_for_item_type.return_value = "latkes, fruit cup, or hash browns"
        return lookup

    @pytest.fixture
    def handler(self, mock_menu_lookup):
        """Create handler with mocked dependencies."""
        return UnrecognizedItemHandler(
            menu_lookup=mock_menu_lookup,
            db_session=None,  # No DB for unit tests
        )

    @pytest.fixture
    def empty_order(self):
        """Create an empty order for testing."""
        return OrderTask()

    @pytest.fixture
    def order_with_items(self):
        """Create an order with some items."""
        order = OrderTask()
        # Add some mock items
        order.items = MagicMock()
        order.items.items = [MagicMock(), MagicMock()]  # 2 items
        return order


class TestFuzzyMatching(TestUnrecognizedItemHandler):
    """Tests for fuzzy matching fallback."""

    def test_fuzzy_matching_finds_similar_items(self, handler, empty_order):
        """Test that fuzzy matching finds similar menu items."""
        # Mock rapidfuzz to be available
        handler._rapidfuzz_available = True

        with patch('orderbot.tasks.unrecognized_item_handler.menu_cache') as mock_cache:
            mock_cache.get_all_menu_item_names.return_value = [
                "Blueberry Muffin",
                "Chocolate Chip Muffin",
                "Plain Bagel",
            ]

            # Mock rapidfuzz.process.extract
            with patch('orderbot.tasks.unrecognized_item_handler.UnrecognizedItemHandler._get_fuzzy_matches') as mock_fuzzy:
                mock_fuzzy.return_value = ["Blueberry Muffin", "Chocolate Chip Muffin"]

                message, category = handler.get_not_found_response(
                    "muffin blueberry", order=empty_order
                )

                assert "Did you mean" in message
                assert "Blueberry Muffin" in message or "muffin" in message.lower()
                assert category is None

    def test_fuzzy_matching_disabled_when_rapidfuzz_unavailable(self, handler, empty_order):
        """Test that fuzzy matching gracefully handles missing rapidfuzz."""
        handler._rapidfuzz_available = False

        matches = handler._get_fuzzy_matches("muffin blueberry")
        assert matches == []


class TestLLMCategoryInference(TestUnrecognizedItemHandler):
    """Tests for LLM-based category inference."""

    def test_llm_inference_suggests_category(self, handler, empty_order, mock_menu_lookup):
        """Test that LLM inference suggests appropriate category."""
        handler._rapidfuzz_available = False  # Skip fuzzy

        with patch('orderbot.tasks.unrecognized_item_handler.menu_cache') as mock_cache:
            mock_cache.get_all_menu_item_names.return_value = []
            mock_cache.get_categories_for_inference.return_value = [
                {"slug": "pastry", "display_name": "Pastries"},
                {"slug": "beverage", "display_name": "Beverages"},
            ]
            mock_cache.get_category_keyword_mapping.return_value = {
                "display_name_plural": "pastries"
            }
            mock_cache.get_available_menu_categories.return_value = {}

            with patch.object(handler, '_infer_category_with_llm') as mock_llm:
                mock_llm.return_value = "pastry"

                message, category = handler.get_not_found_response(
                    "croissant", order=empty_order
                )

                mock_llm.assert_called_once_with("croissant")
                assert "don't have croissant" in message.lower() or "we don't have" in message.lower()

    def test_llm_inference_returns_none_gracefully(self, handler, empty_order):
        """Test that LLM inference gracefully handles failure."""
        handler._rapidfuzz_available = False

        with patch('orderbot.tasks.unrecognized_item_handler.menu_cache') as mock_cache:
            mock_cache.get_all_menu_item_names.return_value = []
            mock_cache.get_categories_for_inference.return_value = []
            mock_cache.get_available_menu_categories.return_value = {
                "drink": "Drinks",
                "food": "Food",
            }

            with patch.object(handler, '_infer_category_with_llm') as mock_llm:
                mock_llm.return_value = None  # LLM fails

                message, category = handler.get_not_found_response(
                    "xyzabc123", order=empty_order
                )

                # Should fall through to generic
                assert "we don't have" in message.lower()


class TestGenericFallback(TestUnrecognizedItemHandler):
    """Tests for generic fallback when all else fails."""

    def test_generic_fallback_shows_categories(self, handler, empty_order):
        """Test that generic fallback shows available categories."""
        handler._rapidfuzz_available = False

        with patch('orderbot.tasks.unrecognized_item_handler.menu_cache') as mock_cache:
            mock_cache.get_all_menu_item_names.return_value = []
            mock_cache.get_categories_for_inference.return_value = []
            mock_cache.get_available_menu_categories.return_value = {
                "drink": "Drinks",
                "food": "Food",
                "pastry": "Pastries",
            }

            with patch.object(handler, '_infer_category_with_llm') as mock_llm:
                mock_llm.return_value = None

                message, category = handler.get_not_found_response(
                    "xyzabc123", order=empty_order
                )

                assert "we don't have" in message.lower()
                assert "Drinks" in message or "Food" in message or "Pastries" in message
                assert category is None

    def test_generic_fallback_with_no_categories(self, handler, empty_order):
        """Test generic fallback when no categories are available."""
        handler._rapidfuzz_available = False

        with patch('orderbot.tasks.unrecognized_item_handler.menu_cache') as mock_cache:
            mock_cache.get_all_menu_item_names.return_value = []
            mock_cache.get_categories_for_inference.return_value = []
            mock_cache.get_available_menu_categories.return_value = {}

            with patch.object(handler, '_infer_category_with_llm') as mock_llm:
                mock_llm.return_value = None

                message, category = handler.get_not_found_response(
                    "unknown item", order=empty_order
                )

                assert "we don't have" in message.lower()
                assert "something else" in message.lower()


class TestOrderStateAwareness(TestUnrecognizedItemHandler):
    """Tests for order-state-aware responses."""

    def test_empty_cart_followup(self, handler):
        """Test follow-up message for empty cart."""
        followup = handler._get_order_aware_followup(order_item_count=0)
        assert "help you find" in followup.lower() or "any of those" in followup.lower()

    def test_few_items_followup(self, handler):
        """Test follow-up message for cart with few items."""
        followup = handler._get_order_aware_followup(order_item_count=2)
        assert "something else" in followup.lower() or "any of those" in followup.lower()

    def test_many_items_followup(self, handler):
        """Test follow-up message for cart with many items."""
        followup = handler._get_order_aware_followup(order_item_count=5)
        assert "check out" in followup.lower() or "add one" in followup.lower()


class TestCuratedSuggestions(TestUnrecognizedItemHandler):
    """Tests for curated suggestion lookup."""

    def test_curated_exact_match(self, handler, empty_order, mock_menu_lookup):
        """Test that curated exact matches are found."""
        # Create a mock session with query result
        mock_session = MagicMock()
        mock_suggestion = MagicMock()
        # Mock the relationships (new FK-based structure)
        mock_item_type = MagicMock()
        mock_item_type.slug = "side"
        mock_suggestion.suggested_item_type = mock_item_type
        mock_suggestion.suggested_menu_items = []  # Empty relationship list
        mock_suggestion.hit_count = 0

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_suggestion
        mock_session.query.return_value = mock_query

        handler._db_session = mock_session

        result = handler._check_curated_suggestions("home fries")

        assert result is not None
        assert result["category_slug"] == "side"

    def test_curated_no_match(self, handler):
        """Test that unmatched items return None."""
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_query.filter.return_value.all.return_value = []
        mock_session.query.return_value = mock_query

        handler._db_session = mock_session

        result = handler._check_curated_suggestions("completely unknown item")

        assert result is None


class TestBuildResponses(TestUnrecognizedItemHandler):
    """Tests for response building methods."""

    def test_build_curated_response_with_menu_items(self, handler, mock_menu_lookup):
        """Test that specific menu items are suggested."""
        curated = {
            "category_slug": None,
            "menu_items": ["Blueberry Muffin", "Chocolate Chip Muffin"],
        }

        message, category = handler._build_curated_response(
            "scone", curated, order_item_count=0
        )

        assert "don't have scone" in message.lower()
        assert "Blueberry Muffin" in message or "Chocolate Chip Muffin" in message

    def test_build_curated_response_with_category(self, handler, mock_menu_lookup):
        """Test that category suggestions work."""
        curated = {
            "category_slug": "side",
            "menu_items": None,
        }

        message, category = handler._build_curated_response(
            "hash browns", curated, order_item_count=0
        )

        # Should have gotten suggestions from menu_lookup
        mock_menu_lookup.get_suggestions_for_item_type.assert_called_once_with("side", limit=4)
        assert "don't have hash browns" in message.lower()

    def test_build_fuzzy_response(self, handler):
        """Test fuzzy match response formatting."""
        fuzzy_matches = ["Iced Coffee", "Iced Latte", "Iced Cappuccino"]

        message = handler._build_fuzzy_response(
            "ice coffee", fuzzy_matches, order_item_count=0
        )

        assert "don't have ice coffee" in message.lower()
        assert "did you mean" in message.lower()
        assert "Iced Coffee" in message or "Iced Latte" in message


class TestLLMCategoryInferenceModule:
    """Tests for the llm_category_inference module."""

    def test_infer_item_category_no_api_key(self):
        """Test that inference skips gracefully without API key."""
        from orderbot.tasks.parsers.llm_category_inference import infer_item_category

        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            result = infer_item_category(
                "croissant",
                [{"slug": "pastry", "display_name": "Pastries"}]
            )
            assert result is None

    def test_infer_item_category_empty_input(self):
        """Test that empty input returns None."""
        from orderbot.tasks.parsers.llm_category_inference import infer_item_category

        result = infer_item_category("", [{"slug": "pastry", "display_name": "Pastries"}])
        assert result is None

    def test_infer_item_category_empty_categories(self):
        """Test that empty categories returns None."""
        from orderbot.tasks.parsers.llm_category_inference import infer_item_category

        result = infer_item_category("croissant", [])
        assert result is None

    def test_infer_item_category_valid_response(self):
        """Test that valid LLM response is returned."""
        from orderbot.tasks.parsers.llm_category_inference import infer_item_category

        # Mock the OpenAI client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "pastry"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('openai.OpenAI', return_value=mock_client):
                result = infer_item_category(
                    "croissant",
                    [
                        {"slug": "pastry", "display_name": "Pastries"},
                        {"slug": "beverage", "display_name": "Beverages"},
                    ]
                )

                assert result == "pastry"

    def test_infer_item_category_invalid_response(self):
        """Test that invalid LLM response returns None."""
        from orderbot.tasks.parsers.llm_category_inference import infer_item_category

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "invalid_category"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('openai.OpenAI', return_value=mock_client):
                result = infer_item_category(
                    "unknown",
                    [{"slug": "pastry", "display_name": "Pastries"}]
                )

                assert result is None  # "invalid_category" not in valid slugs

    def test_infer_item_category_none_response(self):
        """Test that 'none' LLM response returns None."""
        from orderbot.tasks.parsers.llm_category_inference import infer_item_category

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "none"
        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('openai.OpenAI', return_value=mock_client):
                result = infer_item_category(
                    "xyzabc123",
                    [{"slug": "pastry", "display_name": "Pastries"}]
                )

                assert result is None


class TestMenuCacheHelpers:
    """Tests for menu cache helper methods used by the handler."""

    def test_get_all_menu_item_names(self):
        """Test getting all menu item names for fuzzy matching."""
        from orderbot.cache import menu_cache

        # Save original state
        original_is_loaded = menu_cache._is_loaded
        original_menu_items = getattr(menu_cache, '_menu_items', {})

        try:
            # Mock the internal data
            menu_cache._is_loaded = True
            menu_cache._menu_items = {
                "hot coffee": {"name": "Hot Coffee", "item_type": "coffee_based_beverage"},
                "iced coffee": {"name": "Iced Coffee", "item_type": "coffee_based_beverage"},
                "plain bagel": {"name": "Plain Bagel", "item_type": "bagel"},
            }

            names = menu_cache.get_all_menu_item_names()

            assert isinstance(names, list)
            assert len(names) == 3
            assert "Hot Coffee" in names
            assert "Iced Coffee" in names
            assert "Plain Bagel" in names
        finally:
            # Restore original state
            menu_cache._is_loaded = original_is_loaded
            menu_cache._menu_items = original_menu_items

    def test_get_categories_for_inference(self):
        """Test getting categories for LLM inference."""
        from orderbot.cache import menu_cache

        # Save original state
        original_is_loaded = menu_cache._is_loaded
        original_categories = getattr(menu_cache, '_available_categories', {})
        original_displays = getattr(menu_cache, '_item_type_displays', {})

        try:
            menu_cache._is_loaded = True
            menu_cache._available_categories = {
                "drink": "Drinks",
                "food": "Food",
            }
            menu_cache._item_type_displays = {
                "bagel": {"display_name": "Bagels"},
                "coffee_based_beverage": {"display_name": "Coffees and Teas"},
            }

            categories = menu_cache.get_categories_for_inference()

            assert isinstance(categories, list)
            # Should have both menu categories and item types
            slugs = {c["slug"] for c in categories}
            assert "drink" in slugs
            assert "food" in slugs
            assert "bagel" in slugs
            assert "coffee_based_beverage" in slugs
        finally:
            # Restore original state
            menu_cache._is_loaded = original_is_loaded
            menu_cache._available_categories = original_categories
            menu_cache._item_type_displays = original_displays
