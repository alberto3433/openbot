"""
Tests for the parsing module.

Includes:
- Schema validation tests (no LLM required)
- Integration tests with mocked LLM responses
- Optional integration tests with real LLM (requires API key)
"""

import pytest
import os
from unittest.mock import MagicMock

from sandwich_bot.tasks.parsing import (
    ParsedBagelItem,
    ParsedCoffeeItem,
    ItemModification,
    ParsedInput,
    parse_user_message,
    PARSING_SYSTEM_PROMPT,
)


# =============================================================================
# Schema Validation Tests
# =============================================================================

class TestParsedBagelItem:
    """Tests for ParsedBagelItem schema."""

    def test_default_values(self):
        """Test default values are correct."""
        bagel = ParsedBagelItem()
        assert bagel.item_type == "bagel"
        assert bagel.bagel_type is None
        assert bagel.quantity == 1
        assert bagel.toasted is None
        assert bagel.spread is None
        assert bagel.extras == []

    def test_full_bagel(self):
        """Test creating a fully specified bagel."""
        bagel = ParsedBagelItem(
            bagel_type="everything",
            quantity=2,
            toasted=True,
            spread="cream cheese",
            spread_type="scallion",
            extras=["lox", "tomato", "capers"],
        )
        assert bagel.bagel_type == "everything"
        assert bagel.quantity == 2
        assert bagel.toasted is True
        assert bagel.spread == "cream cheese"
        assert bagel.spread_type == "scallion"
        assert bagel.extras == ["lox", "tomato", "capers"]


class TestParsedCoffeeItem:
    """Tests for ParsedCoffeeItem schema."""

    def test_default_values(self):
        """Test default values are correct."""
        coffee = ParsedCoffeeItem()
        assert coffee.item_type == "coffee"
        assert coffee.drink_type is None
        assert coffee.size is None
        assert coffee.iced is None
        assert coffee.milk is None
        assert coffee.extra_shots == 0

    def test_full_coffee(self):
        """Test creating a fully specified coffee."""
        coffee = ParsedCoffeeItem(
            drink_type="latte",
            size="large",
            iced=True,
            milk="oat",
            sweetener="vanilla",
            extra_shots=2,
        )
        assert coffee.drink_type == "latte"
        assert coffee.size == "large"
        assert coffee.iced is True
        assert coffee.milk == "oat"
        assert coffee.sweetener == "vanilla"
        assert coffee.extra_shots == 2


class TestItemModification:
    """Tests for ItemModification schema."""

    def test_modification_by_index(self):
        """Test modification targeting specific index."""
        mod = ItemModification(
            item_index=0,
            field="toasted",
            new_value=False,
        )
        assert mod.item_index == 0
        assert mod.field == "toasted"
        assert mod.new_value is False

    def test_modification_by_type(self):
        """Test modification targeting item type."""
        mod = ItemModification(
            item_type="bagel",
            field="spread",
            new_value="butter",
        )
        assert mod.item_type == "bagel"
        assert mod.field == "spread"
        assert mod.new_value == "butter"


class TestParsedInput:
    """Tests for ParsedInput schema."""

    def test_empty_input(self):
        """Test empty input has correct defaults."""
        parsed = ParsedInput()
        assert parsed.new_bagels == []
        assert parsed.new_coffees == []
        assert parsed.modifications == []
        assert parsed.answers == {}
        assert parsed.wants_checkout is False
        assert parsed.order_type is None
        assert parsed.is_greeting is False

    def test_multi_item_order(self):
        """Test parsing result with multiple items."""
        parsed = ParsedInput(
            new_bagels=[
                ParsedBagelItem(bagel_type="everything", toasted=True),
                ParsedBagelItem(bagel_type="plain"),
            ],
            new_coffees=[
                ParsedCoffeeItem(drink_type="latte", size="large", iced=True),
            ],
        )
        assert len(parsed.new_bagels) == 2
        assert len(parsed.new_coffees) == 1
        assert parsed.new_bagels[0].bagel_type == "everything"
        assert parsed.new_coffees[0].iced is True

    def test_order_with_answers(self):
        """Test parsing result with question answers."""
        parsed = ParsedInput(
            answers={
                "toasted": True,
                "spread": "cream cheese",
            }
        )
        assert parsed.answers["toasted"] is True
        assert parsed.answers["spread"] == "cream cheese"

    def test_checkout_intent(self):
        """Test parsing checkout intent."""
        parsed = ParsedInput(wants_checkout=True)
        assert parsed.wants_checkout is True

    def test_cancellation_intent(self):
        """Test parsing cancellation intent."""
        parsed = ParsedInput(
            cancel_item_index=0,
            cancel_item_description="the plain bagel",
        )
        assert parsed.cancel_item_index == 0
        assert parsed.cancel_item_description == "the plain bagel"

    def test_delivery_info(self):
        """Test parsing delivery information."""
        parsed = ParsedInput(
            order_type="delivery",
            delivery_address="123 Main St, New York NY 10001",
        )
        assert parsed.order_type == "delivery"
        assert parsed.delivery_address == "123 Main St, New York NY 10001"

    def test_customer_info(self):
        """Test parsing customer information."""
        parsed = ParsedInput(
            customer_name="John Doe",
            customer_phone="555-1234",
            customer_email="john@example.com",
        )
        assert parsed.customer_name == "John Doe"
        assert parsed.customer_phone == "555-1234"
        assert parsed.customer_email == "john@example.com"


# =============================================================================
# Parsing System Prompt Tests
# =============================================================================

class TestParsingSystemPrompt:
    """Tests for the parsing system prompt."""

    def test_prompt_exists(self):
        """Test that system prompt is defined."""
        assert PARSING_SYSTEM_PROMPT is not None
        assert len(PARSING_SYSTEM_PROMPT) > 100

    def test_prompt_contains_key_instructions(self):
        """Test that prompt contains key parsing instructions."""
        assert "bagel" in PARSING_SYSTEM_PROMPT.lower()
        assert "coffee" in PARSING_SYSTEM_PROMPT.lower()
        assert "extract" in PARSING_SYSTEM_PROMPT.lower()


# =============================================================================
# Mocked LLM Tests
# =============================================================================

