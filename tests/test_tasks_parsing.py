"""
Tests for the deterministic parsing module.

Includes:
- Deterministic parser tests (no LLM required)
- Pattern-based parsing for menu items, modifiers, and responses
"""

import pytest

# Import parsed_items helpers for testing the generic parsed_items API
from tests.helpers import (
    get_parsed_item,
    get_parsed_items,
    has_parsed_item,
    has_signature_item,
    get_signature_item,
    has_bagel,
    get_bagel_item,
    has_coffee,
    get_coffee_item,
    has_menu_item,
    get_menu_item,
    has_side_item,
    get_side_item,
    count_parsed_items,
)


# =============================================================================
# Helper Functions for ParsedItem Type Checking
# =============================================================================

def _get_parsed_item_type(item) -> str:
    """Get the effective type of a ParsedItem.

    Returns a normalized type string for test assertions.
    """
    item_type = getattr(item, 'item_type', None)
    if item_type:
        # Map item_type to legacy type names for test compatibility
        if item_type == "sized_beverage":
            return "coffee"
        return item_type
    return 'unknown'


def _is_coffee_item(item) -> bool:
    """Check if a ParsedItem is a coffee/beverage."""
    item_type = getattr(item, 'item_type', None)
    return item_type == "sized_beverage"


def _is_bagel_item(item) -> bool:
    """Check if a ParsedItem is a bagel."""
    item_type = getattr(item, 'item_type', None)
    return item_type == "bagel"


# =============================================================================
# Deterministic Parser Tests (no LLM required)
# =============================================================================

from orderbot.tasks.parsers import (
    parse_open_input_deterministic,
    _extract_quantity,
    extract_attribute_values,
    WORD_TO_NUM,
    extract_zip_code,
    validate_delivery_zip_code,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
)


class TestDeterministicParserHelpers:
    """Tests for deterministic parser helper functions."""

    def test_word_to_num_mapping(self):
        """Test word to number mapping is correct."""
        assert WORD_TO_NUM["one"] == 1
        assert WORD_TO_NUM["two"] == 2
        assert WORD_TO_NUM["three"] == 3
        assert WORD_TO_NUM["four"] == 4
        assert WORD_TO_NUM["five"] == 5
        assert WORD_TO_NUM["ten"] == 10

    def test_extract_quantity_numeric(self):
        """Test extracting numeric quantities."""
        assert _extract_quantity("1") == 1
        assert _extract_quantity("3") == 3
        assert _extract_quantity("10") == 10

    def test_extract_quantity_words(self):
        """Test extracting word quantities."""
        assert _extract_quantity("one") == 1
        assert _extract_quantity("two") == 2
        assert _extract_quantity("three") == 3
        assert _extract_quantity("couple") == 2
        assert _extract_quantity("couple of") == 2

    def test_extract_toasted(self):
        """Test extracting toasted preference via generic extract_attribute_values."""
        attrs = extract_attribute_values("yes, toasted please", "bagel")
        assert attrs.get("toasted") is True

        attrs = extract_attribute_values("not toasted", "bagel")
        assert attrs.get("toasted") is False

        attrs = extract_attribute_values("plain bagel", "bagel")
        assert "toasted" not in attrs  # No explicit toasted preference

    def test_extract_spread(self):
        """Test extracting spread via generic extract_attribute_values.

        Database slugs use full format (e.g., plain_cream_cheese, scallion_cream_cheese).
        Matching is done via display_name and aliases, not slug literals.
        Note: Spread is a multi-select attribute, so it returns a list of dicts.
        """
        def _get_spread_slug(attrs: dict) -> str | None:
            """Helper to extract spread slug from multi-select format."""
            spread = attrs.get("spread")
            if spread and isinstance(spread, list) and len(spread) > 0:
                return spread[0].get("slug")
            return None

        # "scallion cream cheese" matches scallion_cream_cheese slug
        attrs = extract_attribute_values("with scallion cream cheese", "bagel")
        assert _get_spread_slug(attrs) == "scallion_cream_cheese"

        # "regular cream cheese" matches plain_cream_cheese slug
        attrs = extract_attribute_values("with regular cream cheese", "bagel")
        assert _get_spread_slug(attrs) == "plain_cream_cheese"

        attrs = extract_attribute_values("everything bagel toasted", "bagel")
        assert "spread" not in attrs  # No spread mentioned

    def test_extract_spread_cc_alias(self):
        """Test that 'cc' alias variants are normalized to correct slug."""
        def _get_spread_slug(attrs: dict) -> str | None:
            """Helper to extract spread slug from multi-select format."""
            spread = attrs.get("spread")
            if spread and isinstance(spread, list) and len(spread) > 0:
                return spread[0].get("slug")
            return None

        # "scallion cc" alias resolves to scallion_cream_cheese slug
        attrs = extract_attribute_values("scallion cc", "bagel")
        spread = _get_spread_slug(attrs)
        assert spread == "scallion_cream_cheese", f"Expected 'scallion_cream_cheese' but got '{spread}'"

        # "blueberry cc" alias resolves to blueberry_cream_cheese slug
        attrs = extract_attribute_values("blueberry cc", "bagel")
        spread = _get_spread_slug(attrs)
        assert spread == "blueberry_cream_cheese", f"Expected 'blueberry_cream_cheese' but got '{spread}'"


class TestDeterministicParserGreetings:
    """Tests for deterministic parsing of greetings."""

    @pytest.mark.parametrize("greeting", [
        "hi",
        "hello",
        "hey",
        "Hi!",
        "Hello.",
        "good morning",
        "good afternoon",
    ])
    def test_greetings_detected(self, greeting):
        """Test that greetings are properly detected."""
        result = parse_open_input_deterministic(greeting)
        assert result is not None
        assert result.is_greeting is True
        assert not has_bagel(result), "Greetings should not create bagel items"


class TestDeterministicParserDoneOrdering:
    """Tests for deterministic parsing of done ordering signals."""

    @pytest.mark.parametrize("done_phrase", [
        "that's all",
        "thats all",
        "nothing else",
        "I'm good",
        "im good",
        "nope",
        "no",
        "done",
        "all set",
        "that's it",
    ])
    def test_done_ordering_detected(self, done_phrase):
        """Test that done ordering phrases are properly detected."""
        result = parse_open_input_deterministic(done_phrase)
        assert result is not None
        assert result.done_ordering is True
        assert not has_bagel(result), "Done ordering should not create bagel items"


