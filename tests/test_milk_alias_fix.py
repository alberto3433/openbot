"""Test that 'milk' is correctly recognized in multi-select config flow.

This tests the fix for GitHub issue where 'milk sugar' during espresso
configuration would only recognize 'sugar' but report 'milk' as unmatched.

The root cause was the disambiguation logic incorrectly triggering when
a single token like 'milk sugar' matched 2 options. The fix checks if
the number of words in the token matches the number of options found,
which indicates each word matched a distinct option (not ambiguous).
"""
import pytest
from orderbot.cache import menu_cache
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask


class TestMilkAliasInMultiSelect:
    """Test milk recognition in multi-select config flow."""

    def test_option_matcher_matches_milk_in_whole_milk(self, menu_cache_loaded):
        """Verify 'milk' matches 'Whole Milk' via word boundary matching."""
        from orderbot.tasks.utils import OptionMatcher, InputNormalizer

        espresso_attrs = menu_cache.get_item_type_attributes('espresso')
        mss_attr = espresso_attrs.get('milk_sweetener_syrup')
        options = mss_attr.get('options', []) if mss_attr else []

        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)

        # "milk" should match only "Whole Milk" (other milks have must_match filters)
        milk_matches = matcher.match_multiple("milk", options)
        assert len(milk_matches) == 1, f"Expected 1 match, got {len(milk_matches)}"
        assert milk_matches[0]['slug'] == 'whole_milk'

    def test_milk_sugar_matches_both_options(self, menu_cache_loaded):
        """Verify 'milk sugar' matches both Whole Milk and Domino Sugar."""
        from orderbot.tasks.utils import OptionMatcher, InputNormalizer

        espresso_attrs = menu_cache.get_item_type_attributes('espresso')
        mss_attr = espresso_attrs.get('milk_sweetener_syrup')
        options = mss_attr.get('options', []) if mss_attr else []

        normalizer = InputNormalizer()
        matcher = OptionMatcher(normalizer)

        result = matcher.match_multiple_with_unmatched("milk sugar", options)
        slugs = [o['slug'] for o in result.matched]

        assert 'whole_milk' in slugs, f"'milk' should match 'whole_milk', got: {slugs}"
        assert 'domino_sugar' in slugs, f"'sugar' should match 'domino_sugar', got: {slugs}"
        assert result.unmatched == [], f"Expected no unmatched tokens, got: {result.unmatched}"

    def test_milk_sugar_in_espresso_config_adds_both(self, menu_cache_loaded):
        """Test full espresso config flow: 'milk sugar' should add both modifiers."""
        order = OrderTask()
        sm = OrderStateMachine()

        # Add espresso
        result = sm.process('espresso', order)
        order = result.order

        # Skip shots
        result = sm.process('no', order)
        order = result.order
        assert 'milk' in result.message.lower() or 'sweetener' in result.message.lower()

        # Test the milk sugar input
        result = sm.process('milk sugar', order)
        order = result.order

        # Should have moved past the question (not asking for disambiguation)
        assert "don't have milk" not in result.message.lower(), \
            f"System incorrectly said 'we don't have milk': {result.message}"
        assert "which" not in result.message.lower(), \
            f"System incorrectly asked for disambiguation: {result.message}"

        # Check that both were added
        item = order.items.items[0]
        selections = item.get_selections('milk_sweetener_syrup')
        slugs = [s.get('slug') for s in selections]

        assert 'whole_milk' in slugs, f"'milk' was not added, got: {slugs}"
        assert 'domino_sugar' in slugs, f"'sugar' was not added, got: {slugs}"