class TestParseUserMessageMocked:
    """Tests for parse_user_message with mocked LLM."""

    def test_parse_simple_bagel_order(self):
        """Test parsing a simple bagel order."""
        # Create a mock client that returns a predefined ParsedInput
        mock_result = ParsedInput(
            new_bagels=[
                ParsedBagelItem(bagel_type="everything", toasted=True)
            ]
        )

        mock_completion = MagicMock()
        mock_completion.create.return_value = mock_result

        mock_client = MagicMock()
        mock_client.chat.completions = mock_completion

        result = parse_user_message(
            "I'd like an everything bagel toasted",
            client=mock_client,
        )

        assert len(result.new_bagels) == 1
        assert result.new_bagels[0].bagel_type == "everything"
        assert result.new_bagels[0].toasted is True

    def test_parse_multi_item_order(self):
        """Test parsing a multi-item order."""
        mock_result = ParsedInput(
            new_bagels=[
                ParsedBagelItem(bagel_type="sesame", spread="cream cheese")
            ],
            new_coffees=[
                ParsedCoffeeItem(drink_type="latte", size="large", iced=True)
            ]
        )

        mock_completion = MagicMock()
        mock_completion.create.return_value = mock_result

        mock_client = MagicMock()
        mock_client.chat.completions = mock_completion

        result = parse_user_message(
            "I want a sesame bagel with cream cheese and a large iced latte",
            client=mock_client,
        )

        assert len(result.new_bagels) == 1
        assert len(result.new_coffees) == 1
        assert result.new_bagels[0].spread == "cream cheese"
        assert result.new_coffees[0].iced is True

    def test_parse_yes_answer(self):
        """Test parsing 'yes' as an answer to pending question."""
        mock_result = ParsedInput(
            answers={"toasted": True}
        )

        mock_completion = MagicMock()
        mock_completion.create.return_value = mock_result

        mock_client = MagicMock()
        mock_client.chat.completions = mock_completion

        result = parse_user_message(
            "yes please",
            pending_question="Would you like that toasted?",
            client=mock_client,
        )

        assert result.answers.get("toasted") is True

    def test_parse_modification(self):
        """Test parsing a modification request."""
        mock_result = ParsedInput(
            modifications=[
                ItemModification(
                    item_index=0,
                    field="toasted",
                    new_value=False,
                )
            ]
        )

        mock_completion = MagicMock()
        mock_completion.create.return_value = mock_result

        mock_client = MagicMock()
        mock_client.chat.completions = mock_completion

        result = parse_user_message(
            "Actually, don't toast the bagel",
            context={"current_item": "everything bagel"},
            client=mock_client,
        )

        assert len(result.modifications) == 1
        assert result.modifications[0].field == "toasted"
        assert result.modifications[0].new_value is False


# =============================================================================
# Integration Tests (require API key)
# =============================================================================

@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set"
)
class TestParseUserMessageIntegration:
    """Integration tests with real LLM (requires API key)."""

    def test_parse_simple_bagel(self):
        """Test parsing a simple bagel order with real LLM."""
        result = parse_user_message(
            "I want an everything bagel toasted with cream cheese"
        )

        assert len(result.new_bagels) >= 1
        bagel = result.new_bagels[0]
        assert bagel.bagel_type == "everything"
        assert bagel.toasted is True
        assert bagel.spread == "cream cheese"

    def test_parse_coffee_order(self):
        """Test parsing a coffee order with real LLM."""
        result = parse_user_message(
            "Large iced latte with oat milk please"
        )

        assert len(result.new_coffees) >= 1
        coffee = result.new_coffees[0]
        assert coffee.drink_type == "latte"
        assert coffee.size == "large"
        assert coffee.iced is True
        assert coffee.milk == "oat"

    def test_parse_coffee_with_milk_defaults_to_whole(self):
        """Test that 'coffee with milk' defaults to whole milk."""
        result = parse_user_message("coffee with milk")

        assert len(result.new_coffees) >= 1
        coffee = result.new_coffees[0]
        assert coffee.milk == "whole"

    def test_parse_coffee_with_splash_of_milk(self):
        """Test that 'coffee with a splash of milk' captures milk preference."""
        result = parse_user_message("small coffee with a splash of milk")

        assert len(result.new_coffees) >= 1
        coffee = result.new_coffees[0]
        assert coffee.size == "small"
        # Deterministic parser returns "whole", LLM may return "splash" or "whole"
        assert coffee.milk is not None

    def test_parse_coffee_with_sweetener_and_syrup(self):
        """Test that coffee with 'sugar and vanilla syrups' extracts both modifiers.

        Regression test for bug where multi-item parser incorrectly split on ' and '
        between coffee modifiers, losing the syrup information.
        """
        result = parse_user_message("large iced coffee with sugar and 2 vanilla syrups")

        assert len(result.new_coffees) >= 1
        coffee = result.new_coffees[0]
        # Coffee type may be "coffee" or "drip coffee" depending on menu config
        assert "coffee" in coffee.drink_type.lower()
        assert coffee.size == "large"
        assert coffee.iced is True
        assert coffee.sweetener == "sugar"
        # flavor_syrup is the correct field name in ParsedCoffeeItem
        assert coffee.flavor_syrup == "vanilla"

    def test_parse_greeting(self):
        """Test parsing a simple greeting."""
        result = parse_user_message("Hi there!")

        assert result.is_greeting is True
        assert len(result.new_bagels) == 0
        assert len(result.new_coffees) == 0

    def test_parse_yes_answer_no_new_items(self):
        """Test that 'yes' answer to a pending question doesn't create new items."""
        result = parse_user_message(
            "yes",
            pending_question="Would you like that toasted?",
            context={"current_item": "plain bagel"}
        )

        # Should NOT create new items - that's the key thing
        assert len(result.new_bagels) == 0
        assert len(result.new_coffees) == 0

        # Should have the answer via either 'answers' field or as a modification
        has_toasted_answer = result.answers.get("toasted") is True
        has_toasted_modification = any(
            m.field == "toasted" and m.new_value is True
            for m in result.modifications
        )
        assert has_toasted_answer or has_toasted_modification

    def test_parse_spread_answer_no_new_items(self):
        """Test that spread answer to a pending question doesn't create new items."""
        result = parse_user_message(
            "cream cheese",
            pending_question="Would you like cream cheese or butter on that?",
            context={"current_item": "plain bagel"}
        )

        # Should NOT create new items - that's the key thing
        assert len(result.new_bagels) == 0

        # Should have the answer via either 'answers' field or as a modification
        has_spread_answer = result.answers.get("spread") == "cream cheese"
        has_spread_modification = any(
            m.field == "spread" and m.new_value == "cream cheese"
            for m in result.modifications
        )
        assert has_spread_answer or has_spread_modification

    def test_parse_checkout_intent(self):
        """Test parsing checkout intent."""
        result = parse_user_message(
            "That's all, I'm ready to pay",
            context={"items_count": 2}
        )

        assert result.wants_checkout is True or result.no_more_items is True

    def test_parse_cancellation(self):
        """Test parsing item cancellation."""
        result = parse_user_message(
            "Actually, forget the bagel. Just the coffee.",
            context={"items": ["everything bagel", "latte"]}
        )

        # Should either have cancel_item_index or cancel_item_description
        assert (
            result.cancel_item_index is not None or
            result.cancel_item_description is not None or
            len(result.modifications) > 0
        )


# =============================================================================
# Deterministic Parser Tests (no LLM required)
# =============================================================================