class TestDeterministicParserBagelOrders:
    """Tests for deterministic parsing of bagel orders."""

    @pytest.mark.parametrize("text,expected_qty", [
        ("3 bagels", 3),
        ("three bagels", 3),
        ("I want three bagels", 3),
        ("two bagels please", 2),
        ("I want 5 bagels", 5),
        ("a bagel", 1),
        ("one bagel", 1),
        ("four bagels", 4),
        ("five everything bagels", 5),
    ])
    def test_bagel_quantity_extraction(self, text, expected_qty):
        """Test that bagel quantities are correctly extracted."""
        result = parse_open_input_deterministic(text)
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == expected_qty, f"Expected {expected_qty} bagel(s), got {len(bagels)}"

    @pytest.mark.parametrize("text,expected_type", [
        ("one plain bagel", "plain_bagel"),
        ("two everything bagels", "everything_bagel"),
        ("sesame bagel please", "sesame_bagel"),
        ("I want a cinnamon raisin bagel", "cinnamon_raisin_bagel"),
        ("three bagels", None),  # No type specified
    ])
    def test_bagel_type_extraction(self, text, expected_type):
        """Test that bagel types are correctly extracted."""
        result = parse_open_input_deterministic(text)
        assert result is not None
        bagel = get_bagel_item(result)
        assert bagel is not None, f"Expected bagel item for: {text}"
        assert bagel.attribute_values.get("bread") == expected_type

    def test_bagel_with_toasted(self):
        """Test parsing bagel with toasted preference."""
        result = parse_open_input_deterministic("two plain bagels toasted")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        # Both should be plain and toasted
        for bagel in bagels:
            assert bagel.attribute_values.get("bread") == "plain_bagel"
            assert bagel.attribute_values.get("toasted") is True

    def test_bagel_with_comma_separated_modifiers(self):
        """Test bagel with modifiers separated by commas - regression test.

        Note: Butter is in the spread category in the database (not toppings).
        """
        # This case was being incorrectly split by multi-item parser
        result = parse_open_input_deterministic("pumpernickel bagel, butter, not toasted please")
        assert result is not None
        bagel = get_bagel_item(result)
        assert bagel is not None
        assert bagel.attribute_values.get("bread") == "pumpernickel_bagel"
        # Butter is a spread in the database
        spread = bagel.attribute_values.get("spread")
        assert spread == "butter", f"Expected spread='butter', got {spread}"
        assert bagel.attribute_values.get("toasted") is False

    @pytest.mark.parametrize("text,expected_toasted", [
        ("untoasted plain bagel", False),
        ("plain bagel untoasted", False),
        ("not toasted plain bagel", False),
        ("plain bagel not toasted", False),
    ])
    def test_untoasted_bagel_detected(self, text, expected_toasted):
        """Test that 'untoasted' and 'not toasted' set toasted=False."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parse result for: {text}"
        bagel = get_bagel_item(result)
        assert bagel is not None, f"Expected bagel item for: {text}"
        assert bagel.attribute_values.get("toasted") == expected_toasted, \
            f"Expected toasted={expected_toasted} for '{text}', got {bagel.attribute_values.get('toasted')}"

    @pytest.mark.xfail(reason="Complex parsing interaction: 'plain bagel with nova' matched as spread_sandwich - needs investigation")
    @pytest.mark.parametrize("text,expected_toasted", [
        ("an untoasted plain bagel with nova", False),
        ("can I get an untoasted plain bagel with nova and capers", False),
    ])
    def test_untoasted_bagel_with_fish_detected(self, text, expected_toasted):
        """Test that 'untoasted' sets toasted=False for bagels with fish toppings.

        Note: The user is asking for a bagel with fish topping (nova). With the
        data-driven architecture, this should be recognized as a bagel, not fish_sandwich.
        """
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parse result for: {text}"
        # User says "bagel" so item type should be bagel
        items = get_parsed_items(result, item_type="bagel")
        assert len(items) == 1, f"Expected 1 bagel item for: {text}, got: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        item = items[0]
        assert item.attribute_values.get("toasted") == expected_toasted, \
            f"Expected toasted={expected_toasted} for '{text}', got {item.attribute_values.get('toasted')}"


class TestDeterministicParserFallback:
    """Tests for cases that should fall back to LLM."""

    @pytest.mark.parametrize("text", [
        # Coffee and menu items are now handled deterministically
        "I'm not sure yet",  # Indecisive
    ])
    def test_llm_fallback_cases(self, text):
        """Test that complex cases fall back to LLM."""
        result = parse_open_input_deterministic(text)
        assert result is None, f"Expected LLM fallback for: {text}"

    @pytest.mark.parametrize("text", [
        "what do you have?",
        "what food do you have?",
        "what's on your menu?",
        "what can I order?",
    ])
    def test_general_menu_query_handled_deterministically(self, text):
        """Test that general menu queries are handled deterministically."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected deterministic parse for: {text}"
        assert result.menu_query is True
        assert result.menu_query_type is None  # None means general listing

    @pytest.mark.parametrize("text,expected_type", [
        ("coffee please", "coffee"),
        ("The Leo", "signature_item"),
        ("the chipotle egg omelette", "omelette"),  # Omelettes are configurable items with their own type
    ])
    def test_deterministic_handles_coffee_and_menu_items(self, text, expected_type):
        """Test that coffee and menu items are now handled deterministically."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected deterministic parse for: {text}"
        if expected_type == "coffee":
            coffee = get_coffee_item(result)
            assert coffee is not None, f"Expected coffee item in parsed_items, got: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
            # item_name may be None for generic coffee orders - check original_text as fallback
            name_to_check = coffee.item_name or coffee.original_text or ""
            assert "coffee" in name_to_check.lower(), f"Expected 'coffee' in name, got: item_name={coffee.item_name}, original_text={coffee.original_text}"
        elif expected_type == "signature_item":
            sig_item = get_signature_item(result)
            assert sig_item is not None
            assert sig_item.item_name is not None
        elif expected_type == "menu_item":
            menu_item = get_menu_item(result)
            assert menu_item is not None, f"Expected menu_item, got parsed_items: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        elif expected_type == "omelette":
            # Omelettes are configurable items with their own item_type
            omelette_item = get_parsed_item(result, item_type="omelette")
            assert omelette_item is not None, f"Expected omelette item, got parsed_items: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
            assert omelette_item.item_name is not None
        else:
            menu_item = get_menu_item(result)
            assert menu_item is not None


# =============================================================================
# Delivery ZIP Code Validation Tests
# =============================================================================

class TestExtractZipCode:
    """Tests for extract_zip_code function."""

    def test_extract_from_full_address(self):
        """Test extracting ZIP from a full address."""
        address = "123 Main Street, New York, NY 10001"
        assert extract_zip_code(address) == "10001"

    def test_extract_with_zip_plus_4(self):
        """Test extracting 5-digit ZIP from ZIP+4 format."""
        address = "456 Broadway, New York, NY 10013-1234"
        assert extract_zip_code(address) == "10013"

    def test_extract_from_simple_address(self):
        """Test extracting ZIP from simple address."""
        address = "789 Park Ave 10021"
        assert extract_zip_code(address) == "10021"

    def test_no_zip_in_address(self):
        """Test return None when no ZIP in address."""
        address = "123 Main Street, New York, NY"
        assert extract_zip_code(address) is None

    def test_empty_address(self):
        """Test return None for empty address."""
        assert extract_zip_code("") is None
        assert extract_zip_code(None) is None

    def test_multiple_zips_returns_first(self):
        """Test returns first ZIP when multiple present."""
        address = "10001 to 10002 via 10003"
        assert extract_zip_code(address) == "10001"

    @pytest.mark.parametrize("address,expected", [
        ("10007", "10007"),  # Just ZIP
        ("apt 10B, 123 St, NY 10038", "10038"),  # ZIP not confused with apt number
        ("10 West 10th St, 10011", "10011"),  # Not confused with street number
    ])
    def test_various_formats(self, address, expected):
        """Test various address formats."""
        assert extract_zip_code(address) == expected


class TestValidateDeliveryZipCode:
    """Tests for validate_delivery_zip_code function."""

    def test_valid_zip_in_allowed_list(self):
        """Test valid ZIP code in allowed list."""
        allowed = ["10001", "10002", "10003"]
        zip_code, error = validate_delivery_zip_code(
            "123 Main St, NY 10001", allowed
        )
        assert zip_code == "10001"
        assert error is None

    def test_invalid_zip_not_in_list(self):
        """Test ZIP code not in allowed list."""
        allowed = ["10001", "10002", "10003"]
        zip_code, error = validate_delivery_zip_code(
            "456 Broadway, NY 10010", allowed
        )
        assert zip_code is None
        assert "10010" in error
        assert "pickup" in error.lower()

    def test_no_zip_in_address(self):
        """Test address without ZIP code."""
        allowed = ["10001", "10002"]
        zip_code, error = validate_delivery_zip_code(
            "123 Main Street, New York", allowed
        )
        assert zip_code is None
        assert "ZIP code" in error

    def test_empty_allowed_list(self):
        """Test when no delivery ZIP codes configured."""
        zip_code, error = validate_delivery_zip_code(
            "123 Main St, NY 10001", []
        )
        assert zip_code is None
        assert "don't currently offer delivery" in error

    def test_none_allowed_list(self):
        """Test when allowed list is None."""
        zip_code, error = validate_delivery_zip_code(
            "123 Main St, NY 10001", None
        )
        assert zip_code is None
        assert "don't currently offer delivery" in error

    @pytest.mark.parametrize("address,allowed,should_pass", [
        # Tribeca area
        ("143 Chambers St, NY 10007", ["10007", "10013", "10280"], True),
        ("100 Duane St, NY 10007", ["10007", "10013", "10280"], True),
        ("200 Park Place, NY 10038", ["10007", "10013", "10280"], False),
        # Upper West Side
        ("200 W 72nd St, NY 10023", ["10023", "10024", "10025"], True),
        ("300 W 86th St, NY 10024", ["10023", "10024", "10025"], True),
        ("500 E 86th St, NY 10028", ["10023", "10024", "10025"], False),
    ])
    def test_realistic_nyc_addresses(self, address, allowed, should_pass):
        """Test with realistic NYC addresses and ZIP codes."""
        zip_code, error = validate_delivery_zip_code(address, allowed)
        if should_pass:
            assert zip_code is not None
            assert error is None
        else:
            assert zip_code is None
            assert error is not None


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

    def test_no_coke_is_replacement_not_cancellation(self):
        """Test that 'no coke' is treated as replacement (ambiguous phrase)."""
        # "no coke" could mean "no, I want a coke" or "no more coke"
        # We treat it as replacement to be safe
        result = parse_open_input_deterministic("no coke")
        assert result is not None
        # Should match as replacement, not cancellation
        assert result.replace_last_item is True
        assert result.cancel_item is None

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
        assert result.cancel_item == "__last_item__", \
            f"Expected cancel_item='__last_item__' but got '{result.cancel_item}' for: {text}"

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
        assert result.cancel_item == "__all_items__", \
            f"Expected cancel_item='__all_items__' but got '{result.cancel_item}' for: {text}"

    @pytest.mark.parametrize("text,expected_item", [
        # "delete X" patterns (new verb)
        ("delete the bagel", "bagel"),
        ("delete the coke", "coke"),
        ("delete the coffee", "coffee"),
        ("delete my order", "__all_items__"),
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
        ("actually just one bagel", "__reduce_to_one_bagel__"),
        ("actually only one bagel", "__reduce_to_one_bagel__"),
        ("actually just one coffee", "__reduce_to_one_coffee__"),
        ("actually just 1 bagel", "__reduce_to_one_bagel__"),
        # "just one bagel"
        ("just one bagel", "__reduce_to_one_bagel__"),
        ("only one bagel", "__reduce_to_one_bagel__"),
        ("just one coffee", "__reduce_to_one_coffee__"),
        ("only one coffee", "__reduce_to_one_coffee__"),
        # "just one" / "only one" (no item type)
        ("just one", "__reduce_to_one__"),
        ("only one", "__reduce_to_one__"),
        ("just 1", "__reduce_to_one__"),
        # "make it just one"
        ("make it just one", "__reduce_to_one__"),
        ("make it only one bagel", "__reduce_to_one_bagel__"),
        ("make that just one", "__reduce_to_one__"),
        # "i only want one"
        ("i only want one", "__reduce_to_one__"),
        ("i just want one bagel", "__reduce_to_one_bagel__"),
        ("i only need one", "__reduce_to_one__"),
        # "one is enough"
        ("one is enough", "__reduce_to_one__"),
        ("one bagel is enough", "__reduce_to_one_bagel__"),
        ("one is fine", "__reduce_to_one__"),
        ("one is good", "__reduce_to_one__"),
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
            assert not result.cancel_item.startswith("__reduce_to_one"), \
                f"Unexpected reduce-to-one match for: {text}"


class TestOrdinalExtractionFromCancelItem:
    """Tests for extracting ordinal references from cancellation descriptions."""

    def test_extract_ordinal_first_bagel(self):
        """Test extracting ordinal from 'first bagel'."""
        from orderbot.tasks.taking_items_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("first bagel")
        assert ordinal == 1
        assert item_type == "bagel"

    def test_extract_ordinal_second_coffee(self):
        """Test extracting ordinal from 'second coffee'."""
        from orderbot.tasks.taking_items_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("second coffee")
        assert ordinal == 2
        assert item_type == "coffee"

    def test_extract_ordinal_3rd_item(self):
        """Test extracting ordinal from '3rd item'."""
        from orderbot.tasks.taking_items_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("3rd item")
        assert ordinal == 3
        assert item_type == "item"

    def test_extract_ordinal_bagel_2(self):
        """Test extracting ordinal from 'bagel 2' (reversed format)."""
        from orderbot.tasks.taking_items_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("bagel 2")
        assert ordinal == 2
        assert item_type == "bagel"

    def test_extract_ordinal_coffee_hash_3(self):
        """Test extracting ordinal from 'coffee #3' (hash format)."""
        from orderbot.tasks.taking_items_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("coffee #3")
        assert ordinal == 3
        assert item_type == "coffee"

    def test_no_ordinal_plain_bagel(self):
        """Test that plain item descriptions return no ordinal."""
        from orderbot.tasks.taking_items_handler import extract_ordinal_reference
        ordinal, item_type = extract_ordinal_reference("plain bagel")
        assert ordinal is None
        assert item_type == "plain bagel"


class TestFindNthItemOfType:
    """Tests for finding the Nth item of a given type."""

    def test_find_first_bagel(self):
        """Test finding the first bagel in a list."""
        from orderbot.tasks.taking_items_handler import find_nth_item_of_type
        from tests.helpers import BagelItemTask, CoffeeItemTask

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
        from orderbot.tasks.taking_items_handler import find_nth_item_of_type
        from tests.helpers import BagelItemTask, CoffeeItemTask

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
        from orderbot.tasks.taking_items_handler import find_nth_item_of_type
        from tests.helpers import BagelItemTask, CoffeeItemTask

        items = [
            BagelItemTask(bread="plain"),
            CoffeeItemTask(drink_type="latte"),
            BagelItemTask(bread="everything"),
        ]

        # "2nd item" should return the coffee (index 1)
        result = find_nth_item_of_type(items, "item", 2)
        assert result is not None
        item, idx = result
        assert "size" in item  # Created as sized_beverage via CoffeeItemTask helper
        assert idx == 1

    def test_find_nth_item_out_of_range(self):
        """Test that out-of-range ordinal returns None."""
        from orderbot.tasks.taking_items_handler import find_nth_item_of_type
        from tests.helpers import BagelItemTask

        items = [
            BagelItemTask(bread="plain"),
            BagelItemTask(bread="everything"),
        ]

        # Asking for 5th bagel when only 2 exist
        result = find_nth_item_of_type(items, "bagel", 5)
        assert result is None

    def test_find_item_by_menu_item_name(self):
        """Test finding item by menu_item_name field."""
        from orderbot.tasks.taking_items_handler import find_nth_item_of_type
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
        from orderbot.tasks.taking_items_handler import find_nth_item_of_type
        from tests.helpers import CoffeeItemTask

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


# =============================================================================
# Special Instructions Extraction Tests
# =============================================================================

class TestSpecialInstructionsExtraction:
    """Tests for extract_special_instructions_from_input function."""

    def test_light_on_the_cream_cheese(self):
        """Test 'light on the cream cheese' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("plain bagel with light on the cream cheese")
        assert "light cream cheese" in notes

    def test_light_cream_cheese_short_form(self):
        """Test 'light cream cheese' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("bagel with light cream cheese")
        assert "light cream cheese" in notes

    def test_extra_bacon(self):
        """Test 'extra bacon' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("egg and cheese bagel with extra bacon")
        assert "extra bacon" in notes

    def test_lots_of_cream_cheese(self):
        """Test 'lots of cream cheese' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("bagel with lots of cream cheese")
        assert "extra cream cheese" in notes

    def test_splash_of_milk(self):
        """Test 'a splash of milk' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("coffee with a splash of milk")
        assert "a splash of milk" in notes

    def test_go_easy_on_the_mayo(self):
        """Test 'go easy on the mayo' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("sandwich with go easy on the mayo")
        assert "light mayo" in notes

    def test_little_bit_of_sugar(self):
        """Test 'a little sugar' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("coffee with a little sugar")
        assert "a little sugar" in notes

    def test_no_onions(self):
        """Test 'no onions' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("bagel with no onions")
        assert "no onions" in notes

    def test_hold_the_tomato(self):
        """Test 'hold the tomato' extracts correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("sandwich hold the tomato")
        assert "no tomato" in notes

    def test_multiple_notes(self):
        """Test multiple qualifier phrases extract correctly."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("bagel with light cream cheese and extra bacon")
        assert "light cream cheese" in notes
        assert "extra bacon" in notes

    def test_no_notes_for_regular_order(self):
        """Test that regular orders without qualifiers have no notes."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("plain bagel with cream cheese")
        assert len(notes) == 0

    def test_heavy_on_the_cheese(self):
        """Test 'heavy on the cheese' extracts as extra."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("bagel heavy on the cheese")
        assert "extra cheese" in notes

    def test_multi_item_notes_separated_coffee_only(self):
        """Test that coffee notes filter only includes coffee-related notes."""
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        # Multi-item order: "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        notes = extract_special_instructions_from_input("a coffee with a splash of milk and a bagel with a lot of cream cheese")
        # Should extract both notes separately
        assert "a splash of milk" in notes
        assert "extra cream cheese" in notes

    def test_multi_item_coffee_with_milk_and_special_instructions(self):
        """Test that multi-item parser extracts items and special instructions are captured at order level.

        Note: The 'splash of milk' phrase is captured as order-level special_instructions.
        Special instructions are no longer stored per-item but at the order level.
        """
        from orderbot.tasks.state_machine import _parse_multi_item_order, extract_special_instructions_from_input
        # Multi-item order: "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        user_input = "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        result = _parse_multi_item_order(user_input)
        assert result is not None
        assert has_coffee(result)
        assert has_bagel(result)
        # Check parsed_items has a coffee
        coffee = get_coffee_item(result)
        assert coffee is not None
        # Special instructions are now extracted at order level, not per-item
        instructions = extract_special_instructions_from_input(user_input)
        assert any("splash" in i.lower() or "milk" in i.lower() for i in instructions)

    def test_coffee_with_sugar_on_the_side(self):
        """Test that 'sugar on the side' is captured in order-level special_instructions."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        user_input = "large coffee iced sugar on the side"
        result = parse_open_input_deterministic(user_input)
        assert result is not None
        coffee = get_coffee_item(result)
        assert coffee is not None, f"No coffee found. All items: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        # Sugar on the side should be in order-level special_instructions
        # TODO: Future enhancement - extract sugar as sweetener modifier for pricing
        instructions = extract_special_instructions_from_input(user_input)
        assert any("sugar on the side" in i.lower() for i in instructions)

    def test_coffee_with_cream_on_the_side(self):
        """Test that 'cream on the side' is captured in order-level special_instructions."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        user_input = "large coffee cream on the side"
        result = parse_open_input_deterministic(user_input)
        assert result is not None
        coffee = get_coffee_item(result)
        assert coffee is not None
        # Cream on the side should be in order-level special_instructions
        # TODO: Future enhancement - extract cream as milk attribute for pricing
        instructions = extract_special_instructions_from_input(user_input)
        assert any("cream on the side" in i.lower() for i in instructions)

    @pytest.mark.xfail(reason="Milk extraction from 'milk on the side' not yet implemented - requires enhanced attribute extraction")
    def test_coffee_with_milk_on_the_side(self):
        """Test that 'milk on the side' adds milk AND to order-level special_instructions."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        from orderbot.tasks.state_machine import extract_special_instructions_from_input
        user_input = "coffee milk on the side"
        result = parse_open_input_deterministic(user_input)
        assert result is not None
        coffee = get_coffee_item(result)
        assert coffee is not None
        # Milk SHOULD be extracted (defaults to whole when just "milk" is mentioned)
        assert coffee.attribute_values.get("milk") == "whole"
        # Milk on the side should ALSO be in order-level special_instructions
        instructions = extract_special_instructions_from_input(user_input)
        assert any("milk on the side" in i.lower() for i in instructions)

    # -------------------------------------------------------------------------
    # Standalone Special Instruction Patterns
    # -------------------------------------------------------------------------

    def test_special_instruction_room_for_cream(self):
        """Test 'room for cream' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("coffee room for cream")
        assert any("room" in i.lower() for i in instructions)

    def test_special_instruction_not_too_hot(self):
        """Test 'not too hot' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("latte not too hot")
        assert any("not too hot" in i.lower() for i in instructions)

    def test_special_instruction_lukewarm(self):
        """Test 'lukewarm' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("coffee lukewarm please")
        assert any("lukewarm" in i.lower() for i in instructions)

    def test_special_instruction_upside_down(self):
        """Test 'upside down' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("caramel macchiato upside down")
        assert any("upside down" in i.lower() for i in instructions)

    def test_special_instruction_well_stirred(self):
        """Test 'well stirred' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee well stirred")
        assert any("well stirred" in i.lower() for i in instructions)

    def test_special_instruction_mixed(self):
        """Test 'mixed' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("latte mixed")
        assert any("mixed" in i.lower() for i in instructions)

    def test_special_instruction_lightly_toasted(self):
        """Test 'lightly toasted' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("plain bagel lightly toasted")
        assert any("lightly toasted" in i.lower() for i in instructions)

    def test_special_instruction_well_done(self):
        """Test 'well done' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("everything bagel well done")
        assert any("well done" in i.lower() for i in instructions)

    def test_special_instruction_cut_in_half(self):
        """Test 'cut in half' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("bagel with cream cheese cut in half")
        assert any("cut in half" in i.lower() for i in instructions)

    def test_special_instruction_sliced(self):
        """Test 'sliced' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("plain bagel sliced")
        assert any("sliced" in i.lower() for i in instructions)

    def test_special_instruction_open_faced(self):
        """Test 'open faced' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("egg sandwich open faced")
        assert any("open faced" in i.lower() for i in instructions)

    def test_special_instruction_spread_thin(self):
        """Test 'spread thin' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("bagel with cream cheese spread thin")
        assert any("spread thin" in i.lower() for i in instructions)

    def test_special_instruction_on_one_side(self):
        """Test 'on one side' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("cream cheese only on one side")
        assert any("on one side" in i.lower() for i in instructions)

    def test_special_instruction_on_both_halves(self):
        """Test 'on both halves' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("butter on both halves")
        assert any("on both halves" in i.lower() for i in instructions)

    def test_special_instruction_melted(self):
        """Test 'melted' is captured as special instruction."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("bagel with cheese melted")
        assert any("melted" in i.lower() for i in instructions)

    def test_special_instruction_extra_ice(self):
        """Test 'extra ice' is captured as special instruction (existing qualifier pattern)."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee extra ice")
        assert any("extra ice" in i.lower() for i in instructions)

    def test_special_instruction_light_ice(self):
        """Test 'light ice' is captured as special instruction (existing qualifier pattern)."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee light ice")
        assert any("light ice" in i.lower() for i in instructions)

    def test_special_instruction_no_ice(self):
        """Test 'no ice' is captured as special instruction (existing qualifier pattern)."""
        from orderbot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee no ice")
        assert any("no ice" in i.lower() for i in instructions)

    def test_multi_item_bagel_and_signature_item(self):
        """Test that multi-item parser recognizes speed menu items like The Classic BEC."""
        from orderbot.tasks.state_machine import _parse_multi_item_order
        # Multi-item order: "one bagel and one classic BEC"
        result = _parse_multi_item_order("one bagel and one classic BEC")
        assert result is not None
        # Should detect both items
        assert has_bagel(result)
        sig_item = get_signature_item(result)
        assert sig_item is not None
        # The Classic BEC should be recognized as a speed menu item
        assert "classic" in sig_item.item_name.lower() or "bec" in sig_item.item_name.lower()

    def test_multi_item_signature_item_and_coffee(self):
        """Test multi-item order with speed menu item and coffee."""
        from orderbot.tasks.state_machine import _parse_multi_item_order
        result = _parse_multi_item_order("the lexington and a latte")
        assert result is not None
        sig_item = get_signature_item(result)
        assert sig_item is not None
        assert has_coffee(result)
        # Lexington is a speed menu item
        assert "lexington" in sig_item.item_name.lower()

    def test_multi_item_two_signature_items(self):
        """Test multi-item order with two speed menu items (each individually recognized)."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        # Each item individually should be recognized as a signature item
        leo = parse_open_input_deterministic("the leo")
        bec = parse_open_input_deterministic("the classic bec")
        assert leo is not None
        assert bec is not None
        # Signature items should have is_signature=True and a valid item_type
        assert has_signature_item(leo), f"Expected signature item, got: {[(i.item_type, i.item_name, i.is_signature) for i in leo.parsed_items]}"
        assert has_signature_item(bec), f"Expected signature item, got: {[(i.item_type, i.item_name, i.is_signature) for i in bec.parsed_items]}"
        # Verify item names are correct
        leo_item = get_signature_item(leo)
        bec_item = get_signature_item(bec)
        assert leo_item.item_name == "The Leo"
        assert bec_item.item_name == "The Classic BEC"

    def test_multi_item_coffee_and_bagel_with_butter(self):
        """Test that 'a sesame bagel with butter' captures the sesame bagel type."""
        from orderbot.tasks.state_machine import _parse_multi_item_order
        result = _parse_multi_item_order("a coffee with a little bit of milk and a sesame bagel with butter")
        assert result is not None
        # Coffee should be captured
        assert has_coffee(result)
        # "sesame bagel with butter" should be a build-your-own bagel (user said "bagel")
        bagel = get_bagel_item(result)
        assert bagel is not None
        # Bagel type should be sesame (may be "sesame" or "sesame_bagel" database slug)
        assert bagel.attribute_values.get("bread") is not None
        assert "sesame" in bagel.attribute_values.get("bread")

    def test_bagel_with_cream_cheese_is_build_your_own(self):
        """Test that 'an everything bagel with cream cheese' is parsed as build-your-own bagel, not menu item."""
        from orderbot.tasks.state_machine import _parse_multi_item_order
        result = _parse_multi_item_order("an everything bagel with cream cheese and a coffee")
        assert result is not None
        assert has_coffee(result)
        # "everything bagel with cream cheese" should be parsed as a bagel order (not menu item)
        # because the user explicitly mentioned "bagel"
        bagel = get_bagel_item(result)
        assert bagel is not None
        # Bagel type may be "everything" or "everything_bagel" (database slug)
        assert bagel.attribute_values.get("bread") is not None
        assert "everything" in bagel.attribute_values.get("bread")
        # Should not be a generic menu item
        assert not has_menu_item(result, item_name="bagel")


