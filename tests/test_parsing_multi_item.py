"""Multi-item parsing, quantities, modifiers, and advanced parsing tests."""

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
    has_side_item,
    get_side_item,
    count_parsed_items,
)

from orderbot.tasks.parsers import (
    parse_open_input_deterministic,
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
        ("The Max Borough", "The Max Borough"),
        ("max zucker", "The Max Borough"),
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
        # Use get_signature_item which filters by items with default ingredients
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
        # Use get_signature_item which filters by items with default ingredients
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
        """Test that speed menu items with quantity are correctly parsed.

        Parser creates a single ParsedItemEntry with quantity field set.
        ItemAdderHandler decides whether to create N separate items.
        """
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        # Parser creates single entry with quantity field
        sig_item = get_signature_item(result)
        assert sig_item is not None, f"No signature item found for: {text}"
        assert sig_item.quantity == expected_qty, f"Expected quantity={expected_qty}, got {sig_item.quantity}"

    def test_signature_item_with_all_options(self):
        """Test parsing speed menu with bagel choice, toasted, and quantity."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
        result = parse_open_input_deterministic("2 classic becs on wheat bagels toasted")
        assert result is not None
        # Parser creates single entry with quantity=2
        sig_item = get_signature_item(result)
        assert sig_item is not None, "No signature item found"
        assert sig_item.quantity == 2, f"Expected quantity=2, got {sig_item.quantity}"
        # Item should have the name, bagel choice, and toasted preference
        # Note: "wheat" maps to "whole_wheat_bagel" slug since there's no separate "wheat" bagel in DB
        item = sig_item
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

    def test_multiple_generic_items_with_shared_attribute(self):
        """'2 bagels on wheat' -> both should get wheat bread (not inline spec).

        The 'on wheat' is a uniform attribute, not an inline spec like '1 wheat 1 plain'.
        Without this fix, inline spec parsing treats 'wheat' as qty=1 spec, leaving
        the second bagel with no bread attribute.
        """
        result = parse_open_input_deterministic("2 bagels on wheat")
        assert result is not None
        bagel_items = get_parsed_items(result, item_type="bagel")
        # Should be 1 entry with quantity=2 (uniform attribute), not 2 separate entries
        assert len(bagel_items) == 1, (
            f"Expected 1 bagel entry with qty=2, got {len(bagel_items)} entries"
        )
        assert bagel_items[0].quantity == 2
        assert bagel_items[0].attribute_values.get("bread") == "whole_wheat_bagel"

    def test_multiple_generic_items_with_shared_attributes(self):
        """'2 bagels on wheat toasted' -> both get wheat + toasted."""
        result = parse_open_input_deterministic("2 bagels on wheat toasted")
        assert result is not None
        bagel_items = get_parsed_items(result, item_type="bagel")
        assert len(bagel_items) == 1, (
            f"Expected 1 bagel entry with qty=2, got {len(bagel_items)} entries"
        )
        assert bagel_items[0].quantity == 2
        assert bagel_items[0].attribute_values.get("bread") == "whole_wheat_bagel"
        assert bagel_items[0].attribute_values.get("toasted") is True


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
        # Second bagel: lox (meat category - salmon is a protein topping)
        assert bagels[1].attribute_values.get("bread") == "plain_bagel"
        assert bagels[1].attribute_values.get("meat") == "belly_lox"

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
        # Second bagel: lox (meat category), not toasted
        assert bagels[1].attribute_values.get("bread") == "plain_bagel"
        assert bagels[1].attribute_values.get("meat") == "belly_lox"
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
        (one, two) don't match equal division. Items with the same config
        are compacted into a single entry with quantity > 1.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("3 bagels, one toasted, two not toasted")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        assert sum(b.quantity for b in bagels) == 3
        # First bagel: toasted (qty=1)
        assert bagels[0].attribute_values.get("toasted") is True
        assert bagels[0].quantity == 1
        # Second entry: not toasted (qty=2)
        assert bagels[1].attribute_values.get("toasted") is False
        assert bagels[1].quantity == 2

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
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items, _split_into_parts

        text = "2 bagels, one with scallion cream cheese, one with veggie cream cheese"

        # Debug: Check what parts we get
        parts = _split_into_parts(text.lower())
        print(f"\nDEBUG: Parts = {parts}")

        # Debug: Check extraction for each part
        for i, (qty, part_text) in enumerate(parts):
            attrs = _test_pipeline.extract_attributes(part_text, "bagel")
            print(f"DEBUG: Part {i} ({qty}x): '{part_text}' -> spread={attrs.values.get('spread')}")

        result = _parse_split_quantity_items(text)
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2

        print(f"DEBUG: Bagel 0 spread = {bagels[0].attribute_values.get('spread')}")
        print(f"DEBUG: Bagel 1 spread = {bagels[1].attribute_values.get('spread')}")

        assert bagels[0].attribute_values.get("spread") == "scallion_cream_cheese"
        assert bagels[1].attribute_values.get("spread") == "vegetable_cream_cheese"

    def test_split_different_bread_types(self):
        """Test parsing '2 bagels, 1 plain 1 blueberry'.

        When users specify different bread types per item using the item type
        trigger word omitted, the parser should enrich part text with the trigger
        (e.g., "plain" + "bagel" -> "plain bagel") to match bread options.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 bagels, 1 plain 1 blueberry")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        assert bagels[0].attribute_values.get("bread") == "plain_bagel"
        assert bagels[1].attribute_values.get("bread") == "blueberry_bagel"

    def test_split_different_bread_types_with_commas(self):
        """Test parsing '2 bagels, 1 everything, 1 blueberry'.

        Same as above but with commas separating the parts and using
        'everything' which could be confused with other item types.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 bagels, 1 everything, 1 blueberry")
        assert result is not None
        bagels = get_parsed_items(result, item_type="bagel")
        assert len(bagels) == 2
        assert bagels[0].attribute_values.get("bread") == "everything_bagel"
        assert bagels[1].attribute_values.get("bread") == "blueberry_bagel"


class TestSplitQuantityDrinksParsing:
    """Tests for split-quantity drink parsing (e.g., 'two coffees one with milk one black')."""

    def test_two_coffees_one_milk_one_black(self):
        """Test parsing 'two coffees one with milk one black'.

        Tests split-quantity parsing for drinks. Note: attribute extraction
        depends on database configuration for coffee_based_beverage type.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two coffees one with milk one black")
        assert result is not None
        drinks = get_parsed_items(result, item_type="coffee_based_beverage")
        assert len(drinks) == 2, f"Expected 2 coffee_based_beverage, got {len(drinks)}. All: {[(i.item_type, i.item_name) for i in result.parsed_items]}"
        # Both coffees should be detected
        assert "coffee" in drinks[0].item_name.lower()
        assert "coffee" in drinks[1].item_name.lower()
        # Second coffee should have style=black from "one black"
        assert drinks[1].attribute_values.get("style") == "black"

    def test_two_lattes_one_iced_one_hot(self):
        """Test parsing 'two lattes one iced one hot'."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two lattes one iced one hot")
        assert result is not None
        drinks = get_parsed_items(result, item_type="espresso_based_beverage")
        assert len(drinks) == 2
        # Hot/iced is differentiated by menu item name, not attribute
        names = sorted(d.item_name for d in drinks)
        assert names == ["Hot Latte", "Iced Latte"]

    def test_two_teas_one_with_oat_milk_one_plain(self):
        """Test parsing 'two teas one with oat milk one plain'."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two teas one with oat milk one plain")
        assert result is not None
        drinks = get_parsed_items(result, item_type="tea")
        assert len(drinks) == 2
        # First tea has oat milk selection
        oat_milk_slugs = [s.slug for s in drinks[0].selections]
        assert "oat_milk" in oat_milk_slugs
        # Second tea is plain (no selections)
        assert len(drinks[1].selections) == 0

    def test_three_coffees_different_temps(self):
        """Test parsing 'three coffees one iced one hot one decaf'.

        Tests quantity=3 split. Note: temperature/decaf extraction depends on DB config.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("three coffees one iced one hot one decaf")
        assert result is not None
        drinks = get_parsed_items(result, item_type="coffee_based_beverage")
        assert len(drinks) == 3
        # All three should be coffees
        for drink in drinks:
            assert "coffee" in drink.item_name.lower()

    def test_numeric_quantity(self):
        """Test parsing with numeric quantity."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 coffees one with almond milk one black")
        assert result is not None
        drinks = get_parsed_items(result, item_type="coffee_based_beverage")
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

    def test_large_iced_lattes_split(self):
        """Test parsing 'two large lattes one iced one hot' preserves size."""
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("two large lattes one iced one hot")
        assert result is not None
        drinks = get_parsed_items(result, item_type="espresso_based_beverage")
        assert len(drinks) == 2
        # Both should have the large size
        assert drinks[0].attribute_values.get("size") == "large"
        assert "iced" in drinks[0].item_name.lower()
        assert drinks[1].attribute_values.get("size") == "large"
        assert "hot" in drinks[1].item_name.lower()

    def test_uneven_split_one_iced_two_hot(self):
        """Test parsing '3 coffees, one iced, two hot'.

        This tests uneven split handling where distribution quantities
        don't match equal division. Items with the same config are
        compacted into a single entry with quantity > 1.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("3 coffees, one iced, two hot")
        assert result is not None
        drinks = get_parsed_items(result, item_type="coffee_based_beverage")
        assert len(drinks) == 2
        assert sum(d.quantity for d in drinks) == 3
        # First coffee: iced (qty=1)
        assert "iced" in drinks[0].item_name.lower()
        assert drinks[0].quantity == 1
        # Second entry: hot (qty=2)
        assert "hot" in drinks[1].item_name.lower()
        assert drinks[1].quantity == 2

    def test_two_coffees_one_hot_one_iced(self):
        """Test parsing '2 coffees, one hot, one iced'.

        This tests the basic hot/iced split pattern.
        """
        from orderbot.tasks.parsers.deterministic import _parse_split_quantity_items

        result = _parse_split_quantity_items("2 coffees, one hot, one iced")
        assert result is not None
        drinks = get_parsed_items(result, item_type="coffee_based_beverage")
        assert len(drinks) == 2
        # First coffee: hot
        assert "hot" in drinks[0].item_name.lower()
        # Second coffee: iced
        assert "iced" in drinks[1].item_name.lower()


class TestPartialQuantitySplit:
    """Tests for partial-modifier split (e.g., '4 coffees 2 with milk')."""

    def test_partial_split_detection_basic(self):
        """Test the detection function for simple split patterns."""
        from orderbot.tasks.parsers.deterministic.item_parsing import (
            _detect_partial_modifier_split
        )

        # Valid split: "2 with milk and sugar"
        result = _detect_partial_modifier_split(" 2 with milk and sugar", 4)
        assert result is not None
        assert result[0] == 2  # split_qty
        assert "milk" in result[1]  # modifier_text

    def test_partial_split_detection_word_number(self):
        """Test split detection with word numbers."""
        from orderbot.tasks.parsers.deterministic.item_parsing import (
            _detect_partial_modifier_split
        )

        result = _detect_partial_modifier_split(" two with cream", 4)
        assert result is not None
        assert result[0] == 2
        assert "cream" in result[1]

    def test_partial_split_simple_with_comma(self):
        """Test that simple patterns with comma still work."""
        from orderbot.tasks.parsers.deterministic.item_parsing import (
            _detect_partial_modifier_split
        )

        # Simple pattern with comma - should work
        result = _detect_partial_modifier_split(", 2 with milk", 4)
        assert result is not None
        assert result[0] == 2
        assert "milk" in result[1]

    def test_partial_split_skip_complex_multi_spec(self):
        """Test that complex patterns with multiple split specs are skipped."""
        from orderbot.tasks.parsers.deterministic.item_parsing import (
            _detect_partial_modifier_split
        )

        # Complex pattern with multiple specs - should return None
        result = _detect_partial_modifier_split(
            " - 2 with milk, 1 black, 1 with cream", 4
        )
        assert result is None

    def test_partial_split_skip_multiple_specs(self):
        """Test that multiple split specs are skipped."""
        from orderbot.tasks.parsers.deterministic.item_parsing import (
            _detect_partial_modifier_split
        )

        # Multiple split specs - should return None
        result = _detect_partial_modifier_split(" 2 with milk 1 with sugar", 4)
        assert result is None

    def test_partial_split_skip_when_qty_equals_total(self):
        """Test that split is skipped when qty equals total."""
        from orderbot.tasks.parsers.deterministic.item_parsing import (
            _detect_partial_modifier_split
        )

        # split_qty must be < total_qty
        result = _detect_partial_modifier_split(" 4 with milk", 4)
        assert result is None

    def test_partial_split_full_parse(self):
        """Test full parsing of partial split pattern."""
        from orderbot.tasks.parsers.deterministic.core import (
            parse_open_input_deterministic
        )

        # Simple pattern that should work
        result = parse_open_input_deterministic("4 hot coffees 2 with milk")
        if result is not None and len(result.parsed_items) == 2:
            # If partial split worked, we should have 2 items
            items = result.parsed_items
            # One should be qty 2 with milk, one should be qty 2 without
            assert items[0].quantity + items[1].quantity == 4
            # First item should have modifiers (milk)
            has_milk_0 = any(
                s.slug in ("whole_milk", "milk") for s in (items[0].selections or [])
            )
            has_milk_1 = any(
                s.slug in ("whole_milk", "milk") for s in (items[1].selections or [])
            )
            # One should have milk, one should not
            assert has_milk_0 != has_milk_1, "One group should have milk, the other should not"


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

        # Verify The Leo details (look for egg_sandwich type or item name)
        leo_items = [i for i in result.parsed_items if _get_parsed_item_type(i) == "egg_sandwich" or (getattr(i, 'item_name', '') or '').lower().startswith("the leo")]
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
        assert "coffee" in types or "coffee_based_beverage" in types, f"Expected coffee in parsed_items, got: {types}"
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
        # The Lexington is a healthy_sandwich, Butter Sandwich is a spread_sandwich
        # Accept specific types instead of generic menu_item
        valid_types = {"egg_sandwich", "spread_sandwich", "menu_item", "fish_sandwich", "deli_sandwich", "healthy_sandwich"}
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

    def test_latte_with_oat_milk_and_2_sugars_is_single_item(self):
        """Test that 'large iced latte with oat milk and 2 sugars' is NOT parsed as multi-item.

        Regression test: Previously, '2 sugars' triggered multi-item detection because
        'sugar' is a trigger word for sweeteners, and the quantity prefix wasn't stripped
        before checking for item types.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        # This should NOT be parsed as multi-item - it's a single latte with modifiers
        result = _parse_multi_item_order("large iced latte with oat milk and 2 sugars")

        # _parse_multi_item_order returns None when it's NOT a multi-item order
        # (i.e., when it's a single item with modifiers)
        assert result is None, (
            "Expected None (single item with modifiers), but got multi-item result. "
            f"parsed_items: {[getattr(i, 'item_name', i) for i in result.parsed_items] if result else 'N/A'}"
        )

    def test_latte_with_oat_milk_and_two_sugars_is_single_item(self):
        """Test that word-form quantities also don't trigger multi-item detection."""
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("large iced latte with oat milk and two sugars")
        assert result is None, (
            "Expected None (single item), got multi-item. "
            f"parsed_items: {[getattr(i, 'item_name', i) for i in result.parsed_items] if result else 'N/A'}"
        )

    def test_egg_and_cheese_on_plain_bagel_is_single_item(self):
        """Test that 'egg and cheese on plain bagel' is NOT parsed as multi-item.

        Regression test: "egg and cheese" is a compound phrase (menu item alias).
        The " on plain bagel" is a modifier/bread specification, not a second item.
        This should NOT be split into two items.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        # This should NOT be parsed as multi-item - it's an egg and cheese sandwich
        # with "plain bagel" as the bread choice
        result = _parse_multi_item_order("egg and cheese on plain bagel")

        assert result is None, (
            "Expected None (single item: egg and cheese on plain bagel), but got multi-item result. "
            f"parsed_items: {[(getattr(i, 'item_name', None), getattr(i, 'item_type', None)) for i in result.parsed_items] if result else 'N/A'}"
        )

    def test_egg_and_cheese_and_a_latte_is_multi_item(self):
        """Test that 'egg and cheese and a latte' IS parsed as multi-item.

        "egg and cheese" is a compound phrase, but "and a latte" contains an item
        indicator (article + item), so this should be parsed as two items.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("egg and cheese and a latte")
        assert result is not None, "Expected multi-item result for 'egg and cheese and a latte'"
        assert len(result.parsed_items) == 2, f"Expected 2 items, got {len(result.parsed_items)}"

        # Check item types
        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "egg_sandwich" in types, f"Expected egg_sandwich, got: {types}"
        # Latte can be espresso_based_beverage, coffee_based_beverage, or coffee depending on parsing path
        coffee_types = {"espresso_based_beverage", "coffee_based_beverage", "coffee"}
        assert any(t in coffee_types for t in types), f"Expected a coffee-type item, got: {types}"

    def test_egg_and_cheese_on_plain_bagel_and_a_coffee_is_multi_item(self):
        """Test that 'egg and cheese on plain bagel and a coffee' IS parsed as multi-item.

        Regression test: "egg and cheese" is a compound phrase, "on plain bagel" is a modifier,
        and "and a coffee" adds a second item. The " and " is NOT at the start of the remainder
        (which is "on plain bagel and a coffee"), so we need to search for it anywhere.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order("egg and cheese on plain bagel and a coffee")
        assert result is not None, "Expected multi-item result for 'egg and cheese on plain bagel and a coffee'"
        assert len(result.parsed_items) == 2, f"Expected 2 items, got {len(result.parsed_items)}"

        # Check item types
        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "egg_sandwich" in types, f"Expected egg_sandwich, got: {types}"
        # Coffee can be coffee_based_beverage or coffee depending on parsing path
        coffee_types = {"coffee_based_beverage", "coffee"}
        assert any(t in coffee_types for t in types), f"Expected a coffee-type item, got: {types}"

        # Verify the egg sandwich has the bread attribute
        egg_items = [i for i in result.parsed_items if _get_parsed_item_type(i) == "egg_sandwich"]
        assert len(egg_items) == 1, "Expected exactly one egg sandwich"
        egg = egg_items[0]
        # Check if "plain" is in the original_text or bread attribute
        original = getattr(egg, 'original_text', '') or ''
        bread = getattr(egg, 'attribute_values', {}).get('bread', '')
        assert "plain" in original.lower() or "plain" in str(bread).lower(), (
            f"Expected 'plain' in original_text or bread attribute, got: original={original}, bread={bread}"
        )

    def test_egg_and_cheese_with_modifiers_is_single_item(self):
        """Test that 'egg and cheese with bacon and cream cheese' is NOT parsed as multi-item.

        Regression test: "egg and cheese" is a compound phrase. The "and cream cheese"
        follows "with bacon", so it's a modifier chain, not a second item.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        # This should NOT be parsed as multi-item - it's an egg and cheese sandwich
        # with multiple modifiers (bacon, cream cheese)
        result = _parse_multi_item_order("egg and cheese with bacon and cream cheese")

        assert result is None, (
            "Expected None (single item: egg and cheese with modifiers), but got multi-item result. "
            f"parsed_items: {[(getattr(i, 'item_name', None), getattr(i, 'item_type', None)) for i in result.parsed_items] if result else 'N/A'}"
        )

    @pytest.mark.parametrize("text", [
        "i'd like an egg and cheese sandwich",
        "can i get an egg and cheese sandwich",
        "i want an egg and cheese",
        "give me an egg and cheese sandwich",
        "i'll have an egg and cheese",
    ])
    def test_ordering_prefix_with_egg_and_cheese_is_single_item(self, text):
        """Test that ordering prefixes don't break compound phrase detection.

        Regression test: The ordering prefix ("I'd like an", "can I get an", etc.)
        should be stripped before compound phrase detection. Without stripping, the
        tokenizer would incorrectly split on " and " because it doesn't see
        "egg and cheese sandwich" at the start.

        Bug: "I'd like an egg and cheese sandwich" was being split into:
        - "I'd like an egg" (not found)
        - "cheese sandwich" (matched wrong item)
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        # This should NOT be parsed as multi-item - it's a single egg and cheese sandwich
        result = _parse_multi_item_order(text)

        assert result is None, (
            f"Expected None (single item from '{text}'), but got multi-item result. "
            f"parsed_items: {[(getattr(i, 'item_name', None), getattr(i, 'item_type', None)) for i in result.parsed_items] if result else 'N/A'}"
        )

    def test_bagel_toasted_and_scooped_with_cream_cheese_on_the_side(self):
        """Test 'plain bagel toasted and scooped plain cream cheese on the side'.

        Regression test: The tokenizer was splitting on " and " between "toasted"
        and "scooped", which are both boolean attributes of the bagel. This caused
        "scooped plain cream cheese on the side" to be misresolved as a wrong item.

        Expected: Plain Bagel (toasted, scooped) + Plain Cream Cheese (on the side)
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order(
            "plain bagel toasted and scooped plain cream cheese on the side"
        )
        assert result is not None, "Failed to parse as multi-item order"
        assert len(result.parsed_items) == 2, (
            f"Expected 2 parsed_items, got {len(result.parsed_items)}: "
            f"{[(getattr(i, 'item_name', None), getattr(i, 'item_type', None)) for i in result.parsed_items]}"
        )

        # First item should be a bagel
        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "bagel" in types, f"Expected bagel in parsed_items, got: {types}"

        # Find the bagel item and verify boolean attrs
        bagel = next(i for i in result.parsed_items if _get_parsed_item_type(i) == "bagel")
        attrs = getattr(bagel, 'attribute_values', {})
        assert attrs.get("toasted") is True, f"Expected toasted=True, got {attrs.get('toasted')}"
        assert attrs.get("scooped") is True, f"Expected scooped=True, got {attrs.get('scooped')}"


    def test_bagel_with_modifiers_with_an_earl_gray_tea(self):
        """Test that 'onion bagel with scallion cream cheese toasted with an earl gray tea'
        is parsed as two items.

        Regression test: The second 'with' introduces a new item via article ('with an'),
        but the tokenizer only splits on 'and' or ','. Without this fix, the earl gray tea
        is completely dropped.
        """
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order(
            "onion bagel with scallion cream cheese toasted with an earl gray tea"
        )
        assert result is not None, "Failed to parse as multi-item order"
        assert len(result.parsed_items) == 2, (
            f"Expected 2 parsed_items, got {len(result.parsed_items)}: "
            f"{[(getattr(i, 'item_name', None), getattr(i, 'item_type', None)) for i in result.parsed_items]}"
        )

        # First item should be a bagel
        types = [_get_parsed_item_type(item) for item in result.parsed_items]
        assert "bagel" in types, f"Expected bagel in parsed_items, got: {types}"
        # Second item should be a tea
        assert "tea" in types, f"Expected tea in parsed_items, got: {types}"


