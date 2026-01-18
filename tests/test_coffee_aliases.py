"""
Tests for coffee/tea beverage alias functionality.

These tests verify that the database-driven coffee type recognition works correctly,
including alias matching from the menu_items.aliases column for sized_beverage items.
"""
import pytest


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test in this module."""


class TestGetCoffeeTypes:
    """Tests for get_coffee_types() function."""

    def test_get_coffee_types_returns_set(self):
        """get_coffee_types should return a set."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        result = get_coffee_types()
        assert isinstance(result, set)

    def test_get_coffee_types_includes_item_names(self):
        """get_coffee_types should include sized_beverage item names from database."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # These are actual item names from the database (lowercase)
        # Note: Database has "Hot Latte", "Iced Latte", not standalone "Latte"
        assert "hot latte" in coffee_types
        assert "hot cappuccino" in coffee_types
        assert "espresso" in coffee_types
        assert "hot coffee" in coffee_types
        assert "cafe americano" in coffee_types

    def test_get_coffee_types_includes_aliases(self):
        """get_coffee_types should include aliases from database."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # These are aliases, not the actual item names
        assert "chai" in coffee_types  # alias for Chai Tea
        assert "matcha" in coffee_types  # alias for Seasonal Matcha Latte
        assert "drip" in coffee_types  # alias for Coffee
        assert "hot cocoa" in coffee_types  # alias for Hot Chocolate

    def test_get_coffee_types_includes_matcha_latte(self):
        """get_coffee_types should include the new Seasonal Matcha Latte."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "seasonal matcha latte" in coffee_types
        assert "matcha latte" in coffee_types  # alias

    def test_get_coffee_types_excludes_soda_drinks(self):
        """get_coffee_types should not include soda/bottled drinks."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # These are beverages (item_type='beverage'), not sized_beverage
        assert "coca-cola" not in coffee_types
        assert "sprite" not in coffee_types
        assert "bottled water" not in coffee_types


class TestCoffeeOrderPattern:
    """Tests for _get_coffee_order_pattern() function."""

    def test_coffee_order_pattern_matches_latte(self):
        """Coffee order pattern should match latte orders."""
        from orderbot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        # Note: Database has "Hot Latte"/"Iced Latte", not standalone "Latte"
        # Pattern should match these full names
        assert pattern.search("I want a hot latte")
        assert pattern.search("can I get an iced latte")
        assert pattern.search("give me an iced latte")

    def test_coffee_order_pattern_matches_chai(self):
        """Coffee order pattern should match chai alias."""
        from orderbot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a chai")
        assert pattern.search("can I get a chai")

    def test_coffee_order_pattern_matches_matcha(self):
        """Coffee order pattern should match matcha alias."""
        from orderbot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a matcha")
        assert pattern.search("can I get a matcha latte")

    def test_coffee_order_pattern_matches_with_size(self):
        """Coffee order pattern should match orders with size."""
        from orderbot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        # Note: Database has "Hot Latte"/"Hot Coffee"/"Hot Cappuccino", not standalone names
        assert pattern.search("I want a large hot latte")
        assert pattern.search("can I get a medium hot coffee")
        assert pattern.search("small hot cappuccino please")

    def test_coffee_order_pattern_matches_with_iced(self):
        """Coffee order pattern should match iced orders."""
        from orderbot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want an iced latte")
        assert pattern.search("can I get an iced coffee")
        assert pattern.search("hot latte please")


class TestParseCoffeeDeterministic:
    """Tests for _parse_coffee_deterministic() function."""

    def test_parse_coffee_with_alias(self):
        """_parse_coffee_deterministic should recognize coffee aliases."""
        from orderbot.tasks.parsers.deterministic import _parse_coffee_deterministic
        from tests.helpers import has_coffee, has_menu_item
        result = _parse_coffee_deterministic("I want a chai")
        assert result is not None
        assert has_menu_item(result) or has_coffee(result)

    def test_parse_coffee_with_matcha_alias(self):
        """_parse_coffee_deterministic should recognize 'matcha' alias."""
        from orderbot.tasks.parsers.deterministic import _parse_coffee_deterministic
        from tests.helpers import has_coffee, has_menu_item
        result = _parse_coffee_deterministic("can I get a matcha")
        assert result is not None
        assert has_menu_item(result) or has_coffee(result)

    def test_parse_coffee_with_drip_alias(self):
        """_parse_coffee_deterministic should recognize 'drip' alias for coffee."""
        from orderbot.tasks.parsers.deterministic import _parse_coffee_deterministic
        from tests.helpers import has_coffee, has_menu_item
        result = _parse_coffee_deterministic("I want a drip coffee")
        assert result is not None
        assert has_menu_item(result) or has_coffee(result)