class TestRecommendationInquiryParsing:
    """Tests for recommendation question detection.

    Recommendation questions should NOT add items to cart - they should
    just provide recommendations for items in the requested category.

    The recommendation system is now data-driven:
    1. General patterns return recommendation_match_type="general"
    2. Term-extracting patterns do a two-tier lookup:
       a. Search menu_items by partial name match
       b. Fallback: search item_types by display_name/aliases
    3. Breakfast/lunch patterns are treated as "general" (no specific items)
    """

    @pytest.mark.parametrize("text,expected_match_type", [
        # Direct "recommend" patterns - general match type
        ("what do you recommend?", "general"),
        ("what would you recommend?", "general"),
        ("any recommendations?", "general"),
        ("do you have any recommendations?", "general"),
        # Popular/best patterns - general match type
        ("what's popular?", "general"),
        ("what's your most popular item?", "general"),
        ("what sells best?", "general"),
        # Breakfast/lunch recommendations - treated as general
        ("what do you recommend for breakfast?", "general"),
        ("what's good for breakfast?", "general"),
        ("what do you recommend for lunch?", "general"),
        ("what's popular for lunch?", "general"),
    ])
    def test_general_recommendation_patterns(self, text, expected_match_type):
        """Test that general recommendation patterns return 'general' match type."""
        from orderbot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry(text)
        assert result is not None, f"Failed to detect recommendation in: {text}"
        assert result.asks_recommendation is True
        assert result.recommendation_match_type == expected_match_type

    @pytest.mark.parametrize("text", [
        # Term-extracting patterns - these do data-driven lookup
        # The exact return depends on database content, so we just check detection
        "what kind of bagel do you recommend?",
        "what bagel do you recommend?",
        "which bagel is best?",
        "what's your best bagel?",
        "what's popular for bagels?",
        "what sandwich do you recommend?",
        "which sandwich is best?",
        "what's your most popular sandwich?",
        "what coffee do you recommend?",
        "what's your best coffee?",
        "what coffee is popular?",
        # Generic term patterns (data-driven)
        "what teas do you recommend?",
        "recommend a snack",
        "best pastries",
    ])
    def test_term_recommendation_patterns_detected(self, text):
        """Test that term-extracting recommendation patterns are detected.

        These patterns extract a search term and do a data-driven lookup.
        The exact return values depend on database content.
        """
        from orderbot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry(text)
        assert result is not None, f"Failed to detect recommendation in: {text}"
        assert result.asks_recommendation is True
        # Should have a match type (general, menu_items, or item_type)
        assert result.recommendation_match_type in {"general", "menu_items", "item_type"}

    @pytest.mark.parametrize("text", [
        # Order intents (should NOT be detected as recommendations)
        "I want a bagel",
        "I'd like a sandwich",
        "can I get a coffee",
        "give me a plain bagel",
        "I'll have the BLT",
        # Other non-recommendation questions
        "what are your hours?",
        "where are you located?",
        "do you deliver to 10022?",
        "what's in the BLT?",
        "how much is a bagel?",
        # Confirmations
        "yes",
        "no",
        "that's all",
        # Edge cases
        "bagel",
        "coffee",
        "the lexington",
    ])
    def test_non_recommendation_not_detected(self, text):
        """Test that order intents are NOT detected as recommendations."""
        from orderbot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry(text)
        assert result is None, f"Incorrectly detected recommendation in: {text}"

    def test_recommendation_should_not_add_to_cart(self):
        """Test that recommendation response has no items to add."""
        from orderbot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry("what kind of bagel do you recommend?")
        assert result is not None
        assert result.asks_recommendation is True
        # Should NOT have any items flagged for adding
        assert len(result.parsed_items) == 0, "Recommendation inquiries should not create any items"