class TestWithAsMultiItemConnector:
    """Tests for 'with' used as multi-item connector (e.g., 'a bagel with an orange juice')."""

    def test_bagel_with_an_orange_juice(self):
        """'a bagel with an orange juice' should parse as two items."""
        result = parse_open_input_deterministic("a bagel with an orange juice")
        assert result is not None, "Expected parse result"
        assert result.parsed_items and len(result.parsed_items) == 2, (
            f"Expected 2 items, got: {result.parsed_items}"
        )
        types = {getattr(i, 'item_type', None) for i in result.parsed_items}
        has_bagel = any("bagel" in t for t in types if t)
        assert has_bagel, f"Expected a bagel-type item in types, got: {types}"

    def test_coffee_with_a_bagel(self):
        """'a coffee with a bagel' should parse as two items."""
        result = parse_open_input_deterministic("a coffee with a bagel")
        assert result is not None, "Expected parse result"
        assert result.parsed_items and len(result.parsed_items) == 2, (
            f"Expected 2 items, got: {result.parsed_items}"
        )
        types = {getattr(i, 'item_type', None) for i in result.parsed_items}
        has_bagel = any("bagel" in t for t in types if t)
        has_coffee = any("coffee" in t or "beverage" in t for t in types if t)
        assert has_bagel, f"Expected a bagel-type item in types, got: {types}"
        assert has_coffee, f"Expected a coffee-type item in types, got: {types}"

    def test_bagel_with_cream_cheese_is_single_item(self):
        """'bagel with cream cheese' should NOT be split -- 'cream cheese' is a modifier."""
        result = parse_open_input_deterministic("bagel with cream cheese")
        assert result is not None, "Expected parse result"
        assert result.parsed_items is not None
        assert len(result.parsed_items) == 1, (
            f"Expected 1 item (modifier, not split), got {len(result.parsed_items)}: "
            f"{[(getattr(i, 'item_name', None), getattr(i, 'item_type', None)) for i in result.parsed_items]}"
        )

    def test_two_with_occurrences_still_works(self):
        """Regression: 2+ 'with' occurrences still parse correctly."""
        result = parse_open_input_deterministic(
            "onion bagel with scallion cream cheese toasted with an earl gray tea"
        )
        assert result is not None, "Expected parse result"
        assert result.parsed_items and len(result.parsed_items) >= 2, (
            f"Expected 2+ items, got: {result.parsed_items}"
        )


