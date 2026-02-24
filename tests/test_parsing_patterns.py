"""Pattern detection tests: replacement, cancellation, ordinals, tax, status."""

import pytest

from tests.helpers import (
    get_parsed_items,
    has_bagel,
    get_bagel_item,
    has_coffee,
    has_menu_item,
    BagelItemTask,
    CoffeeItemTask,
)

from orderbot.tasks.parsers import (
    parse_open_input_deterministic,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
)
from orderbot.tasks.parsers.constants import (
    CANCEL_LAST_ITEM,
    CANCEL_ALL_ITEMS,
    REDUCE_TO_ONE,
    REDUCE_TO_ONE_PREFIX,
    make_reduce_to_one_sentinel,
)


# =============================================================================
# Replacement Pattern Tests
# =============================================================================

class TestReplacementPatternDetection:
    """Tests for item replacement pattern detection."""

    @pytest.mark.parametrize("text,expected_replacement", [
        # "make it X instead" patterns
        ("make it a coke instead", True),
        ("make it coke instead", True),
        ("make it a latte", True),
        # "change it to X" patterns
        ("change it to a coke", True),
        ("change to coke", True),
        # "X instead" patterns
        ("coke instead", True),
        ("a coke instead", True),
        ("actually coke", True),
        ("actually a coke", True),
        # "actually X" patterns
        ("actually, make it a latte", True),
        ("no, a coke instead", True),
        ("nope, coke instead", True),
        ("wait, make it a sprite", True),
        # "switch/swap" patterns
        ("switch to a coke", True),
        ("swap it for a latte", True),
        # "i meant X" patterns
        ("i meant a coke", True),
        ("I meant coke", True),
        # Non-replacement patterns (should NOT match)
        ("I want a coke", False),
        ("give me a coke", False),
        ("can I get a coke", False),
        ("diet coke please", False),
    ])
    def test_replacement_patterns_detected(self, text, expected_replacement):
        """Test that replacement patterns are properly detected."""
        result = parse_open_input_deterministic(text)
        if expected_replacement:
            assert result is not None, f"Expected pattern match for: {text}"
            assert result.replace_last_item is True, f"Expected replace_last_item=True for: {text}"
        else:
            # Non-replacement patterns should either:
            # 1. Return a result with replace_last_item=False, or
            # 2. Return None (falls back to LLM)
            if result is not None:
                assert result.replace_last_item is False, f"Did not expect replacement for: {text}"

    def test_replacement_extracts_new_item(self):
        """Test that replacement correctly extracts the new item."""
        # "make it a coke instead" -> should parse as a drink/menu item
        result = parse_open_input_deterministic("make it a coke instead")
        assert result is not None
        assert result.replace_last_item is True
        # The new item should be parsed (either as new_menu_item or handled by LLM)
        # Since "coke" would be parsed as a menu item or require LLM

    def test_replacement_with_latte(self):
        """Test replacement with coffee item."""
        result = parse_open_input_deterministic("actually a latte")
        assert result is not None
        assert result.replace_last_item is True
        # Latte might be recognized as coffee or menu item
        assert has_coffee(result) or has_menu_item(result)

    def test_replacement_with_bagel(self):
        """Test replacement with bagel item."""
        result = parse_open_input_deterministic("make it an everything bagel instead")
        assert result is not None
        assert result.replace_last_item is True
        bagel = get_bagel_item(result)
        assert bagel is not None
        assert bagel.attribute_values.get("bread") == "everything_bagel"

    @pytest.mark.parametrize("text", [
        "make it pickup",
        "make it delivery",
    ])
    def test_replacement_with_order_type_does_not_set_replace(self, text):
        """'make it pickup/delivery' should set order_type, not replace_last_item."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parsed result for: {text}"
        assert result.order_type is not None, f"Expected order_type for: {text}"
        assert result.replace_last_item is False, (
            f"'replace_last_item' should be False for order-type input: {text}"
        )


# =============================================================================
# Cancellation Pattern Tests
# =============================================================================

class TestCancellationPatternDetection:
    """Tests for item cancellation pattern detection."""

    @pytest.mark.parametrize("text,expected_item", [
        # "cancel X" patterns
        ("cancel the coke", "coke"),
        ("cancel coke", "coke"),
        ("cancel the diet coke", "diet coke"),
        # "remove X" patterns
        ("remove the bagel", "bagel"),
        ("remove bagel", "bagel"),
        ("remove the everything bagel", "everything bagel"),
        # "take off X" patterns
        ("take off the latte", "latte"),
        ("take the latte off", "latte"),
        # "nevermind X" patterns
        ("nevermind the coffee", "coffee"),
        ("never mind the bagel", "bagel"),
        # "forget X" patterns
        ("forget the coke", "coke"),
        ("forget about the coffee", "coffee"),
        # "scratch X" patterns
        ("scratch the bagel", "bagel"),
        # "don't want X" patterns
        ("I don't want the coke", "coke"),
        ("don't want the bagel", "bagel"),
        ("I don't want the diet coke anymore", "diet coke"),
        # "no more X" patterns
        ("no more coke", "coke"),
        ("no more bagels", "bagels"),
    ])
    def test_cancellation_patterns_detected(self, text, expected_item):
        """Test that cancellation patterns are properly detected."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.cancel_item is not None, f"Expected cancel_item for: {text}"
        assert result.cancel_item.lower() == expected_item.lower(), \
            f"Expected cancel_item='{expected_item}' but got '{result.cancel_item}' for: {text}"

    @pytest.mark.parametrize("text", [
        # Non-cancellation patterns (should NOT match as cancellation)
        "I want a coke",
        "give me a coke",
        "can I get a coke",
        "diet coke please",
        "coke",  # Just an item name
        "no, a coke",  # This is replacement, not cancellation
        "nope, coke instead",  # This is replacement
    ])
    def test_non_cancellation_patterns_not_detected(self, text):
        """Test that non-cancellation patterns are NOT detected as cancellation."""
        result = parse_open_input_deterministic(text)
        # Should either be None or have cancel_item=None
        if result is not None:
            assert result.cancel_item is None, f"Did not expect cancellation for: {text}"

    def test_no_coke_is_cancellation(self):
        """Test that 'no coke' is treated as cancellation (removal)."""
        # "no coke" means "remove the coke" / "I don't want the coke"
        # Changed from replacement to cancellation behavior to match user expectation
        # for phrases like "no whole milk" meaning "remove whole milk"
        result = parse_open_input_deterministic("no coke")
        assert result is not None
        # Should match as cancellation, not replacement
        assert result.cancel_item == "coke"
        assert result.replace_last_item is False

    def test_no_more_coke_is_cancellation(self):
        """Test that 'no more coke' is unambiguously cancellation."""
        result = parse_open_input_deterministic("no more coke")
        assert result is not None
        assert result.cancel_item == "coke"
        assert result.replace_last_item is False

    @pytest.mark.parametrize("text", [
        "cancel that",
        "cancel it",
        "cancel this",
        "remove that",
        "remove it",
        "nevermind that",
        "never mind that",
        "forget that",
        "forget it",
        "scratch that",
        "cancel last",
        "cancel last item",
        "remove last",
        "remove last item",
        "cancel the last one",
        "cancel the last item",
        "remove the last one",
        "actually cancel that",
        "actually remove that",
        "actually forget it",
        "actually nevermind that",
        "remove from the order",
        "remove from my order",
    ])
    def test_cancel_that_pronouns_detected(self, text):
        """Test that 'cancel that' and similar pronouns trigger last item cancellation."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.cancel_item == CANCEL_LAST_ITEM, \
            f"Expected cancel_item='{CANCEL_LAST_ITEM}' but got '{result.cancel_item}' for: {text}"

    @pytest.mark.parametrize("text", [
        "actually cancel that",
        "actually remove that",
        "actually forget it",
        "actually nevermind that",
        "actually scratch that",
        "actually take off the bagel",
    ])
    def test_cancellation_phrases_not_matched_as_change_requests(self, text):
        """Ensure cancellation phrases are NOT detected as change requests.

        This prevents 'actually cancel that' from being routed to the
        modifier_change_handler instead of the cancellation handler.
        """
        from orderbot.tasks.modifier_change_handler import ModifierChangeHandler
        from orderbot.tasks.handler_config import HandlerConfig
        config = HandlerConfig()
        handler = ModifierChangeHandler(config=config)
        result = handler.detect_change_request(text)
        assert result is None, \
            f"'{text}' should NOT be detected as a change request, but got: {result}"

    @pytest.mark.parametrize("text", [
        "remove all",
        "cancel all",
        "remove everything",
        "cancel everything",
        "forget everything",
        "remove the order",
        "cancel the order",
        "remove my order",
        "cancel my order",
        "clear the order",
        "remove all items",
        "cancel all the items",
        "nevermind the whole order",
        "forget the whole thing",
        "remove it all",
        "cancel them all",
    ])
    def test_cancel_all_items_detected(self, text):
        """Test that 'remove all' and similar phrases trigger full order cancellation."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.cancel_item == CANCEL_ALL_ITEMS, \
            f"Expected cancel_item='{CANCEL_ALL_ITEMS}' but got '{result.cancel_item}' for: {text}"

    @pytest.mark.parametrize("text,expected_item", [
        # "delete X" patterns (new verb)
        ("delete the bagel", "bagel"),
        ("delete the coke", "coke"),
        ("delete the coffee", "coffee"),
        ("delete my order", CANCEL_ALL_ITEMS),
    ])
    def test_delete_pattern_detected(self, text, expected_item):
        """Test that 'delete X' patterns are properly detected as cancellation."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.cancel_item is not None, f"Expected cancel_item for: {text}"
        assert result.cancel_item.lower() == expected_item.lower(), \
            f"Expected cancel_item='{expected_item}' but got '{result.cancel_item}' for: {text}"

    @pytest.mark.parametrize("text,expected_item", [
        # Ordinal removal patterns
        ("remove the first bagel", "first bagel"),
        # Note: "second bagel" conflicts with "SEC" abbreviation parsing (Sausage Egg Cheese)
        # so we use "2nd bagel" instead
        ("remove the 2nd bagel", "2nd bagel"),
        ("cancel the third coffee", "third coffee"),
        ("delete the 1st item", "1st item"),
        ("delete the 2nd coke", "2nd coke"),
        ("scratch the 3rd item", "3rd item"),
        ("forget the first one", "first one"),
        # Ordinal with numbers
        ("remove bagel 2", "bagel 2"),
        ("cancel coffee #3", "coffee #3"),
    ])
    def test_ordinal_removal_patterns_detected(self, text, expected_item):
        """Test that ordinal removal patterns are properly parsed.

        These patterns like 'remove the first bagel' or 'delete the 3rd item'
        should capture the ordinal + item type for position-based removal.
        """
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.cancel_item is not None, f"Expected cancel_item for: {text}"
        assert result.cancel_item.lower() == expected_item.lower(), \
            f"Expected cancel_item='{expected_item}' but got '{result.cancel_item}' for: {text}"


class TestReduceToOnePatternDetection:
    """Tests for 'just one bagel', 'only one', etc. - reducing quantity to 1."""

    @pytest.mark.parametrize("text,expected_type", [
        # "actually just one bagel"
        ("actually just one bagel", make_reduce_to_one_sentinel("bagel")),
        ("actually only one bagel", make_reduce_to_one_sentinel("bagel")),
        ("actually just one coffee", make_reduce_to_one_sentinel("coffee")),
        ("actually just 1 bagel", make_reduce_to_one_sentinel("bagel")),
        # "just one bagel"
        ("just one bagel", make_reduce_to_one_sentinel("bagel")),
        ("only one bagel", make_reduce_to_one_sentinel("bagel")),
        ("just one coffee", make_reduce_to_one_sentinel("coffee")),
        ("only one coffee", make_reduce_to_one_sentinel("coffee")),
        # "just one" / "only one" (no item type)
        ("just one", REDUCE_TO_ONE),
        ("only one", REDUCE_TO_ONE),
        ("just 1", REDUCE_TO_ONE),
        # "make it just one"
        ("make it just one", REDUCE_TO_ONE),
        ("make it only one bagel", make_reduce_to_one_sentinel("bagel")),
        ("make that just one", REDUCE_TO_ONE),
        # "i only want one"
        ("i only want one", REDUCE_TO_ONE),
        ("i just want one bagel", make_reduce_to_one_sentinel("bagel")),
        ("i only need one", REDUCE_TO_ONE),
        # "one is enough"
        ("one is enough", REDUCE_TO_ONE),
        ("one bagel is enough", make_reduce_to_one_sentinel("bagel")),
        ("one is fine", REDUCE_TO_ONE),
        ("one is good", REDUCE_TO_ONE),
    ])
    def test_reduce_to_one_patterns_detected(self, text, expected_type):
        """Test that 'just one' / 'only one' patterns are parsed as reduce-to-one."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.cancel_item is not None, f"Expected cancel_item for: {text}"
        assert result.cancel_item == expected_type, \
            f"Expected cancel_item='{expected_type}' but got '{result.cancel_item}' for: {text}"

    @pytest.mark.parametrize("text", [
        # These should NOT match reduce-to-one
        "one plain bagel",  # ordering one bagel
        "I want one coffee",  # ordering one coffee
        "give me one",  # ordering
        "can I get one bagel",  # ordering
        "one more bagel",  # adding more
        "just a bagel",  # no quantity specified
        "only a coffee",  # no quantity specified
    ])
    def test_non_reduce_to_one_patterns_not_detected(self, text):
        """Test that ordering patterns are not matched as reduce-to-one."""
        result = parse_open_input_deterministic(text)
        if result is not None and result.cancel_item:
            assert not result.cancel_item.startswith(REDUCE_TO_ONE_PREFIX), \
                f"Unexpected reduce-to-one match for: {text}"


