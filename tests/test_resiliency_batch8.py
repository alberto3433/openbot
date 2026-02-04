"""
Resiliency Test Batch 8: Menu Inquiries

Tests the system's ability to handle questions about the menu,
prices, and store information.
"""

from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
from orderbot.tasks.models import OrderTask


class TestMenuInquiries:
    """Batch 8: Menu Inquiries."""

    def test_what_bagels_do_you_have(self):
        """
        Test: User asks about available bagels.

        Scenario:
        - User says: "what bagels do you have?"
        - Expected: System lists available bagel types
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what bagels do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should mention bagels or list options
        message_lower = result.message.lower()
        mentions_bagels = any(word in message_lower for word in [
            "plain", "everything", "sesame", "poppy", "bagel", "have", "offer"
        ])

        assert mentions_bagels, \
            f"Should list bagel options. Message: {result.message}"

    def test_what_types_of_bread_do_you_have(self):
        """
        Test: User asks about available bread types.

        Scenario:
        - User says: "what types of bread do you have?"
        - Expected: System lists bread options (not generic category list)

        This tests that attribute slugs (like "bread") are recognized
        even when the user doesn't mention the item type (like "bagel").
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what types of bread do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should start with "For bread, we have" indicating attribute inquiry response
        message_lower = result.message.lower()
        is_attribute_response = "for bread, we have" in message_lower

        # Should list actual bread types (bagels, bialy, wrap, croissant, etc.)
        lists_bread_options = any(word in message_lower for word in [
            "bagel", "bialy", "wrap", "croissant", "roll", "bread"
        ])

        # Should NOT return generic category list (categories like "bagels", "sandwiches")
        # A generic response would say something like "We have Bagels, Sandwiches, Drinks..."
        is_generic_category_response = (
            "bagels," in message_lower and "sandwiches" in message_lower
        )

        assert is_attribute_response, \
            f"Should respond with 'For bread, we have...'. Message: {result.message}"
        assert lists_bread_options, \
            f"Should list bread options. Message: {result.message}"
        assert not is_generic_category_response, \
            f"Should NOT return generic category list. Message: {result.message}"

    def test_what_type_of_omelettes_do_you_have(self):
        """
        Test: User asks about omelette types - should show omelette options, NOT bread.

        This tests that the data-driven attribute inquiry system correctly uses
        the item type's primary attribute when signal words like "type" are used,
        instead of falling back to hardcoded mappings like "type" -> "bread".

        Scenario:
        - User says: "what type of omelettes do you have?"
        - Expected: System lists omelette options (cheese types, toppings, etc.),
          NOT bread options
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what type of omelettes do you have?", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should NOT return bread options
        is_bread_response = "for bread, we have" in message_lower
        assert not is_bread_response, \
            f"Should NOT show bread options for omelette query. Message: {result.message}"

        # Should mention omelette-related things (cheese, options, omelette)
        # or list specific omelette items
        mentions_omelette_context = any(word in message_lower for word in [
            "omelette", "omelet", "cheese", "western", "veggie", "options"
        ])

        assert mentions_omelette_context, \
            f"Should mention omelette-related options. Message: {result.message}"

    def test_how_much_is_a_latte(self):
        """
        Test: User asks about latte price.

        Scenario:
        - User says: "how much is a latte?"
        - Expected: System responds about pricing (may not have info)
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("how much is a latte?", order)

        # Should have a response
        assert result.message is not None

        # Should acknowledge the price question (even if no info available)
        message_lower = result.message.lower()
        responds = any(word in message_lower for word in [
            "$", "price", "cost", "latte", "small", "medium", "large",
            "pricing", "sorry", "don't have", "information"
        ])

        assert responds, \
            f"Should respond to price question. Message: {result.message}"

    def test_whats_on_the_classic(self):
        """
        Test: User asks what's on a menu item.

        Scenario:
        - User says: "what's on the classic?"
        - Expected: System describes The Classic
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what's on the classic?", order)

        # Should have a response
        assert result.message is not None

        # Should describe the item
        message_lower = result.message.lower()
        describes = any(word in message_lower for word in [
            "classic", "bacon", "egg", "cheese", "cream cheese", "comes with"
        ])

        assert describes, \
            f"Should describe The Classic. Message: {result.message}"

    def test_what_drinks_do_you_have(self):
        """
        Test: User asks about available drinks.

        Scenario:
        - User says: "what drinks do you have?"
        - Expected: System lists drink options
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what drinks do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should list drinks or categories
        message_lower = result.message.lower()
        mentions_drinks = any(word in message_lower for word in [
            "coffee", "latte", "espresso", "tea", "juice", "soda",
            "drink", "beverage", "have", "offer"
        ])

        assert mentions_drinks, \
            f"Should list drink options. Message: {result.message}"

    def test_what_sandwiches_do_you_have(self):
        """
        Test: User asks about sandwiches.

        Scenario:
        - User says: "what sandwiches do you have?"
        - Expected: System lists sandwich options
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what sandwiches do you have?", order)

        # Should have a response
        assert result.message is not None

        # Should mention sandwiches
        message_lower = result.message.lower()
        mentions_sandwiches = any(word in message_lower for word in [
            "sandwich", "blt", "tuna", "egg", "classic", "have", "offer"
        ])

        assert mentions_sandwiches, \
            f"Should list sandwich options. Message: {result.message}"

    def test_what_iced_drinks_do_you_have(self):
        """
        Test: User asks about iced drinks.

        Scenario:
        - User says: "what iced drinks do you have"
        - Expected: System lists iced drinks (like Iced Coffee, Iced Tea)
        - NOT generic category list or all categories

        This tests the "adjective + category" pattern handling where
        "iced drinks" should find the drink category and filter by "iced".
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what iced drinks do you have", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should mention iced items specifically
        mentions_iced = "iced" in message_lower

        # Should NOT be a generic category listing
        is_category_list = (
            "salads" in message_lower and
            "pastries" in message_lower and
            "sandwiches" in message_lower
        )

        # Should NOT say "various drink options"
        is_generic_response = "various" in message_lower and "options" in message_lower

        assert not is_category_list, \
            f"Should NOT list all categories. Message: {result.message}"
        assert not is_generic_response, \
            f"Should NOT give generic 'various options' response. Message: {result.message}"
        assert mentions_iced, \
            f"Should list iced items. Message: {result.message}"

    def test_what_kind_of_drinks_do_you_have(self):
        """
        Test: User asks what kind of drinks are available.

        Scenario:
        - User says: "what kind of drinks do you have?"
        - Expected: System lists drink items (same as "what drinks do you have")
        - NOT attribute options (like bread types)
        - NOT generic "various options" response

        This tests that "what kind of X" with non-configurable item types
        is treated as a menu query, not an attribute inquiry.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what kind of drinks do you have?", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should list actual drink items (same as "what drinks do you have")
        lists_drinks = any(word in message_lower for word in [
            "coffee", "latte", "tea", "juice", "soda", "espresso"
        ])

        # Should NOT return bread/bagel options (wrong attribute resolution)
        returns_bread = "for bread" in message_lower or "plain" in message_lower

        # Should NOT be generic "various options" response
        is_generic = "various" in message_lower and "options" in message_lower

        assert lists_drinks, \
            f"Should list drink items. Message: {result.message}"
        assert not returns_bread, \
            f"Should NOT return bread options. Message: {result.message}"
        assert not is_generic, \
            f"Should NOT give generic 'various options' response. Message: {result.message}"

    def test_what_kinds_of_sweetener_do_you_have(self):
        """
        Test: User asks about available sweeteners.

        Scenario:
        - User says: "what kinds of sweetener do you have?"
        - Expected: System lists sweetener options (Sugar, Splenda, etc.)
        - NOT generic category list

        This tests that ingredient categories (like "sweetener") are
        recognized and routed to the modifier inquiry handler.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what kinds of sweetener do you have?", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should NOT return generic category list
        is_category_list = (
            "salads" in message_lower and
            "sandwiches" in message_lower
        )

        # Should mention sweetener-related terms
        mentions_sweeteners = any(word in message_lower for word in [
            "sugar", "splenda", "stevia", "sweetener", "honey", "sweet"
        ])

        assert not is_category_list, \
            f"Should NOT list all categories. Message: {result.message}"
        assert mentions_sweeteners, \
            f"Should list sweetener options. Message: {result.message}"

    def test_what_kinds_of_syrups_do_you_have(self):
        """
        Test: User asks about available syrups.

        Scenario:
        - User says: "what kinds of syrups do you have?"
        - Expected: System lists syrup options (Vanilla, Caramel, etc.)
        - NOT generic category list

        This tests that ingredient categories (like "syrup") are
        recognized and routed to the modifier inquiry handler.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what kinds of syrups do you have?", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should NOT return generic category list
        is_category_list = (
            "salads" in message_lower and
            "sandwiches" in message_lower
        )

        # Should mention syrup-related terms
        mentions_syrups = any(word in message_lower for word in [
            "vanilla", "caramel", "hazelnut", "syrup", "flavor"
        ])

        assert not is_category_list, \
            f"Should NOT list all categories. Message: {result.message}"
        assert mentions_syrups, \
            f"Should list syrup options. Message: {result.message}"

    def test_what_tea_flavors_do_you_have(self):
        """
        Test: User asks about tea flavors.

        Scenario:
        - User says: "what tea flavors do you have?"
        - Expected: System lists tea flavor options (English Breakfast, Green Tea, Earl Gray, etc.)
        - NOT generic category list

        This tests compound attribute resolution where "tea" + "flavors" = "tea_flavor" global attribute.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what tea flavors do you have?", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should NOT be a generic category listing
        is_category_list = (
            "salads" in message_lower and
            "sandwiches" in message_lower
        )

        # Should mention tea flavor options from the tea_flavor global attribute
        mentions_tea_flavors = any(word in message_lower for word in [
            "english breakfast", "green tea", "earl gray", "earl grey",
            "peppermint", "camomile", "raspberry", "tea"
        ])

        assert not is_category_list, \
            f"Should NOT list all categories. Message: {result.message}"
        assert mentions_tea_flavors, \
            f"Should list tea flavor options. Message: {result.message}"

    def test_what_chai_flavors_do_you_have(self):
        """
        Test: User asks about chai flavors.

        Scenario:
        - User says: "what chai flavors do you have?"
        - Expected: System lists chai flavor options (Spiced Chai, Vanilla Chai, etc.)
        - NOT generic category list

        This tests compound attribute resolution where "chai" + "flavors" = "chai_flavor" global attribute.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("what chai flavors do you have?", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should NOT be a generic category listing
        is_category_list = (
            "salads" in message_lower and
            "sandwiches" in message_lower
        )

        # Should mention chai flavor options from the chai_flavor global attribute
        mentions_chai_flavors = any(word in message_lower for word in [
            "spiced", "vanilla", "chai", "flavor"
        ])

        assert not is_category_list, \
            f"Should NOT list all categories. Message: {result.message}"
        assert mentions_chai_flavors, \
            f"Should list chai flavor options. Message: {result.message}"

    def test_i_want_caramel_syrup(self):
        """
        Test: User orders just a modifier without an item.

        Scenario:
        - User says: "I want caramel syrup"
        - Expected: System suggests items that can have caramel syrup
        - NOT generic "item not found" response

        This tests the standalone ingredient suggestion feature where
        ordering just a modifier (without specifying a drink/item) triggers
        helpful suggestions of items that can have that modifier.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()
        result = sm.process("I want caramel syrup", order)

        # Should have a response
        assert result.message is not None

        message_lower = result.message.lower()

        # Should suggest items that can have caramel syrup
        suggests_items = any(word in message_lower for word in [
            "latte", "cappuccino", "mocha", "coffee", "espresso", "could make"
        ])

        # Should mention caramel syrup
        mentions_ingredient = "caramel" in message_lower

        # Should NOT say "couldn't find" or "not on the menu"
        is_not_found_response = (
            "couldn't find" in message_lower or
            "not on" in message_lower or
            "don't have" in message_lower
        )

        assert not is_not_found_response, \
            f"Should NOT say item not found. Message: {result.message}"
        assert suggests_items, \
            f"Should suggest items that can have caramel syrup. Message: {result.message}"
        assert mentions_ingredient, \
            f"Should mention caramel. Message: {result.message}"

    def test_ingredient_suggestion_applies_to_selected_item(self):
        """
        Test: User orders modifier first, then selects an item.

        Full conversation flow:
        1. User says: "I want caramel syrup"
        2. Bot suggests items that can have caramel
        3. User says: "yes"
        4. Bot asks: "Great! Which would you like - X, Y, Z?"
        5. User says: "iced coffee"
        6. Item should be created with caramel syrup already applied

        This tests the pending_ingredient_to_apply feature that preserves
        the ingredient across the disambiguation/selection turns.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Step 1: Order just the modifier
        result1 = sm.process("I want caramel syrup", order)
        assert "caramel" in result1.message.lower()
        assert "would you like" in result1.message.lower()

        # Step 2: Confirm we want one of the suggested items
        result2 = sm.process("yes", result1.order)
        assert "which would you like" in result2.message.lower()

        # Step 3: Select an item (iced coffee)
        result3 = sm.process("iced coffee large", result2.order)

        # Should have added the item to the order
        active_items = result3.order.items.get_active_items()
        assert len(active_items) >= 1, "Should have added an item"

        # Find the iced coffee item
        coffee_item = None
        for item in active_items:
            item_name = getattr(item, 'menu_item_name', '').lower()
            if 'coffee' in item_name or 'iced' in item_name:
                coffee_item = item
                break

        assert coffee_item is not None, \
            f"Should have an iced coffee item. Items: {[getattr(i, 'menu_item_name', 'unknown') for i in active_items]}"

        # Check that caramel was applied as a modifier
        modifiers = getattr(coffee_item, 'modifiers', [])
        modifier_slugs = [m.get('slug', '').lower() for m in modifiers]

        has_caramel = any('caramel' in slug for slug in modifier_slugs)
        assert has_caramel, \
            f"Caramel should be applied to the coffee. Modifiers: {modifiers}"

    def test_ingredient_suggestion_direct_item_selection(self):
        """
        Test: User orders modifier first, then directly picks an item (skips "yes").

        Conversation flow:
        1. User says: "I want caramel syrup"
        2. Bot suggests items
        3. User says: "iced latte" (directly picks item, skips "yes")
        4. Item should be created with caramel syrup already applied

        This is the more natural flow where users skip the confirmation step.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value

        sm = OrderStateMachine()

        # Step 1: Order just the modifier
        result1 = sm.process("I want caramel syrup", order)
        assert "caramel" in result1.message.lower()
        assert "would you like" in result1.message.lower()

        # Step 2: Directly pick an item (skip "yes")
        result2 = sm.process("iced latte large", result1.order)

        # Should have added the item to the order
        active_items = result2.order.items.get_active_items()
        assert len(active_items) >= 1, "Should have added an item"

        # Find the iced latte item
        latte_item = None
        for item in active_items:
            item_name = getattr(item, 'menu_item_name', '').lower()
            if 'latte' in item_name:
                latte_item = item
                break

        assert latte_item is not None, \
            f"Should have an iced latte item. Items: {[getattr(i, 'menu_item_name', 'unknown') for i in active_items]}"

        # Check that caramel was applied as a modifier
        modifiers = getattr(latte_item, 'modifiers', [])
        modifier_slugs = [m.get('slug', '').lower() for m in modifiers]

        has_caramel = any('caramel' in slug for slug in modifier_slugs)
        assert has_caramel, \
            f"Caramel should be applied to the latte. Modifiers: {modifiers}"