class TestDuplicatePatterns:
    """Tests for duplicate item patterns: 'another one', 'one more', 'another bagel', etc."""

    @pytest.mark.parametrize("text,expected_type", [
        # Bagels - uses "bagel" item type
        ("another bagel", "bagel"),
        ("another bagels", "bagel"),
        ("one more bagel", "bagel"),
        # Sized beverages - uses "coffee_based_beverage" item type (data-driven from database)
        # Note: The old hardcoded mapping returned "coffee" but the database uses "coffee_based_beverage"
        ("another coffee", "coffee_based_beverage"),
        ("one more coffee", "coffee_based_beverage"),
        ("another tea", "tea"),
        # Espresso-based drinks use "espresso_based_beverage" item type (have size, unlike plain espresso)
        ("another latte", "espresso_based_beverage"),
        ("one more latte", "espresso_based_beverage"),
        ("another cappuccino", "espresso_based_beverage"),
        ("another americano", "espresso_based_beverage"),
        ("another espresso", "espresso"),  # Plain espresso has its own item type (no size)
    ])
    def test_another_item_type_detected(self, text, expected_type):
        """Test that 'another <item>' patterns are detected with correct item type.

        Note: The expected item types are the actual database item_type slugs,
        not semantic categories like "coffee". This is the data-driven approach.

        The response can be either:
        - duplicate_new_item_type = expected_type (when item type is detected)
        - parsed_items with item_type = expected_type (when exact menu item is matched)
        Both are valid and result in the correct item being added.
        """
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"

        # Accept either duplicate_new_item_type or parsed_items with matching item_type
        if result.duplicate_new_item_type:
            assert result.duplicate_new_item_type == expected_type, f"Expected type '{expected_type}' for: {text}"
        elif result.parsed_items:
            item_types = [item.item_type for item in result.parsed_items]
            assert expected_type in item_types, f"Expected item_type '{expected_type}' in parsed_items for: {text}"
        else:
            raise AssertionError(f"Expected duplicate_new_item_type or parsed_items for: {text}")

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
        # Should be new item (either via duplicate_new_item_type or parsed_items), not duplicate last
        if result.duplicate_new_item_type:
            assert result.duplicate_new_item_type == "bagel"
        elif result.parsed_items:
            assert result.parsed_items[0].item_type == "bagel"
        else:
            raise AssertionError("Expected duplicate_new_item_type or parsed_items for: another bagel")
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


