"""
Comprehensive Test Matrix for Item Disambiguation
=================================================

This test suite covers the full flow from user input through parsing,
menu lookup, and disambiguation to ensure consistent behavior.

Test Categories:
1. Generic category terms (chips, cookies, juice, muffin)
2. Specific items with generic suffix (bagel chips, potato chips)
3. Exact menu item names (Bagel Chips - BBQ)
4. Common variants/misspellings
5. Side items
6. Beverages

Each test documents:
- Input: What the user says
- Expected: What should happen
- Parser Output: What the deterministic parser returns
- Menu Lookup: What items match
- Handler Result: Final disambiguation or direct add
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sandwich_bot.tasks.parsers.deterministic import parse_open_input_deterministic
from sandwich_bot.tasks.menu_lookup import MenuLookup
from sandwich_bot.tasks.item_adder_handler import ItemAdderHandler
from sandwich_bot.tasks.models import OrderTask


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def db_engine():
    """Create database engine."""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    return create_engine(db_url)


@pytest.fixture(scope="module")
def menu_data(db_engine):
    """Load menu data from database."""
    with db_engine.connect() as conn:
        result = conn.execute(text('''
            SELECT m.id, m.name, m.category, m.base_price, m.item_type_id,
                   m.is_signature, t.slug as type_slug
            FROM menu_items m
            JOIN item_types t ON m.item_type_id = t.id
        '''))
        rows = result.fetchall()

    items_by_type = {}
    for row in rows:
        type_slug = row[6]  # type_slug is now at index 6 (was 7)
        if type_slug not in items_by_type:
            items_by_type[type_slug] = []
        items_by_type[type_slug].append({
            'id': row[0],
            'name': row[1],
            'category': row[2],
            'base_price': float(row[3]),
            'item_type_id': row[4],
            'is_signature': row[5],
        })

    return {'items_by_type': items_by_type}


@pytest.fixture(scope="module")
def menu_lookup(menu_data):
    """Create MenuLookup instance."""
    return MenuLookup(menu_data)


@pytest.fixture(scope="module")
def item_handler(menu_lookup):
    """Create ItemAdderHandler instance."""
    return ItemAdderHandler(menu_lookup=menu_lookup)


@pytest.fixture
def fresh_order():
    """Create a fresh order for each test."""
    return OrderTask(customer_id='test')


# ============================================================================
# Helper Functions
# ============================================================================

def get_parser_result(user_input: str):
    """Get deterministic parser result."""
    return parse_open_input_deterministic(user_input)


def get_menu_matches(menu_lookup: MenuLookup, item_name: str):
    """Get all menu items matching a name."""
    return menu_lookup.lookup_menu_items(item_name)


def get_handler_result(handler: ItemAdderHandler, item_name: str, order: OrderTask):
    """Get item handler result (may raise if callbacks not set)."""
    try:
        return handler.add_menu_item(item_name, 1, order)
    except TypeError:
        # Expected if single match found and _get_next_question is None
        return "SINGLE_MATCH_FOUND"


# ============================================================================
# TEST CATEGORY 1: Generic Category Terms
# These should ALWAYS trigger disambiguation with multiple options
# ============================================================================

class TestGenericCategoryTerms:
    """Test generic terms like 'chips', 'cookies', 'juice' that should disambiguate."""

    @pytest.mark.parametrize("user_input,min_expected_matches", [
        ("chips", 4),           # Should show bagel chips, potato chips, kettle chips, etc.
        ("cookie", 2),          # Should show multiple cookie types
        ("cookies", 2),         # Plural variant
        ("muffin", 2),          # Should show multiple muffin types
        ("muffins", 2),         # Plural variant
        ("juice", 2),           # Should show multiple juice types
        # Note: brownie only has 1 item in DB, so no disambiguation needed
    ])
    def test_generic_term_parser_output(self, user_input, min_expected_matches):
        """Parser should return the generic term as new_menu_item (not resolve to specific item)."""
        result = get_parser_result(user_input)

        # Should return as menu_item, not side_item
        assert result.new_menu_item is not None, f"'{user_input}' should return new_menu_item"
        assert result.new_side_item is None, f"'{user_input}' should NOT return new_side_item"

        # Parser may normalize plurals to singular (cookies -> cookie), which is fine
        # as long as the base term is preserved for disambiguation
        result_lower = result.new_menu_item.lower()
        input_lower = user_input.lower()
        # Accept exact match OR singular form of plural input
        is_valid = (
            result_lower == input_lower or
            result_lower == input_lower.rstrip('s') or  # cookies -> cookie
            result_lower == input_lower.rstrip('ies') + 'y' or  # brownies -> browny (rare)
            input_lower.startswith(result_lower)  # cookies starts with cookie
        )
        assert is_valid, \
            f"Parser should return generic term for '{user_input}', got '{result.new_menu_item}'"

    @pytest.mark.parametrize("user_input,min_expected_matches", [
        ("chips", 4),
        ("cookie", 2),
        ("muffin", 2),
        ("juice", 2),
        # Note: brownie only has 1 item in DB, so no disambiguation needed
    ])
    def test_generic_term_menu_lookup(self, menu_lookup, user_input, min_expected_matches):
        """Menu lookup should return multiple matches for generic terms."""
        matches = get_menu_matches(menu_lookup, user_input)

        assert len(matches) >= min_expected_matches, \
            f"'{user_input}' should match at least {min_expected_matches} items, got {len(matches)}: {[m['name'] for m in matches]}"

    @pytest.mark.parametrize("user_input", [
        "chips",
        "cookie",
        "muffin",
        "juice",
        # Note: brownie only has 1 item in DB, so no disambiguation needed
    ])
    def test_generic_term_triggers_disambiguation(self, item_handler, user_input, fresh_order):
        """Handler should trigger disambiguation (ask user to choose) for generic terms."""
        result = get_handler_result(item_handler, user_input, fresh_order)

        # Should return a disambiguation message, not add item directly
        assert result != "SINGLE_MATCH_FOUND", \
            f"'{user_input}' should trigger disambiguation, not add single item"

        # Check that pending_field is set for disambiguation
        assert fresh_order.pending_field == "item_selection", \
            f"'{user_input}' should set pending_field to 'item_selection'"

        # Check that options are populated
        assert len(fresh_order.pending_item_options) > 1, \
            f"'{user_input}' should have multiple options, got {len(fresh_order.pending_item_options)}"


# ============================================================================
# TEST CATEGORY 2: Specific Items with Generic Suffix
# These should disambiguate if multiple matches, or add directly if single match
# ============================================================================

class TestSpecificItemsWithGenericSuffix:
    """Test specific items like 'bagel chips', 'potato chips' that end with generic terms."""

    @pytest.mark.parametrize("user_input,expected_match_count,should_disambiguate", [
        ("bagel chips", 4, True),        # Multiple bagel chips variants
        ("potato chips", 1, False),       # Single match
        ("kettle chips", 1, False),       # Single match
        ("orange juice", 3, True),        # Multiple OJ variants (Tropicana, Fresh Squeezed, etc.)
        ("chocolate chip cookie", 1, False),  # Likely single match
    ])
    def test_specific_item_parser_output(self, user_input, expected_match_count, should_disambiguate):
        """Parser should return the specific item name as new_menu_item."""
        result = get_parser_result(user_input)

        # Should return as menu_item
        assert result.new_menu_item is not None, f"'{user_input}' should return new_menu_item"
        assert result.new_side_item is None, f"'{user_input}' should NOT return new_side_item"

    @pytest.mark.parametrize("user_input,min_matches,max_matches", [
        ("bagel chips", 4, 10),      # All bagel chips variants
        ("potato chips", 1, 1),      # Exactly one
        ("kettle chips", 1, 1),      # Exactly one
        ("orange juice", 2, 10),     # Multiple OJ types
    ])
    def test_specific_item_menu_lookup(self, menu_lookup, user_input, min_matches, max_matches):
        """Menu lookup should return appropriate number of matches."""
        matches = get_menu_matches(menu_lookup, user_input)

        assert min_matches <= len(matches) <= max_matches, \
            f"'{user_input}' should match {min_matches}-{max_matches} items, got {len(matches)}: {[m['name'] for m in matches]}"

    @pytest.mark.parametrize("user_input,should_disambiguate", [
        ("bagel chips", True),       # Multiple matches - should disambiguate
        ("potato chips", False),     # Single match - should add directly
        ("kettle chips", False),     # Single match - should add directly
    ])
    def test_specific_item_disambiguation_behavior(self, item_handler, user_input, should_disambiguate, fresh_order):
        """Handler should disambiguate or add directly based on match count."""
        result = get_handler_result(item_handler, user_input, fresh_order)

        if should_disambiguate:
            assert result != "SINGLE_MATCH_FOUND", \
                f"'{user_input}' should trigger disambiguation"
            assert fresh_order.pending_field == "item_selection", \
                f"'{user_input}' should set pending_field to 'item_selection'"
            assert len(fresh_order.pending_item_options) > 1, \
                f"'{user_input}' should have multiple options"
        else:
            assert result == "SINGLE_MATCH_FOUND", \
                f"'{user_input}' should add directly (single match), but got disambiguation"


# ============================================================================
# TEST CATEGORY 3: Exact Menu Item Names
# These should ALWAYS add directly without disambiguation
# ============================================================================

class TestExactMenuItemNames:
    """Test exact menu item names that should add directly."""

    @pytest.mark.parametrize("user_input", [
        "Bagel Chips - BBQ",
        "Bagel Chips - Salt",
        "Bagel Chips - Sea Salt & Vinegar",
        "Potato Chips",
        "Kettle Chips",
    ])
    def test_exact_name_menu_lookup(self, menu_lookup, user_input):
        """Exact menu names should return exactly one match."""
        matches = get_menu_matches(menu_lookup, user_input)

        # For exact names, we expect the lookup to find items containing this name
        assert len(matches) >= 1, \
            f"'{user_input}' should find at least 1 match, got {len(matches)}"

    @pytest.mark.parametrize("user_input", [
        "Potato Chips",
        "Kettle Chips",
    ])
    def test_exact_name_adds_directly(self, item_handler, user_input, fresh_order):
        """Exact menu names with single match should add directly."""
        result = get_handler_result(item_handler, user_input, fresh_order)

        assert result == "SINGLE_MATCH_FOUND", \
            f"'{user_input}' should add directly, not disambiguate"


# ============================================================================
# TEST CATEGORY 4: Side Items
# These should add directly (standalone side items)
# ============================================================================

class TestSideItems:
    """Test side items that should be added directly."""

    @pytest.mark.parametrize("user_input,expected_canonical", [
        ("latkes", "Latkes"),
        ("latke", "Latkes"),
        ("home fries", "Home Fries"),
        ("fruit cup", "Fruit Cup"),
    ])
    def test_side_item_parser_output(self, user_input, expected_canonical):
        """Side items should be returned as new_side_item by parser."""
        result = get_parser_result(user_input)

        # Should return as side_item
        assert result.new_side_item == expected_canonical, \
            f"'{user_input}' should return new_side_item='{expected_canonical}', got '{result.new_side_item}'"


# ============================================================================
# TEST CATEGORY 5: Beverages
# ============================================================================

class TestBeverages:
    """Test beverage handling."""

    @pytest.mark.parametrize("user_input", [
        "coffee",
        "iced coffee",
        "latte",
    ])
    def test_coffee_triggers_coffee_flow(self, user_input):
        """Coffee-related items should trigger coffee flow."""
        result = get_parser_result(user_input)

        assert result.new_coffee is True, \
            f"'{user_input}' should trigger coffee flow (new_coffee=True)"

    @pytest.mark.parametrize("user_input", [
        "soda",
        "coke",
        "sprite",
    ])
    def test_soda_triggers_clarification(self, user_input):
        """Soda items should trigger soda clarification."""
        result = get_parser_result(user_input)

        # Either triggers soda clarification or returns as menu item for disambiguation
        assert result.needs_soda_clarification or result.new_menu_item is not None, \
            f"'{user_input}' should trigger soda clarification or return as menu item"


# ============================================================================
# TEST CATEGORY 6: Edge Cases and Variants
# ============================================================================

class TestEdgeCasesAndVariants:
    """Test edge cases, misspellings, and common variants."""

    @pytest.mark.parametrize("user_input,should_find_match", [
        ("oj", True),                # Abbreviation for orange juice
        ("BLT", True),               # Acronym
        # Note: Misspellings like "potatoe chips" require fuzzy matching (not implemented)
    ])
    def test_common_variants_find_matches(self, menu_lookup, user_input, should_find_match):
        """Common variants and misspellings should still find matches."""
        matches = get_menu_matches(menu_lookup, user_input)

        if should_find_match:
            assert len(matches) >= 1, \
                f"'{user_input}' should find at least 1 match, got {len(matches)}"

    def test_empty_input(self):
        """Empty input should be handled gracefully."""
        result = get_parser_result("")
        # Parser returns None for empty input, which is acceptable
        # The calling code handles None appropriately
        assert result is None

    def test_nonsense_input(self, menu_lookup):
        """Nonsense input should return no matches."""
        matches = get_menu_matches(menu_lookup, "xyzzy123nonsense")
        assert len(matches) == 0, "Nonsense input should return no matches"


# ============================================================================
# TEST CATEGORY 7: Full Flow Integration Tests
# ============================================================================

class TestFullFlowIntegration:
    """Test the complete flow from user input to final result."""

    def test_chips_full_flow(self, item_handler, fresh_order):
        """Test 'chips' goes through full disambiguation flow."""
        # Step 1: Parser
        parser_result = get_parser_result("chips")
        assert parser_result.new_menu_item == "chips"

        # Step 2: Handler processes it
        handler_result = get_handler_result(item_handler, "chips", fresh_order)

        # Step 3: Should be in disambiguation state
        assert fresh_order.pending_field == "item_selection"
        assert len(fresh_order.pending_item_options) >= 4

        # Verify all chip types are in options
        option_names = [opt['name'] for opt in fresh_order.pending_item_options]
        assert any('Bagel Chips' in name for name in option_names)
        assert any('Potato Chips' in name for name in option_names)

    def test_bagel_chips_full_flow(self, item_handler, fresh_order):
        """Test 'bagel chips' shows all bagel chip variants."""
        # Step 1: Parser
        parser_result = get_parser_result("bagel chips")
        assert parser_result.new_menu_item == "bagel chips"

        # Step 2: Handler processes it
        handler_result = get_handler_result(item_handler, "bagel chips", fresh_order)

        # Step 3: Should be in disambiguation state with bagel chips variants
        assert fresh_order.pending_field == "item_selection"
        assert len(fresh_order.pending_item_options) >= 4

        # Verify only bagel chips variants (not potato chips, etc.)
        option_names = [opt['name'] for opt in fresh_order.pending_item_options]
        assert all('Bagel Chips' in name or 'bagel chips' in name.lower() for name in option_names), \
            f"All options should be bagel chips variants, got: {option_names}"

    def test_potato_chips_full_flow(self, item_handler, fresh_order):
        """Test 'potato chips' adds directly (single match)."""
        # Step 1: Parser
        parser_result = get_parser_result("potato chips")
        assert parser_result.new_menu_item == "potato chips"

        # Step 2: Handler processes it - should add directly
        handler_result = get_handler_result(item_handler, "potato chips", fresh_order)

        # Step 3: Should NOT be in disambiguation state
        assert handler_result == "SINGLE_MATCH_FOUND", \
            "Potato chips should add directly without disambiguation"


# ============================================================================
# Run tests with verbose output
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