from sandwich_bot.tasks.parsers import (
    parse_open_input_deterministic,
    _extract_quantity,
    _extract_bagel_type,
    _extract_toasted,
    _extract_spread,
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

    def test_extract_bagel_type(self):
        """Test extracting bagel types from text."""
        assert _extract_bagel_type("I want a plain bagel") == "plain"
        assert _extract_bagel_type("everything bagel please") == "everything"
        assert _extract_bagel_type("sesame toasted") == "sesame"
        assert _extract_bagel_type("cinnamon raisin with butter") == "cinnamon raisin"
        assert _extract_bagel_type("just coffee") is None

    def test_extract_toasted(self):
        """Test extracting toasted preference."""
        assert _extract_toasted("yes, toasted please") is True
        assert _extract_toasted("not toasted") is False
        assert _extract_toasted("plain bagel") is None

    def test_extract_spread(self):
        """Test extracting spread and spread type."""
        spread, spread_type = _extract_spread("with cream cheese")
        assert spread == "cream cheese"
        assert spread_type is None

        spread, spread_type = _extract_spread("with scallion cream cheese")
        assert spread == "cream cheese"
        assert spread_type == "scallion"

        spread, spread_type = _extract_spread("with butter")
        assert spread == "butter"
        assert spread_type is None

        spread, spread_type = _extract_spread("plain bagel")
        assert spread is None
        assert spread_type is None

    def test_extract_spread_cc_alias(self):
        """Test that 'cc' alias is normalized to 'cream cheese'."""
        # "cc" is an alias for "Cream Cheese" in the database
        # The extraction should normalize it to "cream cheese" for:
        # 1. Consistent display in the order summary
        # 2. Correct pricing lookup
        spread, spread_type = _extract_spread("cc")
        assert spread == "cream cheese", f"Expected 'cream cheese' but got '{spread}'"
        assert spread_type is None


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
        assert result.new_bagel is False


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
        assert result.new_bagel is False


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
        assert result.new_bagel is True
        assert result.new_bagel_quantity == expected_qty

    @pytest.mark.parametrize("text,expected_type", [
        ("one plain bagel", "plain"),
        ("two everything bagels", "everything"),
        ("sesame bagel please", "sesame"),
        ("I want a cinnamon raisin bagel", "cinnamon raisin"),
        ("three bagels", None),  # No type specified
    ])
    def test_bagel_type_extraction(self, text, expected_type):
        """Test that bagel types are correctly extracted."""
        result = parse_open_input_deterministic(text)
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_type == expected_type

    def test_bagel_with_toasted(self):
        """Test parsing bagel with toasted preference."""
        result = parse_open_input_deterministic("two plain bagels toasted")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_quantity == 2
        assert result.new_bagel_type == "plain"
        assert result.new_bagel_toasted is True

    def test_bagel_with_spread(self):
        """Test parsing bagel with spread."""
        result = parse_open_input_deterministic("everything bagel with cream cheese")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_type == "everything"
        assert result.new_bagel_spread == "cream cheese"

    def test_bagel_with_spread_type(self):
        """Test parsing bagel with spread type - now correctly matches menu item."""
        result = parse_open_input_deterministic("plain bagel with scallion cream cheese")
        assert result is not None
        # Parser now correctly identifies this as the Scallion Cream Cheese Sandwich menu item
        assert result.new_menu_item == "Scallion Cream Cheese Sandwich"
        assert result.new_menu_item_bagel_choice == "plain"

    def test_full_bagel_order(self):
        """Test parsing a fully specified bagel order."""
        result = parse_open_input_deterministic(
            "three everything bagels toasted with cream cheese"
        )
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_quantity == 3
        assert result.new_bagel_type == "everything"
        assert result.new_bagel_toasted is True
        assert result.new_bagel_spread == "cream cheese"

    def test_bagel_with_comma_separated_modifiers(self):
        """Test bagel with modifiers separated by commas - regression test."""
        # This case was being incorrectly split by multi-item parser
        result = parse_open_input_deterministic("pumpernickel bagel, butter, not toasted please")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_type == "pumpernickel"
        assert result.new_bagel_spread == "butter"
        assert result.new_bagel_toasted is False

    @pytest.mark.parametrize("text,expected_toasted", [
        ("untoasted plain bagel", False),
        ("an untoasted plain bagel with nova", False),
        ("can I get an untoasted plain bagel with nova and capers", False),
        ("plain bagel untoasted", False),
        ("not toasted plain bagel", False),
        ("plain bagel not toasted", False),
    ])
    def test_untoasted_bagel_detected(self, text, expected_toasted):
        """Test that 'untoasted' and 'not toasted' set toasted=False."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parse result for: {text}"
        assert result.new_bagel is True, f"Expected new_bagel=True for: {text}"
        assert result.new_bagel_toasted == expected_toasted, \
            f"Expected toasted={expected_toasted} for '{text}', got {result.new_bagel_toasted}"


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
        ("the chipotle egg omelette", "signature_item"),  # Signature item
    ])
    def test_deterministic_handles_coffee_and_menu_items(self, text, expected_type):
        """Test that coffee and menu items are now handled deterministically."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected deterministic parse for: {text}"
        if expected_type == "coffee":
            assert result.new_coffee is True
            assert result.new_coffee_type.lower() == "coffee"
        elif expected_type == "signature_item":
            assert result.new_signature_item is True
            assert result.new_signature_item_name is not None
        else:
            assert result.new_menu_item is not None


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
        # Latte might be recognized as coffee
        assert result.new_coffee is True or result.new_menu_item is not None

    def test_replacement_with_bagel(self):
        """Test replacement with bagel item."""
        result = parse_open_input_deterministic("make it an everything bagel instead")
        assert result is not None
        assert result.replace_last_item is True
        assert result.new_bagel is True
        assert result.new_bagel_type == "everything"


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
        from sandwich_bot.tasks.modifier_change_handler import ModifierChangeHandler
        handler = ModifierChangeHandler()
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
# Notes Extraction Tests
# =============================================================================

class TestNotesExtraction:
    """Tests for extract_notes_from_input function."""

    def test_light_on_the_cream_cheese(self):
        """Test 'light on the cream cheese' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("plain bagel with light on the cream cheese")
        assert "light cream cheese" in notes

    def test_light_cream_cheese_short_form(self):
        """Test 'light cream cheese' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("bagel with light cream cheese")
        assert "light cream cheese" in notes

    def test_extra_bacon(self):
        """Test 'extra bacon' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("egg and cheese bagel with extra bacon")
        assert "extra bacon" in notes

    def test_lots_of_cream_cheese(self):
        """Test 'lots of cream cheese' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("bagel with lots of cream cheese")
        assert "extra cream cheese" in notes

    def test_splash_of_milk(self):
        """Test 'a splash of milk' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("coffee with a splash of milk")
        assert "a splash of milk" in notes

    def test_go_easy_on_the_mayo(self):
        """Test 'go easy on the mayo' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("sandwich with go easy on the mayo")
        assert "light mayo" in notes

    def test_little_bit_of_sugar(self):
        """Test 'a little sugar' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("coffee with a little sugar")
        assert "a little sugar" in notes

    def test_no_onions(self):
        """Test 'no onions' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("bagel with no onions")
        assert "no onions" in notes

    def test_hold_the_tomato(self):
        """Test 'hold the tomato' extracts correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("sandwich hold the tomato")
        assert "no tomato" in notes

    def test_multiple_notes(self):
        """Test multiple qualifier phrases extract correctly."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("bagel with light cream cheese and extra bacon")
        assert "light cream cheese" in notes
        assert "extra bacon" in notes

    def test_no_notes_for_regular_order(self):
        """Test that regular orders without qualifiers have no notes."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("plain bagel with cream cheese")
        assert len(notes) == 0

    def test_heavy_on_the_cheese(self):
        """Test 'heavy on the cheese' extracts as extra."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        notes = extract_notes_from_input("bagel heavy on the cheese")
        assert "extra cheese" in notes

    def test_multi_item_notes_separated_coffee_only(self):
        """Test that coffee notes filter only includes coffee-related notes."""
        from sandwich_bot.tasks.state_machine import extract_notes_from_input
        # Multi-item order: "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        notes = extract_notes_from_input("a coffee with a splash of milk and a bagel with a lot of cream cheese")
        # Should extract both notes separately
        assert "a splash of milk" in notes
        assert "extra cream cheese" in notes

    def test_multi_item_modifiers_bagel_only(self):
        """Test that extract_modifiers_from_input filters to bagel-related special instructions only."""
        from sandwich_bot.tasks.state_machine import extract_modifiers_from_input
        # Multi-item order: "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        modifiers = extract_modifiers_from_input("a coffee with a splash of milk and a bagel with a lot of cream cheese")
        # Bagel modifiers should only include bagel-related instructions (cream cheese), not coffee-related (splash of milk)
        instructions_str = modifiers.get_special_instructions_string() or ""
        assert "cream cheese" in instructions_str
        assert "splash" not in instructions_str or "milk" not in instructions_str  # Coffee instruction should be filtered out

    def test_multi_item_coffee_with_milk_and_special_instructions(self):
        """Test that multi-item parser extracts milk and special instructions for coffee."""
        from sandwich_bot.tasks.state_machine import _parse_multi_item_order
        from sandwich_bot.tasks.schemas import ParsedCoffeeEntry
        # Multi-item order: "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        result = _parse_multi_item_order("a coffee with a splash of milk and a bagel with a lot of cream cheese")
        assert result is not None
        assert result.new_coffee is True
        assert result.new_bagel is True
        # Check parsed_items has a coffee with milk and special instructions
        coffee_items = [item for item in result.parsed_items if isinstance(item, ParsedCoffeeEntry)]
        assert len(coffee_items) >= 1
        coffee = coffee_items[0]
        assert coffee.milk == "whole"  # "with a splash of milk" should default to whole
        assert coffee.special_instructions is not None
        assert "splash" in coffee.special_instructions.lower() or "milk" in coffee.special_instructions.lower()

    def test_coffee_with_sugar_on_the_side(self):
        """Test that 'sugar on the side' adds sugar as sweetener AND to special_instructions."""
        from sandwich_bot.tasks.parsers.deterministic import parse_open_input_deterministic
        from sandwich_bot.tasks.schemas import ParsedCoffeeEntry
        result = parse_open_input_deterministic("large coffee iced sugar on the side")
        assert result is not None
        assert result.new_coffee is True
        # Sugar SHOULD be extracted as a sweetener (for pricing/cart)
        assert result.new_coffee_sweetener == "sugar"
        # Sugar on the side should ALSO be in special_instructions
        assert result.new_coffee_special_instructions is not None
        assert "sugar on the side" in result.new_coffee_special_instructions.lower()
        # Also check parsed_items
        coffee_items = [item for item in result.parsed_items if isinstance(item, ParsedCoffeeEntry)]
        assert len(coffee_items) >= 1
        coffee = coffee_items[0]
        assert len(coffee.sweeteners) >= 1  # Sweetener added for pricing
        assert coffee.sweeteners[0].type == "sugar"
        assert coffee.special_instructions is not None
        assert "sugar on the side" in coffee.special_instructions.lower()

    def test_coffee_with_cream_on_the_side(self):
        """Test that 'cream on the side' adds cream as milk AND to special_instructions."""
        from sandwich_bot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic("large coffee cream on the side")
        assert result is not None
        assert result.new_coffee is True
        # Cream SHOULD be extracted as milk (for pricing/cart)
        assert result.new_coffee_milk == "cream"
        # Cream on the side should ALSO be in special_instructions
        assert result.new_coffee_special_instructions is not None
        assert "cream on the side" in result.new_coffee_special_instructions.lower()

    def test_coffee_with_milk_on_the_side(self):
        """Test that 'milk on the side' adds milk AND to special_instructions."""
        from sandwich_bot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic("coffee milk on the side")
        assert result is not None
        assert result.new_coffee is True
        # Milk SHOULD be extracted (defaults to whole when just "milk" is mentioned)
        assert result.new_coffee_milk == "whole"
        # Milk on the side should ALSO be in special_instructions
        assert result.new_coffee_special_instructions is not None
        assert "milk on the side" in result.new_coffee_special_instructions.lower()

    # -------------------------------------------------------------------------
    # Standalone Special Instruction Patterns
    # -------------------------------------------------------------------------

    def test_special_instruction_room_for_cream(self):
        """Test 'room for cream' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("coffee room for cream")
        assert any("room" in i.lower() for i in instructions)

    def test_special_instruction_not_too_hot(self):
        """Test 'not too hot' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("latte not too hot")
        assert any("not too hot" in i.lower() for i in instructions)

    def test_special_instruction_lukewarm(self):
        """Test 'lukewarm' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("coffee lukewarm please")
        assert any("lukewarm" in i.lower() for i in instructions)

    def test_special_instruction_upside_down(self):
        """Test 'upside down' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("caramel macchiato upside down")
        assert any("upside down" in i.lower() for i in instructions)

    def test_special_instruction_well_stirred(self):
        """Test 'well stirred' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee well stirred")
        assert any("well stirred" in i.lower() for i in instructions)

    def test_special_instruction_mixed(self):
        """Test 'mixed' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("latte mixed")
        assert any("mixed" in i.lower() for i in instructions)

    def test_special_instruction_lightly_toasted(self):
        """Test 'lightly toasted' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("plain bagel lightly toasted")
        assert any("lightly toasted" in i.lower() for i in instructions)

    def test_special_instruction_well_done(self):
        """Test 'well done' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("everything bagel well done")
        assert any("well done" in i.lower() for i in instructions)

    def test_special_instruction_cut_in_half(self):
        """Test 'cut in half' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("bagel with cream cheese cut in half")
        assert any("cut in half" in i.lower() for i in instructions)

    def test_special_instruction_sliced(self):
        """Test 'sliced' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("plain bagel sliced")
        assert any("sliced" in i.lower() for i in instructions)

    def test_special_instruction_open_faced(self):
        """Test 'open faced' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("egg sandwich open faced")
        assert any("open faced" in i.lower() for i in instructions)

    def test_special_instruction_spread_thin(self):
        """Test 'spread thin' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("bagel with cream cheese spread thin")
        assert any("spread thin" in i.lower() for i in instructions)

    def test_special_instruction_on_one_side(self):
        """Test 'on one side' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("cream cheese only on one side")
        assert any("on one side" in i.lower() for i in instructions)

    def test_special_instruction_on_both_halves(self):
        """Test 'on both halves' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("butter on both halves")
        assert any("on both halves" in i.lower() for i in instructions)

    def test_special_instruction_melted(self):
        """Test 'melted' is captured as special instruction."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("bagel with cheese melted")
        assert any("melted" in i.lower() for i in instructions)

    def test_special_instruction_extra_ice(self):
        """Test 'extra ice' is captured as special instruction (existing qualifier pattern)."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee extra ice")
        assert any("extra ice" in i.lower() for i in instructions)

    def test_special_instruction_light_ice(self):
        """Test 'light ice' is captured as special instruction (existing qualifier pattern)."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee light ice")
        assert any("light ice" in i.lower() for i in instructions)

    def test_special_instruction_no_ice(self):
        """Test 'no ice' is captured as special instruction (existing qualifier pattern)."""
        from sandwich_bot.tasks.parsers.deterministic import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input("iced coffee no ice")
        assert any("no ice" in i.lower() for i in instructions)

    def test_multi_item_bagel_and_signature_item(self):
        """Test that multi-item parser recognizes speed menu items like The Classic BEC."""
        from sandwich_bot.tasks.state_machine import _parse_multi_item_order
        # Multi-item order: "one bagel and one classic BEC"
        result = _parse_multi_item_order("one bagel and one classic BEC")
        assert result is not None
        # Should detect both items
        assert result.new_bagel is True
        assert result.new_signature_item is True
        # The Classic BEC should be recognized as a speed menu item
        assert "classic" in result.new_signature_item_name.lower() or "bec" in result.new_signature_item_name.lower()

    def test_multi_item_signature_item_and_coffee(self):
        """Test multi-item order with speed menu item and coffee."""
        from sandwich_bot.tasks.state_machine import _parse_multi_item_order
        result = _parse_multi_item_order("the lexington and a latte")
        assert result is not None
        assert result.new_signature_item is True
        assert result.new_coffee is True
        # Lexington is a speed menu item
        assert "lexington" in result.new_signature_item_name.lower()

    def test_multi_item_two_signature_items(self):
        """Test multi-item order with two speed menu items (takes the last one)."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_signature_item_deterministic
        # Note: Multi-item parser only tracks one speed menu item at a time
        # Each item individually should be recognized as a speed menu item
        leo = _parse_signature_item_deterministic("the leo")
        bec = _parse_signature_item_deterministic("the classic bec")
        assert leo is not None
        assert bec is not None
        assert leo.new_signature_item is True
        assert bec.new_signature_item is True

    def test_multi_item_coffee_and_spread_sandwich_with_bagel_type(self):
        """Test that 'a sesame bagel with butter' captures the sesame bagel type."""
        from sandwich_bot.tasks.state_machine import _parse_multi_item_order
        result = _parse_multi_item_order("a coffee with a little bit of milk and a sesame bagel with butter")
        assert result is not None
        # Coffee should be captured
        assert result.new_coffee is True
        # "sesame bagel with butter" should be recognized as Butter Sandwich
        assert result.new_menu_item is not None
        assert "butter" in result.new_menu_item.lower()
        # Most importantly: bagel choice should be "sesame"
        assert result.new_menu_item_bagel_choice == "sesame"

    def test_bagel_with_cream_cheese_is_build_your_own(self):
        """Test that 'an everything bagel with cream cheese' is parsed as build-your-own bagel, not menu item."""
        from sandwich_bot.tasks.state_machine import _parse_multi_item_order
        result = _parse_multi_item_order("an everything bagel with cream cheese and a coffee")
        assert result is not None
        assert result.new_coffee is True
        # "everything bagel with cream cheese" should be parsed as a bagel order (not menu item)
        # because the user explicitly mentioned "bagel"
        assert result.new_bagel is True
        assert result.new_bagel_type == "everything"
        assert result.new_bagel_spread == "cream cheese"
        assert result.new_menu_item is None  # Not a menu item


