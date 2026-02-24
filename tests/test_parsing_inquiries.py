"""Inquiry parsing and special instructions tests."""

import pytest

from tests.helpers import (
    get_parsed_items,
    has_parsed_item,
    has_signature_item,
    get_signature_item,
    has_bagel,
    get_bagel_item,
    has_coffee,
    get_coffee_item,
    has_menu_item,
)

from orderbot.tasks.parsers import (
    parse_open_input_deterministic,
)


# =============================================================================
# Special Instructions Extraction Tests
# =============================================================================

class TestSpecialInstructionsExtraction:
    """Tests for extract_special_instructions_from_input function."""

    # ----- Parameterized: simple qualifier extraction (exact match in notes) -----
    @pytest.mark.parametrize("user_input, expected_note", [
        ("plain bagel with light on the cream cheese", "light cream cheese"),
        ("bagel with light cream cheese", "light cream cheese"),
        ("egg and cheese bagel with extra bacon", "extra bacon"),
        ("bagel with lots of cream cheese", "extra cream cheese"),
        ("coffee with a splash of milk", "splash milk"),
        ("sandwich with go easy on the mayo", "light mayo"),
        ("coffee with a little sugar", "light sugar"),
        ("bagel with no onions", "no onions"),
        ("sandwich hold the tomato", "no tomato"),
        ("bagel heavy on the cheese", "extra cheese"),
    ])
    def test_qualifier_extraction(self, user_input, expected_note):
        """Test that qualifier phrases are correctly extracted from input."""
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input(user_input)
        assert expected_note in notes

    # ----- Parameterized: standalone special instruction patterns (substring in any note) -----
    @pytest.mark.parametrize("user_input, expected_substring", [
        ("coffee room for cream", "room"),
        ("latte not too hot", "not too hot"),
        ("coffee lukewarm please", "lukewarm"),
        ("caramel macchiato upside down", "upside down"),
        ("iced coffee well stirred", "well stirred"),
        ("latte mixed", "mixed"),
        ("plain bagel lightly toasted", "lightly toasted"),
        ("everything bagel well done", "well done"),
        ("bagel with cream cheese cut in half", "cut in half"),
        ("plain bagel sliced", "sliced"),
        ("egg sandwich open faced", "open faced"),
        ("bagel with cream cheese spread thin", "spread thin"),
        ("cream cheese only on one side", "on one side"),
        ("butter on both halves", "on both halves"),
        ("bagel with cheese melted", "melted"),
        ("iced coffee extra ice", "extra ice"),
        ("iced coffee light ice", "light ice"),
        ("iced coffee no ice", "no ice"),
    ])
    def test_standalone_special_instruction(self, user_input, expected_substring):
        """Test that standalone instruction patterns are captured."""
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        instructions = extract_special_instructions_from_input(user_input)
        assert any(expected_substring in i.lower() for i in instructions)

    # ----- Non-parameterizable tests (multiple assertions or different logic) -----

    def test_multiple_notes(self):
        """Test multiple qualifier phrases extract correctly."""
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("bagel with light cream cheese and extra bacon")
        assert "light cream cheese" in notes
        assert "extra bacon" in notes

    def test_no_notes_for_regular_order(self):
        """Test that regular orders without qualifiers have no notes."""
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input("plain bagel with cream cheese")
        assert len(notes) == 0

    def test_multi_item_notes_separated_coffee_only(self):
        """Test that coffee notes filter only includes coffee-related notes."""
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        notes = extract_special_instructions_from_input(
            "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        )
        assert "splash milk" in notes
        assert "extra cream cheese" in notes

    def test_multi_item_coffee_with_milk_and_special_instructions(self):
        """Test that multi-item parser extracts items and special instructions are captured at order level."""
        from orderbot.tasks.parsers import _parse_multi_item_order, extract_special_instructions_from_input
        user_input = "a coffee with a splash of milk and a bagel with a lot of cream cheese"
        result = _parse_multi_item_order(user_input)
        assert result is not None
        assert has_coffee(result)
        assert has_bagel(result)
        coffee = get_coffee_item(result)
        assert coffee is not None
        instructions = extract_special_instructions_from_input(user_input)
        assert any("splash" in i.lower() or "milk" in i.lower() for i in instructions)

    def test_coffee_with_sugar_on_the_side(self):
        """Test that 'sugar on the side' is captured in order-level special_instructions."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        user_input = "large coffee iced sugar on the side"
        result = parse_open_input_deterministic(user_input)
        assert result is not None
        coffee = get_coffee_item(result)
        assert coffee is not None, f"No coffee found. All items: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        instructions = extract_special_instructions_from_input(user_input)
        assert any("sugar on the side" in i.lower() for i in instructions)

    def test_coffee_with_cream_on_the_side(self):
        """Test that 'cream on the side' is captured in order-level special_instructions."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        from orderbot.tasks.parsers import extract_special_instructions_from_input
        user_input = "large coffee cream on the side"
        result = parse_open_input_deterministic(user_input)
        assert result is not None
        coffee = get_coffee_item(result)
        assert coffee is not None
        instructions = extract_special_instructions_from_input(user_input)
        assert any("cream on the side" in i.lower() for i in instructions)

    def test_coffee_with_milk_on_the_side(self):
        """Test that 'milk on the side' attaches qualifier to milk selection."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        user_input = "coffee milk on the side"
        result = parse_open_input_deterministic(user_input)
        assert result is not None
        coffee = get_coffee_item(result)
        assert coffee is not None
        milk_sel = [s for s in coffee.selections if "milk" in s.slug]
        assert milk_sel, f"Expected milk selection, got selections: {coffee.selections}"
        assert "(on the side)" in milk_sel[0].display_name, (
            f"Expected '(on the side)' in display_name, got: {milk_sel[0].display_name}"
        )

    def test_multi_item_bagel_and_signature_item(self):
        """Test that multi-item parser recognizes speed menu items like The Classic BEC."""
        from orderbot.tasks.parsers import _parse_multi_item_order
        # Multi-item order: "one plain bagel and one classic BEC"
        # Note: bare "bagel" (no variety) is resolved at the state machine level
        # via disambiguation, not at the parser level.
        result = _parse_multi_item_order("one plain bagel and one classic BEC")
        assert result is not None
        # Should detect both items
        assert has_bagel(result)
        sig_item = get_signature_item(result)
        assert sig_item is not None
        # The Classic BEC should be recognized as a speed menu item
        assert "classic" in sig_item.item_name.lower() or "bec" in sig_item.item_name.lower()

    def test_multi_item_signature_item_and_coffee(self):
        """Test multi-item order with speed menu item and coffee."""
        from orderbot.tasks.parsers import _parse_multi_item_order
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
        # Signature items should have default ingredients and a valid item_type
        assert has_signature_item(leo), f"Expected signature item, got: {[(i.item_type, i.item_name) for i in leo.parsed_items]}"
        assert has_signature_item(bec), f"Expected signature item, got: {[(i.item_type, i.item_name) for i in bec.parsed_items]}"
        # Verify item names are correct
        leo_item = get_signature_item(leo)
        bec_item = get_signature_item(bec)
        assert leo_item.item_name == "The Leo"
        assert bec_item.item_name == "The Classic BEC"

    def test_multi_item_coffee_and_bagel_with_butter(self):
        """Test that 'a sesame bagel with butter' captures the sesame bagel type."""
        from orderbot.tasks.parsers import _parse_multi_item_order
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
        from orderbot.tasks.parsers import _parse_multi_item_order
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
        from orderbot.tasks.parsers import parse_recommendation_inquiry
        result = parse_recommendation_inquiry(text)
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
        from orderbot.tasks.parsers import parse_recommendation_inquiry
        result = parse_recommendation_inquiry(text)
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
        from orderbot.tasks.parsers import parse_recommendation_inquiry
        result = parse_recommendation_inquiry(text)
        assert result is None, f"Incorrectly detected recommendation in: {text}"

    def test_recommendation_should_not_add_to_cart(self):
        """Test that recommendation response has no items to add."""
        from orderbot.tasks.parsers import parse_recommendation_inquiry
        result = parse_recommendation_inquiry("what kind of bagel do you recommend?")
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
        from orderbot.tasks.parsers import parse_item_description_inquiry
        result = parse_item_description_inquiry(text)
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
        from orderbot.tasks.parsers import parse_item_description_inquiry
        result = parse_item_description_inquiry(text)
        assert result is None, f"Incorrectly detected item description inquiry in: {text}"

    def test_item_description_should_not_add_to_cart(self):
        """Test that item description response has no items to add."""
        from orderbot.tasks.parsers import parse_item_description_inquiry
        result = parse_item_description_inquiry("what's on the health nut?")
        assert result is not None
        assert result.asks_item_description is True
        # Should NOT have any items flagged for adding
        assert len(result.parsed_items) == 0, "Item description inquiries should not create any items"


# =============================================================================
# Order Type Detection Tests
# =============================================================================

class TestOrderTypeDetection:
    """Tests for pickup/delivery order type detection."""

    @pytest.mark.parametrize("input_text,expected", [
        # Delivery order patterns
        ("I would like to place a delivery order", "delivery"),
        ("I'd like to place a delivery order", "delivery"),
        ("place a delivery order", "delivery"),
        ("this is for delivery", "delivery"),
        ("for delivery please", "delivery"),
        ("can you deliver", "delivery"),
        ("delivery please", "delivery"),
        ("delivery", "delivery"),
        ("to be delivered", "delivery"),
        # Pickup order patterns
        ("I would like to place a pickup order", "pickup"),
        ("I'd like to place a pick up order", "pickup"),
        ("place a pickup order", "pickup"),
        ("this is for pickup", "pickup"),
        ("for pickup please", "pickup"),
        ("I'll pick it up", "pickup"),
        ("I will pick it up", "pickup"),
        ("pickup please", "pickup"),
        ("pickup", "pickup"),
        ("pick-up", "pickup"),
    ])
    def test_order_type_detection_only(self, input_text, expected):
        """Test detecting order type when no items are specified."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic
        result = parse_open_input_deterministic(input_text)
        assert result is not None, f"Expected result for '{input_text}'"
        assert result.order_type == expected, f"Expected order_type='{expected}' for '{input_text}', got '{result.order_type}'"
        # When only order type is specified, no items should be parsed
        assert not result.parsed_items, f"Expected no items for '{input_text}', got {result.parsed_items}"

    def test_order_type_not_detected_for_regular_input(self):
        """Test that order type is not detected for unrelated input."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic
        # These should not trigger order type detection
        result = parse_open_input_deterministic("I'd like a bagel")
        assert result is not None
        assert result.order_type is None

    def test_delivery_with_items(self):
        """Test that order type is captured along with items when both are specified."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic
        # This tests that "delivery order" + item works
        result = parse_open_input_deterministic("I'd like to place a delivery order and get a bagel")
        assert result is not None
        assert result.order_type == "delivery"
        # Should also have parsed the bagel
        assert result.parsed_items is not None
        assert len(result.parsed_items) > 0


# =============================================================================
# Availability Inquiry Tests
# =============================================================================

class TestAvailabilityInquiry:
    """Tests for 'do you have X' availability inquiry detection.

    These tests ensure that 'do you have X' questions are recognized as
    availability inquiries rather than being misinterpreted as modifier
    additions or order requests.
    """

    @pytest.mark.parametrize("text,expected_item", [
        # Simple availability questions (the bug case)
        ("do you have bialy", "bialy"),
        ("do you have any bialy", "bialy"),
        ("do you have bialys", "bialys"),
        ("do you have any bialy?", "bialy"),
        # With explicit qualifiers (already worked)
        ("do you have bialy in stock", "bialy"),
        ("do you have any bialys available", "bialys"),
        ("do you have cream cheese left", "cream cheese"),
        # Other item examples
        ("do you have lox", "lox"),
        ("do you have any plain bagels", "plain bagels"),
        ("do you have the classic", "the classic"),
    ])
    def test_availability_inquiry_detected(self, text, expected_item):
        """Test that 'do you have X' is detected as an availability inquiry."""
        from orderbot.tasks.parsers.deterministic.inquiry.dietary import parse_availability_inquiry
        result = parse_availability_inquiry(text)
        assert result is not None, f"Failed to detect availability inquiry in: {text}"
        assert result.asks_availability is True
        assert result.availability_query_item == expected_item

    @pytest.mark.parametrize("text", [
        # Order requests should NOT match availability patterns
        "can I have a bialy",
        "I'd like a bialy",
        "I want a bialy",
        "give me a bialy",
        "get me a bialy",
        "I'll take a bialy",
    ])
    def test_order_requests_not_availability(self, text):
        """Test that order requests are NOT detected as availability inquiries."""
        from orderbot.tasks.parsers.deterministic.inquiry.dietary import parse_availability_inquiry
        result = parse_availability_inquiry(text)
        assert result is None, f"'{text}' should NOT be an availability inquiry"