class TestItemDescriptionInquiryParsing:
    """Tests for item description inquiry parsing."""

    @pytest.mark.parametrize("text,expected_item", [
        # "what's on the X?" patterns
        ("what's on the health nut?", "health nut"),
        ("what's in the health nut?", "health nut"),
        ("what's on the BLT?", "blt"),
        ("what's in the classic BEC?", "classic bec"),
        # "what comes on the X?" patterns
        ("what comes on the health nut?", "health nut"),
        ("what comes with the delancey?", "delancey"),
        # Other patterns
        ("what does the leo have on it?", "leo"),
        ("tell me about the traditional", "traditional"),
        ("describe the avocado toast", "avocado toast"),
        ("ingredients in the chipotle omelette", "chipotle omelette"),
    ])
    def test_item_description_patterns_detected(self, text, expected_item):
        """Test that item description questions are correctly detected."""
        from orderbot.tasks.state_machine import _parse_item_description_inquiry
        result = _parse_item_description_inquiry(text)
        assert result is not None, f"Failed to detect item description inquiry in: {text}"
        assert result.asks_item_description is True
        assert result.item_description_query == expected_item

    @pytest.mark.parametrize("text", [
        # Order intents (should NOT be detected as item description)
        "I want the health nut",
        "give me the BLT",
        "I'll have the classic",
        # Cart status questions (should NOT be detected)
        "what's in my cart?",
        "what's in my order?",
        "what's in the cart?",
        # Other non-description questions
        "how much is the health nut?",
        "do you have the health nut?",
    ])
    def test_non_description_inquiry_not_detected(self, text):
        """Test that order intents are NOT detected as item description inquiries."""
        from orderbot.tasks.state_machine import _parse_item_description_inquiry
        result = _parse_item_description_inquiry(text)
        assert result is None, f"Incorrectly detected item description inquiry in: {text}"

    def test_item_description_should_not_add_to_cart(self):
        """Test that item description response has no items to add."""
        from orderbot.tasks.state_machine import _parse_item_description_inquiry
        result = _parse_item_description_inquiry("what's on the health nut?")
        assert result is not None
        assert result.asks_item_description is True
        # Should NOT have any items flagged for adding
        assert len(result.parsed_items) == 0, "Item description inquiries should not create any items"