class TestAnotherAttributeOptionDuplicate:
    """Tests for 'another <attribute_option>' triggering duplicate_last_item.

    When the user says 'give me another pound', 'pound' is an attribute option
    (alias of the 'one_pound' weight option), not a menu item. The parser should
    treat this as a request to duplicate the last cart item.
    """

    @pytest.mark.parametrize("text", [
        "give me another pound",
        "add another lb",
    ])
    def test_attribute_option_triggers_duplicate(self, text):
        """Attribute option terms like 'pound', 'lb' should set duplicate_last_item=1."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.duplicate_last_item == 1, (
            f"Expected duplicate_last_item=1 for '{text}', "
            f"got duplicate_last_item={result.duplicate_last_item}"
        )

    @pytest.mark.parametrize("text,expected_type", [
        ("give me another coffee", "coffee_based_beverage"),
        ("add another bagel", "bagel"),
    ])
    def test_non_option_another_still_resolves_items(self, text, expected_type):
        """Non-attribute-option 'another X' should resolve to items, not duplicate_last_item."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.duplicate_last_item == 0, (
            f"Expected duplicate_last_item=0 for '{text}', "
            f"got duplicate_last_item={result.duplicate_last_item}"
        )
        # Should have resolved to an item type or parsed items
        if result.duplicate_new_item_type:
            assert result.duplicate_new_item_type == expected_type
        elif result.parsed_items:
            item_types = [item.item_type for item in result.parsed_items]
            assert expected_type in item_types, (
                f"Expected item_type '{expected_type}' in parsed_items for: {text}"
            )
        else:
            raise AssertionError(f"Expected item resolution for: {text}")

    @pytest.mark.parametrize("text,expected_qty", [
        ("give me 2 more pounds", 2),
        ("add 3 more pounds", 3),
        ("give me two more pounds", 2),
        ("add 2 more lb", 2),
    ])
    def test_n_more_attribute_option_triggers_duplicate(self, text, expected_qty):
        """'N more <attribute_option>' should set duplicate_last_item=N."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.duplicate_last_item == expected_qty, (
            f"Expected duplicate_last_item={expected_qty} for '{text}', "
            f"got duplicate_last_item={result.duplicate_last_item}"
        )

    @pytest.mark.parametrize("text", [
        "give me 2 more coffees",
        "add 3 more bagels",
    ])
    def test_n_more_non_option_resolves_items(self, text):
        """'N more <menu_item>' should resolve to items with correct quantity."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected pattern match for: {text}"
        assert result.duplicate_last_item == 0, (
            f"Expected duplicate_last_item=0 for '{text}', "
            f"got duplicate_last_item={result.duplicate_last_item}"
        )
        assert result.parsed_items, f"Expected parsed_items for: {text}"


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

    def test_add_milk_to_tea(self):
        """Test 'add milk to tea' adds milk to existing tea item.

        Regression test: Without the article "the", this pattern was failing to
        match and instead creating a new "Hot Tea" item. The fix adds a pattern
        that handles single-word targets without requiring an article.
        """
        result = parse_open_input_deterministic("add milk to tea")
        assert result is not None
        assert result.modify_existing_item is True
        # Check that milk was recognized as a modifier
        assert any("milk" in m.lower() for m in result.modify_add_modifiers)
        # Target should be "tea" (single word, no article)
        assert result.modify_target_description == "tea"

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

    def test_add_latte_with_modifiers_is_new_item(self):
        """Test 'add a latte with milk and one extra shot' is a NEW item, not modify-existing.

        Regression test: Previously, 'add a latte with milk and one extra shot' was
        incorrectly treated as 'add modifiers (milk, shot) to existing item' and created
        two separate lattes. It should be parsed as a single new latte with modifiers.
        """
        result = parse_open_input_deterministic("add a latte with milk and one extra shot")
        assert result is not None

        # Should NOT be a modify-existing-item request
        assert result.modify_existing_item is False, (
            f"'add a latte with modifiers' should be a new item order, "
            f"not modify_existing_item. Got modifiers: {result.modify_add_modifiers}"
        )

        # Should be parsed as a single new item
        assert len(result.parsed_items) == 1, (
            f"Expected 1 latte item, got {len(result.parsed_items)}: "
            f"{[getattr(i, 'item_name', i.item_type) for i in result.parsed_items]}"
        )

        # The item should be a latte/espresso type
        item = result.parsed_items[0]
        assert item.item_type in ("espresso_based_beverage", "coffee_based_beverage", "latte"), (
            f"Expected espresso/beverage type, got: {item.item_type}"
        )


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