class TestCoffeeAliasesIntegration:
    """Integration tests for the full coffee alias flow."""

    def test_tea_variations_recognized(self):
        """Various tea drinks should be recognized."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # Full names
        assert "hot tea" in coffee_types
        assert "iced tea" in coffee_types
        assert "chai tea" in coffee_types
        assert "green tea" in coffee_types
        assert "earl grey tea" in coffee_types
        # Aliases
        assert "chai" in coffee_types

    def test_espresso_variations_recognized(self):
        """Espresso drinks should be recognized."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "espresso" in coffee_types
        # Note: "double espresso" and "triple espresso" are now modifiers,
        # not separate coffee types. They are handled by the coffee parser.

    def test_hot_chocolate_aliases(self):
        """Hot chocolate should be recognized by various terms."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "hot chocolate" in coffee_types
        assert "hot cocoa" in coffee_types
        assert "cocoa" in coffee_types

    def test_cold_brew_recognized(self):
        """Cold brew should be recognized."""
        from orderbot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "cold brew" in coffee_types


class TestEspressoParsingIntegration:
    """Integration tests for espresso ordering flow."""

    def test_espresso_parses_as_coffee_not_menu_item(self):
        """Espresso should be parsed as coffee, not as a menu item."""
        from orderbot.tasks.parsers import parse_open_input
        from tests.helpers import has_coffee, get_coffee_item, has_menu_item
        result = parse_open_input("espresso")
        assert has_coffee(result), "Espresso should be detected as coffee"
        coffee = get_coffee_item(result)
        assert coffee is not None
        assert coffee.item_name == "Espresso", f"Coffee type should be 'Espresso', got '{coffee.item_name}'"
        assert not has_menu_item(result), "Espresso should not be parsed as menu item"

    def test_double_espresso_parses_as_coffee(self):
        """Double espresso should be parsed as coffee with extra shots."""
        from orderbot.tasks.parsers import parse_open_input
        from tests.helpers import has_coffee, get_coffee_item, has_menu_item
        result = parse_open_input("double espresso")
        assert has_coffee(result), "Double espresso should be detected as coffee"
        coffee = get_coffee_item(result)
        assert coffee is not None
        assert coffee.item_name == "Espresso", f"Coffee type should be 'Espresso', got '{coffee.item_name}'"
        assert not has_menu_item(result), "Double espresso should not be parsed as menu item"

    def test_triple_espresso_parses_as_coffee(self):
        """Triple espresso should be parsed as coffee with extra shots."""
        from orderbot.tasks.parsers import parse_open_input
        from tests.helpers import has_coffee, get_coffee_item, has_menu_item
        result = parse_open_input("triple espresso")
        assert has_coffee(result), "Triple espresso should be detected as coffee"
        coffee = get_coffee_item(result)
        assert coffee is not None
        assert coffee.item_name == "Espresso", f"Coffee type should be 'Espresso', got '{coffee.item_name}'"
        assert not has_menu_item(result), "Triple espresso should not be parsed as menu item"

    def test_espresso_with_milk_parses_correctly(self):
        """Espresso with milk modifier should parse correctly."""
        from orderbot.tasks.parsers import parse_open_input
        from tests.helpers import has_coffee, get_coffee_item
        result = parse_open_input("espresso with oat milk")
        assert has_coffee(result), "Espresso with milk should be detected as coffee"
        coffee = get_coffee_item(result)
        assert coffee is not None
        assert coffee.item_name == "Espresso", f"Coffee type should be 'Espresso', got '{coffee.item_name}'"
        milk_mods = coffee.get_modifiers_by_category("milk")
        assert any(m.get("slug") == "oat" for m in milk_mods), f"Milk should be 'oat', got modifiers: {milk_mods}"