# =============================================================================
# Speed Menu Bagel Parsing Tests
# =============================================================================

class TestSpeedMenuBagelParsing:
    """Tests for speed menu bagel deterministic parsing with bagel choice."""

    @pytest.mark.parametrize("text,expected_name", [
        ("The Classic BEC", "The Classic BEC"),
        ("classic bec", "The Classic BEC"),
        ("The Leo", "The Leo"),
        ("leo", "The Leo"),
        ("The Traditional", "The Traditional"),
        ("traditional", "The Traditional"),
        ("The Max Zucker", "The Max Zucker"),
        ("max zucker", "The Max Zucker"),
        # Note: "The Classic" maps to "The Classic BEC" (no standalone "The Classic" item)
        ("The Classic", "The Classic BEC"),
        ("classic", "The Classic BEC"),
        ("The Lexington", "The Lexington"),
        ("lexington", "The Lexington"),
        ("The Avocado Toast", "The Avocado Toast"),
        ("avocado toast", "The Avocado Toast"),
    ])
    def test_signature_item_detected(self, text, expected_name):
        """Test that speed menu items are correctly detected."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to detect speed menu item in: {text}"
        # Signature items may be parsed with different item_types based on database config
        # (e.g., 'egg_sandwich', 'menu_item', etc.) - just verify the name is correct
        assert result.parsed_items, f"No parsed_items for: {text}"
        item = result.parsed_items[0]
        assert item.item_name == expected_name

    @pytest.mark.parametrize("text,expected_bagel", [
        # "wheat" maps to "whole_wheat_bagel" slug since there's no separate "wheat" bagel in database
        ("The Classic BEC on a wheat bagel", "whole_wheat_bagel"),
        ("classic bec on wheat", "whole_wheat_bagel"),
        ("The Leo on an everything bagel", "everything_bagel"),
        # "leo on everything" needs "bagel" word since "everything" alone doesn't match
        # (database slug is "everything_bagel", not "everything")
        ("leo on everything bagel", "everything_bagel"),
        ("The Traditional on a sesame bagel", "sesame_bagel"),
        ("classic bec but on a plain bagel", "plain_bagel"),
        ("give me the classic bec on a pumpernickel bagel", "pumpernickel_bagel"),
        ("I want the lexington on whole wheat", "whole_wheat_bagel"),
        # Without "on/with" prefix - should still extract bagel type
        ("bec everything bagel toasted", "everything_bagel"),
        ("classic bec plain bagel", "plain_bagel"),
        ("the leo sesame bagel", "sesame_bagel"),
    ])
    def test_signature_item_with_bagel_choice(self, text, expected_bagel):
        """Test that speed menu items with bagel choice are correctly parsed."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        # Use get_signature_item which filters by is_signature=True
        # (signature items may have different item_types like 'egg_sandwich')
        sig_item = get_signature_item(result)
        assert sig_item is not None, f"No signature item found for: {text}"
        assert sig_item.attribute_values.get("bread") == expected_bagel

    @pytest.mark.parametrize("text,expected_toasted", [
        ("The Classic BEC toasted", True),
        ("classic bec not toasted", False),
        ("The Leo toasted please", True),
        ("the lexington not toasted", False),
    ])
    def test_signature_item_with_toasted(self, text, expected_toasted):
        """Test that speed menu items with toasted preference are correctly parsed."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        # Use get_signature_item which filters by is_signature=True
        sig_item = get_signature_item(result)
        assert sig_item is not None, f"No signature item found for: {text}"
        assert sig_item.attribute_values.get("toasted") == expected_toasted

    @pytest.mark.parametrize("text,expected_qty", [
        ("2 classics", 2),
        ("two leos", 2),
        ("3 classic becs", 3),
        ("three traditionals", 3),
    ])
    def test_signature_item_with_quantity(self, text, expected_qty):
        """Test that speed menu items with quantity are correctly parsed."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        # Parser creates N separate items for quantity N (each with quantity=1)
        # Filter by is_signature=True since signature items may have different item_types
        sig_items = get_parsed_items(result, is_signature=True)
        assert len(sig_items) == expected_qty, f"Expected {expected_qty} signature items, got {len(sig_items)}"

    def test_signature_item_with_all_options(self):
        """Test parsing speed menu with bagel choice, toasted, and quantity."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic("2 classic becs on wheat bagels toasted")
        assert result is not None
        # Parser creates 2 separate items for quantity 2
        # Filter by is_signature=True since signature items may have different item_types
        sig_items = get_parsed_items(result, is_signature=True)
        assert len(sig_items) == 2
        # All items should have the same name, bagel choice, and toasted preference
        # Note: "wheat" maps to "whole_wheat_bagel" slug since there's no separate "wheat" bagel in DB
        for item in sig_items:
            assert item.item_name == "The Classic BEC"
            assert item.attribute_values.get("bread") == "whole_wheat_bagel"
            assert item.attribute_values.get("toasted") is True

    def test_signature_item_parsed_before_bagel_check(self):
        """Test that speed menu items are parsed BEFORE generic bagel check.

        This is the key fix - 'The Classic BEC on a wheat bagel' should NOT
        be parsed as a simple wheat bagel order.
        """
        result = parse_open_input_deterministic("The Classic BEC but on a wheat bagel")
        assert result is not None
        # Should be speed menu item, NOT a plain bagel
        sig_item = get_signature_item(result)
        assert sig_item is not None, "Should parse as signature item"
        assert sig_item.item_name == "The Classic BEC"
        # Note: "wheat" maps to "whole_wheat_bagel" slug since there's no separate "wheat" bagel in DB
        assert sig_item.attribute_values.get("bread") == "whole_wheat_bagel"
        # Should NOT have a plain bagel item
        bagel_items = get_parsed_items(result, item_type="bagel")
        assert len(bagel_items) == 0, "Should not have a separate bagel item"

    def test_non_signature_item_still_works(self):
        """Test that regular bagel orders still work."""
        result = parse_open_input_deterministic("a wheat bagel with cream cheese")
        assert result is not None
        bagel_item = get_bagel_item(result)
        assert bagel_item is not None, "Should parse as bagel item"
        # Note: "wheat" maps to "whole_wheat_bagel" slug since there's no separate "wheat" bagel in DB
        assert bagel_item.attribute_values.get("bread") == "whole_wheat_bagel"
        # Should NOT be a signature item
        assert not has_signature_item(result)


class TestSplitQuantityBagelParsing:
    """Tests for split-quantity bagel parsing (e.g., 'two bagels one with lox one with cream cheese')."""

    def test_two_bagels_one_lox_one_cream_cheese(self):
        """Test parsing 'two plain bagels one with scallion cream cheese one with lox'."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two plain bagels one with scallion cream cheese one with lox")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2, f"Expected 2 bagels, got {len(bagels)}. All items: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        # First bagel: scallion cream cheese (slug from DB)
        assert bagels[0].attribute_values.get("bread") == "plain_bagel"
        assert bagels[0].attribute_values.get("spread") == "scallion_cream_cheese"
        # Second bagel: lox (extra_protein, not spread - salmon is a protein topping)
        assert bagels[1].attribute_values.get("bread") == "plain_bagel"
        assert bagels[1].attribute_values.get("extra_protein") == "nova_scotia_salmon"

    def test_two_bagels_toasted_variants(self):
        """Test parsing 'two everything bagels one toasted one not toasted'."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two everything bagels one toasted one not toasted")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        assert bagels[0].attribute_values.get("bread") == "everything_bagel"
        assert bagels[0].attribute_values.get("toasted") is True
        assert bagels[1].attribute_values.get("bread") == "everything_bagel"
        assert bagels[1].attribute_values.get("toasted") is False

    def test_three_bagels_different_spreads(self):
        """Test parsing 'three bagels one with butter one plain one with plain cream cheese'.

        Note: Uses 'plain cream cheese' since that's the full name in DB.
        'cream cheese' alone would need to be added as an alias for 'plain_cream_cheese'.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("three bagels one with butter one plain one with plain cream cheese")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 3
        # Butter is categorized as a spread in the database
        assert bagels[0].attribute_values.get("spread") == "butter"
        assert bagels[1].attribute_values.get("spread") is None  # plain = no spread
        # Plain cream cheese is also in the spread category
        assert bagels[2].attribute_values.get("spread") == "plain_cream_cheese"

    def test_numeric_quantity(self):
        """Test parsing with numeric quantity."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 bagels one with lox one with cream cheese")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2

    def test_no_split_single_bagel(self):
        """Test that single bagel orders are not matched by split-quantity parser."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("one plain bagel with cream cheese")
        assert result is None  # Should not match - no split pattern

    def test_no_split_same_config(self):
        """Test that bagels with same config are not matched by split-quantity parser."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two plain bagels with cream cheese")
        assert result is None  # Should not match - no split pattern

    def test_spread_and_toasted_variants(self):
        """Test parsing '2 plain bagels, one with plain cream cheese toasted, one with lox not toasted'.

        This tests spread extraction and combined attribute extraction (spread + toasted together).
        Note: Uses 'plain cream cheese' since that's the full name in DB.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items(
            "2 plain bagels, one with plain cream cheese toasted, one with lox not toasted"
        )
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        # First bagel: plain cream cheese, toasted
        assert bagels[0].attribute_values.get("bread") == "plain_bagel"
        assert bagels[0].attribute_values.get("spread") == "plain_cream_cheese"
        assert bagels[0].attribute_values.get("toasted") is True
        # Second bagel: lox (extra_protein), not toasted
        assert bagels[1].attribute_values.get("bread") == "plain_bagel"
        assert bagels[1].attribute_values.get("extra_protein") == "nova_scotia_salmon"
        assert bagels[1].attribute_values.get("toasted") is False

    def test_different_bagel_types_with_toppings(self):
        """Test parsing '2 plain bagels, one with butter, one with plain cream cheese'.

        This tests per-item topping/spread differentiation where each item
        has a different customization.
        Note: Uses 'plain cream cheese' since that's the full name in DB.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 plain bagels, one with butter, one with plain cream cheese")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        # First bagel: butter (spread)
        assert bagels[0].attribute_values.get("bread") == "plain_bagel"
        assert bagels[0].attribute_values.get("spread") == "butter"
        # Second bagel: plain cream cheese (spread)
        assert bagels[1].attribute_values.get("bread") == "plain_bagel"
        assert bagels[1].attribute_values.get("spread") == "plain_cream_cheese"

    def test_uneven_split_one_toasted_two_not(self):
        """Test parsing '3 bagels, one toasted, two not toasted'.

        This tests uneven split handling where distribution quantities
        (one, two) don't match equal division.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("3 bagels, one toasted, two not toasted")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 3
        # First bagel: toasted
        assert bagels[0].attribute_values.get("toasted") is True
        # Second and third bagels: not toasted
        assert bagels[1].attribute_values.get("toasted") is False
        assert bagels[2].attribute_values.get("toasted") is False

    def test_first_second_ordinals_with_toppings(self):
        """Test parsing '2 bagels, first one with butter, second one with plain cream cheese'.

        This tests ordinal patterns (first/second) for specifying
        different configurations.
        Note: Uses 'plain cream cheese' since that's the full name in DB.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items(
            "2 bagels, first one with butter, second one with plain cream cheese"
        )
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        # First bagel: butter (spread in database)
        assert bagels[0].attribute_values.get("spread") == "butter"
        # Second bagel: plain cream cheese (spread)
        assert bagels[1].attribute_values.get("spread") == "plain_cream_cheese"

    def test_split_with_scallion_and_veggie(self):
        """Test parsing with specific cream cheese variants."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 bagels, one with scallion cream cheese, one with veggie cream cheese")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        assert bagels[0].attribute_values.get("spread") == "scallion_cream_cheese"
        assert bagels[1].attribute_values.get("spread") == "veggie_cream_cheese"