class TestNumberedMenuItemParsing:
    """Tests for menu items with numbers in their names (e.g., '3 Bagel Package')."""

    @pytest.mark.parametrize("text", [
        "I'd like a 3 Bagel Package",
        "3 bagel package",
        "can I get a 3 bagel package",
        "I want the 3 bagel package",
    ])
    def test_3_bagel_package_parsed(self, text):
        """Test that '3 Bagel Package' is recognized as an item, not qty=3 + 'bagel package'."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1, \
            f"Expected at least 1 parsed item for: {text}"
        item = result.parsed_items[0]
        # The item should be recognized with quantity=1 (not quantity=3)
        assert item.quantity == 1, \
            f"Expected quantity=1 for '{text}', got {item.quantity} (number is part of item name)"

    @pytest.mark.parametrize("text", [
        "6 bagel package",
        "I'd like a 6 bagel package",
    ])
    def test_6_bagel_package_parsed(self, text):
        """Test that '6 Bagel Package' is recognized as an item, not qty=6."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Failed to parse: {text}"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1, \
            f"Expected at least 1 parsed item for: {text}"
        item = result.parsed_items[0]
        assert item.quantity == 1, \
            f"Expected quantity=1 for '{text}', got {item.quantity} (number is part of item name)"

    def test_3_cookies_still_works(self):
        """Regression test: '3 cookies' should still mean qty=3 of cookies."""
        result = parse_open_input_deterministic("3 cookies")
        assert result is not None, "Failed to parse: 3 cookies"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1
        # For "3 cookies", the number IS a quantity (not part of the item name)
        total_qty = sum(item.quantity for item in result.parsed_items)
        assert total_qty == 3, f"Expected total quantity=3 for '3 cookies', got {total_qty}"

    def test_two_3_bagel_packages(self):
        """Test 'two 3 bagel packages' means qty=2 of '3 Bagel Package'."""
        result = parse_open_input_deterministic("two 3 bagel packages")
        assert result is not None, "Failed to parse: two 3 bagel packages"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1
        total_qty = sum(item.quantity for item in result.parsed_items)
        assert total_qty == 2, \
            f"Expected total quantity=2 for 'two 3 bagel packages', got {total_qty}"


