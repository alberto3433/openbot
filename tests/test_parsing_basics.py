"""Basic deterministic parser tests: helpers, greetings, done patterns, bagel orders, fallback."""

import pytest

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
)

from orderbot.tasks.parsers import (
    parse_open_input_deterministic,
    _extract_quantity,
    WORD_TO_NUM,
    extract_zip_code,
    validate_delivery_zip_code,
)
from orderbot.tasks.parsers.deterministic import ExtractionPipeline

# Create a module-level pipeline for attribute extraction tests
_test_pipeline = ExtractionPipeline()


def _get_parsed_item_type(item) -> str:
    """Get the effective type of a ParsedItem.

    Returns a normalized type string for test assertions.
    """
    item_type = getattr(item, 'item_type', None)
    if item_type:
        # Map item_type to legacy type names for test compatibility
        if item_type in ("coffee_based_beverage", "espresso_based_beverage"):
            return "coffee"
        return item_type
    return 'unknown'


def _is_coffee_item(item) -> bool:
    """Check if a ParsedItem is a coffee/beverage."""
    item_type = getattr(item, 'item_type', None)
    return item_type in ("coffee_based_beverage", "espresso_based_beverage")


def _is_bagel_item(item) -> bool:
    """Check if a ParsedItem is a bagel."""
    item_type = getattr(item, 'item_type', None)
    return item_type == "bagel"