class TestRecommendationInquiryParsing:
    """Tests for recommendation question detection.

    Recommendation questions should NOT add items to cart - they should
    just provide recommendations for items in the requested category.
    """

    @pytest.mark.parametrize("text,expected_category", [
        # Direct "recommend" patterns
        ("what do you recommend?", "general"),
        ("what would you recommend?", "general"),
        ("any recommendations?", "general"),
        ("do you have any recommendations?", "general"),
        # Bagel recommendations
        ("what kind of bagel do you recommend?", "bagel"),
        ("what bagel do you recommend?", "bagel"),
        ("which bagel is best?", "bagel"),
        ("what's your best bagel?", "bagel"),
        ("what's popular for bagels?", "bagel"),
        # Sandwich recommendations
        ("what sandwich do you recommend?", "sandwich"),
        ("which sandwich is best?", "sandwich"),
        ("what's your most popular sandwich?", "sandwich"),
        # Coffee recommendations
        ("what coffee do you recommend?", "coffee"),
        ("what's your best coffee?", "coffee"),
        ("what coffee is popular?", "coffee"),
        # Breakfast recommendations
        ("what do you recommend for breakfast?", "breakfast"),
        ("what's good for breakfast?", "breakfast"),
        # Lunch recommendations
        ("what do you recommend for lunch?", "lunch"),
        ("what's popular for lunch?", "lunch"),
        # Popular/best patterns
        ("what's popular?", "general"),
        ("what's your most popular item?", "general"),
        ("what sells best?", "general"),
    ])
    def test_recommendation_patterns_detected(self, text, expected_category):
        """Test that recommendation questions are detected with correct category."""
        from sandwich_bot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry(text)
        assert result is not None, f"Failed to detect recommendation in: {text}"
        assert result.asks_recommendation is True
        assert result.recommendation_category == expected_category

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
        from sandwich_bot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry(text)
        assert result is None, f"Incorrectly detected recommendation in: {text}"

    def test_recommendation_should_not_add_to_cart(self):
        """Test that recommendation response has no items to add."""
        from sandwich_bot.tasks.state_machine import _parse_recommendation_inquiry
        result = _parse_recommendation_inquiry("what kind of bagel do you recommend?")
        assert result is not None
        assert result.asks_recommendation is True
        # Should NOT have any items flagged for adding
        assert result.new_bagel is False
        assert result.new_coffee is False
        assert result.new_menu_item is None  # sandwiches use new_menu_item


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
        from sandwich_bot.tasks.state_machine import _parse_item_description_inquiry
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
        from sandwich_bot.tasks.state_machine import _parse_item_description_inquiry
        result = _parse_item_description_inquiry(text)
        assert result is None, f"Incorrectly detected item description inquiry in: {text}"

    def test_item_description_should_not_add_to_cart(self):
        """Test that item description response has no items to add."""
        from sandwich_bot.tasks.state_machine import _parse_item_description_inquiry
        result = _parse_item_description_inquiry("what's on the health nut?")
        assert result is not None
        assert result.asks_item_description is True
        # Should NOT have any items flagged for adding
        assert result.new_bagel is False
        assert result.new_coffee is False
        assert result.new_menu_item is None


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
        from sandwich_bot.tasks.state_machine import _parse_signature_item_deterministic
        result = _parse_signature_item_deterministic(text)
        assert result is not None, f"Failed to detect speed menu item in: {text}"
        assert result.new_signature_item is True
        assert result.new_signature_item_name == expected_name

    @pytest.mark.parametrize("text,expected_bagel", [
        ("The Classic BEC on a wheat bagel", "wheat"),
        ("classic bec on wheat", "wheat"),
        ("The Leo on an everything bagel", "everything"),
        ("leo on everything", "everything"),
        ("The Traditional on a sesame bagel", "sesame"),
        ("classic bec but on a plain bagel", "plain"),
        ("give me the classic bec on a pumpernickel bagel", "pumpernickel"),
        ("I want the lexington on whole wheat", "whole wheat"),
        # Without "on/with" prefix - should still extract bagel type
        ("bec everything bagel toasted", "everything"),
        ("classic bec plain bagel", "plain"),
        ("the leo sesame bagel", "sesame"),
    ])
    def test_signature_item_with_bagel_choice(self, text, expected_bagel):
        """Test that speed menu items with bagel choice are correctly parsed."""
        from sandwich_bot.tasks.state_machine import _parse_signature_item_deterministic
        result = _parse_signature_item_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        assert result.new_signature_item is True
        assert result.new_signature_item_bagel_choice == expected_bagel

    @pytest.mark.parametrize("text,expected_toasted", [
        ("The Classic BEC toasted", True),
        ("classic bec not toasted", False),
        ("The Leo toasted please", True),
        ("the lexington not toasted", False),
    ])
    def test_signature_item_with_toasted(self, text, expected_toasted):
        """Test that speed menu items with toasted preference are correctly parsed."""
        from sandwich_bot.tasks.state_machine import _parse_signature_item_deterministic
        result = _parse_signature_item_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        assert result.new_signature_item is True
        assert result.new_signature_item_toasted == expected_toasted

    @pytest.mark.parametrize("text,expected_qty", [
        ("2 classics", 2),
        ("two leos", 2),
        ("3 classic becs", 3),
        ("three traditionals", 3),
    ])
    def test_signature_item_with_quantity(self, text, expected_qty):
        """Test that speed menu items with quantity are correctly parsed."""
        from sandwich_bot.tasks.state_machine import _parse_signature_item_deterministic
        result = _parse_signature_item_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        assert result.new_signature_item is True
        assert result.new_signature_item_quantity == expected_qty

    def test_signature_item_with_all_options(self):
        """Test parsing speed menu with bagel choice, toasted, and quantity."""
        from sandwich_bot.tasks.state_machine import _parse_signature_item_deterministic
        result = _parse_signature_item_deterministic("2 classic becs on wheat bagels toasted")
        assert result is not None
        assert result.new_signature_item is True
        assert result.new_signature_item_name == "The Classic BEC"
        assert result.new_signature_item_quantity == 2
        assert result.new_signature_item_bagel_choice == "wheat"
        assert result.new_signature_item_toasted is True

    def test_signature_item_parsed_before_bagel_check(self):
        """Test that speed menu items are parsed BEFORE generic bagel check.

        This is the key fix - 'The Classic BEC on a wheat bagel' should NOT
        be parsed as a simple wheat bagel order.
        """
        result = parse_open_input_deterministic("The Classic BEC but on a wheat bagel")
        assert result is not None
        # Should be speed menu bagel, NOT a plain bagel
        assert result.new_signature_item is True
        assert result.new_signature_item_name == "The Classic BEC"
        assert result.new_signature_item_bagel_choice == "wheat"
        # Should NOT be a plain bagel
        assert result.new_bagel is False

    def test_non_signature_item_still_works(self):
        """Test that regular bagel orders still work."""
        result = parse_open_input_deterministic("a wheat bagel with cream cheese")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_type == "wheat"
        assert result.new_signature_item is False