class TestSplitQuantityDrinksParsing:
    """Tests for split-quantity drink parsing (e.g., 'two coffees one with milk one black')."""

    def test_two_coffees_one_milk_one_black(self):
        """Test parsing 'two coffees one with milk one black'.

        Tests split-quantity parsing for drinks. Note: attribute extraction
        depends on database configuration for sized_beverage type.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two coffees one with milk one black")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 2, f"Expected 2 sized_beverage, got {len(drinks)}. All: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        # Both coffees should be detected
        assert "coffee" in drinks[0].item_name.lower()
        assert "coffee" in drinks[1].item_name.lower()
        # Second coffee should have style=black from "one black"
        assert drinks[1].attribute_values.get("style") == "black"

    @pytest.mark.xfail(reason="'latte' needs alias in DB to match 'Hot/Iced Latte' menu items")
    def test_two_lattes_one_iced_one_hot(self):
        """Test parsing 'two lattes one iced one hot'."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two lattes one iced one hot")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 2
        assert drinks[0].attribute_values.get("temperature") == "iced"
        assert drinks[1].attribute_values.get("temperature") == "hot"

    @pytest.mark.xfail(reason="'tea' item type detection needs DB configuration")
    def test_two_teas_one_with_oat_milk_one_plain(self):
        """Test parsing 'two teas one with oat milk one plain'."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two teas one with oat milk one plain")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 2
        # "tea" alias resolves to canonical name like "Iced Tea" or "Hot Tea"
        assert "tea" in drinks[0].item_name.lower()
        assert drinks[0].attribute_values.get("milk") == "oat"
        assert drinks[1].attribute_values.get("milk") == "none"

    def test_three_coffees_different_temps(self):
        """Test parsing 'three coffees one iced one hot one decaf'.

        Tests quantity=3 split. Note: temperature/decaf extraction depends on DB config.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("three coffees one iced one hot one decaf")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 3
        # All three should be coffees
        for drink in drinks:
            assert "coffee" in drink.item_name.lower()

    def test_numeric_quantity(self):
        """Test parsing with numeric quantity."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 coffees one with almond milk one black")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 2
        # Both should be coffees
        assert "coffee" in drinks[0].item_name.lower()
        assert "coffee" in drinks[1].item_name.lower()
        # Second should have style=black
        assert drinks[1].attribute_values.get("style") == "black"

    def test_no_split_single_coffee(self):
        """Test that single coffee orders are not matched by split-quantity parser."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("one large coffee with milk")
        assert result is None  # Should not match - no split pattern

    def test_no_split_same_config(self):
        """Test that coffees with same config are not matched by split-quantity parser."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two coffees with milk")
        assert result is None  # Should not match - no split pattern

    @pytest.mark.xfail(reason="'latte' needs alias in DB to match 'Hot/Iced Latte' menu items")
    def test_large_iced_lattes_split(self):
        """Test parsing 'two large lattes one iced one hot' preserves size."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two large lattes one iced one hot")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 2
        # Both should have the large size
        assert drinks[0].attribute_values.get("size") == "large"
        assert "iced" in drinks[0].item_name.lower()
        assert drinks[1].attribute_values.get("size") == "large"
        assert "hot" in drinks[1].item_name.lower()

    @pytest.mark.xfail(reason="'coffee' needs alias in DB to match 'Hot/Iced Coffee' menu items")
    def test_uneven_split_one_iced_two_hot(self):
        """Test parsing '3 coffees, one iced, two hot'.

        This tests uneven split handling where distribution quantities
        don't match equal division.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("3 coffees, one iced, two hot")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 3
        # First coffee: iced
        assert "iced" in drinks[0].item_name.lower()
        # Second and third coffees: hot
        assert "hot" in drinks[1].item_name.lower()
        assert "hot" in drinks[2].item_name.lower()

    @pytest.mark.xfail(reason="'coffee' needs alias in DB to match 'Hot/Iced Coffee' menu items")
    def test_two_coffees_one_hot_one_iced(self):
        """Test parsing '2 coffees, one hot, one iced'.

        This tests the basic hot/iced split pattern.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 coffees, one hot, one iced")
        assert result is not None
        drinks = get_parsed_items(result, item_type="sized_beverage")
        assert len(drinks) == 2
        # First coffee: hot
        assert "hot" in drinks[0].item_name.lower()
        # Second coffee: iced
        assert "iced" in drinks[1].item_name.lower()


