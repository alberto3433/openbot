"""
Resiliency Test Batch 2: Ambiguous Item Orders

Tests the system's ability to handle ambiguous orders where the user's request
could match multiple items and needs clarification or disambiguation.
"""

import pytest
from sandwich_bot.tasks.state_machine import OrderStateMachine, OrderPhase
from sandwich_bot.tasks.models import OrderTask, BagelItemTask, CoffeeItemTask, MenuItemTask


class TestAmbiguousItemOrders:
    """Batch 2: Ambiguous Item Orders."""

    def test_orange_juice_shows_options(self):
        """
        Test: User says "orange juice" which matches multiple sizes/brands.

        Scenario:
        - User says: "orange juice"
        - Expected: System either adds a default OJ or asks which one they want
        - Should NOT error or return empty
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("orange juice", order)

        # Should have a response (not an error)
        assert result.message is not None
        assert len(result.message) > 0

        # Should either:
        # 1. Add an item and confirm, OR
        # 2. Ask for clarification about which OJ
        items = result.order.items.get_active_items()
        has_item = len(items) > 0
        asks_clarification = any(word in result.message.lower() for word in [
            "which", "what size", "tropicana", "fresh", "would you like"
        ])

        assert has_item or asks_clarification, \
            f"Should either add OJ or ask for clarification. Message: {result.message}"

    def test_muffin_shows_options(self):
        """
        Test: User says "muffin" which matches multiple flavors.

        Scenario:
        - User says: "muffin"
        - Expected: System asks which flavor OR shows options
        - Should NOT just add a random muffin without asking
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("muffin", order)

        # Should have a response
        assert result.message is not None

        # Should ask for clarification about flavor
        # OR show available options
        message_lower = result.message.lower()
        asks_flavor = any(word in message_lower for word in [
            "which", "what kind", "what flavor", "blueberry", "chocolate",
            "corn", "bran", "would you like"
        ])

        assert asks_flavor, \
            f"Should ask which muffin flavor. Message: {result.message}"

    def test_coffee_asks_for_size_and_temp(self):
        """
        Test: User says "coffee" which needs size and hot/iced.

        Scenario:
        - User says: "coffee"
        - Expected: System asks for size or adds with default and asks to confirm
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("coffee", order)

        # Should have a response
        assert result.message is not None

        # Should either ask about size/temp OR add coffee and start configuring
        coffees = [i for i in result.order.items.items if isinstance(i, CoffeeItemTask)]

        if coffees:
            # Coffee was added - check if it's asking for configuration
            coffee = coffees[0]
            needs_config = coffee.size is None or coffee.iced is None
            if needs_config:
                # Should be asking about size or hot/iced
                assert any(word in result.message.lower() for word in [
                    "size", "small", "medium", "large", "hot", "iced"
                ]), f"Should ask about size/temp. Message: {result.message}"
        else:
            # No coffee added yet - should be asking for clarification
            assert any(word in result.message.lower() for word in [
                "size", "small", "medium", "large", "hot", "iced", "drip", "latte"
            ]), f"Should ask about coffee preferences. Message: {result.message}"

    def test_bagel_with_cream_cheese_asks_flavor(self):
        """
        Test: User says "bagel with cream cheese" - should ask which flavor.

        Scenario:
        - User says: "bagel with cream cheese"
        - Expected: System adds bagel and asks about cream cheese flavor
                    OR asks about bagel type first
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("bagel with cream cheese", order)

        # Should have a response
        assert result.message is not None

        # Should have added a bagel or be asking about it
        bagels = [i for i in result.order.items.items if isinstance(i, BagelItemTask)]

        # Either:
        # 1. Bagel was added (possibly asking about type or cream cheese flavor)
        # 2. Still asking for clarification
        message_lower = result.message.lower()

        if bagels:
            # Bagel added - should be asking about type, toasted, or cream cheese
            assert any(word in message_lower for word in [
                "what type", "which bagel", "toasted", "plain", "veggie",
                "scallion", "what kind", "cream cheese"
            ]) or "anything else" in message_lower, \
                f"Should configure bagel or confirm. Message: {result.message}"
        else:
            # Should be asking about the bagel
            assert any(word in message_lower for word in [
                "what type", "which bagel", "what kind"
            ]), f"Should ask about bagel type. Message: {result.message}"

    def test_the_classic_matches_speed_menu(self):
        """
        Test: User says "the classic" which should match a speed menu item.

        Scenario:
        - User says: "the classic"
        - Expected: Should match "The Classic" or "The Classic BEC" speed menu item
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("the classic", order)

        # Should have a response
        assert result.message is not None

        # Should have added an item OR be asking for clarification
        items = result.order.items.get_active_items()
        message_lower = result.message.lower()

        if items:
            # Check if it's a speed menu item (MenuItemTask) or asking to configure
            menu_items = [i for i in items if isinstance(i, MenuItemTask)]
            bagels = [i for i in items if isinstance(i, BagelItemTask)]

            # Should have added The Classic as a speed menu item
            if menu_items:
                item = menu_items[0]
                assert "classic" in (item.menu_item_name or "").lower(), \
                    f"Should be The Classic. Got: {item.menu_item_name}"
            elif bagels:
                # Could be configured as a bagel
                assert "classic" in message_lower or "bagel" in message_lower
        else:
            # Should be asking which Classic they want
            assert any(word in message_lower for word in [
                "classic", "bec", "which"
            ]), f"Should reference The Classic. Message: {result.message}"