class TestMoreCheeseForAttributeSelection:
    """Test 'more cheese' increments quantity when cheese is an attribute category."""

    def _navigate_to_cheese_question(self, sm, order):
        """Helper to navigate through egg sandwich config to cheese question.

        Flow: bread -> toasted -> egg_style -> cheese
        """
        # Start with egg and cheese sandwich
        result = sm.process('egg and cheese sandwich', order)
        order = result.order

        # Answer bread question
        result = sm.process('plain', order)
        order = result.order

        # Answer toasted question
        result = sm.process('yes', order)
        order = result.order

        # Answer egg style question
        result = sm.process('scrambled', order)
        order = result.order

        return order, result

    def test_more_cheese_increments_existing_provolone(self, menu_cache_loaded):
        """After selecting provolone, 'more cheese' should increment its quantity."""
        order = OrderTask()
        sm = OrderStateMachine()

        order, result = self._navigate_to_cheese_question(sm, order)
        # Now at cheese question, select provolone
        assert 'cheese' in result.message.lower(), f"Expected cheese question, got: {result.message}"

        result = sm.process('provolone', order)
        order = result.order

        # Now at customization checkpoint, say "more cheese"
        result = sm.process('more cheese', order)
        order = result.order

        # Should NOT say "we don't have more cheese"
        assert "don't have" not in result.message.lower(), \
            f"System incorrectly said we don't have it: {result.message}"

        # Provolone should now have quantity 2
        item = order.items.items[0]
        cheese_selection = item.get_selection('cheese')
        assert cheese_selection is not None, \
            f"Cheese selection should exist. Selections: {item.selections}"
        assert cheese_selection.get('quantity', 1) == 2, \
            f"Expected quantity=2, got: {cheese_selection}"

    def test_extra_cheese_increments_existing_selection(self, menu_cache_loaded):
        """'extra cheese' should also increment the cheese selection."""
        order = OrderTask()
        sm = OrderStateMachine()

        order, result = self._navigate_to_cheese_question(sm, order)
        result = sm.process('swiss', order)
        order = result.order

        # Say "extra cheese" at customization checkpoint
        result = sm.process('extra cheese', order)
        order = result.order

        item = order.items.items[0]
        cheese_selection = item.get_selection('cheese')
        assert cheese_selection is not None, \
            f"Cheese selection should exist. Selections: {item.selections}"
        assert cheese_selection.get('quantity', 1) == 2, \
            f"Expected quantity=2, got: {cheese_selection}"

    def test_double_cheese_sets_absolute_quantity(self, menu_cache_loaded):
        """'double cheese' should set quantity to 2 (absolute, not additive)."""
        order = OrderTask()
        sm = OrderStateMachine()

        order, result = self._navigate_to_cheese_question(sm, order)
        result = sm.process('cheddar', order)
        order = result.order

        # Say "double cheese"
        result = sm.process('double cheese', order)
        order = result.order

        item = order.items.items[0]
        cheese_selection = item.get_selection('cheese')
        assert cheese_selection is not None, \
            f"Cheese selection should exist. Selections: {item.selections}"
        assert cheese_selection.get('quantity', 1) == 2, \
            f"Expected quantity=2, got: {cheese_selection}"

    def test_triple_cheese_sets_quantity_three(self, menu_cache_loaded):
        """'triple cheese' should set quantity to 3."""
        order = OrderTask()
        sm = OrderStateMachine()

        order, result = self._navigate_to_cheese_question(sm, order)
        result = sm.process('american', order)
        order = result.order

        result = sm.process('triple cheese', order)
        order = result.order

        item = order.items.items[0]
        cheese_selection = item.get_selection('cheese')
        assert cheese_selection is not None, \
            f"Cheese selection should exist. Selections: {item.selections}"
        assert cheese_selection.get('quantity', 1) == 3, \
            f"Expected quantity=3, got: {cheese_selection}"

    def test_more_cheese_in_taking_items_phase(self, menu_cache_loaded):
        """'more cheese' in TAKING_ITEMS phase should increment cheese quantity.

        This tests the fix for the bug where saying 'more cheese' after completing
        an item's configuration would result in 'More of what?' instead of
        incrementing the cheese quantity. The root cause was that 'cheese' is also
        an item type slug (Cheese by the Pound), so the parser incorrectly thought
        the user was trying to order a new item.
        """
        from orderbot.tasks.schemas.phases import OrderPhase

        order = OrderTask()
        sm = OrderStateMachine()

        # Navigate to cheese question and complete the item
        order, result = self._navigate_to_cheese_question(sm, order)
        result = sm.process('american', order)
        order = result.order

        # Complete the item by saying "no more"
        result = sm.process('no more', order)
        order = result.order

        # Verify we're in TAKING_ITEMS phase
        assert order.phase == OrderPhase.TAKING_ITEMS, \
            f"Expected TAKING_ITEMS phase, got: {order.phase}"

        # Now say "more cheese" - this is where the bug occurred
        result = sm.process('more cheese', order)
        order = result.order

        # Should NOT say "More of what?" or ask what to list
        assert "more of what" not in result.message.lower(), \
            f"System incorrectly asked 'More of what?': {result.message}"
        assert "what would you like me to list" not in result.message.lower(), \
            f"System incorrectly asked to list items: {result.message}"
        assert "don't have" not in result.message.lower(), \
            f"System incorrectly said we don't have it: {result.message}"

        # Cheese should now have quantity 2
        item = order.items.items[0]
        cheese_selection = item.get_selection('cheese')
        assert cheese_selection is not None, \
            f"Cheese selection should exist. Selections: {item.selections}"
        assert cheese_selection.get('quantity', 1) == 2, \
            f"Expected quantity=2 after 'more cheese', got: {cheese_selection}"

    def test_extra_cheese_in_taking_items_phase(self, menu_cache_loaded):
        """'extra cheese' in TAKING_ITEMS phase should also increment cheese quantity."""
        from orderbot.tasks.schemas.phases import OrderPhase

        order = OrderTask()
        sm = OrderStateMachine()

        # Navigate to cheese question and complete the item
        order, result = self._navigate_to_cheese_question(sm, order)
        result = sm.process('swiss', order)
        order = result.order

        # Complete the item by saying "no more"
        result = sm.process('no more', order)
        order = result.order

        # Verify we're in TAKING_ITEMS phase
        assert order.phase == OrderPhase.TAKING_ITEMS, \
            f"Expected TAKING_ITEMS phase, got: {order.phase}"

        # Now say "extra cheese" - this should also increment
        result = sm.process('extra cheese', order)
        order = result.order

        # Should NOT trigger disambiguation or error
        assert "more of what" not in result.message.lower(), \
            f"System incorrectly asked 'More of what?': {result.message}"

        # Cheese should now have quantity 2
        item = order.items.items[0]
        cheese_selection = item.get_selection('cheese')
        assert cheese_selection is not None, \
            f"Cheese selection should exist. Selections: {item.selections}"
        assert cheese_selection.get('quantity', 1) == 2, \
            f"Expected quantity=2 after 'extra cheese', got: {cheese_selection}"