class TestSplitQuantityBagelParsing:
    """Tests for split-quantity bagel parsing (e.g., 'two bagels one with lox one with cream cheese')."""

    def test_two_bagels_one_lox_one_cream_cheese(self):
        """Test parsing 'two plain bagels one with scallion cream cheese one with lox'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("two plain bagels one with scallion cream cheese one with lox")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_quantity == 2
        assert result.new_bagel_type == "plain"
        assert len(result.parsed_items) == 2
        # First bagel: scallion cream cheese
        assert result.parsed_items[0].bagel_type == "plain"
        assert result.parsed_items[0].spread == "cream cheese"
        assert result.parsed_items[0].spread_type == "scallion"
        # Second bagel: lox (normalized to canonical name from database)
        assert result.parsed_items[1].bagel_type == "plain"
        assert result.parsed_items[1].spread == "Nova Scotia Salmon"

    def test_two_bagels_toasted_variants(self):
        """Test parsing 'two everything bagels one toasted one not toasted'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("two everything bagels one toasted one not toasted")
        assert result is not None
        assert result.new_bagel_quantity == 2
        assert result.new_bagel_type == "everything"
        assert len(result.parsed_items) == 2
        assert result.parsed_items[0].toasted is True
        assert result.parsed_items[1].toasted is False

    def test_three_bagels_different_spreads(self):
        """Test parsing 'three bagels one with butter one plain one with cream cheese'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("three bagels one with butter one plain one with cream cheese")
        assert result is not None
        assert result.new_bagel_quantity == 3
        assert result.new_bagel_type is None  # No base type specified
        assert len(result.parsed_items) == 3
        assert result.parsed_items[0].spread == "butter"
        assert result.parsed_items[1].spread is None  # plain = no spread
        assert result.parsed_items[2].spread == "cream cheese"

    def test_numeric_quantity(self):
        """Test parsing with numeric quantity."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("2 bagels one with lox one with cream cheese")
        assert result is not None
        assert result.new_bagel_quantity == 2
        assert len(result.parsed_items) == 2

    def test_no_split_single_bagel(self):
        """Test that single bagel orders are not matched by split-quantity parser."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("one plain bagel with cream cheese")
        assert result is None  # Should not match - no split pattern

    def test_no_split_same_config(self):
        """Test that bagels with same config are not matched by split-quantity parser."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("two plain bagels with cream cheese")
        assert result is None  # Should not match - no split pattern

    def test_spread_alias_cc_toasted_lox(self):
        """Test parsing '2 plain bagels, one with cc toasted, one with lox not toasted'.

        This tests spread alias normalization (cc -> cream cheese) and combined
        attribute extraction (spread + toasted together).
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels(
            "2 plain bagels, one with cc toasted, one with lox not toasted"
        )
        assert result is not None
        assert result.new_bagel_quantity == 2
        assert result.new_bagel_type == "plain"
        assert len(result.parsed_items) == 2
        # First bagel: cream cheese (from "cc" alias), toasted
        assert result.parsed_items[0].bagel_type == "plain"
        assert result.parsed_items[0].spread == "cream cheese"
        assert result.parsed_items[0].toasted is True
        # Second bagel: lox, not toasted
        assert result.parsed_items[1].bagel_type == "plain"
        assert result.parsed_items[1].spread == "Nova Scotia Salmon"
        assert result.parsed_items[1].toasted is False

    def test_different_bagel_types_one_plain_one_everything(self):
        """Test parsing '2 bagels, one plain, one everything'.

        This tests per-item bagel type detection where each item
        specifies a different bagel type.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("2 bagels, one plain, one everything")
        assert result is not None
        assert result.new_bagel_quantity == 2
        assert len(result.parsed_items) == 2
        # First bagel: plain
        assert result.parsed_items[0].bagel_type == "plain"
        # Second bagel: everything
        assert result.parsed_items[1].bagel_type == "everything"

    def test_uneven_split_one_toasted_two_not(self):
        """Test parsing '3 bagels, one toasted, two not toasted'.

        This tests uneven split handling where distribution quantities
        (one, two) don't match equal division.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("3 bagels, one toasted, two not toasted")
        assert result is not None
        assert result.new_bagel_quantity == 3
        assert len(result.parsed_items) == 3
        # First bagel: toasted
        assert result.parsed_items[0].toasted is True
        # Second and third bagels: not toasted
        assert result.parsed_items[1].toasted is False
        assert result.parsed_items[2].toasted is False

    def test_first_second_ordinals_with_spreads(self):
        """Test parsing '2 bagels, first one with butter, second one with cream cheese'.

        This tests ordinal patterns (first/second) for specifying
        different configurations.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels(
            "2 bagels, first one with butter, second one with cream cheese"
        )
        assert result is not None
        assert result.new_bagel_quantity == 2
        assert len(result.parsed_items) == 2
        # First bagel: butter
        assert result.parsed_items[0].spread == "butter"
        # Second bagel: cream cheese
        assert result.parsed_items[1].spread == "cream cheese"

    def test_spread_alias_pb(self):
        """Test parsing with peanut butter alias 'pb'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_bagels

        result = _parse_split_quantity_bagels("2 bagels, one with pb, one with cc")
        assert result is not None
        assert len(result.parsed_items) == 2
        assert result.parsed_items[0].spread == "peanut butter"
        assert result.parsed_items[1].spread == "cream cheese"


class TestSplitQuantityDrinksParsing:
    """Tests for split-quantity drink parsing (e.g., 'two coffees one with milk one black')."""

    def test_two_coffees_one_milk_one_black(self):
        """Test parsing 'two coffees one with milk one black'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("two coffees one with milk one black")
        assert result is not None
        assert result.new_coffee is True
        assert result.new_coffee_quantity == 2
        assert result.new_coffee_type.lower() == "coffee"
        assert len(result.parsed_items) == 2
        # First coffee: with milk
        assert result.parsed_items[0].drink_type.lower() == "coffee"
        assert result.parsed_items[0].milk == "whole"
        # Second coffee: black
        assert result.parsed_items[1].drink_type.lower() == "coffee"
        assert result.parsed_items[1].milk == "none"

    def test_two_lattes_one_iced_one_hot(self):
        """Test parsing 'two lattes one iced one hot'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("two lattes one iced one hot")
        assert result is not None
        assert result.new_coffee_quantity == 2
        assert result.new_coffee_type.lower() == "latte"
        assert len(result.parsed_items) == 2
        assert result.parsed_items[0].temperature == "iced"
        assert result.parsed_items[1].temperature == "hot"

    def test_two_teas_one_with_oat_milk_one_plain(self):
        """Test parsing 'two teas one with oat milk one plain'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("two teas one with oat milk one plain")
        assert result is not None
        assert result.new_coffee_quantity == 2
        # "tea" alias resolves to canonical name like "Iced Tea" or "Hot Tea"
        assert "tea" in result.new_coffee_type.lower()
        assert len(result.parsed_items) == 2
        assert result.parsed_items[0].milk == "oat"
        assert result.parsed_items[1].milk == "none"

    def test_three_coffees_different_temps(self):
        """Test parsing 'three coffees one iced one hot one decaf'."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("three coffees one iced one hot one decaf")
        assert result is not None
        assert result.new_coffee_quantity == 3
        assert len(result.parsed_items) == 3
        assert result.parsed_items[0].temperature == "iced"
        assert result.parsed_items[1].temperature == "hot"
        assert result.parsed_items[2].decaf is True

    def test_numeric_quantity(self):
        """Test parsing with numeric quantity."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("2 coffees one with almond milk one black")
        assert result is not None
        assert result.new_coffee_quantity == 2
        assert len(result.parsed_items) == 2
        assert result.parsed_items[0].milk == "almond"
        assert result.parsed_items[1].milk == "none"

    def test_no_split_single_coffee(self):
        """Test that single coffee orders are not matched by split-quantity parser."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("one large coffee with milk")
        assert result is None  # Should not match - no split pattern

    def test_no_split_same_config(self):
        """Test that coffees with same config are not matched by split-quantity parser."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("two coffees with milk")
        assert result is None  # Should not match - no split pattern

    def test_large_iced_lattes_split(self):
        """Test parsing 'two large lattes one iced one hot' preserves size."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("two large lattes one iced one hot")
        assert result is not None
        assert result.new_coffee_quantity == 2
        assert result.new_coffee_size == "large"
        assert len(result.parsed_items) == 2
        # Both should have the large size
        assert result.parsed_items[0].size == "large"
        assert result.parsed_items[0].temperature == "iced"
        assert result.parsed_items[1].size == "large"
        assert result.parsed_items[1].temperature == "hot"

    def test_uneven_split_one_iced_two_hot(self):
        """Test parsing '3 coffees, one iced, two hot'.

        This tests uneven split handling where distribution quantities
        don't match equal division.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("3 coffees, one iced, two hot")
        assert result is not None
        assert result.new_coffee_quantity == 3
        assert len(result.parsed_items) == 3
        # First coffee: iced
        assert result.parsed_items[0].temperature == "iced"
        # Second and third coffees: hot
        assert result.parsed_items[1].temperature == "hot"
        assert result.parsed_items[2].temperature == "hot"

    def test_two_coffees_one_hot_one_iced(self):
        """Test parsing '2 coffees, one hot, one iced'.

        This tests the basic hot/iced split pattern.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_split_quantity_drinks

        result = _parse_split_quantity_drinks("2 coffees, one hot, one iced")
        assert result is not None
        assert result.new_coffee_quantity == 2
        assert len(result.parsed_items) == 2
        # First coffee: hot
        assert result.parsed_items[0].temperature == "hot"
        # Second coffee: iced
        assert result.parsed_items[1].temperature == "iced"


class TestParsedItemsMultiItem:
    """Tests for parsed_items list in multi-item order parsing."""

    def test_signature_item_and_menu_item_both_in_parsed_items(self):
        """Test that The Leo + Butter Sandwich both appear in parsed_items.

        This was the original bug: 'the leo on wheat toasted and an everything bagel with butter'
        would only add the bagel (parsed as Butter Sandwich), skipping The Leo.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("the leo on wheat toasted and an everything bagel with butter")
        assert result is not None, "Failed to parse multi-item order"
        assert len(result.parsed_items) == 2, f"Expected 2 parsed_items, got {len(result.parsed_items)}"

        # Check the parsed_items list contains both items
        types = [item.type for item in result.parsed_items]
        assert "signature_item" in types, "Speed menu bagel should be in parsed_items"
        assert "menu_item" in types, "Menu item should be in parsed_items"

        # Verify The Leo details
        speed_items = [i for i in result.parsed_items if i.type == "signature_item"]
        assert len(speed_items) == 1
        assert speed_items[0].signature_item_name == "The Leo"
        assert speed_items[0].bagel_type == "wheat"
        assert speed_items[0].toasted is True

    def test_bagel_and_coffee_both_in_parsed_items(self):
        """Test that bagel + coffee both appear in parsed_items."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("a plain bagel toasted and a large iced latte")
        assert result is not None
        assert len(result.parsed_items) == 2

        types = [item.type for item in result.parsed_items]
        assert "bagel" in types
        assert "coffee" in types

    def test_latte_with_modifiers_and_bagel_with_modifiers(self):
        """Test that latte (with milk/syrup) + bagel (with spread) both appear in parsed_items.

        This tests the specific scenario where "latte" could be matched as a menu item
        instead of a coffee if parsing order is wrong.
        """
        from sandwich_bot.tasks.parsers.deterministic import _parse_multi_item_order

        # The exact problematic scenario
        result = _parse_multi_item_order(
            "large iced oat milk latte with vanilla and a gluten free everything bagel with veggie cc toasted"
        )
        assert result is not None
        assert len(result.parsed_items) == 2

        types = [item.type for item in result.parsed_items]
        assert "coffee" in types, f"Expected coffee in parsed_items, got: {types}"
        assert "bagel" in types or "menu_item" in types, f"Expected bagel/menu_item in parsed_items, got: {types}"

        # Verify coffee details
        coffee_items = [item for item in result.parsed_items if item.type == "coffee"]
        assert len(coffee_items) == 1
        coffee = coffee_items[0]
        assert coffee.drink_type.lower() == "latte"
        assert coffee.size == "large"
        assert coffee.temperature == "iced"
        assert coffee.milk == "oat"

    def test_two_menu_items_both_in_parsed_items(self):
        """Test that two menu items both appear in parsed_items."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("the lexington and a butter sandwich")
        assert result is not None
        # May get 2 menu items
        assert len(result.parsed_items) >= 2

        types = [item.type for item in result.parsed_items]
        # All should be menu_item or signature_item
        for t in types:
            assert t in ["menu_item", "signature_item"]

    def test_signature_item_and_coffee_both_in_parsed_items(self):
        """Test that speed menu bagel + coffee both appear in parsed_items."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("the classic bec and a coffee")
        assert result is not None
        assert len(result.parsed_items) == 2

        types = [item.type for item in result.parsed_items]
        assert "signature_item" in types
        assert "coffee" in types


class TestDuplicatePatterns:
    """Tests for duplicate item patterns: 'another one', 'one more', 'another bagel', etc."""

    @pytest.mark.parametrize("text,expected_type", [
        ("another bagel", "bagel"),
        ("another bagels", "bagel"),
        ("one more bagel", "bagel"),
        ("another coffee", "coffee"),
        ("one more coffee", "coffee"),
        ("another latte", "coffee"),
        ("one more latte", "coffee"),
        ("another cappuccino", "coffee"),
        ("another espresso", "coffee"),
        ("another americano", "coffee"),
        ("another mocha", "coffee"),
        ("another tea", "coffee"),  # Tea treated as coffee for ordering flow
        ("another sandwich", "sandwich"),
        ("one more sandwich", "sandwich"),
    ])
    def test_another_item_type_detected(self, text, expected_type):
        """Test that 'another <item>' patterns are detected with correct item type."""
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
        from sandwich_bot.tasks.parsers.deterministic import DUPLICATE_ALL_PATTERN
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


class TestEggCheeseSandwichAbbreviations:
    """Tests for egg+cheese sandwich abbreviation parsing (SEC, HEC, BEC, etc.)."""

    def test_ham_egg_and_cheese_on_wheat_toasted(self):
        """Test 'ham egg and cheese on wheat toasted' parses as breakfast sandwich.

        This is a regression test for a bug where 'ham egg and cheese on wheat toasted'
        was incorrectly parsed as 'Ham (1 lb)' deli item instead of a breakfast sandwich.
        """
        result = parse_open_input_deterministic("ham egg and cheese on wheat toasted")
        assert result is not None
        # Should be a bagel order with ham and egg proteins, not a deli item
        assert result.new_bagel is True
        assert result.new_bagel_proteins is not None
        assert "ham" in result.new_bagel_proteins
        assert "egg" in result.new_bagel_proteins
        assert result.new_bagel_needs_cheese_clarification is True
        assert result.new_bagel_toasted is True
        # Should NOT be a menu item
        assert result.new_menu_item is None

    def test_hec_abbreviation(self):
        """Test 'HEC' abbreviation parses as ham egg and cheese sandwich."""
        result = parse_open_input_deterministic("HEC")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_proteins is not None
        assert "ham" in result.new_bagel_proteins
        assert "egg" in result.new_bagel_proteins
        assert result.new_bagel_needs_cheese_clarification is True

    def test_sec_abbreviation(self):
        """Test 'SEC' abbreviation parses as sausage egg and cheese sandwich."""
        result = parse_open_input_deterministic("SEC")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_proteins is not None
        assert "sausage" in result.new_bagel_proteins
        assert "egg" in result.new_bagel_proteins
        assert result.new_bagel_needs_cheese_clarification is True

    def test_bec_abbreviation(self):
        """Test 'BEC' abbreviation parses as 'The Classic BEC' signature item.

        Note: BEC matches the signature item 'The Classic BEC' which is checked
        before egg cheese sandwich abbreviations, so it returns as a signature item.
        """
        result = parse_open_input_deterministic("BEC")
        assert result is not None
        # BEC matches as a signature item
        assert result.new_signature_item is True
        assert result.new_signature_item_name == "The Classic BEC"

    def test_ham_egg_cheese_without_bagel_word(self):
        """Test 'ham egg cheese' without explicit 'bagel' word."""
        result = parse_open_input_deterministic("ham egg cheese")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_proteins is not None
        assert "ham" in result.new_bagel_proteins

    def test_ham_egg_and_cheese_on_everything_bagel(self):
        """Test 'ham egg and cheese on an everything bagel'."""
        result = parse_open_input_deterministic("ham egg and cheese on an everything bagel")
        assert result is not None
        assert result.new_bagel is True
        assert result.new_bagel_proteins is not None
        assert "ham" in result.new_bagel_proteins
        assert result.new_bagel_type == "everything"


class TestAddModifierToItem:
    """Tests for add-modifier patterns (add bacon, extra cheese, etc.)."""

    def test_add_bacon_simple(self):
        """Test 'add bacon' returns modify_existing_item with bacon modifier."""
        result = parse_open_input_deterministic("add bacon")
        assert result is not None
        assert result.modify_existing_item is True
        assert "bacon" in result.modify_add_modifiers
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
        assert "bacon" in result.modify_add_modifiers

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
        assert "bacon" in result.modify_add_modifiers
        # Check for any cheese variant (American Cheese, Swiss Cheese, etc.)
        assert any("cheese" in m.lower() for m in result.modify_add_modifiers)

    def test_add_bacon_to_the_bagel(self):
        """Test 'add bacon to the bagel' specifies target."""
        result = parse_open_input_deterministic("add bacon to the bagel")
        assert result is not None
        assert result.modify_existing_item is True
        assert "bacon" in result.modify_add_modifiers
        assert result.modify_target_description == "bagel"

    def test_add_bacon_to_the_plain_bagel(self):
        """Test 'add bacon to the plain bagel' specifies target with type."""
        result = parse_open_input_deterministic("add bacon to the plain bagel")
        assert result is not None
        assert result.modify_existing_item is True
        assert "bacon" in result.modify_add_modifiers
        assert result.modify_target_description == "plain bagel"

    def test_add_bacon_to_the_omelette(self):
        """Test 'add bacon to the omelette' works for non-bagel items."""
        result = parse_open_input_deterministic("add bacon to the omelette")
        assert result is not None
        assert result.modify_existing_item is True
        assert "bacon" in result.modify_add_modifiers
        assert result.modify_target_description == "omelette"

    def test_put_bacon_on_it(self):
        """Test 'put bacon on it' is treated as add bacon."""
        result = parse_open_input_deterministic("put bacon on it")
        assert result is not None
        assert result.modify_existing_item is True
        assert "bacon" in result.modify_add_modifiers
        assert result.modify_target_description is None  # "it" = implicit target

    def test_add_egg(self):
        """Test 'add egg' adds egg modifier."""
        result = parse_open_input_deterministic("add egg")
        assert result is not None
        assert result.modify_existing_item is True
        # Check case-insensitively since function may return "Egg"
        assert any("egg" in m.lower() for m in result.modify_add_modifiers)

    def test_add_tomato_and_onion(self):
        """Test 'add tomato and onion' adds both toppings."""
        result = parse_open_input_deterministic("add tomato and onion")
        assert result is not None
        assert result.modify_existing_item is True
        # Check case-insensitively since function may return "Tomato", "Onion"
        assert any("tomato" in m.lower() for m in result.modify_add_modifiers)
        assert any("onion" in m.lower() for m in result.modify_add_modifiers)

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
