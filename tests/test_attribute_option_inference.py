"""Tests for attribute option inference (e.g., 'earl grey' -> tea)."""
import pytest


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test."""


class TestAttributeOptionInference:
    """Tests for inferring item type from attribute option aliases."""

    def test_earl_grey_infers_tea_item_type(self):
        """'earl grey' should be recognized as tea order."""
        from orderbot.tasks.parsers.deterministic import _parse_configurable_item
        result = _parse_configurable_item('earl grey')
        assert result is not None
        assert len(result.parsed_items) == 1
        item = result.parsed_items[0]
        assert item.item_type == 'tea'
        # Check tea_flavor is set to earl_gray
        tea_flavor_selections = [s for s in item.selections if s.category == 'tea_flavor']
        assert len(tea_flavor_selections) == 1
        assert tea_flavor_selections[0].slug == 'earl_gray'

    def test_earl_gray_us_spelling_infers_tea(self):
        """'earl gray' (US spelling) should also be recognized as tea order."""
        from orderbot.tasks.parsers.deterministic import _parse_configurable_item
        result = _parse_configurable_item('earl gray')
        assert result is not None
        assert len(result.parsed_items) == 1
        item = result.parsed_items[0]
        assert item.item_type == 'tea'
        # Check tea_flavor is set to earl_gray
        tea_flavor_selections = [s for s in item.selections if s.category == 'tea_flavor']
        assert len(tea_flavor_selections) == 1
        assert tea_flavor_selections[0].slug == 'earl_gray'

    def test_earl_grey_tea_still_works(self):
        """'earl grey tea' should still work via trigger detection."""
        from orderbot.tasks.parsers.deterministic import _parse_configurable_item
        result = _parse_configurable_item('earl grey tea')
        assert result is not None
        assert len(result.parsed_items) == 1
        item = result.parsed_items[0]
        assert item.item_type == 'tea'

    def test_get_item_type_from_option_alias_returns_tuple(self):
        """get_item_type_from_option_alias should return (item_type, attr, option)."""
        from orderbot.cache import menu_cache
        result = menu_cache.get_item_type_from_option_alias('earl grey')
        assert result is not None
        item_type_slug, attr_slug, option_slug = result
        assert item_type_slug == 'tea'
        assert attr_slug == 'tea_flavor'
        assert option_slug == 'earl_gray'

    def test_get_item_type_from_option_alias_unknown_returns_none(self):
        """Unknown aliases should return None."""
        from orderbot.cache import menu_cache
        result = menu_cache.get_item_type_from_option_alias('nonexistent flavor')
        assert result is None