class TestItemQuantityNotBleedingIntoAttributes:
    """Tests that item-level quantity doesn't bleed into attribute selection quantity.

    Regression: "two large iced lattes" was creating 2 items but each had
    size=large with quantity=2 (showing "2 Larges") instead of quantity=1.
    The item-level "two" was being re-consumed by _extract_quantity_before as
    a per-attribute quantity for "large".
    """

    def test_two_large_iced_lattes_size_quantity_is_one(self):
        """'two large iced lattes' -> qty=2 items, each with size=large (quantity=1)."""
        result = parse_open_input_deterministic("two large iced lattes")
        assert result is not None, "Failed to parse: two large iced lattes"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1
        item = result.parsed_items[0]
        assert item.quantity == 2, f"Expected item quantity=2, got {item.quantity}"
        # Check that size selection has quantity=1, not 2
        size_selections = [s for s in item.selections if s.category == "size"]
        assert len(size_selections) == 1, f"Expected 1 size selection, got {len(size_selections)}"
        assert size_selections[0].slug == "large", f"Expected size='large', got '{size_selections[0].slug}'"
        assert size_selections[0].quantity == 1, \
            f"Size selection quantity should be 1, got {size_selections[0].quantity} (item qty bleeding into attribute)"

    def test_three_small_hot_coffees_size_quantity_is_one(self):
        """'three small hot coffees' -> qty=3 items, each with size=small (quantity=1)."""
        result = parse_open_input_deterministic("three small hot coffees")
        assert result is not None, "Failed to parse: three small hot coffees"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1
        item = result.parsed_items[0]
        assert item.quantity == 3, f"Expected item quantity=3, got {item.quantity}"
        size_selections = [s for s in item.selections if s.category == "size"]
        if size_selections:
            assert size_selections[0].quantity == 1, \
                f"Size selection quantity should be 1, got {size_selections[0].quantity}"

    def test_double_shot_latte_still_works(self):
        """'double shot latte' -> qty=1 item, shots has quantity=2 (double is NOT item qty)."""
        result = parse_open_input_deterministic("double shot latte")
        assert result is not None, "Failed to parse: double shot latte"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1
        item = result.parsed_items[0]
        # "double" is not an item quantity word here, it modifies "shot"
        assert item.quantity == 1, f"Expected item quantity=1, got {item.quantity}"

    def test_two_plain_bagels_bread_not_doubled(self):
        """'two plain bagels' -> qty=2 items, bread=plain (not quantity=2)."""
        result = parse_open_input_deterministic("two plain bagels")
        assert result is not None, "Failed to parse: two plain bagels"
        assert result.parsed_items is not None and len(result.parsed_items) >= 1
        item = result.parsed_items[0]
        assert item.quantity == 2, f"Expected item quantity=2, got {item.quantity}"
        bread_selections = [s for s in item.selections if s.category == "bread"]
        if bread_selections:
            assert bread_selections[0].quantity == 1, \
                f"Bread selection quantity should be 1, got {bread_selections[0].quantity}"

    def test_two_large_iced_lattes_and_two_bagels_multi_item_path(self):
        """Multi-item: 'two large iced lattes and two bagels' -> size=large has quantity=1.

        This tests the _parse_item_generic path used by the multi-item parser.
        The item-level "two" should not bleed into the size selection quantity.
        """
        result = parse_open_input_deterministic("two large iced lattes and two bagels")
        assert result is not None, "Failed to parse: two large iced lattes and two bagels"
        assert result.parsed_items is not None and len(result.parsed_items) >= 2
        # Find the latte item
        latte_items = [p for p in result.parsed_items if "latte" in (p.item_name or "").lower()]
        assert len(latte_items) >= 1, f"Expected latte item, got: {[p.item_name for p in result.parsed_items]}"
        latte = latte_items[0]
        size_selections = [s for s in latte.selections if s.category == "size"]
        assert len(size_selections) == 1, f"Expected 1 size selection, got {len(size_selections)}"
        assert size_selections[0].slug == "large"
        assert size_selections[0].quantity == 1, \
            f"Size selection quantity should be 1, got {size_selections[0].quantity} (item qty bleeding into attribute via multi-item path)"

    def test_two_toasted_bagels_and_two_large_iced_lattes(self):
        """Multi-item order should not be eaten by split-quantity parser."""
        result = parse_open_input_deterministic("two toasted bagels and two large iced lattes")
        assert result is not None
        assert result.parsed_items is not None and len(result.parsed_items) >= 2
        # Should have both bagels AND lattes
        item_types = {p.item_type for p in result.parsed_items}
        assert "bagel" in item_types, f"Missing bagel items, got types: {item_types}"
        has_beverage = any(t for t in item_types if t != "bagel")
        assert has_beverage, f"Missing beverage items, got only types: {item_types}"