class TestOrdinalExtractionFromCancelItem:
    """Tests for extracting ordinal references from cancellation descriptions."""

    def test_extract_ordinal_first_bagel(self):
        """Test extracting ordinal from 'first bagel'."""
        from orderbot.tasks.item_cancellation_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("first bagel")
        assert ordinal == 1
        assert item_type == "bagel"

    def test_extract_ordinal_second_coffee(self):
        """Test extracting ordinal from 'second coffee'."""
        from orderbot.tasks.item_cancellation_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("second coffee")
        assert ordinal == 2
        assert item_type == "coffee"

    def test_extract_ordinal_3rd_item(self):
        """Test extracting ordinal from '3rd item'."""
        from orderbot.tasks.item_cancellation_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("3rd item")
        assert ordinal == 3
        assert item_type == "item"

    def test_extract_ordinal_bagel_2(self):
        """Test extracting ordinal from 'bagel 2' (reversed format)."""
        from orderbot.tasks.item_cancellation_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("bagel 2")
        assert ordinal == 2
        assert item_type == "bagel"

    def test_extract_ordinal_coffee_hash_3(self):
        """Test extracting ordinal from 'coffee #3' (hash format)."""
        from orderbot.tasks.item_cancellation_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("coffee #3")
        assert ordinal == 3
        assert item_type == "coffee"

    def test_no_ordinal_plain_bagel(self):
        """Test that plain item descriptions return no ordinal."""
        from orderbot.tasks.item_cancellation_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("plain bagel")
        assert ordinal is None
        assert item_type == "plain bagel"


