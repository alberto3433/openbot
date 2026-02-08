"""
Tests for bagel package selection functionality.

Tests the package_variety and package_contents attributes for bagel packages.
"""

import pytest
from unittest.mock import patch, MagicMock

from orderbot.tasks.models import OrderTask, MenuItemTask
from orderbot.tasks.config.package_input import PackageInputHandler
from orderbot.tasks.utils import OptionMatcher, InputNormalizer


# =============================================================================
# Mock Data
# =============================================================================

def get_mock_bagel_package_attributes():
    """Return mock attribute data for bagel_package item type."""
    return {
        "package_variety": {
            "slug": "package_variety",
            "display_name": "Package Variety",
            "question_text": "Would you like an assorted mix, or would you prefer to choose your bagel types?",
            "ask_in_conversation": True,
            "input_type": "single_select",
            "display_order": 1,
            "options": [
                {"slug": "assorted", "display_name": "Assorted Mix", "price": 0, "aliases": ["mix it up", "you pick", "assorted"]},
                {"slug": "custom", "display_name": "Choose Types", "price": 0, "aliases": ["choose", "pick", "custom"]},
            ],
        },
        "package_contents": {
            "slug": "package_contents",
            "display_name": "Package Contents",
            "question_text": "What bagel types would you like? For example, '3 plain and 3 everything'",
            "ask_in_conversation": True,
            "input_type": "package_multi_select",
            "display_order": 2,
        },
    }


def get_mock_bread_options():
    """Return mock bread options for bagel matching."""
    return [
        {"slug": "plain_bagel", "display_name": "Plain Bagel", "aliases": ["plain"]},
        {"slug": "everything_bagel", "display_name": "Everything Bagel", "aliases": ["everything"]},
        {"slug": "sesame_bagel", "display_name": "Sesame Bagel", "aliases": ["sesame"]},
        {"slug": "poppy_bagel", "display_name": "Poppy Bagel", "aliases": ["poppy"]},
        {"slug": "onion_bagel", "display_name": "Onion Bagel", "aliases": ["onion"]},
        {"slug": "salt_bagel", "display_name": "Salt Bagel", "aliases": ["salt"]},
    ]


# =============================================================================
# PackageInputHandler Tests
# =============================================================================

class TestPackageInputParsing:
    """Tests for parsing package contents input."""

    @pytest.fixture
    def handler(self):
        """Create a PackageInputHandler instance."""
        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)
        return PackageInputHandler(option_matcher=matcher, input_normalizer=normalizer)

    def test_parse_comma_separated(self, handler):
        """Test parsing comma-separated bagel types."""
        result = handler._parse_package_contents(
            "3 plain, 2 everything, 1 sesame",
            get_mock_bread_options(),
            pack_size=6
        )

        assert result["total"] == 6
        assert len(result["selections"]) == 3
        assert result["is_valid"] is True

        # Check individual selections
        plain_sel = next(s for s in result["selections"] if "plain" in s["bread"].lower())
        assert plain_sel["quantity"] == 3

        everything_sel = next(s for s in result["selections"] if "everything" in s["bread"].lower())
        assert everything_sel["quantity"] == 2

        sesame_sel = next(s for s in result["selections"] if "sesame" in s["bread"].lower())
        assert sesame_sel["quantity"] == 1

    def test_parse_and_separated(self, handler):
        """Test parsing 'and'-separated bagel types."""
        result = handler._parse_package_contents(
            "3 plain and 3 everything",
            get_mock_bread_options(),
            pack_size=6
        )

        assert result["total"] == 6
        assert len(result["selections"]) == 2
        assert result["is_valid"] is True

    def test_parse_under_specified(self, handler):
        """Test parsing when total doesn't match pack size."""
        result = handler._parse_package_contents(
            "4 plain",
            get_mock_bread_options(),
            pack_size=6
        )

        assert result["total"] == 4
        assert result["remaining"] == 2
        assert result["is_valid"] is False

    def test_parse_over_specified(self, handler):
        """Test parsing when total exceeds pack size."""
        result = handler._parse_package_contents(
            "5 plain, 5 everything",
            get_mock_bread_options(),
            pack_size=6
        )

        assert result["total"] == 10
        assert result["is_valid"] is False

    def test_parse_without_quantities(self, handler):
        """Test parsing types without explicit quantities (defaults to 1 each)."""
        result = handler._parse_package_contents(
            "plain, everything, sesame",
            get_mock_bread_options(),
            pack_size=3
        )

        assert result["total"] == 3
        assert len(result["selections"]) == 3
        assert result["is_valid"] is True

        for sel in result["selections"]:
            assert sel["quantity"] == 1

    def test_parse_space_separated(self, handler):
        """Test parsing space-separated input (no commas or 'and')."""
        result = handler._parse_package_contents(
            "2 plain 2 everything 2 sesame",
            get_mock_bread_options(),
            pack_size=6
        )

        assert result["total"] == 6
        assert len(result["selections"]) == 3
        assert result["is_valid"] is True

        plain_sel = next(s for s in result["selections"] if "plain" in s["bread"].lower())
        assert plain_sel["quantity"] == 2


