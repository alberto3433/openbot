"""
Tests for soda/beverage alias functionality.

These tests verify that the database-driven soda type recognition works correctly,
including alias matching from the menu_items.aliases column.
"""
import pytest


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test in this module."""


class TestGetSodaTypes:
    """Tests for get_soda_types() function."""

    def test_get_soda_types_returns_set(self):
        """get_soda_types should return a set."""
        from orderbot.tasks.parsers.constants import get_soda_types
        result = get_soda_types()
        assert isinstance(result, set)

    def test_get_soda_types_includes_item_names(self):
        """get_soda_types should include beverage item names from database."""
        from orderbot.tasks.parsers.constants import get_soda_types
        soda_types = get_soda_types()
        # These are actual item names from the database (lowercase)
        assert "coca-cola" in soda_types
        assert "sprite" in soda_types
        assert "diet coke" in soda_types

    def test_get_soda_types_includes_aliases(self):
        """get_soda_types should include aliases from database."""
        from orderbot.tasks.parsers.constants import get_soda_types
        soda_types = get_soda_types()
        # These are aliases, not the actual item names
        assert "coke" in soda_types  # alias for Coca-Cola
        assert "oj" in soda_types  # alias for Fresh Squeezed Orange Juice
        assert "seltzer" in soda_types  # alias for San Pellegrino
        assert "sparkling water" in soda_types  # alias for San Pellegrino

    def test_get_soda_types_excludes_nonexistent_items(self):
        """get_soda_types should not include items not in the database."""
        from orderbot.tasks.parsers.constants import get_soda_types
        soda_types = get_soda_types()
        # These are not in the Zucker's menu
        assert "pepsi" not in soda_types
        assert "mountain dew" not in soda_types
        assert "gatorade" not in soda_types
        assert "fanta" not in soda_types


class TestIsSodaDrink:
    """Tests for test_is_soda_drink() helper function."""

    def test_is_soda_drink_with_exact_match(self):
        """test_is_soda_drink should return True for exact item name match."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        assert test_is_soda_drink("Coca-Cola") is True
        assert test_is_soda_drink("Sprite") is True
        assert test_is_soda_drink("Diet Coke") is True

    def test_is_soda_drink_with_alias(self):
        """test_is_soda_drink should return True for alias match."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        assert test_is_soda_drink("coke") is True
        assert test_is_soda_drink("oj") is True
        assert test_is_soda_drink("seltzer") is True

    def test_is_soda_drink_case_insensitive(self):
        """test_is_soda_drink should be case insensitive."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        assert test_is_soda_drink("COKE") is True
        assert test_is_soda_drink("Coke") is True
        assert test_is_soda_drink("OJ") is True
        assert test_is_soda_drink("Oj") is True

    def test_is_soda_drink_with_nonexistent_item(self):
        """test_is_soda_drink should return False for items not in database."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        assert test_is_soda_drink("pepsi") is False
        assert test_is_soda_drink("mountain dew") is False
        assert test_is_soda_drink("monster energy") is False  # Not on menu

    def test_is_soda_drink_with_none(self):
        """test_is_soda_drink should return False for None input."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        assert test_is_soda_drink(None) is False

    def test_is_soda_drink_with_empty_string(self):
        """test_is_soda_drink should return False for empty string."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        assert test_is_soda_drink("") is False

    def test_is_soda_drink_with_coffee_beverage(self):
        """test_is_soda_drink should return False for coffee beverages."""
        from tests.helpers.menu_helpers import test_is_soda_drink
        # Coffee beverages are sized_beverage, not beverage
        assert test_is_soda_drink("latte") is False
        assert test_is_soda_drink("cappuccino") is False
        assert test_is_soda_drink("espresso") is False


class TestParseSodaDeterministic:
    """Tests for _parse_soda_deterministic() function."""

    def test_parse_soda_with_alias(self):
        """_parse_soda_deterministic should recognize soda aliases."""
        from orderbot.tasks.parsers.deterministic import _parse_soda_deterministic
        from tests.helpers import get_menu_item
        result = _parse_soda_deterministic("I want a coke")
        assert result is not None
        menu_item = get_menu_item(result)
        assert menu_item is not None
        # "coke" alias should map to the canonical name "Coca-Cola"
        assert "coca" in menu_item.item_name.lower()

    def test_parse_soda_with_oj_alias(self):
        """_parse_soda_deterministic should recognize 'oj' alias."""
        from orderbot.tasks.parsers.deterministic import _parse_soda_deterministic
        from tests.helpers import get_menu_item
        result = _parse_soda_deterministic("can I get an oj")
        assert result is not None
        menu_item = get_menu_item(result)
        assert menu_item is not None

    def test_parse_soda_with_seltzer_alias(self):
        """_parse_soda_deterministic should recognize 'seltzer' alias."""
        from orderbot.tasks.parsers.deterministic import _parse_soda_deterministic
        from tests.helpers import get_menu_item
        result = _parse_soda_deterministic("I'll have a seltzer")
        assert result is not None
        menu_item = get_menu_item(result)
        assert menu_item is not None

    def test_parse_soda_with_nonexistent_item(self):
        """_parse_soda_deterministic should return None for non-existent sodas."""
        from orderbot.tasks.parsers.deterministic import _parse_soda_deterministic
        result = _parse_soda_deterministic("I want a pepsi")
        # Pepsi is not in the database, so it shouldn't match
        assert result is None

    def test_parse_soda_with_generic_term(self):
        """_parse_soda_deterministic should request clarification for generic terms."""
        from orderbot.tasks.parsers.deterministic import _parse_soda_deterministic
        result = _parse_soda_deterministic("can I get a soda")
        assert result is not None
        assert result.needs_category_clarification is not None


class TestSodaAliasesIntegration:
    """Integration tests for the full soda alias flow."""

    def test_dr_browns_aliases(self):
        """Dr. Brown's sodas should be recognized by various spellings."""
        from orderbot.tasks.parsers.constants import get_soda_types
        soda_types = get_soda_types()
        # Original name (lowercase)
        assert "dr. brown's cel-ray" in soda_types
        # Various alias spellings
        assert "cel-ray" in soda_types
        assert "dr browns cel-ray" in soda_types
        assert "dr brown's cel-ray" in soda_types

    def test_water_aliases(self):
        """Water should be recognized by various terms."""
        from orderbot.tasks.parsers.constants import get_soda_types
        soda_types = get_soda_types()
        assert "bottled water" in soda_types
        assert "water" in soda_types
        assert "sparkling water" in soda_types
        assert "seltzer" in soda_types
