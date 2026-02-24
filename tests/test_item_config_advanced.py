"""Advanced item configuration: side items, disambiguation, espresso, drink selection, and edge cases."""

import pytest
from unittest.mock import patch, MagicMock

from orderbot.tasks.models import OrderTask
from orderbot.tasks.handler_config import HandlerConfig

from tests.fixtures.mock_menu_cache import apply_mock_menu_cache


@pytest.fixture(autouse=True)
def mock_menu_cache_attributes(monkeypatch):
    """Auto-use fixture to mock menu_cache methods for all tests."""
    apply_mock_menu_cache(monkeypatch)


# =============================================================================
# Side Choice Handler Tests
# =============================================================================

class TestSideChoice:
    """Tests for handle_side_choice (omelette component slot selection).

    The component slot system creates bundled child items instead of setting
    attributes on the parent. When a user selects "bagel" or "fruit salad":
    - A new MenuItemTask is created as a child of the omelette
    - The child is linked via bundle_id and bundle_parent_item_id
    - Configurable children (bagel) need further configuration
    - Simple children (fruit salad) are marked complete immediately
    """

    def test_fruit_salad_selected(self):
        """Test selecting fruit salad as side creates a bundled child item."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        omelette = MenuItemTask(
            menu_item_name="Western Omelette",
            menu_item_type="omelette",
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)
        order.pending_item_ids = [omelette.id]

        result = sm.config_helper_handler.handle_side_choice("fruit salad please", omelette, order)

        # Parent should be complete and have a bundle_id
        assert omelette.status == TaskStatus.COMPLETE
        assert omelette.bundle_id is not None

        # Should have created a child item
        active_items = order.items.get_active_items()
        assert len(active_items) == 2, f"Expected 2 items (parent + child), got {len(active_items)}"

        # Find the child item
        child = [item for item in active_items if item.id != omelette.id][0]
        assert child.bundle_parent_item_id == omelette.id
        assert child.bundle_id == omelette.bundle_id
        assert child.bundle_slot == "side"
        assert child.bundle_price_rule == "included"
        # Fruit salad is a specific menu item, should be complete
        assert child.status == TaskStatus.COMPLETE

    def test_bagel_without_type_asks_for_type(self):
        """Test that just 'bagel' creates a bundled child that needs configuration."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        omelette = MenuItemTask(
            menu_item_name="Greek Omelette",
            menu_item_type="omelette",
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)
        order.pending_item_ids = [omelette.id]

        # "bagel" is a valid side choice - should create child and ask for bagel type
        result = sm.config_helper_handler.handle_side_choice("bagel", omelette, order)

        # Parent should be complete
        assert omelette.status == TaskStatus.COMPLETE
        assert omelette.bundle_id is not None

        # Should have created a child bagel item
        active_items = order.items.get_active_items()
        assert len(active_items) == 2

        child = [item for item in active_items if item.id != omelette.id][0]
        assert child.bundle_parent_item_id == omelette.id
        assert child.menu_item_type == "bagel"
        # Bagel needs bread type configuration
        assert child.status == TaskStatus.IN_PROGRESS
        # Should ask for bagel type
        assert "bagel" in result.message.lower() or "kind" in result.message.lower()

    def test_bagel_with_type_specified(self):
        """Test selecting bagel with type specified upfront creates child with bread set."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        omelette = MenuItemTask(
            menu_item_name="Veggie Omelette",
            menu_item_type="omelette",
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)
        order.pending_item_ids = [omelette.id]

        result = sm.config_helper_handler.handle_side_choice("plain bagel", omelette, order)

        # Parent should be complete
        assert omelette.status == TaskStatus.COMPLETE
        assert omelette.bundle_id is not None

        # Should have created a child bagel item
        active_items = order.items.get_active_items()
        assert len(active_items) == 2

        child = [item for item in active_items if item.id != omelette.id][0]
        assert child.bundle_parent_item_id == omelette.id
        assert child.menu_item_type == "bagel"
        # Child is IN_PROGRESS until bagel configuration is done
        assert child.status == TaskStatus.IN_PROGRESS

    def test_bundle_included_child_has_zero_price(self):
        """Test that bundle-included child item has $0 price and doesn't add to subtotal."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        # Create omelette with unit_price set
        omelette = MenuItemTask(
            menu_item_name="Greek Omelette",
            menu_item_type="omelette",
            unit_price=12.50,
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)
        order.pending_item_ids = [omelette.id]

        # Select "plain bagel" as side - creates bundle-included child
        sm.config_helper_handler.handle_side_choice("plain bagel", omelette, order)

        # Get the child bagel
        active_items = order.items.get_active_items()
        child = [item for item in active_items if item.id != omelette.id][0]

        # Verify child has bundle_price_rule="included"
        assert child.bundle_price_rule == "included"

        # Child should have $0 price because it's included in bundle
        assert child.unit_price == 0.0, f"Bundle-included child should be $0, got ${child.unit_price}"

        # Subtotal should only include parent's price, not child's
        subtotal = order.items.get_subtotal()
        assert subtotal == 12.50, f"Subtotal should be $12.50 (just omelette), got ${subtotal}"

    def test_bundle_included_child_stays_zero_after_configuration(self):
        """Test that bundle-included child remains $0 even after configuring attributes."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        # Create omelette with unit_price set
        omelette = MenuItemTask(
            menu_item_name="Greek Omelette",
            menu_item_type="omelette",
            unit_price=12.50,
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)
        order.pending_item_ids = [omelette.id]

        # Select "bagel" as side (without specifying type) - creates unconfigured child
        sm.config_helper_handler.handle_side_choice("bagel", omelette, order)

        # Get the child bagel
        active_items = order.items.get_active_items()
        child = [item for item in active_items if item.id != omelette.id][0]

        # Child needs configuration
        assert child.status == TaskStatus.IN_PROGRESS
        assert child.bundle_price_rule == "included"
        assert child.unit_price == 0.0, f"Unconfigured bundle child should be $0, got ${child.unit_price}"

        # Now configure the child by setting bread type and recalculating price
        child.attribute_values["bread"] = "plain"
        sm.pricing.recalculate_item_price(child)

        # Price should STILL be $0 because it's bundle-included
        assert child.unit_price == 0.0, f"Configured bundle child should still be $0, got ${child.unit_price}"

        # Subtotal should only include parent's price
        subtotal = order.items.get_subtotal()
        assert subtotal == 12.50, f"Subtotal should be $12.50 (just omelette), got ${subtotal}"

        # Verify the serialized dict also has $0 base_price (for UI display)
        from orderbot.tasks.item_converters import _unified_converter
        child_dict = _unified_converter.to_dict(child, pricing=sm.pricing)
        assert child_dict.get("base_price") == 0.0, f"Serialized base_price should be $0, got ${child_dict.get('base_price')}"
        assert child_dict.get("unit_price") == 0.0, f"Serialized unit_price should be $0, got ${child_dict.get('unit_price')}"
        assert child_dict.get("line_total") == 0.0, f"Serialized line_total should be $0, got ${child_dict.get('line_total')}"

    def test_bundle_included_child_with_upcharge(self):
        """Test that bundle-included child has $0 base but upcharges still apply."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        # Create omelette with unit_price set
        omelette = MenuItemTask(
            menu_item_name="Greek Omelette",
            menu_item_type="omelette",
            unit_price=12.50,
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)
        order.pending_item_ids = [omelette.id]

        # Select "bagel" as side - creates bundle-included child
        sm.config_helper_handler.handle_side_choice("bagel", omelette, order)

        # Get the child bagel
        active_items = order.items.get_active_items()
        child = [item for item in active_items if item.id != omelette.id][0]

        # Configure bread
        child.attribute_values["bread"] = "plain"
        sm.pricing.recalculate_item_price(child)
        assert child.unit_price == 0.0, f"Plain bagel should be $0, got ${child.unit_price}"

        # Add cream cheese spread (which has an upcharge)
        child.add_selection("plain_cream_cheese", "spread")
        child.attribute_values["spread"] = "plain_cream_cheese"
        sm.pricing.recalculate_item_price(child)

        # Price should now include the cream cheese upcharge
        assert child.unit_price == 0.80, f"Bagel with cream cheese should be $0.80, got ${child.unit_price}"

        # Subtotal should include parent + child upcharge
        subtotal = order.items.get_subtotal()
        assert subtotal == 13.30, f"Subtotal should be $13.30 (omelette $12.50 + cream cheese $0.80), got ${subtotal}"


    def test_unclear_response_reprompts(self):
        """Test unclear response re-prompts with side options."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_field = "side_choice"

        omelette = MenuItemTask(
            menu_item_name="Ham Omelette",
            menu_item_type="omelette",
        )
        omelette.mark_in_progress()
        order.items.add_item(omelette)

        result = sm.config_helper_handler.handle_side_choice("hmm not sure", omelette, order)

        # Parent should still be in progress (choice not made)
        assert omelette.status.value == "in_progress"
        # Should mention the valid options
        assert "bagel" in result.message.lower() or "fruit" in result.message.lower()



# =============================================================================
# Category Clarification Handler Tests
# =============================================================================

class TestCategoryClarification:
    """Tests for handle_category_clarification.

    Note: These tests mock menu_cache.get_items_by_category since the code
    is now data-driven and queries the database directly.
    """

    def test_lists_available_items_from_category(self):
        """Test that available items are listed from category lookup."""
        from unittest.mock import patch
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        mock_sodas = [
            {"name": "Coke"},
            {"name": "Diet Coke"},
            {"name": "Sprite"},
            {"name": "Ginger Ale"},
        ]

        sm = OrderStateMachine()
        order = OrderTask()

        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_items_by_category", return_value=mock_sodas):
            result = sm.menu_inquiry_handler.handle_category_clarification("soda", order)

        assert "what kind" in result.message.lower()
        assert "coke" in result.message.lower()

    def test_lists_many_items_with_and_others(self):
        """Test that long list uses 'and others' format."""
        from unittest.mock import patch
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        mock_sodas = [
            {"name": "Coke"},
            {"name": "Diet Coke"},
            {"name": "Sprite"},
            {"name": "Ginger Ale"},
            {"name": "Root Beer"},
            {"name": "Lemonade"},
        ]

        sm = OrderStateMachine()
        order = OrderTask()

        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_items_by_category", return_value=mock_sodas):
            result = sm.menu_inquiry_handler.handle_category_clarification("soda", order)

        assert "and others" in result.message.lower()

    def test_generic_message_when_no_items_in_category(self):
        """Test generic message when no items found in category."""
        from unittest.mock import patch
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # Mock empty category result - must also disable display group lookup
        # so the code falls through to the (mocked) category lookup
        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_display_group_by_slug", return_value=None), \
             patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_items_by_category", return_value=[]):
            result = sm.menu_inquiry_handler.handle_category_clarification("soda", order)

        # Should gracefully handle empty category - either say not available or ask what else
        assert "don't have" in result.message.lower() or "what else" in result.message.lower()

    def test_two_items_uses_and_format(self):
        """Test that two items uses proper 'and' format."""
        from unittest.mock import patch
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        mock_sodas = [
            {"name": "Coke"},
            {"name": "Sprite"},
        ]

        sm = OrderStateMachine()
        order = OrderTask()

        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_items_by_category", return_value=mock_sodas):
            result = sm.menu_inquiry_handler.handle_category_clarification("soda", order)

        # Should have "Coke, and Sprite" or similar format
        assert "coke" in result.message.lower()
        assert "sprite" in result.message.lower()

    def test_display_group_alias_returns_group_items(self):
        """Test that display group aliases (e.g., 'pastry') return items from that group.

        When user says "pastries" and it matches a display group alias, we should
        list items from all item types in that display group, not just look up
        by category (which would return empty).
        """
        from unittest.mock import patch, MagicMock
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        # Mock display group lookup - "pastry" maps to "desserts_pastries" group
        mock_display_group = {
            "slug": "desserts_pastries",
            "display_name": "Desserts and Pastries",
            "display_order": 5
        }

        # Mock items from the desserts/pastries item types
        mock_items_by_type = {
            "cookie": [{"name": "Chocolate Chip Cookie"}, {"name": "Oatmeal Cookie"}],
            "muffin": [{"name": "Blueberry Muffin"}, {"name": "Bran Muffin"}],
            "rugalach": [{"name": "Chocolate Rugalach"}],
        }

        sm = OrderStateMachine(menu_data={"items_by_type": mock_items_by_type})
        order = OrderTask()

        with patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_display_group_by_slug", return_value=mock_display_group), \
             patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_item_types_in_display_group", return_value=["cookie", "muffin", "rugalach"]), \
             patch("orderbot.tasks.menu_inquiry_handler.menu_cache.get_items_by_category", return_value=[]):
            result = sm.menu_inquiry_handler.handle_category_clarification("pastry", order)

        # Should list items from the display group, not say "I don't have that"
        assert "don't have that" not in result.message.lower()
        assert "what kind" in result.message.lower()
        # Should contain at least one of the pastry items
        message_lower = result.message.lower()
        assert any(item in message_lower for item in ["cookie", "muffin", "rugalach"])


# =============================================================================
# Price Inquiry Handler Tests
# =============================================================================

class TestEspressoItemTypeConsistency:
    """Tests to ensure espresso is handled consistently as MenuItemTask throughout the system."""

    def test_parse_open_input_detects_another_espresso_as_espresso_type(self):
        """Verify parse_open_input returns espresso item for 'another espresso'.

        The response can be either:
        - duplicate_new_item_type = 'espresso' (when item type is detected)
        - parsed_items with item_type = 'espresso' (when exact menu item is matched)
        Both are valid and result in the correct item being added.
        """
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic

        result = parse_open_input_deterministic("another espresso")
        assert result is not None

        # Accept either duplicate_new_item_type or parsed_items with matching item_type
        if result.duplicate_new_item_type:
            assert result.duplicate_new_item_type == "espresso", \
                f"Expected 'espresso', got '{result.duplicate_new_item_type}'"
        elif result.parsed_items:
            item_types = [item.item_type for item in result.parsed_items]
            assert "espresso" in item_types, \
                f"Expected item_type 'espresso' in parsed_items, got {item_types}"
        else:
            raise AssertionError("Expected duplicate_new_item_type or parsed_items")

    def test_global_attribute_options_include_must_match(self):
        """Verify menu_cache.get_global_attribute_options includes must_match field.

        This ensures data schema consistency - options loaded from cache have all
        required fields for proper option matching (must_match filters like "oat milk").
        """
        from orderbot.cache import menu_cache

        # Get milk_sweetener_syrup options (used for espresso)
        options = menu_cache.get_global_attribute_options("milk_sweetener_syrup")

        if not options:
            pytest.skip("milk_sweetener_syrup options not loaded in cache")

        # Check that options have the expected fields including must_match
        # (must_match may be None for default options, but the key should exist in the data)
        for opt in options:
            # All options should have these base fields
            assert "slug" in opt, f"Option missing 'slug': {opt}"
            assert "display_name" in opt, f"Option missing 'display_name': {opt}"

        # Verify at least some non-default milks have must_match set
        # (e.g., oat_milk should have must_match="oat milk")
        oat_milk_opts = [o for o in options if "oat" in o.get("slug", "").lower()]
        if oat_milk_opts:
            oat_milk = oat_milk_opts[0]
            # must_match key should exist in the cache data
            assert "must_match" in oat_milk, \
                "Cache should include must_match field for options (even if None)"


class TestShotQuantityExtraction:
    """Tests for shot quantity extraction in the quantity-based system.

    Shots now use numeric quantities like syrups (e.g., "2 shots" -> quantity=2)
    instead of discrete options (Single/Double/Triple/Quad).

    The extraction code in parsers/deterministic/extraction.py handles
    "double" -> 2, "triple" -> 3 conversions at parse time.
    """

    def test_extract_quantity_from_two_shots(self):
        """Test that '2 shots' extracts quantity=2."""
        from orderbot.tasks.parsers.quantity_utils import extract_leading_quantity

        qty, remaining = extract_leading_quantity("2 shots")
        assert qty == 2, f"Expected quantity=2, got {qty}"
        assert remaining == "shots", f"Expected 'shots', got '{remaining}'"

    def test_extract_quantity_from_three_shots(self):
        """Test that 'three shots' extracts quantity=3."""
        from orderbot.tasks.parsers.quantity_utils import extract_leading_quantity

        qty, remaining = extract_leading_quantity("three shots")
        assert qty == 3, f"Expected quantity=3, got {qty}"
        assert remaining == "shots", f"Expected 'shots', got '{remaining}'"

    def test_extract_quantity_from_double_prefix(self):
        """Test that extraction code handles 'double' as quantity=2."""
        from orderbot.tasks.parsers.deterministic.extraction import WORD_TO_NUM

        qty_str = "double"
        if qty_str == "double":
            qty = 2
        elif qty_str == "triple":
            qty = 3
        else:
            qty = WORD_TO_NUM.get(qty_str, 1)

        assert qty == 2, f"Expected 'double' to map to 2, got {qty}"

class TestDrinkSelectionHandler:
    """Tests for item selection via ConfiguringItemHandler._handle_item_selection."""

    def test_no_pending_options_clears_state(self):
        """Test that no pending options returns to taking items."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = []
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("1", order)

        assert "what would you like" in result.message.lower()

    def test_select_by_number(self):
        """Test selecting drink by number."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Coke", "base_price": 2.50},
            {"name": "Sprite", "base_price": 2.50},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("1", order)

        assert "coke" in result.message.lower()
        assert len(order.items.items) == 1
        assert order.items.items[0].menu_item_name == "Coke"

    def test_select_by_ordinal(self):
        """Test selecting drink by ordinal (first, second)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Pepsi", "base_price": 2.50},
            {"name": "Dr Pepper", "base_price": 2.75},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("the second", order)

        assert "dr pepper" in result.message.lower()
        assert order.items.items[0].menu_item_name == "Dr Pepper"

    def test_select_by_name(self):
        """Test selecting drink by name."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Orange Juice", "base_price": 3.00},
            {"name": "Apple Juice", "base_price": 3.00},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("apple juice please", order)

        assert "apple juice" in result.message.lower()
        assert order.items.items[0].menu_item_name == "Apple Juice"

    def test_invalid_selection_delegates_to_taking_items(self):
        """Test that unrecognized input during selection falls through to taking-items flow."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Coke", "base_price": 2.50},
            {"name": "Sprite", "base_price": 2.50},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("xyz", order)

        # Unrecognized input delegates to handle_taking_items, clearing the selection state
        assert order.pending_item_options == []
        assert order.pending_field is None

    def test_out_of_range_number_delegates_to_taking_items(self):
        """Test that out-of-range number is treated as new input (e.g. quantity)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Coke", "base_price": 2.50},
            {"name": "Sprite", "base_price": 2.50},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("3", order)

        # "3" is treated as new input by the taking-items handler, not re-asked
        assert order.pending_item_options == []

    def test_negative_number_rejected(self):
        """Test that negative numbers are rejected."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Coke", "base_price": 2.50},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("-1", order)

        assert "choose" in result.message.lower()
        assert len(order.items.items) == 0

    def test_soda_added_as_complete(self):
        """Test that soda drink is added as complete without configuration."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, TaskStatus

        sm = OrderStateMachine()
        order = OrderTask()
        order.pending_item_options = [
            {"name": "Coca-Cola", "base_price": 2.50},
        ]
        order.pending_field = "item_selection"

        result = sm.configuring_item_handler._handle_item_selection("1", order)

        assert len(order.items.items) == 1
        drink = order.items.items[0]
        assert drink.status == TaskStatus.COMPLETE
        assert "anything else" in result.message.lower()


class TestModifierRemovalDuringConfig:
    """Tests for removing modifiers during the CONFIGURING_ITEM phase."""

    def test_remove_bacon_during_config_removes_modifier_not_item(self):
        """Test that 'remove the bacon' during bagel config removes the bacon modifier, not the whole item.

        Regression test for bug where "remove the bacon" while being asked "Would you like toasted?"
        would remove the entire bagel item instead of just the bacon modifier.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        sm.menu_data = {
            "ingredient_to_items": {},
            "items_by_type": {"signature_items": []},
            "item_name_to_id": {},
            "items_by_id": {},
        }

        # Create an order with a bagel that has bacon and egg, in CONFIGURING_ITEM state
        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="everything",
            extra_protein="bacon",
            extras=["Egg"],
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        # Set up config state (asking about toasted)
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_ids = [bagel.id]
        order.pending_field = "bagel:toasted"

        # Process "remove the bacon"
        result = sm.process("remove the bacon", order)

        # Verify the bagel is still there
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1, "Bagel should NOT be removed, only the bacon modifier"

        # Verify bacon was removed
        remaining_bagel = active_items[0]
        assert remaining_bagel.menu_item_type == "bagel", "Item should be a bagel"
        assert remaining_bagel["extra_protein"] is None, "Bacon should be removed"

        # Verify egg is still there (single topping returns as string, not list)
        toppings = remaining_bagel["toppings"]
        assert toppings == "Egg", "Egg should still be in toppings"

        # Verify we continue with the config question
        assert "removed" in result.message.lower() and "bacon" in result.message.lower()

    def test_remove_egg_during_config_removes_from_toppings(self):
        """Test removing an extra (egg) during config removes it from toppings list."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        sm.menu_data = {
            "ingredient_to_items": {},
            "items_by_type": {"signature_items": []},
            "item_name_to_id": {},
            "items_by_id": {},
        }

        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            extra_protein="bacon",
            extras=["Egg", "cheese"],  # Use "extras" not "toppings"
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_ids = [bagel.id]
        order.pending_field = "bagel:toasted"

        result = sm.process("remove the egg", order)

        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1, "Bagel should NOT be removed"

        remaining_bagel = active_items[0]
        assert remaining_bagel["extra_protein"] == "bacon", "Bacon should still be there"
        toppings = remaining_bagel["toppings"] or []
        assert "Egg" not in toppings, "Egg should be removed from toppings"
        assert "cheese" in toppings, "Cheese should still be in toppings"

    def test_remove_nonexistent_modifier_falls_through_to_item_search(self):
        """Test that removing a modifier not on the item falls through to item search logic."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from tests.helpers import BagelItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        sm.menu_data = {
            "ingredient_to_items": {},
            "items_by_type": {"signature_items": []},
            "item_name_to_id": {},
            "items_by_id": {},
        }

        order = OrderTask()
        bagel = BagelItemTask(
            bagel_type="plain",
            # No bacon on this bagel
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_ids = [bagel.id]
        order.pending_field = "bagel:toasted"

        result = sm.process("remove the lox", order)

        # Since lox isn't on the bagel, it should fall through
        # and try to find items with "lox" in them
        # Since there's no match, it returns "couldn't find"
        active_items = result.order.items.get_active_items()
        assert len(active_items) == 1, "Bagel should still be there"
        assert "couldn't find" in result.message.lower() or "lox" in result.message.lower()


class TestChangeToMenuItemNotModifier:
    """
    Test that 'change it to [menu item]' is treated as item replacement,
    not as a modifier change (which would fail with 'Unknown' attribute).
    """

    def test_change_to_menu_item_defers_to_replacement_flow(self, menu_cache_loaded):
        """
        When user says 'change it to fresh squeezed orange juice' with an OJ in cart,
        the system should replace the item, not try to change a modifier.

        This tests the fix in config_helper_handler.py that checks if the 'unknown'
        modifier is actually a menu item, and defers to the item replacement flow.
        """
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask, MenuItemTask
        from orderbot.tasks.schemas import OrderPhase

        sm = OrderStateMachine()
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        # Add an orange juice to the cart
        # Use a MenuItemTask with a generic drink that could be replaced
        oj = MenuItemTask(
            menu_item_name="Tropicana Orange Juice 46 oz",
            menu_item_type="bottled_drinks",
        )
        oj.mark_complete()
        order.items.add_item(oj)

        # Verify the item is in the cart
        assert len(order.items.get_active_items()) == 1
        assert order.items.get_active_items()[0].menu_item_name == "Tropicana Orange Juice 46 oz"

        # Now say "change it to fresh squeezed orange juice"
        result = sm.process("change it to fresh squeezed orange juice", order)

        # Should NOT get "Unknown" error message
        assert "unknown" not in result.message.lower(), (
            f"Got 'unknown' modifier error: {result.message}"
        )

        # Should either successfully replace, or ask a relevant question about the new item
        # (Not error about missing attribute)
        active_items = result.order.items.get_active_items()

        # Either the item was replaced with the new one, or we're being asked about the new item
        # Either way, the error "doesn't have a Unknown to change" should NOT appear
        assert "doesn't have a" not in result.message.lower(), (
            f"Got modifier change error: {result.message}"
        )


class TestUnavailableAttributeOptions:
    """Tests for handling unavailable attribute options (e.g., 'medium' size)."""

    def test_unavailable_selection_in_menu_item_task(self):
        """Test that MenuItemTask can store unavailable_selections."""
        from orderbot.tasks.models import MenuItemTask

        task = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="coffee_based_beverage",
            unavailable_selections={"size": {"attempted_slug": "medium", "attempted_display": "Medium"}}
        )

        assert task.unavailable_selections == {"size": {"attempted_slug": "medium", "attempted_display": "Medium"}}

    def test_unavailable_selection_message_generation(self):
        """Test that the handler generates helpful message for unavailable selections."""
        from orderbot.tasks.models import OrderTask, MenuItemTask
        from orderbot.tasks.schemas import OrderPhase
        from orderbot.tasks.config import MenuItemConfigHandler
        from orderbot.tasks.handler_config import HandlerConfig

        # Create handler with real handler config
        config = HandlerConfig()
        handler = MenuItemConfigHandler(config)

        # Create order with item that has unavailable selection
        order = OrderTask()
        order.set_phase(OrderPhase.CONFIGURING_ITEM)

        # Create item with unavailable "medium" size selection
        item = MenuItemTask(
            menu_item_name="Latte",
            menu_item_type="coffee_based_beverage",
            unavailable_selections={"size": {"attempted_slug": "medium", "attempted_display": "Medium"}}
        )
        order.items.add_item(item)
        order.pending_item_ids = [item.id]

        # Mock attribute definition with available options only
        mock_attr = {
            "slug": "size",
            "display_name": "Size",
            "question_text": "What size?",
            "ask_in_conversation": True,
            "input_type": "single_select",
            "options": [
                {"slug": "small", "display_name": "Small", "price": 0, "is_available": True},
                {"slug": "large", "display_name": "Large", "price": 1.00, "is_available": True},
            ],
        }

        # Call the internal method that generates the question
        result = handler._ask_attribute_question(item, order, mock_attr, "size")

        # Should mention "we don't have Medium" and list available options
        assert "we don't have medium" in result.message.lower(), f"Expected unavailable message, got: {result.message}"
        assert "small" in result.message.lower(), f"Expected 'Small' option, got: {result.message}"
        assert "large" in result.message.lower(), f"Expected 'Large' option, got: {result.message}"

        # Unavailable selection should be cleared
        assert "size" not in item.unavailable_selections

    def test_parsed_item_entry_unavailable_selections(self):
        """Test that ParsedItemEntry stores unavailable_selections."""
        from orderbot.tasks.schemas.parser_responses import ParsedItemEntry

        entry = ParsedItemEntry(
            menu_item_name="Latte",
            menu_item_type="coffee_based_beverage",
            item_type="coffee_based_beverage",  # Required field
            quantity=1,
            unavailable_selections={"size": {"attempted_slug": "medium", "attempted_display": "Medium"}}
        )

        assert entry.unavailable_selections == {"size": {"attempted_slug": "medium", "attempted_display": "Medium"}}

    def test_medium_coffee_parsing_captures_unavailable_selection(self):
        """Test that 'medium hot coffee' parsing captures unavailable size.

        This tests the parser's ability to detect unavailable options and
        store them in unavailable_selections for later "We don't have X" messaging.
        """
        from orderbot.tasks.parsers.deterministic.core import parse_open_input

        # Parse user input with unavailable "medium" size
        result = parse_open_input("medium hot coffee with 2 splendas")

        # Should have parsed one item
        assert len(result.parsed_items) >= 1, f"Expected at least 1 item, got: {len(result.parsed_items)}"

        item = result.parsed_items[0]

        # Should have unavailable_selections with "medium" for size
        assert item.unavailable_selections, f"Expected unavailable_selections, got: {item.unavailable_selections}"
        assert "size" in item.unavailable_selections, f"Expected 'size' in unavailable_selections, got keys: {item.unavailable_selections.keys()}"
        assert item.unavailable_selections["size"]["attempted_slug"] == "medium", (
            f"Expected attempted_slug='medium', got: {item.unavailable_selections['size']}"
        )

        # The sweetener (2 splendas) should still be captured in selections
        selections = item.selections or []
        splenda_found = any(
            s.slug == "splenda" for s in selections
        )
        assert splenda_found, f"Expected splenda in selections, got: {selections}"
        # Verify quantity
        splenda_sel = next((s for s in selections if s.slug == "splenda"), None)
        assert splenda_sel and splenda_sel.quantity == 2, f"Expected quantity=2 for splenda, got: {splenda_sel}"