class TestPackageDisplayFormatting:
    """Tests for formatting package contents for display."""

    @pytest.fixture
    def handler(self):
        """Create a PackageInputHandler instance."""
        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)
        return PackageInputHandler(option_matcher=matcher, input_normalizer=normalizer)

    def test_format_with_quantities(self, handler):
        """Test formatting selections with quantities."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )
            selections = [
                {"bread": "plain_bagel", "quantity": 3, "display_name": "Plain Bagel"},
                {"bread": "everything_bagel", "quantity": 2, "display_name": "Everything Bagel"},
                {"bread": "sesame_bagel", "quantity": 1, "display_name": "Sesame Bagel"},
            ]

            result = handler._format_selections_display(selections, item)

            assert "3 Plain" in result
            assert "2 Everything" in result
            assert "Sesame" in result
            # Should not have "1 Sesame" since quantity is 1
            assert "1 Sesame" not in result

    def test_format_removes_bagel_suffix(self, handler):
        """Test that item type suffix is removed for cleaner display."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )
            selections = [
                {"bread": "plain_bagel", "quantity": 2, "display_name": "Plain Bagel"},
            ]

            result = handler._format_selections_display(selections, item)

            # Should be "2 Plain" not "2 Plain Bagel"
            assert result == "2 Plain"


# =============================================================================
# Integration Tests with Menu Cache Mocking
# =============================================================================

class TestBagelPackageFlow:
    """Integration tests for the full bagel package ordering flow."""

    @pytest.fixture
    def mock_menu_cache(self):
        """Set up mock menu cache with bagel package data."""
        with patch("orderbot.tasks.config.handler.menu_cache") as mock_cache:
            mock_cache.get_item_type_attributes.return_value = get_mock_bagel_package_attributes()
            mock_cache.get_configurable_item_types.return_value = {"bagel_package"}
            mock_cache.get_global_attribute_options.return_value = get_mock_bread_options()
            mock_cache.get_response_patterns.return_value = ["yes", "yeah", "yep"]
            mock_cache.get_skipped_attributes_for_option.return_value = set()
            mock_cache.get_item_by_name.return_value = {"quantity_per_unit": 6}

            yield mock_cache

    def test_create_bagel_package_item(self, mock_menu_cache):
        """Test creating a bagel package menu item task."""
        item = MenuItemTask(
            menu_item_name="6 Bagel Package",
            menu_item_type="bagel_package",
            unit_price=12.00,
        )

        assert item.menu_item_type == "bagel_package"
        assert item.menu_item_name == "6 Bagel Package"

    def test_assorted_selection_stores_correctly(self, mock_menu_cache):
        """Test that selecting 'assorted' stores the selection correctly."""
        item = MenuItemTask(
            menu_item_name="6 Bagel Package",
            menu_item_type="bagel_package",
            unit_price=12.00,
        )

        # Simulate selecting assorted
        item.add_selection(
            slug="assorted",
            category="package_variety",
            quantity=1,
            price=0.0,
            display_name="Assorted Mix",
        )

        assert item.get_selection_value("package_variety") == "assorted"
        assert "Assorted Mix" in item.get_summary()

    def test_custom_selection_with_contents(self, mock_menu_cache):
        """Test that custom selection with contents displays correctly."""
        item = MenuItemTask(
            menu_item_name="6 Bagel Package",
            menu_item_type="bagel_package",
            unit_price=12.00,
        )

        # Simulate selecting custom + contents
        item.add_selection(
            slug="custom",
            category="package_variety",
            quantity=1,
            price=0.0,
            display_name="Choose Types",
        )
        item.add_selection(
            slug="_package_contents",
            category="package_contents",
            quantity=1,
            price=0.0,
            display_name="3 plain, 2 everything, 1 sesame",
        )

        summary = item.get_summary()
        assert "6 Bagel Package" in summary
        # Contents should be in the summary
        assert "3 plain" in summary.lower() or "plain" in summary.lower()