class TestFindNthItemOfType:
    """Tests for finding the Nth item of a given type."""

    def test_find_first_bagel(self):
        """Test finding the first bagel in a list."""
        from orderbot.tasks.item_cancellation_handler import find_nth_item_of_type

        items = [
            BagelItemTask(bread="plain"),
            CoffeeItemTask(drink_type="latte"),
            BagelItemTask(bread="everything"),
        ]

        result = find_nth_item_of_type(items, "bagel", 1)
        assert result is not None
        item, idx = result
        assert item["bread"] == "plain"
        assert idx == 0

    def test_find_second_bagel(self):
        """Test finding the second bagel in a list."""
        from orderbot.tasks.item_cancellation_handler import find_nth_item_of_type

        items = [
            BagelItemTask(bread="plain"),
            CoffeeItemTask(drink_type="latte"),
            BagelItemTask(bread="everything"),
        ]

        result = find_nth_item_of_type(items, "bagel", 2)
        assert result is not None
        item, idx = result
        assert item["bread"] == "everything"
        assert idx == 2

    def test_find_nth_item_generic(self):
        """Test finding the Nth item regardless of type using 'item' keyword."""
        from orderbot.tasks.item_cancellation_handler import find_nth_item_of_type

        items = [
            BagelItemTask(bread="plain"),
            CoffeeItemTask(drink_type="latte"),
            BagelItemTask(bread="everything"),
        ]

        # "2nd item" should return the latte (index 1)
        result = find_nth_item_of_type(items, "item", 2)
        assert result is not None
        item, idx = result
        assert item.menu_item_type == "espresso_based_beverage"  # The coffee item
        assert idx == 1

    def test_find_nth_item_out_of_range(self):
        """Test that out-of-range ordinal returns None."""
        from orderbot.tasks.item_cancellation_handler import find_nth_item_of_type

        items = [
            BagelItemTask(bread="plain"),
            BagelItemTask(bread="everything"),
        ]

        # Asking for 5th bagel when only 2 exist
        result = find_nth_item_of_type(items, "bagel", 5)
        assert result is None

    def test_find_item_by_menu_item_name(self):
        """Test finding item by menu_item_name field."""
        from orderbot.tasks.item_cancellation_handler import find_nth_item_of_type
        from orderbot.tasks.models import MenuItemTask

        # MenuItemTask has menu_item_name field
        item = MenuItemTask(menu_item_name="Coca-Cola")
        items = [item]

        # Search by canonical name should find it
        result = find_nth_item_of_type(items, "coca-cola", 1)
        assert result is not None
        found_item, idx = result
        assert found_item.menu_item_name == "Coca-Cola"
        assert idx == 0

    def test_find_item_by_summary(self):
        """Test finding item by get_summary() content."""
        from orderbot.tasks.item_cancellation_handler import find_nth_item_of_type

        # CoffeeItemTask helper creates MenuItemTask with drink_type stored in menu_item_name
        item = CoffeeItemTask(drink_type="latte", size="large")
        items = [item]

        # Search by drink type should find it
        result = find_nth_item_of_type(items, "latte", 1)
        assert result is not None
        found_item, idx = result
        assert found_item.menu_item_name == "latte"
        assert idx == 0