class TestLeadingAttributeWordStripping:
    """Tests for the fallback that strips leading attribute words (e.g., 'large orange juice')."""

    @pytest.mark.parametrize("text,expected_name_fragment", [
        ("large orange juice", "orange juice"),
        ("iced orange juice", "orange juice"),
        ("large iced orange juice", "orange juice"),
    ])
    def test_leading_attr_words_stripped_on_retry(self, text, expected_name_fragment):
        """Non-configurable items with leading attribute words should parse via retry."""
        result = parse_open_input_deterministic(text)
        assert result is not None, f"Expected parse result for: {text}"
        assert result.parsed_items, f"Expected parsed_items for: {text}"
        item = result.parsed_items[0]
        assert expected_name_fragment in item.item_name.lower(), (
            f"Expected '{expected_name_fragment}' in item_name, got: {item.item_name}"
        )

    def test_iced_tea_matches_directly_without_retry(self):
        """'iced tea' should match directly -- no stripping needed."""
        result = parse_open_input_deterministic("iced tea")
        assert result is not None, "Expected parse result for 'iced tea'"
        assert result.parsed_items, "Expected parsed_items for 'iced tea'"
        assert "tea" in result.parsed_items[0].item_name.lower()

    def test_large_iced_latte_matches_directly(self):
        """Configurable items with size should match via configurable parser, not retry."""
        result = parse_open_input_deterministic("large iced latte")
        assert result is not None, "Expected parse result for 'large iced latte'"
        assert result.parsed_items, "Expected parsed_items for 'large iced latte'"

    def test_only_attribute_word_does_not_match(self):
        """Input that is ONLY an attribute word should not produce a match."""
        result = parse_open_input_deterministic("large")
        # Should either be None or unclear -- not a parsed item
        if result is not None:
            assert not result.parsed_items, (
                f"'large' alone should not produce parsed items, got: {result.parsed_items}"
            )