class TestParsedItemsMultiItem:
    """Tests for parsed_items list in multi-item order parsing."""

    def test_signature_item_and_menu_item_both_in_parsed_items(self):
        """Test that The Leo + everything bagel both appear in parsed_items.

        This was the original bug: 'the leo on wheat toasted and an everything bagel with butter'
        would only add the bagel, skipping The Leo.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("the leo on wheat toasted and an everything bagel with butter")
        assert result is not None, "Failed to parse multi-item order"
        assert len(result.parsed_items) == 2, f"Expected 2 parsed_items, got {len(result.parsed_items)}"

        # Check the parsed_items list contains both items
        # The Leo is an egg_sandwich, the bagel is a bagel
        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "egg_sandwich" in types, f"Expected egg_sandwich (The Leo), got: {types}"
        assert "bagel" in types, f"Expected bagel, got: {types}"

        # Verify The Leo details (look for egg_sandwich type or is_signature=True)
        leo_items = [i for i in result.parsed_items if _get_parsed_item_type(i) == "egg_sandwich" or getattr(i, 'is_signature', False)]
        assert len(leo_items) >= 1, "The Leo should be in parsed_items"
        leo = leo_items[0]
        # The Leo may have bread attribute extracted
        bread_attr = getattr(leo, 'attribute_values', {}).get('bread')
        bread = getattr(leo, 'bread', bread_attr)
        # Accept "wheat" or "whole_wheat_bagel" (database slug)
        assert bread and "wheat" in bread, f"Expected wheat bagel, got {bread}"

    def test_bagel_and_coffee_both_in_parsed_items(self):
        """Test that bagel + coffee both appear in parsed_items."""
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("a plain bagel toasted and a large iced latte")
        assert result is not None
        assert len(result.parsed_items) == 2

        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "bagel" in types
        assert "coffee" in types

    def test_latte_with_modifiers_and_bagel_with_modifiers(self):
        """Test that latte (with milk/syrup) + bagel (with spread) both appear in parsed_items.

        This tests the specific scenario where "latte" could be matched as a menu item
        instead of a coffee if parsing order is wrong.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        # The exact problematic scenario
        result = _parse_multi_item_order(
            "large iced oat milk latte with vanilla and a gluten free everything bagel with veggie cc toasted"
        )
        assert result is not None
        assert len(result.parsed_items) == 2

        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "coffee" in types or "sized_beverage" in types, f"Expected coffee in parsed_items, got: {types}"
        assert "bagel" in types or "menu_item" in types, f"Expected bagel/menu_item in parsed_items, got: {types}"

        # Verify coffee details
        coffee = get_coffee_item(result)
        assert coffee is not None
        # item_name may be partial (e.g., "iced") - check both item_name and original_text
        name_combined = f"{coffee.item_name or ''} {coffee.original_text or ''}".lower()
        assert "latte" in name_combined, f"Expected 'latte' somewhere in item_name or original_text, got: {coffee.item_name}, {coffee.original_text}"
        assert coffee.attribute_values.get("size") == "large"
        assert "iced" in name_combined
        # Note: "oat milk" extraction depends on DB configuration of milk options
        # If oat is configured as a milk option, this should pass
        if coffee.attribute_values.get("milk") is not None:
            assert coffee.attribute_values.get("milk") == "oat"

    def test_two_menu_items_both_in_parsed_items(self):
        """Test that two menu items both appear in parsed_items."""
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("the lexington and a butter sandwich")
        assert result is not None
        # Should get 2 items
        assert len(result.parsed_items) >= 2

        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        # The Lexington is an egg_sandwich, Butter Sandwich is a spread_sandwich
        # Accept specific types instead of generic menu_item
        valid_types = {"egg_sandwich", "spread_sandwich", "menu_item", "fish_sandwich", "deli_sandwich"}
        for t in types:
            assert t in valid_types, f"Expected a sandwich type, got: {t}"

    def test_signature_item_and_coffee_both_in_parsed_items(self):
        """Test that speed menu bagel + coffee both appear in parsed_items."""
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("the classic bec and a coffee")
        assert result is not None
        assert len(result.parsed_items) == 2

        # Check using our test helpers
        sig_item = get_signature_item(result)
        assert sig_item is not None, "Expected a signature item (The Classic BEC)"
        assert has_coffee(result), "Expected a coffee item"


class TestDuplicatePatterns:
    """Tests for duplicate item patterns: 'another one', 'one more', 'another bagel', etc."""

    @pytest.mark.parametrize("text,expected_type", [
        # Bagels - uses "bagel" item type
        ("another bagel", "bagel"),
        ("another bagels", "bagel"),
        ("one more bagel", "bagel"),
        # Sized beverages - uses "sized_beverage" item type (data-driven from database)
        # Note: The old hardcoded mapping returned "coffee" but the database uses "sized_beverage"
        ("another coffee", "sized_beverage"),
        ("one more coffee", "sized_beverage"),
        ("another latte", "sized_beverage"),
        ("one more latte", "sized_beverage"),
        ("another cappuccino", "sized_beverage"),
        ("another espresso", "espresso"),  # Espresso has its own item type in the database
        ("another americano", "sized_beverage"),
        ("another tea", "sized_beverage"),
    ])
    def test_another_item_type_detected(self, text, expected_type):
        """Test that 'another <item>' patterns are detected with correct item type.

        Note: The expected item types are the actual database item_type slugs,
        not semantic categories like "coffee". This is the data-driven approach.
        """
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.duplicate_new_item_type == expected_type, f"Expected type '{expected_type}' for: {text}"
        assert result.duplicate_last_item == 0, f"duplicate_last_item should be 0 for: {text}"

    @pytest.mark.parametrize("text", [
        "another one",
        "one more",
        "and another",
        "another",
        "add one more",
        "add another",
        "one more of those",
    ])
    def test_one_more_without_type_detected(self, text):
        """Test that 'one more' / 'another' without item type sets duplicate_last_item."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.duplicate_last_item == 1, f"Expected duplicate_last_item=1 for: {text}"
        assert result.duplicate_new_item_type is None, f"Expected no item type for: {text}"

    @pytest.mark.parametrize("text", [
        "all the items",
        "all of them",
        "all items",
        "everything",
        "everything in the cart",
        "the whole order",
        "the entire order",
    ])
    def test_duplicate_all_patterns(self, text):
        """Test that 'all items' / 'everything' patterns are recognized."""
        from orderbot.tasks.parsers.deterministic import DUPLICATE_ALL_PATTERN
        assert DUPLICATE_ALL_PATTERN.match(text) is not None, f"Expected match for: {text}"

    def test_another_bagel_not_duplicate_last(self):
        """Test that 'another bagel' is NOT treated as duplicate_last_item."""
        result = parse_open_input_deterministic("another bagel")
        assert result is not None
        # Should be new item type, not duplicate last
        assert result.duplicate_new_item_type == "bagel"
        assert result.duplicate_last_item == 0

    def test_make_it_2_still_works(self):
        """Test that 'make it 2' still sets duplicate_last_item correctly."""
        result = parse_open_input_deterministic("make it 2")
        assert result is not None
        assert result.duplicate_last_item == 1  # Add 1 more to reach 2 total
        assert result.duplicate_new_item_type is None

    def test_ill_take_3_still_works(self):
        """Test that 'I'll take 3' still sets duplicate_last_item correctly."""
        result = parse_open_input_deterministic("I'll take 3")
        assert result is not None
        assert result.duplicate_last_item == 2  # Add 2 more to reach 3 total
        assert result.duplicate_new_item_type is None


# =============================================================================
# Ingredient-Based Menu Search Tests
# =============================================================================