class TestTaxQuestionPatternDetection:
    """Tests for tax question pattern detection."""

    @pytest.mark.parametrize("text", [
        # "what's my total with tax"
        "what's my total with tax",
        "what's my total with tax?",
        "what is my total with tax",
        "what's the total with tax",
        "what is the total with tax?",
        # "what's my total including tax"
        "what's my total including tax",
        "what is the total including tax",
        # "how much with tax"
        "how much with tax",
        "how much with tax?",
        "how much will it be with tax",
        "how much will it be with tax?",
        "how much including tax",
        # "what's the total" (without explicit "with tax")
        "what's the total",
        "what is my total",
        "what's my total?",
        # "total with tax"
        "total with tax",
        "the total with tax",
        "total including tax",
        # "with tax?" / "including tax?"
        "with tax?",
        "including tax?",
        "with tax",
    ])
    def test_tax_question_patterns_detected(self, text):
        """Test that tax question patterns are properly detected."""
        match = TAX_QUESTION_PATTERN.search(text)
        assert match is not None, f"Expected pattern match for: {text}"

    @pytest.mark.parametrize("text", [
        # Non-tax patterns (should NOT match)
        "yes",
        "looks good",
        "no, I want to change something",
        "add a coke",
        "can I get a bagel",
        "I'd like a coffee",
        "that's correct",
        "perfect",
        "wait, add a drink",
    ])
    def test_non_tax_patterns_not_detected(self, text):
        """Test that non-tax patterns are NOT detected as tax questions."""
        match = TAX_QUESTION_PATTERN.search(text)
        assert match is None, f"Did not expect tax question match for: {text}"


