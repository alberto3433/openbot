"""
Tests for configurable item recognition and pattern matching.

These tests verify that the database-driven configurable item type recognition works correctly,
including alias matching from the menu_items.aliases column.
"""
import pytest


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test in this module."""


class TestGetConfigurableItemNames:
    """Tests for menu_cache.get_configurable_item_names() method."""

    def test_get_configurable_item_names_returns_set(self):
        """get_configurable_item_names should return a set."""
        from orderbot.cache import menu_cache
        result = menu_cache.get_configurable_item_names()
        assert isinstance(result, set)

    def test_get_configurable_item_names_includes_beverage_items(self):
        """get_configurable_item_names should include sized_beverage item names from database."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        # These are actual item names from the database (lowercase)
        assert "hot latte" in item_names
        assert "hot cappuccino" in item_names
        assert "espresso" in item_names
        assert "hot coffee" in item_names
        assert "cafe americano" in item_names

    def test_get_configurable_item_names_includes_beverage_aliases(self):
        """get_configurable_item_names should include aliases from database."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        # These are aliases, not the actual item names
        assert "chai" in item_names  # alias for Chai Tea
        assert "matcha" in item_names  # alias for Seasonal Matcha Latte
        assert "drip" in item_names  # alias for Coffee
        assert "hot cocoa" in item_names  # alias for Hot Chocolate

    def test_get_configurable_item_names_includes_matcha_latte(self):
        """get_configurable_item_names should include the Seasonal Matcha Latte."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        assert "seasonal matcha latte" in item_names
        assert "matcha latte" in item_names  # alias

    def test_get_configurable_item_names_includes_bagel_items(self):
        """get_configurable_item_names should include bagel item names."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        # Bagels are configurable items - check for bagel-related items
        # Note: Individual bagel types (plain, everything) are attribute options,
        # not separate menu items. Check for actual bagel menu items or aliases.
        bagel_items = [n for n in item_names if "bagel" in n.lower()]
        assert len(bagel_items) > 0, f"Expected bagel items in configurable names, got: {bagel_items}"

    def test_get_configurable_item_names_excludes_soda_drinks(self):
        """get_configurable_item_names should not include non-configurable items like sodas."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        # These are beverages (item_type='beverage'), not sized_beverage
        # They don't have askable attributes so should not be included
        assert "coca-cola" not in item_names
        assert "sprite" not in item_names


class TestConfigurableItemPattern:
    """Tests for _get_configurable_item_pattern() function."""

    def test_configurable_item_pattern_matches_latte(self):
        """Configurable item pattern should match latte orders."""
        from orderbot.tasks.parsers.deterministic import _get_configurable_item_pattern
        pattern = _get_configurable_item_pattern()
        # Note: Database has "Hot Latte"/"Iced Latte", not standalone "Latte"
        # Pattern should match these full names
        assert pattern.search("I want a hot latte")
        assert pattern.search("can I get an iced latte")
        assert pattern.search("give me an iced latte")

    def test_configurable_item_pattern_matches_chai(self):
        """Configurable item pattern should match chai alias."""
        from orderbot.tasks.parsers.deterministic import _get_configurable_item_pattern
        pattern = _get_configurable_item_pattern()
        assert pattern.search("I want a chai")
        assert pattern.search("can I get a chai")

    def test_configurable_item_pattern_matches_matcha(self):
        """Configurable item pattern should match matcha alias."""
        from orderbot.tasks.parsers.deterministic import _get_configurable_item_pattern
        pattern = _get_configurable_item_pattern()
        assert pattern.search("I want a matcha")
        assert pattern.search("can I get a matcha latte")

    def test_configurable_item_pattern_matches_with_size(self):
        """Configurable item pattern should match orders with size."""
        from orderbot.tasks.parsers.deterministic import _get_configurable_item_pattern
        pattern = _get_configurable_item_pattern()
        # Note: Database has "Hot Latte"/"Hot Coffee"/"Hot Cappuccino"
        assert pattern.search("I want a large hot latte")
        assert pattern.search("can I get a medium hot coffee")
        assert pattern.search("small hot cappuccino please")

    def test_configurable_item_pattern_matches_with_iced(self):
        """Configurable item pattern should match iced orders."""
        from orderbot.tasks.parsers.deterministic import _get_configurable_item_pattern
        pattern = _get_configurable_item_pattern()
        assert pattern.search("I want an iced latte")
        assert pattern.search("can I get an iced coffee")
        assert pattern.search("hot latte please")

    def test_configurable_item_pattern_matches_bagels(self):
        """Configurable item pattern should match bagel orders."""
        from orderbot.tasks.parsers.deterministic import _get_configurable_item_pattern
        pattern = _get_configurable_item_pattern()
        assert pattern.search("I want a plain bagel")
        assert pattern.search("can I get an everything bagel")