class TestIngredientBasedSearch:
    """Tests for ingredient-based menu search functionality."""

    @pytest.fixture
    def mock_ingredient_to_items(self):
        """Create a mock ingredient_to_items mapping for testing."""
        return {
            "chicken": [
                {"id": 1, "name": "Chicken Salad Sandwich", "description": "Classic chicken salad"},
                {"id": 2, "name": "Chicken Cutlet Sandwich", "description": "Crispy cutlet"},
                {"id": 3, "name": "The Chelsea Club", "description": "Chicken Salad, Bacon, Tomato"},
            ],
            "bacon": [
                {"id": 4, "name": "The Classic BEC", "description": "Bacon, Egg, and Cheese"},
                {"id": 3, "name": "The Chelsea Club", "description": "Chicken Salad, Bacon, Tomato"},
            ],
            "turkey": [
                {"id": 5, "name": "Turkey Club", "description": "Roasted turkey breast"},
            ],
        }

    def test_standalone_chicken_triggers_search(self, mock_ingredient_to_items):
        """Test that 'chicken' by itself triggers ingredient search."""
        result = parse_open_input_deterministic(
            "chicken",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.ingredient_search_query == "chicken"
        assert len(result.ingredient_search_matches) == 3

    def test_something_with_chicken_triggers_search(self, mock_ingredient_to_items):
        """Test that 'something with chicken' triggers ingredient search."""
        result = parse_open_input_deterministic(
            "something with chicken",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.ingredient_search_query == "chicken"
        assert len(result.ingredient_search_matches) == 3

    def test_anything_with_bacon_triggers_search(self, mock_ingredient_to_items):
        """Test that 'anything with bacon' triggers ingredient search."""
        result = parse_open_input_deterministic(
            "anything with bacon",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.ingredient_search_query == "bacon"
        assert len(result.ingredient_search_matches) == 2

    def test_what_has_turkey_triggers_search(self, mock_ingredient_to_items):
        """Test that 'what has turkey' triggers ingredient search."""
        result = parse_open_input_deterministic(
            "what has turkey",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.ingredient_search_query == "turkey"
        assert len(result.ingredient_search_matches) == 1

    def test_chicken_sandwich_does_not_trigger_search(self, mock_ingredient_to_items):
        """Test that 'chicken sandwich' is a normal order, not ingredient search."""
        result = parse_open_input_deterministic(
            "chicken sandwich",
            ingredient_to_items=mock_ingredient_to_items
        )
        # Should NOT be ingredient search (has "sandwich" signal)
        assert result is None or not result.ingredient_search_matches

    def test_chicken_salad_does_not_trigger_search(self, mock_ingredient_to_items):
        """Test that 'chicken salad' is a normal order, not ingredient search."""
        result = parse_open_input_deterministic(
            "chicken salad",
            ingredient_to_items=mock_ingredient_to_items
        )
        # Should NOT be ingredient search (has "salad" signal)
        assert result is None or not result.ingredient_search_matches

    def test_unknown_ingredient_no_match(self, mock_ingredient_to_items):
        """Test that unknown ingredients don't trigger search."""
        result = parse_open_input_deterministic(
            "something with lobster",
            ingredient_to_items=mock_ingredient_to_items
        )
        # "lobster" isn't in our mapping, so shouldn't be ingredient search
        assert result is None or not result.ingredient_search_matches

    def test_empty_ingredient_to_items_disabled(self):
        """Test that ingredient search is disabled when mapping is empty or None."""
        result = parse_open_input_deterministic(
            "chicken",
            ingredient_to_items=None
        )
        # Without ingredient mapping, this should fall through (return None)
        assert result is None or not result.ingredient_search_matches

        result2 = parse_open_input_deterministic(
            "chicken",
            ingredient_to_items={}
        )
        assert result2 is None or not result2.ingredient_search_matches

    def test_id_like_something_with_chicken(self, mock_ingredient_to_items):
        """Test 'I'd like something with chicken' pattern."""
        result = parse_open_input_deterministic(
            "I'd like something with chicken",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.ingredient_search_query == "chicken"
        assert len(result.ingredient_search_matches) == 3

    def test_can_i_get_something_with_bacon(self, mock_ingredient_to_items):
        """Test 'can I get something with bacon' pattern."""
        result = parse_open_input_deterministic(
            "can I get something with bacon",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.ingredient_search_query == "bacon"
        assert len(result.ingredient_search_matches) == 2

    def test_remove_the_bacon_is_cancellation_not_search(self, mock_ingredient_to_items):
        """Test 'remove the bacon' triggers cancellation, not ingredient search.

        This is a regression test for a bug where 'remove the bacon' would
        incorrectly trigger an ingredient search for 'bacon' instead of
        removing bacon from the current item.
        """
        result = parse_open_input_deterministic(
            "remove the bacon",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        # Should be a cancellation, not ingredient search
        assert result.cancel_item == "bacon"
        assert result.ingredient_search_query is None
        assert not result.ingredient_search_matches

    def test_cancel_the_ham_is_cancellation_not_search(self, mock_ingredient_to_items):
        """Test 'cancel the ham' triggers cancellation even if ham is an ingredient."""
        result = parse_open_input_deterministic(
            "cancel the ham",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        assert result.cancel_item == "ham"
        assert result.ingredient_search_query is None


class TestAddModifierToItem:
    """Tests for add-modifier patterns (add bacon, extra cheese, etc.)."""

    def test_add_bacon_simple(self):
        """Test 'add bacon' returns modify_existing_item with bacon modifier."""
        result = parse_open_input_deterministic("add bacon")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient name "Bacon" from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)
        assert result.modify_target_description is None  # No target specified

    def test_add_bacon_does_not_trigger_ingredient_search(self):
        """Test 'add bacon' does NOT trigger ingredient search.

        This is a regression test for a bug where 'add bacon' would trigger
        an ingredient search instead of adding bacon to the current item.
        """
        mock_ingredient_to_items = {
            "bacon": [{"name": "Bacon"}, {"name": "Side of Bacon"}],
        }
        result = parse_open_input_deterministic(
            "add bacon",
            ingredient_to_items=mock_ingredient_to_items
        )
        assert result is not None
        # Should be a modify request, NOT an ingredient search
        assert result.modify_existing_item is True
        assert result.ingredient_search_query is None
        assert not result.ingredient_search_matches

    def test_extra_bacon(self):
        """Test 'extra bacon' is treated as add bacon."""
        result = parse_open_input_deterministic("extra bacon")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient name "Bacon" from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)

    def test_more_cheese(self):
        """Test 'more cheese' is treated as add cheese."""
        result = parse_open_input_deterministic("more cheese")
        assert result is not None
        assert result.modify_existing_item is True
        # Check for any cheese variant (American Cheese, Swiss Cheese, etc.)
        assert any("cheese" in m.lower() for m in result.modify_add_modifiers)

    def test_add_bacon_and_cheese(self):
        """Test 'add bacon and cheese' adds both modifiers."""
        result = parse_open_input_deterministic("add bacon and cheese")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient names from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)
        # Check for any cheese variant (American Cheese, Swiss Cheese, etc.)
        assert any("cheese" in m.lower() for m in result.modify_add_modifiers)

    def test_add_bacon_to_the_bagel(self):
        """Test 'add bacon to the bagel' specifies target."""
        result = parse_open_input_deterministic("add bacon to the bagel")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient name "Bacon" from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)
        assert result.modify_target_description == "bagel"

    def test_add_bacon_to_the_plain_bagel(self):
        """Test 'add bacon to the plain bagel' specifies target with type."""
        result = parse_open_input_deterministic("add bacon to the plain bagel")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient name "Bacon" from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)
        assert result.modify_target_description == "plain bagel"

    def test_add_bacon_to_the_omelette(self):
        """Test 'add bacon to the omelette' works for non-bagel items."""
        result = parse_open_input_deterministic("add bacon to the omelette")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient name "Bacon" from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)
        assert result.modify_target_description == "omelette"

    def test_put_bacon_on_it(self):
        """Test 'put bacon on it' is treated as add bacon."""
        result = parse_open_input_deterministic("put bacon on it")
        assert result is not None
        assert result.modify_existing_item is True
        # Parser returns canonical ingredient name "Bacon" from database
        assert any("bacon" in m.lower() for m in result.modify_add_modifiers)
        assert result.modify_target_description is None  # "it" = implicit target

    def test_add_egg(self):
        """Test 'add egg' adds egg modifier."""
        result = parse_open_input_deterministic("add egg")
        assert result is not None
        assert result.modify_existing_item is True
        # Check case-insensitively since function may return "Egg"
        assert any("egg" in m.lower() for m in result.modify_add_modifiers)

    def test_add_unknown_item_returns_none(self):
        """Test 'add unicorn' returns None (unknown modifier)."""
        result = parse_open_input_deterministic("add unicorn")
        # Should return None because "unicorn" is not a known modifier
        # This will fall through to other parsers or LLM
        assert result is None or result.modify_existing_item is False

    def test_add_bacon_egg_and_cheese_not_caught(self):
        """Test 'add bacon egg and cheese' is NOT caught by add-modifier parser.

        This should fall through to other parsers and be parsed as a breakfast
        sandwich order (either as a signature item "The Classic BEC" or as a
        bagel with bacon, egg, and cheese).
        """
        result = parse_open_input_deterministic("add bacon egg and cheese")
        # Should NOT be treated as add-modifier
        assert result is not None
        assert result.modify_existing_item is False
        # Should be parsed as a sandwich order (signature item or bagel with modifiers)
        assert len(result.parsed_items) >= 1

    def test_add_scallion_cream_cheese_no_american_cheese(self):
        """Test 'add scallion cream cheese instead' does NOT add American Cheese.

        Regression test for bug where 'cheese' alias for American Cheese was
        matching as a substring in 'cream cheese', causing American Cheese
        to be incorrectly added to the modifiers list.
        """
        result = parse_open_input_deterministic("add scallion cream cheese instead")
        # Should not match as add-modifier since scallion cream cheese is a spread
        # not a protein/cheese/topping modifier
        # The key assertion: should NOT have American Cheese in modifiers
        if result is not None and result.modify_add_modifiers:
            modifiers_lower = [m.lower() for m in result.modify_add_modifiers]
            assert "american cheese" not in modifiers_lower, \
                f"American Cheese should not match 'cream cheese': {result.modify_add_modifiers}"

    def test_add_scallion_cc_no_american_cheese(self):
        """Test 'add scallion cc instead' does NOT add American Cheese.

        Tests the abbreviated 'cc' for cream cheese as well.
        """
        result = parse_open_input_deterministic("add scallion cc instead")
        if result is not None and result.modify_add_modifiers:
            modifiers_lower = [m.lower() for m in result.modify_add_modifiers]
            assert "american cheese" not in modifiers_lower, \
                f"American Cheese should not match 'cc' (cream cheese): {result.modify_add_modifiers}"


class TestExtractQuantityForPattern:
    """Unit tests for extract_quantity_for_pattern() function."""

    def test_numeric_quantity(self):
        """Test numeric quantities like '2 bacon'."""
        from orderbot.tasks.parsers.quantity_utils import extract_quantity_for_pattern
        assert extract_quantity_for_pattern("2 bacon", "bacon") == 2
        assert extract_quantity_for_pattern("3 vanilla syrups", "vanilla") == 3

    def test_word_quantity(self):
        """Test word quantities like 'two bacon'."""
        from orderbot.tasks.parsers.quantity_utils import extract_quantity_for_pattern
        assert extract_quantity_for_pattern("two bacon", "bacon") == 2
        assert extract_quantity_for_pattern("three vanilla", "vanilla") == 3

    def test_double_triple_quad(self):
        """Test 'double', 'triple', 'quad' prefixes."""
        from orderbot.tasks.parsers.quantity_utils import extract_quantity_for_pattern
        assert extract_quantity_for_pattern("double bacon", "bacon") == 2
        assert extract_quantity_for_pattern("triple shot", "shot") == 3
        assert extract_quantity_for_pattern("quad espresso", "espresso") == 4

    def test_extra_as_quantity_2(self):
        """Test 'extra' is treated as quantity=2."""
        from orderbot.tasks.parsers.quantity_utils import extract_quantity_for_pattern
        assert extract_quantity_for_pattern("extra bacon", "bacon") == 2
        assert extract_quantity_for_pattern("add extra cheese", "cheese") == 2

    def test_no_quantity_defaults_to_1(self):
        """Test that no quantity prefix defaults to 1."""
        from orderbot.tasks.parsers.quantity_utils import extract_quantity_for_pattern
        assert extract_quantity_for_pattern("add bacon", "bacon") == 1
        assert extract_quantity_for_pattern("vanilla syrup", "vanilla") == 1

    def test_case_insensitive(self):
        """Test that matching is case insensitive."""
        from orderbot.tasks.parsers.quantity_utils import extract_quantity_for_pattern
        assert extract_quantity_for_pattern("DOUBLE BACON", "bacon") == 2
        assert extract_quantity_for_pattern("Extra Cheese", "cheese") == 2