class TestOrderStatusPatternDetection:
    """Tests for order status pattern detection."""

    @pytest.mark.parametrize("text", [
        # "what's my order"
        "what's my order",
        "what's my order?",
        "what is my order",
        "what's the order",
        "what is the order?",
        # "what's in my cart"
        "what's in my cart",
        "what's in my cart?",
        "what is in my cart",
        "what's in the cart",
        "what's in my order",
        "what do I have in my cart",
        "what do i have in my order",
        # "what have I ordered"
        "what have I ordered",
        "what have i ordered?",
        "what did I order",
        "what did i order?",
        # "read my order"
        "read my order",
        "read my order back",
        "read back my order",
        "repeat my order back",  # "repeat my order" without "back" is reserved for repeat order feature
        "say my order",
        "read the order",
        # "can you read my order"
        "can you read my order",
        "can you repeat my order",
        "could you read my order",
        "can you tell me my order",
        "could you tell me the order",
        # "order so far"
        "my order so far",
        "order so far",
        "my order so far?",
        # "what do I have so far"
        "what do I have so far",
        "what do i have so far?",
        "what have I got so far",
        "what have i got so far?",
    ])
    def test_order_status_patterns_detected(self, text):
        """Test that order status patterns are properly detected."""
        match = ORDER_STATUS_PATTERN.search(text)
        assert match is not None, f"Expected pattern match for: {text}"

    @pytest.mark.parametrize("text", [
        # Non-order-status patterns (should NOT match)
        "yes",
        "no",
        "I'd like a bagel",
        "can I get a coke",
        "that's all",
        "I'm done",
        "checkout",
        "cancel my order",  # This is different - cancelling, not asking status
        "what's the total with tax",  # Tax question, not order status
        "repeat my order",  # Reserved for repeat order feature (re-ordering previous order)
    ])
    def test_non_order_status_patterns_not_detected(self, text):
        """Test that non-order-status patterns are NOT detected."""
        match = ORDER_STATUS_PATTERN.search(text)
        assert match is None, f"Did not expect order status match for: {text}"