class TestParseConfigurableItem:
    """Tests for _parse_configurable_item() function for beverages."""

    def test_parse_coffee_with_alias(self):
        """_parse_configurable_item should recognize coffee aliases."""
        from orderbot.tasks.parsers.deterministic import _parse_configurable_item
        from tests.helpers import has_coffee, has_menu_item
        result = _parse_configurable_item("I want a chai")
        assert result is not None
        assert has_menu_item(result) or has_coffee(result)

    def test_parse_coffee_with_matcha_alias(self):
        """_parse_configurable_item should recognize 'matcha' alias."""
        from orderbot.tasks.parsers.deterministic import _parse_configurable_item
        from tests.helpers import has_coffee, has_menu_item
        result = _parse_configurable_item("can I get a matcha")
        assert result is not None
        assert has_menu_item(result) or has_coffee(result)

    def test_parse_coffee_with_drip_alias(self):
        """_parse_configurable_item should recognize 'drip' alias for coffee."""
        from orderbot.tasks.parsers.deterministic import _parse_configurable_item
        from tests.helpers import has_coffee, has_menu_item
        result = _parse_configurable_item("I want a drip coffee")
        assert result is not None
        assert has_menu_item(result) or has_coffee(result)


class TestConfigurableItemAliasesIntegration:
    """Integration tests for the configurable item alias flow."""

    def test_tea_variations_recognized(self):
        """Various tea drinks should be recognized."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        # Full names
        assert "hot tea" in item_names
        assert "iced tea" in item_names
        assert "chai tea" in item_names
        assert "green tea" in item_names
        assert "earl grey tea" in item_names
        # Aliases
        assert "chai" in item_names

    def test_espresso_variations_recognized(self):
        """Espresso drinks should be recognized."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        assert "espresso" in item_names
        # Note: "double espresso" and "triple espresso" are now modifiers,
        # not separate coffee types. They are handled by the coffee parser.

    def test_hot_chocolate_aliases(self):
        """Hot chocolate should be recognized by various terms."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        assert "hot chocolate" in item_names
        assert "hot cocoa" in item_names
        assert "cocoa" in item_names

    def test_cold_brew_recognized(self):
        """Cold brew should be recognized."""
        from orderbot.cache import menu_cache
        item_names = menu_cache.get_configurable_item_names()
        assert "cold brew" in item_names


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
        # Check for oat milk in selections or attribute_values
        milk_mods = coffee.get_selections("milk")
        milk_in_attrs = coffee.attribute_values.get("milk_sweetener_syrup") or coffee.attribute_values.get("milk")
        has_oat_milk = (
            # Check selections (returns list of dicts)
            any(m.get("slug", "").startswith("oat") for m in milk_mods if isinstance(m, dict)) or
            # Check attribute_values (can be string or list)
            (isinstance(milk_in_attrs, str) and "oat" in milk_in_attrs.lower()) or
            (isinstance(milk_in_attrs, list) and any(
                (isinstance(m, dict) and "oat" in m.get("slug", "").lower()) or
                (isinstance(m, str) and "oat" in m.lower())
                for m in milk_in_attrs
            ))
        )
        assert has_oat_milk, f"Milk should be oat-based, got modifiers: {milk_mods}, attrs: {milk_in_attrs}"