def _get_spread_slug(values: dict) -> str | None:
    """Helper to extract spread slug from multi-select attribute format."""
    spread = values.get("spread")
    if spread and isinstance(spread, list) and len(spread) > 0:
        return spread[0].get("slug")
    return None


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
        """Test extracting toasted preference via generic extract_attributes."""
        result = _test_pipeline.extract_attributes("yes, toasted please", "bagel")
        assert result.values.get("toasted") is True

        result = _test_pipeline.extract_attributes("not toasted", "bagel")
        assert result.values.get("toasted") is False

        result = _test_pipeline.extract_attributes("plain bagel", "bagel")
        assert "toasted" not in result.values  # No explicit toasted preference

    def test_extract_spread(self):
        """Test extracting spread via generic extract_attribute_values.

        Database slugs use full format (e.g., plain_cream_cheese, scallion_cream_cheese).
        Matching is done via display_name and aliases, not slug literals.
        Note: Spread is a multi-select attribute, so it returns a list of dicts.
        """
        # "scallion cream cheese" matches scallion_cream_cheese slug
        attrs = _test_pipeline.extract_attributes("with scallion cream cheese", "bagel")
        assert _get_spread_slug(attrs.values) == "scallion_cream_cheese"

        # "regular cream cheese" matches plain_cream_cheese slug
        attrs = _test_pipeline.extract_attributes("with regular cream cheese", "bagel")
        assert _get_spread_slug(attrs.values) == "plain_cream_cheese"

        attrs = _test_pipeline.extract_attributes("everything bagel toasted", "bagel")
        assert "spread" not in attrs.values  # No spread mentioned

    def test_extract_spread_cc_alias(self):
        """Test that 'cc' alias variants are normalized to correct slug."""
        # "scallion cc" alias resolves to scallion_cream_cheese slug
        attrs = _test_pipeline.extract_attributes("scallion cc", "bagel")
        spread = _get_spread_slug(attrs.values)
        assert spread == "scallion_cream_cheese", f"Expected 'scallion_cream_cheese' but got '{spread}'"

        # "blueberry cc" alias resolves to blueberry_cream_cheese slug
        attrs = _test_pipeline.extract_attributes("blueberry cc", "bagel")
        spread = _get_spread_slug(attrs.values)
        assert spread == "blueberry_cream_cheese", f"Expected 'blueberry_cream_cheese' but got '{spread}'"

    def test_extract_unavailable_size_option(self):
        """Test that extraction detects unavailable 'medium' size for coffee_based_beverage.

        Database has medium size with is_available=False. The extraction should
        detect this and store it in .unavailable list for helpful user messaging.
        """
        # "medium hot coffee" should detect that medium is unavailable
        result = _test_pipeline.extract_attributes("medium hot coffee", "coffee_based_beverage")

        # Should have unavailable entry for size attribute
        size_unavail = [u for u in result.unavailable if u.attr_slug == "size"]
        assert len(size_unavail) == 1, (
            f"Expected 1 unavailable entry for 'size', got: {result.unavailable}"
        )
        assert size_unavail[0].attempted_slug == "medium", (
            f"Expected attempted_slug='medium', got: {size_unavail[0]}"
        )

        # Should NOT have size set to medium (since it's unavailable)
        assert result.values.get("size") != "medium", (
            f"Size should NOT be 'medium' since it's unavailable, got: {result.values.get('size')}"
        )

    def test_extract_available_size_option(self):
        """Test that available size options are extracted normally."""
        # "large hot coffee" should extract size=large (available)
        result = _test_pipeline.extract_attributes("large hot coffee", "coffee_based_beverage")

        # Should have size=large (single_select returns slug directly)
        assert result.values.get("size") == "large", (
            f"Expected size='large', got: {result.values.get('size')}"
        )

        # Should NOT have any unavailable entries for size
        size_unavail = [u for u in result.unavailable if u.attr_slug == "size"]
        assert len(size_unavail) == 0, (
            f"Should not have unavailable size for available option, got: {size_unavail}"
        )

    def test_oat_milk_not_duplicated(self):
        """Verify 'oat milk' doesn't create duplicate Oat Milk + Oat entries.

        Bug regression test: The oat_milk ingredient has two aliases:
        "oat milk" and "oat". Previously, extract_attribute_values matched
        "oat milk" correctly, but _extract_modifiers_generic also matched
        "oat" (the short alias) because it wasn't filtered out. This caused
        duplicate modifiers in the cart display.

        The fix adds option aliases to attr_option_slugs so they're properly
        skipped by _extract_modifiers_generic.
        """
        result = _test_pipeline.extract_attributes("small coffee with oat milk", "coffee_based_beverage")
        milk_entries = result.values.get("milk_sweetener_syrup", [])
        assert len(milk_entries) == 1, (
            f"Expected 1 milk entry, got {len(milk_entries)}: {milk_entries}"
        )
        assert milk_entries[0]["slug"] == "oat_milk", (
            f"Expected slug='oat_milk', got: {milk_entries[0]}"
        )


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
        ("two bagel sandwiches", 2),
    ])
    def test_bagel_quantity_extraction(self, text, expected_qty):
        """Test that bagel quantities are correctly extracted.

        Parser creates a single ParsedItemEntry with quantity field set.
        ItemAdderHandler decides whether to create N separate items.
        """
        result = parse_open_input_deterministic(text)
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 1, f"Parser should create 1 entry with quantity, got {len(bagels)}"
        assert bagels[0].quantity == expected_qty, f"Expected quantity={expected_qty}, got {bagels[0].quantity}"

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
        """Test parsing bagel with toasted preference.

        Parser returns 1 item with quantity=2. The state machine later
        splits this into separate items when adding to the order.
        """
        result = parse_open_input_deterministic("two plain bagels toasted")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 1
        bagel = bagels[0]
        assert bagel.quantity == 2
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
# "By the Pound" Menu Query Tests
# =============================================================================

class TestByThePoundMenuQuery:
    """Tests that question prefixes are stripped from 'by the pound' queries."""

    @pytest.mark.parametrize("text,should_not_contain", [
        ("what's your food by the pound?", "what"),
        ("what is your food by the pound", "what"),
        ("tell me about your fish by the pound", "tell"),
        ("show me your cheese by the pound", "show"),
        ("can i see your food by the pound?", "can"),
    ])
    def test_by_the_pound_strips_question_prefix(self, text, should_not_contain):
        """Question words must not leak into menu_query_type."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parse for: {text}"
        assert result.menu_query is True, f"Expected menu_query for: {text}"
        assert result.menu_query_type is not None, f"Expected menu_query_type for: {text}"
        assert should_not_contain not in result.menu_query_type.lower(), (
            f"menu_query_type '{result.menu_query_type}' should not contain '{should_not_contain}'"
        )

    @pytest.mark.parametrize("text", [
        "food by the pound",
        "fish by the pound",
        "cheese by the pound",
    ])
    def test_by_the_pound_no_prefix_still_works(self, text):
        """Bare category + 'by the pound' still parses correctly (regression)."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parse for: {text}"
        assert result.menu_query is True, f"Expected menu_query for: {text}"
        assert result.menu_query_type is not None, f"Expected menu_query_type for: {text}"


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
