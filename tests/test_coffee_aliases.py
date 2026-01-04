"""
Tests for coffee/tea beverage alias functionality.

These tests verify that the database-driven coffee type recognition works correctly,
including alias matching from the menu_items.aliases column for sized_beverage items.
"""
import pytest


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test in this module."""
    pass


class TestGetCoffeeTypes:
    """Tests for get_coffee_types() function."""

    def test_get_coffee_types_returns_set(self):
        """get_coffee_types should return a set."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        result = get_coffee_types()
        assert isinstance(result, set)

    def test_get_coffee_types_includes_item_names(self):
        """get_coffee_types should include sized_beverage item names from database."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # These are actual item names from the database (lowercase)
        assert "latte" in coffee_types
        assert "cappuccino" in coffee_types
        assert "espresso" in coffee_types
        assert "coffee" in coffee_types
        assert "americano" in coffee_types

    def test_get_coffee_types_includes_aliases(self):
        """get_coffee_types should include aliases from database."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # These are aliases, not the actual item names
        assert "chai" in coffee_types  # alias for Chai Tea
        assert "tea" in coffee_types  # alias for Hot Tea, Iced Tea, etc.
        assert "matcha" in coffee_types  # alias for Seasonal Matcha Latte
        assert "drip" in coffee_types  # alias for Coffee
        assert "hot cocoa" in coffee_types  # alias for Hot Chocolate

    def test_get_coffee_types_includes_matcha_latte(self):
        """get_coffee_types should include the new Seasonal Matcha Latte."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "seasonal matcha latte" in coffee_types
        assert "matcha latte" in coffee_types  # alias

    def test_get_coffee_types_excludes_soda_drinks(self):
        """get_coffee_types should not include soda/bottled drinks."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # These are beverages (item_type='beverage'), not sized_beverage
        assert "coca-cola" not in coffee_types
        assert "sprite" not in coffee_types
        assert "bottled water" not in coffee_types


class TestCoffeeOrderPattern:
    """Tests for _get_coffee_order_pattern() function."""

    def test_coffee_order_pattern_matches_latte(self):
        """Coffee order pattern should match latte orders."""
        from sandwich_bot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a latte")
        assert pattern.search("can I get a latte")
        assert pattern.search("give me a latte")

    def test_coffee_order_pattern_matches_chai(self):
        """Coffee order pattern should match chai alias."""
        from sandwich_bot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a chai")
        assert pattern.search("can I get a chai")

    def test_coffee_order_pattern_matches_matcha(self):
        """Coffee order pattern should match matcha alias."""
        from sandwich_bot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a matcha")
        assert pattern.search("can I get a matcha latte")

    def test_coffee_order_pattern_matches_tea(self):
        """Coffee order pattern should match tea alias."""
        from sandwich_bot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a tea")
        assert pattern.search("can I get a hot tea")

    def test_coffee_order_pattern_matches_with_size(self):
        """Coffee order pattern should match orders with size."""
        from sandwich_bot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want a large latte")
        assert pattern.search("can I get a medium coffee")
        assert pattern.search("small cappuccino please")

    def test_coffee_order_pattern_matches_with_iced(self):
        """Coffee order pattern should match iced orders."""
        from sandwich_bot.tasks.parsers.deterministic import _get_coffee_order_pattern
        pattern = _get_coffee_order_pattern()
        assert pattern.search("I want an iced latte")
        assert pattern.search("can I get an iced coffee")
        assert pattern.search("hot latte please")


class TestParseCoffeeDeterministic:
    """Tests for _parse_coffee_deterministic() function."""

    def test_parse_coffee_with_alias(self):
        """_parse_coffee_deterministic should recognize coffee aliases."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_coffee_deterministic
        result = _parse_coffee_deterministic("I want a chai")
        assert result is not None
        assert result.new_menu_item is not None or result.new_coffee_type is not None

    def test_parse_coffee_with_matcha_alias(self):
        """_parse_coffee_deterministic should recognize 'matcha' alias."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_coffee_deterministic
        result = _parse_coffee_deterministic("can I get a matcha")
        assert result is not None
        assert result.new_menu_item is not None or result.new_coffee_type is not None

    def test_parse_coffee_with_tea_alias(self):
        """_parse_coffee_deterministic should recognize 'tea' alias."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_coffee_deterministic
        result = _parse_coffee_deterministic("I'll have a tea")
        assert result is not None
        assert result.new_menu_item is not None or result.new_coffee_type is not None

    def test_parse_coffee_with_drip_alias(self):
        """_parse_coffee_deterministic should recognize 'drip' alias for coffee."""
        from sandwich_bot.tasks.parsers.deterministic import _parse_coffee_deterministic
        result = _parse_coffee_deterministic("I want a drip coffee")
        assert result is not None
        assert result.new_menu_item is not None or result.new_coffee_type is not None


class TestCoffeeAliasesIntegration:
    """Integration tests for the full coffee alias flow."""

    def test_tea_variations_recognized(self):
        """Various tea drinks should be recognized."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        # Full names
        assert "hot tea" in coffee_types
        assert "iced tea" in coffee_types
        assert "chai tea" in coffee_types
        assert "green tea" in coffee_types
        assert "earl grey tea" in coffee_types
        # Aliases
        assert "tea" in coffee_types
        assert "chai" in coffee_types

    def test_espresso_variations_recognized(self):
        """Espresso drinks should be recognized."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "espresso" in coffee_types
        assert "double espresso" in coffee_types

    def test_hot_chocolate_aliases(self):
        """Hot chocolate should be recognized by various terms."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "hot chocolate" in coffee_types
        assert "hot cocoa" in coffee_types
        assert "cocoa" in coffee_types

    def test_cold_brew_recognized(self):
        """Cold brew should be recognized."""
        from sandwich_bot.tasks.parsers.constants import get_coffee_types
        coffee_types = get_coffee_types()
        assert "cold brew" in coffee_types
