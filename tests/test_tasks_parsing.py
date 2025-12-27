"""
Tests for the parsing module.

Includes:
- Schema validation tests (no LLM required)
- Integration tests with mocked LLM responses
- Optional integration tests with real LLM (requires API key)
"""

import pytest
import os
from unittest.mock import MagicMock, patch

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

from sandwich_bot.tasks.state_machine import (
    parse_open_input_deterministic,
    _extract_quantity,
    _extract_bagel_type,
    _extract_toasted,
    _extract_spread,
    WORD_TO_NUM,
    extract_zip_code,
    validate_delivery_zip_code,
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
        """Test parsing bagel with spread type."""
        result = parse_open_input_deterministic("plain bagel with scallion cream cheese")
        assert result is not None
        assert result.new_bagel_type == "plain"
        assert result.new_bagel_spread == "cream cheese"
        assert result.new_bagel_spread_type == "scallion"

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


class TestDeterministicParserFallback:
    """Tests for cases that should fall back to LLM."""

    @pytest.mark.parametrize("text", [
        # Coffee and menu items are now handled deterministically
        "what do you have?",  # Question
        "I'm not sure yet",  # Indecisive
    ])
    def test_llm_fallback_cases(self, text):
        """Test that complex cases fall back to LLM."""
        result = parse_open_input_deterministic(text)
        assert result is None, f"Expected LLM fallback for: {text}"

    @pytest.mark.parametrize("text,expected_type", [
        ("coffee please", "coffee"),
        ("The Leo", "menu_item"),
        ("the chipotle egg omelette", "menu_item"),
    ])
    def test_deterministic_handles_coffee_and_menu_items(self, text, expected_type):
        """Test that coffee and menu items are now handled deterministically."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected deterministic parse for: {text}"
        if expected_type == "coffee":
            assert result.new_coffee is True
            assert result.new_coffee_type == "coffee"
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