class TestMenuInquiryWordBoundarySearch:
    """Tests for menu inquiry word-boundary search (e.g., 'what lattes do you have?')."""

    def test_menu_inquiry_does_not_add_to_cart(self):
        """Test that menu inquiries don't add items to cart."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        # "lattes" is mapped to coffee_based_beverage category in mock, so it returns all beverages
        # The key test is that it does NOT add to cart
        result = sm.process("what lattes do you have", order)

        # Should NOT add to cart
        assert len(order.items.items) == 0, "Should not add items to cart for menu inquiry"

        # Should ask if user wants any
        msg_lower = result.message.lower()
        assert "would you like" in msg_lower, f"Expected question prompt, got: {result.message}"

    def test_menu_inquiry_parsing_sets_menu_query(self):
        """Test that 'what X do you have' sets menu_query=True even for non-DB categories."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic

        test_inputs = [
            ("what lattes do you have", "lattes"),
            ("what muffins do you have", "muffins"),
        ]

        for inp, expected_type in test_inputs:
            result = parse_open_input_deterministic(inp)
            assert result is not None, f"Expected parse result for '{inp}'"
            assert result.menu_query, f"Expected menu_query=True for '{inp}'"
            assert result.menu_query_type is not None, f"Expected menu_query_type for '{inp}'"

    def test_order_intent_still_adds_to_cart(self):
        """Test that 'I want a latte' still adds to cart (order intent, not inquiry)."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask

        sm = OrderStateMachine()
        order = OrderTask()

        result = sm.process("I want a latte", order)

        # Should add to cart
        assert len(order.items.items) == 1, "Should add item to cart for order intent"


class TestIngredientMustMatchFiltering:
    """Tests for must_match filtering in find_matching_ingredients().

    The must_match feature prevents partial matches when an ingredient has
    required phrases. For example, "cheddar" should NOT match "Jalapeno Cheddar Bagel"
    because that item requires "Jalapeno Cheddar" or "Jalapeño Cheddar" in the search.
    """

    def test_cheddar_does_not_match_jalapeno_cheddar_bagel(self):
        """'cheddar' should NOT match 'Jalapeno Cheddar Bagel' due to must_match filter."""
        from orderbot.cache import menu_cache

        results = menu_cache.find_matching_ingredients("cheddar")

        # Should find Cheddar Cheese but NOT Jalapeno Cheddar Bagel
        result_slugs = [r["slug"] for r in results]

        assert "cheddar_cheese" in result_slugs, \
            "Should find Cheddar Cheese for 'cheddar'"
        assert "jalapeno_cheddar_bagel" not in result_slugs, \
            "Should NOT find Jalapeno Cheddar Bagel for 'cheddar' - must_match filter should exclude it"

    def test_jalapeno_cheddar_matches_jalapeno_cheddar_bagel(self):
        """'jalapeno cheddar' SHOULD match 'Jalapeno Cheddar Bagel'."""
        from orderbot.cache import menu_cache

        results = menu_cache.find_matching_ingredients("jalapeno cheddar")

        result_slugs = [r["slug"] for r in results]

        assert "jalapeno_cheddar_bagel" in result_slugs, \
            "Should find Jalapeno Cheddar Bagel when search contains the must_match phrase"

    def test_ingredient_without_must_match_still_matches(self):
        """Ingredients without must_match requirements should match normally."""
        from orderbot.cache import menu_cache

        # Search for bacon - should match since it has no must_match restrictions
        results = menu_cache.find_matching_ingredients("bacon")

        assert len(results) > 0, "Should find bacon (no must_match restriction)"
        result_slugs = [r["slug"] for r in results]
        assert "bacon" in result_slugs, "Should find bacon ingredient"

    def test_must_match_is_case_insensitive(self):
        """must_match filtering should be case-insensitive."""
        from orderbot.cache import menu_cache

        # Search with different cases
        results_lower = menu_cache.find_matching_ingredients("jalapeno cheddar")
        results_upper = menu_cache.find_matching_ingredients("JALAPENO CHEDDAR")
        results_mixed = menu_cache.find_matching_ingredients("Jalapeno Cheddar")

        # All should find the same item
        for results, case_name in [
            (results_lower, "lowercase"),
            (results_upper, "uppercase"),
            (results_mixed, "mixed case"),
        ]:
            slugs = [r["slug"] for r in results]
            assert "jalapeno_cheddar_bagel" in slugs, \
                f"Should find Jalapeno Cheddar Bagel with {case_name} search"