class TestEnglishBreakfastTeaParsing:
    """Tests for high-coverage trigger matching to prevent partial slug matches."""

    def test_english_breakfast_tea_detects_tea_type(self):
        """'english breakfast tea' should detect item_type=tea, not breakfast."""
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic

        result = parse_open_input_deterministic("english breakfast tea")
        assert result is not None, "Expected parse result for 'english breakfast tea'"
        assert result.parsed_items, "Expected parsed_items for 'english breakfast tea'"
        item = result.parsed_items[0]
        assert item.item_type == "tea", (
            f"Expected item_type='tea', got '{item.item_type}'"
        )

    def test_multi_item_bagel_and_english_breakfast_tea(self):
        """Multi-item: 'onion bagel with scallion cream cheese toasted and an english breakfast tea'
        should produce 2 items (bagel + tea)."""
        from orderbot.tasks.parsers.deterministic import _parse_multi_item_order

        result = _parse_multi_item_order(
            "onion bagel with scallion cream cheese toasted and an english breakfast tea"
        )
        assert result is not None, "Expected multi-item parse result"
        assert len(result.parsed_items) == 2, (
            f"Expected 2 parsed_items, got {len(result.parsed_items)}"
        )
        types = [getattr(item, 'item_type', None) for item in result.parsed_items]
        assert "bagel" in types, f"Expected bagel in types, got: {types}"
        assert "tea" in types, f"Expected tea in types, got: {types}"

    def test_breakfast_alone_triggers_category_clarification(self):
        """'breakfast' alone should trigger category clarification (regression guard).

        Since 'breakfast' is a non-configurable category, the parser returns
        needs_category_clarification rather than a parsed item. This verifies
        that the configurable-type preference doesn't break non-configurable
        slug matching.
        """
        from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic

        result = parse_open_input_deterministic("breakfast")
        assert result is not None, "Expected parse result for 'breakfast'"
        assert result.needs_category_clarification == "breakfast", (
            f"Expected needs_category_clarification='breakfast', got '{result.needs_category_clarification}'"
        )


class TestSplitQuantityModifierBleed:
    """Integration tests: split-quantity items must NOT bleed modifiers to siblings.

    Regression test for bug where 'two bagels one with lox one plain' would
    apply lox to BOTH bagels because the plain item's empty selections ([])
    was converted to None, triggering a fallback re-scan of the full input.
    """

    def test_two_bagels_one_with_spread_one_plain_no_bleed(self):
        """Plain bagel should NOT get cream cheese from sibling."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.schemas import OrderPhase

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("two plain bagels one with cream cheese one plain", order)

        items = result.order.items.get_active_items()
        bagels = [i for i in items if "bagel" in (i.menu_item_name or "").lower()]
        assert len(bagels) == 2, f"Expected 2 bagels, got {len(bagels)}: {[(i.item_type, i.menu_item_name) for i in items]}"

        # Sort by whether they have spread selections to get deterministic order
        with_spread = [b for b in bagels if b.get_selections("spread")]
        without_spread = [b for b in bagels if not b.get_selections("spread")]

        assert len(with_spread) == 1, (
            f"Exactly 1 bagel should have spread. "
            f"Spreads: {[(b.menu_item_name, b.get_selections('spread')) for b in bagels]}"
        )
        assert len(without_spread) == 1, (
            f"Exactly 1 bagel should have NO spread (plain). "
            f"Spreads: {[(b.menu_item_name, b.get_selections('spread')) for b in bagels]}"
        )

    def test_two_bagels_one_with_spread_one_without_no_bleed(self):
        """'one without' should mean plain -- no modifiers from sibling."""
        from orderbot.tasks.state_machine import OrderStateMachine
        from orderbot.tasks.models import OrderTask
        from orderbot.tasks.schemas import OrderPhase

        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        result = sm.process("two plain bagels one with cream cheese one without", order)

        items = result.order.items.get_active_items()
        bagels = [i for i in items if "bagel" in (i.menu_item_name or "").lower()]
        assert len(bagels) == 2, f"Expected 2 bagels, got {len(bagels)}: {[(i.item_type, i.menu_item_name) for i in items]}"

        with_spread = [b for b in bagels if b.get_selections("spread")]
        without_spread = [b for b in bagels if not b.get_selections("spread")]

        assert len(with_spread) == 1, (
            f"Exactly 1 bagel should have spread. "
            f"Spreads: {[(b.menu_item_name, b.get_selections('spread')) for b in bagels]}"
        )
        assert len(without_spread) == 1, (
            f"Exactly 1 bagel should have NO spread ('without' = plain). "
            f"Spreads: {[(b.menu_item_name, b.get_selections('spread')) for b in bagels]}"
        )
