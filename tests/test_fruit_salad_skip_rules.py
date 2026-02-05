"""Test skip rules for fruit_salad side choice.

When a user selects fruit_salad as the side choice for an omelette,
the bagel and cheese attributes should be skipped (not asked).
"""
import pytest

from orderbot.tasks.config.attribute_resolver import get_skipped_attributes, get_unanswered_mandatory
from orderbot.tasks.models import MenuItemTask
from orderbot.cache import menu_cache


@pytest.fixture(autouse=True)
def ensure_cache_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded before each test."""
    pass


class TestFruitSaladSkipRules:
    """Tests for fruit_salad skip rules."""

    def test_fruit_salad_triggers_skip_rules(self):
        """Test that selecting fruit_salad triggers skip rules for bagel and cheese."""
        # Check that menu cache has the skip rules loaded
        skipped = menu_cache.get_skipped_attributes_for_option('fruit_salad')

        assert 'bagel' in skipped, f"Expected 'bagel' in skipped attributes, got: {skipped}"
        assert 'cheese' in skipped, f"Expected 'cheese' in skipped attributes, got: {skipped}"

    def test_omelette_with_fruit_salad_skips_bagel_question(self):
        """Test that omelette with fruit_salad side doesn't ask about bagel type."""
        item = MenuItemTask(
            menu_item_name='Test Omelette',
            menu_item_type='omelette',
        )
        item['side_choice'] = 'fruit_salad'  # User picked fruit salad
        item['egg_quantity'] = 'egg'  # Default egg quantity

        # Check what attributes should be skipped
        skipped = get_skipped_attributes(item)
        assert 'bagel' in skipped, f"bagel should be in skipped attributes: {skipped}"
        assert 'cheese' in skipped, f"cheese should be in skipped attributes: {skipped}"

        # Check that bagel and cheese are not in unanswered mandatory attributes
        unanswered = get_unanswered_mandatory(item, 'omelette')
        unanswered_slugs = [a['slug'] for a in unanswered]

        assert 'bagel' not in unanswered_slugs, f"bagel should not be asked: {unanswered_slugs}"
        assert 'cheese' not in unanswered_slugs, f"cheese should not be asked: {unanswered_slugs}"

    def test_omelette_with_bagel_asks_about_bagel_type(self):
        """Test that omelette with bagel side still asks about bagel type."""
        item = MenuItemTask(
            menu_item_name='Test Omelette',
            menu_item_type='omelette',
        )
        item['side_choice'] = 'bagel'  # User picked bagel
        item['egg_quantity'] = 'egg'  # Default egg quantity

        # Check that bagel is NOT skipped when bagel is the side choice
        skipped = get_skipped_attributes(item)
        assert 'bagel' not in skipped, f"bagel should not be skipped when bagel is chosen: {skipped}"

        # Note: cheese might or might not be asked depending on configuration