class TestPackageVarietySkip:
    """Tests for skipping the variety question when user provides contents directly."""

    @pytest.fixture
    def handler(self):
        """Create a PackageInputHandler instance."""
        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)
        return PackageInputHandler(option_matcher=matcher, input_normalizer=normalizer)

    def test_looks_like_package_contents_true(self, handler):
        """Test that input with bagel selections is detected as package contents."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            # Mock get_ingredient_details (primary lookup) and get_global_attribute_options (fallback)
            mock_cache.get_ingredient_details.return_value = get_mock_bread_options()
            mock_cache.get_global_attribute_options.return_value = get_mock_bread_options()
            mock_cache.get_menu_item_unit_info.return_value = ("each", 6)

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )

            # Space-separated bagel types should be detected
            assert handler.looks_like_package_contents("2 plain 2 everything 2 sesame", item) is True

    def test_looks_like_package_contents_false(self, handler):
        """Test that variety options like 'assorted' are not detected as package contents."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            # Mock get_ingredient_details (primary lookup) and get_global_attribute_options (fallback)
            mock_cache.get_ingredient_details.return_value = get_mock_bread_options()
            mock_cache.get_global_attribute_options.return_value = get_mock_bread_options()
            mock_cache.get_menu_item_unit_info.return_value = ("each", 6)

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )

            # These should NOT be detected as package contents
            assert handler.looks_like_package_contents("assorted", item) is False
            assert handler.looks_like_package_contents("choose", item) is False
            assert handler.looks_like_package_contents("mix it up", item) is False


class TestPackageSkipRules:
    """Tests for skip rules - assorted should skip package_contents."""

    def test_assorted_triggers_package_contents_skip(self):
        """Test that selecting assorted triggers the skip rule for package_contents."""
        with patch("orderbot.tasks.config.attribute_resolver.menu_cache") as mock_cache:
            # When assorted is selected, package_contents should be in skipped set
            mock_cache.get_skipped_attributes_for_option.return_value = {"package_contents"}
            mock_cache.get_item_type_attributes.return_value = get_mock_bagel_package_attributes()

            from orderbot.tasks.config.attribute_resolver import get_skipped_attributes

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )
            item.add_selection(
                slug="assorted",
                category="package_variety",
                quantity=1,
                price=0.0,
                display_name="Assorted Mix",
            )

            skipped = get_skipped_attributes(item)
            assert "package_contents" in skipped


# =============================================================================
# Edge Cases
# =============================================================================

class TestPackageEdgeCases:
    """Edge case tests for bagel packages."""

    @pytest.fixture
    def handler(self):
        """Create a PackageInputHandler instance."""
        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)
        return PackageInputHandler(option_matcher=matcher, input_normalizer=normalizer)

    def test_bakers_dozen_13_bagels(self, handler):
        """Test Baker's Dozen which has 13 bagels."""
        result = handler._parse_package_contents(
            "7 plain, 6 everything",
            get_mock_bread_options(),
            pack_size=13
        )

        assert result["total"] == 13
        assert result["is_valid"] is True

    def test_mixed_formats(self, handler):
        """Test input with mixed formats (some with quantities, some without)."""
        result = handler._parse_package_contents(
            "3 plain, everything, sesame",
            get_mock_bread_options(),
            pack_size=5
        )

        assert result["total"] == 5
        assert result["is_valid"] is True

    def test_unrecognized_bagel_type(self, handler):
        """Test that unrecognized bagel types are ignored."""
        result = handler._parse_package_contents(
            "3 plain, 2 blueberry",  # blueberry not in options
            get_mock_bread_options(),
            pack_size=6
        )

        # Only plain should match
        assert result["total"] == 3
        assert len(result["selections"]) == 1
        assert result["is_valid"] is False

    def test_empty_input(self, handler):
        """Test empty input handling."""
        result = handler._parse_package_contents(
            "",
            get_mock_bread_options(),
            pack_size=6
        )

        assert result["total"] == 0
        assert len(result["selections"]) == 0
        assert result["is_valid"] is False


# =============================================================================
# Validation Logic Tests
# =============================================================================

class TestPackageValidation:
    """Tests for validation logic - over-specified should NOT update cart."""

    @pytest.fixture
    def handler(self):
        """Create a PackageInputHandler instance."""
        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)
        return PackageInputHandler(option_matcher=matcher, input_normalizer=normalizer)

    def test_over_specified_does_not_store(self, handler):
        """Test that over-specified input does NOT store to cart."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_menu_item_unit_info.return_value = ("each", 3)
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="3 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=8.00,
            )
            order = OrderTask()

            attr = {"slug": "package_contents"}
            options = get_mock_bread_options()

            # Over-specify: 6 bagels for a 3-pack (all valid types)
            result = handler.handle_package_input(
                "2 plain 2 everything 2 sesame",
                item,
                order,
                attr,
                options,
                advance_callback=lambda i, o, a, d: None,
            )

            # Should NOT have stored the selection
            assert item.get_selection("package_contents") is None
            # Message should ask to try again
            assert "includes 3" in result.message

    def test_exact_match_stores_and_advances(self, handler):
        """Test that exact match stores and advances."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_menu_item_unit_info.return_value = ("each", 3)
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="3 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=8.00,
            )
            order = OrderTask()

            attr = {"slug": "package_contents"}
            options = get_mock_bread_options()

            advanced = [False]

            def mock_advance(i, o, a, d):
                advanced[0] = True
                return StateMachineResult(message="Advanced", order=o)

            from orderbot.tasks.schemas import StateMachineResult

            result = handler.handle_package_input(
                "1 plain 1 everything 1 sesame",
                item,
                order,
                attr,
                options,
                advance_callback=mock_advance,
            )

            # Should have stored the selection
            assert item.get_selection("package_contents") is not None
            # Should have advanced
            assert advanced[0] is True

    def test_under_specified_stores_partial(self, handler):
        """Test that under-specified input stores partial selection."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_menu_item_unit_info.return_value = ("each", 6)
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )
            order = OrderTask()

            attr = {"slug": "package_contents"}
            options = get_mock_bread_options()

            result = handler.handle_package_input(
                "2 plain",
                item,
                order,
                attr,
                options,
                advance_callback=lambda i, o, a, d: None,
            )

            # Should have stored partial selection
            sel = item.get_selection("package_contents")
            assert sel is not None
            assert "Plain" in sel.get("display_name", "")
            # Message should ask for more
            assert "4 more" in result.message

    def test_accumulation_merges_selections(self, handler):
        """Test that follow-up input merges with existing selection."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_menu_item_unit_info.return_value = ("each", 6)
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )
            order = OrderTask()

            attr = {"slug": "package_contents"}
            options = get_mock_bread_options()

            # First input: 2 plain (partial)
            handler.handle_package_input(
                "2 plain",
                item,
                order,
                attr,
                options,
                advance_callback=lambda i, o, a, d: None,
            )

            advanced = [False]

            def mock_advance(i, o, a, d):
                advanced[0] = True
                return StateMachineResult(message="Advanced", order=o)

            from orderbot.tasks.schemas import StateMachineResult

            # Second input: 2 everything 2 sesame (completes to 6)
            result = handler.handle_package_input(
                "2 everything 2 sesame",
                item,
                order,
                attr,
                options,
                advance_callback=mock_advance,
            )

            # Should have merged and advanced
            sel = item.get_selection("package_contents")
            assert sel is not None
            display = sel.get("display_name", "")
            # Should contain all three types
            assert "Plain" in display
            assert "Everything" in display
            assert "Sesame" in display
            assert advanced[0] is True

    def test_accumulation_overflow_rejects(self, handler):
        """Test that accumulation exceeding pack size is rejected."""
        with patch("orderbot.tasks.config.package_input.menu_cache") as mock_cache:
            mock_cache.get_menu_item_unit_info.return_value = ("each", 6)
            mock_cache.get_item_type_display_name.return_value = "Bagel"

            item = MenuItemTask(
                menu_item_name="6 Bagel Package",
                menu_item_type="bagel_package",
                unit_price=12.00,
            )
            order = OrderTask()

            attr = {"slug": "package_contents"}
            options = get_mock_bread_options()

            # First input: 2 plain (partial)
            handler.handle_package_input(
                "2 plain",
                item,
                order,
                attr,
                options,
                advance_callback=lambda i, o, a, d: None,
            )

            # Store what was there after first input
            first_selection = item.get_selection("package_contents")
            assert first_selection is not None

            # Second input: 3 everything 2 sesame = 5 more = 7 total > 6
            result = handler.handle_package_input(
                "3 everything 2 sesame",
                item,
                order,
                attr,
                options,
                advance_callback=lambda i, o, a, d: None,
            )

            # Should reject - the existing selection should remain unchanged
            sel = item.get_selection("package_contents")
            assert sel is not None
            # Selection should NOT have been updated with the overflow
            display = sel.get("display_name", "")
            assert "Plain" in display
            # Should NOT have merged the overflow
            # Error message should mention the total (uses dynamic unit name now)
            assert "7 bagels" in result.message.lower() or "would be 7" in result.message.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
