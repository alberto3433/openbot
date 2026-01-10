"""Seed item types, global attributes, options, and links

Revision ID: s7t8u9v0w1x2
Revises: r6s7t8u9v0w1
Create Date: 2026-01-09 14:00:00.000000

This migration seeds the exact state of item_types, global_attributes,
global_attribute_options, and item_type_global_attributes tables as
configured through the admin UI. This ensures reproducibility on fresh databases.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's7t8u9v0w1x2'
down_revision: Union[str, Sequence[str], None] = 'r6s7t8u9v0w1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed data exported from database
ITEM_TYPES = [
    {"id": 1, "slug": "sized_beverage", "display_name": "Sized Beverage", "display_name_plural": "coffees and teas", "aliases": None, "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 2, "slug": "bagel", "display_name": "Bagel", "display_name_plural": None, "aliases": "bagels", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 3, "slug": "beverage", "display_name": "Beverage", "display_name_plural": None, "aliases": None, "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 4, "slug": "by_the_lb", "display_name": "By the Pound", "display_name_plural": "food by the pound", "aliases": None, "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 5, "slug": "cream_cheese", "display_name": "Cream Cheese", "display_name_plural": "cream cheeses", "aliases": None, "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 6, "slug": "egg_sandwich", "display_name": "Egg Sandwich", "display_name_plural": None, "aliases": "egg sandwiches", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 7, "slug": "fish_sandwich", "display_name": "Fish Sandwich", "display_name_plural": None, "aliases": "fish sandwiches", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 8, "slug": "omelette", "display_name": "Omelette", "display_name_plural": None, "aliases": "omelettes,omelets", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 10, "slug": "side", "display_name": "Side", "display_name_plural": None, "aliases": "sides", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 12, "slug": "snack", "display_name": "Snack", "display_name_plural": None, "aliases": "snacks", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 13, "slug": "spread_sandwich", "display_name": "Spread Sandwich", "display_name_plural": None, "aliases": "spread sandwiches,cream cheese sandwiches", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 17, "slug": "deli_sandwich", "display_name": "Deli Sandwich", "display_name_plural": None, "aliases": "deli sandwiches,deli classics", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 18, "slug": "soup", "display_name": "Soup", "display_name_plural": None, "aliases": "soups", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 19, "slug": "salad", "display_name": "Fresh Salad", "display_name_plural": None, "aliases": "salads", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 20, "slug": "pastry", "display_name": "Pastry", "display_name_plural": None, "aliases": "pastries", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 21, "slug": "breakfast", "display_name": "Breakfast", "display_name_plural": None, "aliases": "breakfasts", "expands_to": None, "name_filter": None, "is_virtual": False},
    {"id": 30, "slug": "espresso", "display_name": "Espresso", "display_name_plural": None, "aliases": None, "expands_to": None, "name_filter": None, "is_virtual": False},
]

GLOBAL_ATTRIBUTES = [
    {"id": 1, "slug": "add_egg", "display_name": "Add Egg", "input_type": "single_select", "description": "Migrated from deli_sandwich"},
    {"id": 2, "slug": "bagel_choice", "display_name": "Bagel Choice", "input_type": "single_select", "description": "Migrated from omelette [ingredient_group: bagel_choice]"},
    {"id": 3, "slug": "bread", "display_name": "Bread", "input_type": "single_select", "description": "Migrated from deli_sandwich [ingredient_group: bread]"},
    {"id": 4, "slug": "cheese", "display_name": "Cheese", "input_type": "single_select", "description": "Migrated from bagel [ingredient_group: cheese]"},
    {"id": 6, "slug": "decaf", "display_name": "Decaf", "input_type": "boolean", "description": "Migrated from espresso"},
    {"id": 7, "slug": "egg_quantity", "display_name": "Egg Quantity", "input_type": "single_select", "description": "Migrated from omelette [ingredient_group: egg_quantity]"},
    {"id": 8, "slug": "egg_style", "display_name": "Egg Preparation", "input_type": "single_select", "description": "Migrated from egg_sandwich [ingredient_group: egg_style]"},
    {"id": 9, "slug": "extra_cheese", "display_name": "Extra Cheese", "input_type": "single_select", "description": "Migrated from spread_sandwich [ingredient_group: cheese]"},
    {"id": 10, "slug": "extra_protein", "display_name": "Extra Protein", "input_type": "multi_select", "description": "Migrated from bagel [ingredient_group: extra_protein]"},
    {"id": 11, "slug": "extra_spread", "display_name": "Extra Spread", "input_type": "boolean", "description": "Migrated from spread_sandwich"},
    {"id": 15, "slug": "milk_sweetener_syrup", "display_name": "Milk, Sweetener, or Syrup", "input_type": "multi_select", "description": "Migrated from espresso [ingredient_group: milk_sweetener_syrup]"},
    {"id": 17, "slug": "scooped", "display_name": "Scooped Out", "input_type": "boolean", "description": "Migrated from egg_sandwich"},
    {"id": 18, "slug": "shots", "display_name": "Shots", "input_type": "single_select", "description": "Migrated from espresso [ingredient_group: shots]"},
    {"id": 19, "slug": "side_choice", "display_name": "Side Choice", "input_type": "single_select", "description": "Migrated from omelette [ingredient_group: side_choice]"},
    {"id": 21, "slug": "size", "display_name": "Size", "input_type": "single_select", "description": "Migrated from sized_beverage"},
    {"id": 22, "slug": "spread", "display_name": "Spread", "input_type": "multi_select", "description": "Migrated from egg_sandwich [ingredient_group: spread]"},
    {"id": 23, "slug": "style", "display_name": "Style", "input_type": "single_select", "description": "Migrated from sized_beverage [ingredient_group: style]"},
    {"id": 24, "slug": "temperature", "display_name": "Temperature", "input_type": "single_select", "description": "Migrated from sized_beverage [ingredient_group: iced]"},
    {"id": 25, "slug": "toasted", "display_name": "Toasted", "input_type": "boolean", "description": "Migrated from spread_sandwich"},
    {"id": 26, "slug": "toppings", "display_name": "Toppings", "input_type": "multi_select", "description": "Migrated from egg_sandwich [ingredient_group: topping]"},
]

GLOBAL_ATTRIBUTE_OPTIONS = [
    # add_egg options (global_attribute_id: 1)
    {"global_attribute_id": 1, "slug": "scrambled_egg", "display_name": "Scrambled Egg", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 1, "slug": "fried_egg_sunny_side_up", "display_name": "Fried Egg (Sunny Side Up)", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 1, "slug": "over_easy_egg", "display_name": "Over Easy Egg", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},
    {"global_attribute_id": 1, "slug": "over_medium_egg", "display_name": "Over Medium Egg", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 4},
    {"global_attribute_id": 1, "slug": "over_hard_egg", "display_name": "Over Hard Egg", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 5},
    {"global_attribute_id": 1, "slug": "egg_whites_2", "display_name": "Egg Whites (2)", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 6},

    # bagel_choice options (global_attribute_id: 2)
    {"global_attribute_id": 2, "slug": "plain", "display_name": "Plain Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 2, "slug": "everything", "display_name": "Everything Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 2, "slug": "sesame", "display_name": "Sesame Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 2, "slug": "poppy", "display_name": "Poppy Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},
    {"global_attribute_id": 2, "slug": "onion", "display_name": "Onion Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 4},
    {"global_attribute_id": 2, "slug": "salt", "display_name": "Salt Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 5},
    {"global_attribute_id": 2, "slug": "garlic", "display_name": "Garlic Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 6},
    {"global_attribute_id": 2, "slug": "pumpernickel", "display_name": "Pumpernickel Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 7},
    {"global_attribute_id": 2, "slug": "cinnamon_raisin", "display_name": "Cinnamon Raisin Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 8},
    {"global_attribute_id": 2, "slug": "whole_wheat", "display_name": "Whole Wheat Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 9},
    {"global_attribute_id": 2, "slug": "everything_wheat", "display_name": "Everything Wheat Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 10},
    {"global_attribute_id": 2, "slug": "bialy", "display_name": "Bialy", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 11},
    {"global_attribute_id": 2, "slug": "omelette_whole_wheat_everything_bagel", "display_name": "Whole Wheat Everything Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 12},
    {"global_attribute_id": 2, "slug": "omelette_whole_wheat_flatz", "display_name": "Whole Wheat Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 13},
    {"global_attribute_id": 2, "slug": "omelette_whole_wheat_everything_flatz", "display_name": "Whole Wheat Everything Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 14},
    {"global_attribute_id": 2, "slug": "omelette_plain_sourdough_bagel", "display_name": "Plain Sourdough Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 15},
    {"global_attribute_id": 2, "slug": "omelette_sesame_sourdough_bagel", "display_name": "Sesame Sourdough Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 16},
    {"global_attribute_id": 2, "slug": "omelette_everything_sourdough_bagel", "display_name": "Everything Sourdough Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 17},
    {"global_attribute_id": 2, "slug": "omelette_plain_sourdough_bagel_flatz", "display_name": "Plain Sourdough Bagel Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 18},
    {"global_attribute_id": 2, "slug": "omelette_everything_sourdough_bagel_flatz", "display_name": "Everything Sourdough Bagel Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 19},
    {"global_attribute_id": 2, "slug": "omelette_gf_plain_bagel", "display_name": "GF Plain Bagel", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 20},
    {"global_attribute_id": 2, "slug": "omelette_gf_everything_bagel", "display_name": "GF Everything Bagel", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 21},

    # bread options (global_attribute_id: 3)
    {"global_attribute_id": 3, "slug": "french_toast_bagel", "display_name": "French Toast Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "bagel", "display_name": "Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "plain_bagel", "display_name": "Plain Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "sesame_bagel", "display_name": "Sesame Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "poppy_bagel", "display_name": "Poppy Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "onion_bagel", "display_name": "Onion Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "salt_bagel", "display_name": "Salt Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "garlic_bagel", "display_name": "Garlic Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "egg_bagel", "display_name": "Egg Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "rainbow_bagel", "display_name": "Rainbow Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "everything_bagel", "display_name": "Everything Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "sun_dried_tomato_bagel", "display_name": "Sun Dried Tomato Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "multigrain_bagel", "display_name": "Multigrain Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "cinnamon_raisin_bagel", "display_name": "Cinnamon Raisin Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "asiago_bagel", "display_name": "Asiago Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "jalapeno_cheddar_bagel", "display_name": "Jalapeno Cheddar Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "bialy", "display_name": "Bialy", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "flagel", "display_name": "Flagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "gf_sesame_bagel", "display_name": "Gluten Free Sesame Bagel", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "gf_cinnamon_raisin_bagel", "display_name": "Gluten Free Cinnamon Raisin Bagel", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "croissant", "display_name": "Croissant", "price_modifier": 1.8, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "wrap", "display_name": "Wrap", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "gf_wrap", "display_name": "Gluten Free Wrap", "price_modifier": 1.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "no_bread", "display_name": "No Bread (in a bowl)", "price_modifier": 2.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "whole_wheat_bagel", "display_name": "Whole Wheat Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "pumpernickel_bagel", "display_name": "Pumpernickel Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "gf_plain_bagel", "display_name": "Gluten Free Plain Bagel", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "gf_everything_bagel", "display_name": "Gluten Free Everything Bagel", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 3, "slug": "deli_sandwich_whole_wheat_everything_bagel", "display_name": "Whole Wheat Everything Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 3, "slug": "deli_sandwich_whole_wheat_flatz", "display_name": "Whole Wheat Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 3, "slug": "deli_sandwich_whole_wheat_everything_flatz", "display_name": "Whole Wheat Everything Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},
    {"global_attribute_id": 3, "slug": "deli_sandwich_plain_sourdough_bagel", "display_name": "Plain Sourdough Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 4},
    {"global_attribute_id": 3, "slug": "deli_sandwich_sesame_sourdough_bagel", "display_name": "Sesame Sourdough Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 5},
    {"global_attribute_id": 3, "slug": "deli_sandwich_everything_sourdough_bagel", "display_name": "Everything Sourdough Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 6},
    {"global_attribute_id": 3, "slug": "deli_sandwich_plain_sourdough_bagel_flatz", "display_name": "Plain Sourdough Bagel Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 7},
    {"global_attribute_id": 3, "slug": "deli_sandwich_everything_sourdough_bagel_flatz", "display_name": "Everything Sourdough Bagel Flatz", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 8},
    {"global_attribute_id": 3, "slug": "deli_sandwich_white_bread", "display_name": "White Bread", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 9},
    {"global_attribute_id": 3, "slug": "deli_sandwich_rye", "display_name": "Rye", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 10},
    {"global_attribute_id": 3, "slug": "deli_sandwich_whole_wheat_bread", "display_name": "Whole Wheat Bread", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 11},
    {"global_attribute_id": 3, "slug": "deli_sandwich_whole_wheat_wrap", "display_name": "Whole Wheat Wrap", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 12},
    {"global_attribute_id": 3, "slug": "deli_sandwich_challah_roll", "display_name": "Challah Roll", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 13},

    # cheese options (global_attribute_id: 4)
    {"global_attribute_id": 4, "slug": "american", "display_name": "American", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 4, "slug": "swiss", "display_name": "Swiss", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 4, "slug": "cheddar", "display_name": "Cheddar", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},
    {"global_attribute_id": 4, "slug": "muenster", "display_name": "Muenster", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 4},
    {"global_attribute_id": 4, "slug": "provolone", "display_name": "Provolone", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 5},

    # egg_quantity options (global_attribute_id: 7)
    {"global_attribute_id": 7, "slug": "3_eggs", "display_name": "3 eggs (standard)", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 7, "slug": "4_eggs", "display_name": "4 eggs", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 7, "slug": "5_eggs", "display_name": "5 eggs", "price_modifier": 3.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 7, "slug": "6_eggs", "display_name": "6 eggs", "price_modifier": 4.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},

    # egg_style options (global_attribute_id: 8)
    {"global_attribute_id": 8, "slug": "scrambled", "display_name": "Scrambled", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 8, "slug": "fried", "display_name": "Fried", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 8, "slug": "over_easy", "display_name": "Over Easy", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 8, "slug": "over_medium", "display_name": "Over Medium", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 8, "slug": "over_hard", "display_name": "Over Hard", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 8, "slug": "egg_whites", "display_name": "Substitute Egg Whites", "price_modifier": 2.05, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},

    # extra_cheese options (global_attribute_id: 9)
    {"global_attribute_id": 9, "slug": "american", "display_name": "American", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "swiss", "display_name": "Swiss", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "fresh_mozzarella", "display_name": "Fresh Mozzarella", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "havarti", "display_name": "Havarti", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "cheddar", "display_name": "Cheddar", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "muenster", "display_name": "Muenster", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "provolone", "display_name": "Provolone", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 9, "slug": "pepper_jack", "display_name": "Pepper Jack", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},

    # extra_protein options (global_attribute_id: 10)
    {"global_attribute_id": 10, "slug": "ham", "display_name": "Ham", "price_modifier": 3.45, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 10, "slug": "bacon", "display_name": "Bacon", "price_modifier": 2.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 10, "slug": "egg", "display_name": "Egg", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},
    {"global_attribute_id": 10, "slug": "nova_scotia_salmon", "display_name": "Nova Scotia Salmon", "price_modifier": 6.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 4},
    {"global_attribute_id": 10, "slug": "turkey", "display_name": "Turkey", "price_modifier": 2.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 5},
    {"global_attribute_id": 10, "slug": "pastrami", "display_name": "Pastrami", "price_modifier": 3.45, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 6},
    {"global_attribute_id": 10, "slug": "sausage", "display_name": "Sausage", "price_modifier": 2.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 7},
    {"global_attribute_id": 10, "slug": "egg_white", "display_name": "Egg White", "price_modifier": 1.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 8},
    {"global_attribute_id": 10, "slug": "turkey_bacon", "display_name": "Turkey Bacon", "price_modifier": 2.95, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 9},
    {"global_attribute_id": 10, "slug": "smoked_turkey", "display_name": "Smoked Turkey", "price_modifier": 3.45, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 10},
    {"global_attribute_id": 10, "slug": "black_forest_ham", "display_name": "Black Forest Ham", "price_modifier": 3.45, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 11},
    {"global_attribute_id": 10, "slug": "corned_beef", "display_name": "Corned Beef", "price_modifier": 3.45, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 12},
    {"global_attribute_id": 10, "slug": "egg_salad", "display_name": "Egg Salad", "price_modifier": 2.55, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 13},
    {"global_attribute_id": 10, "slug": "applewood_smoked_bacon", "display_name": "Applewood Smoked Bacon", "price_modifier": 2.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 14},
    {"global_attribute_id": 10, "slug": "sausage_patty", "display_name": "Sausage Patty", "price_modifier": 2.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 15},
    {"global_attribute_id": 10, "slug": "chicken_sausage", "display_name": "Chicken Sausage", "price_modifier": 2.95, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 16},
    {"global_attribute_id": 10, "slug": "roast_beef", "display_name": "Roast Beef", "price_modifier": 3.45, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 17},
    {"global_attribute_id": 10, "slug": "espositos_sausage", "display_name": "Esposito's Sausage", "price_modifier": 2.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 18},

    # shots options (global_attribute_id: 18)
    {"global_attribute_id": 18, "slug": "single", "display_name": "Single", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 18, "slug": "double", "display_name": "Double", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 18, "slug": "triple", "display_name": "Triple", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 18, "slug": "quad", "display_name": "Quad", "price_modifier": 2.25, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},

    # side_choice options (global_attribute_id: 19)
    {"global_attribute_id": 19, "slug": "bagel", "display_name": "Bagel", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 19, "slug": "fruit_salad", "display_name": "Fruit Salad", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},

    # size options (global_attribute_id: 21)
    {"global_attribute_id": 21, "slug": "small", "display_name": "Small", "price_modifier": 0.0, "iced_price_modifier": 1.65, "is_default": True, "is_available": True, "display_order": 1},
    {"global_attribute_id": 21, "slug": "medium", "display_name": "Medium", "price_modifier": 0.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 21, "slug": "large", "display_name": "Large", "price_modifier": 0.9, "iced_price_modifier": 1.1, "is_default": False, "is_available": True, "display_order": 2},

    # spread options (global_attribute_id: 22)
    {"global_attribute_id": 22, "slug": "plain_cc", "display_name": "Plain Cream Cheese", "price_modifier": 0.8, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "scallion_cc", "display_name": "Scallion Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "veggie_cc", "display_name": "Veggie Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "lox_cc", "display_name": "Lox Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "walnut_raisin_cc", "display_name": "Walnut Raisin Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "jalapeno_cc", "display_name": "Jalapeno Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "honey_walnut_cc", "display_name": "Honey Walnut Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "strawberry_cc", "display_name": "Strawberry Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "blueberry_cc", "display_name": "Blueberry Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "olive_pimento_cc", "display_name": "Olive Pimento Cream Cheese", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "nova_scotia_cc", "display_name": "Nova Scotia Cream Cheese", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "chipotle_cc", "display_name": "Chipotle Cream Cheese", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "truffle_cc", "display_name": "Truffle Cream Cheese", "price_modifier": 1.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "plain_tofu", "display_name": "Plain Tofu", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "scallion_tofu", "display_name": "Scallion Tofu", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 22, "slug": "veggie_tofu", "display_name": "Veggie Tofu", "price_modifier": 0.9, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},

    # style options (global_attribute_id: 23)
    {"global_attribute_id": 23, "slug": "black", "display_name": "Black", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 23, "slug": "light", "display_name": "Light", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 23, "slug": "dark", "display_name": "Dark", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},

    # temperature options (global_attribute_id: 24)
    {"global_attribute_id": 24, "slug": "hot", "display_name": "Hot", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": True, "is_available": True, "display_order": 0},
    {"global_attribute_id": 24, "slug": "iced", "display_name": "Iced", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},

    # toppings options (global_attribute_id: 26)
    {"global_attribute_id": 26, "slug": "spinach", "display_name": "Spinach", "price_modifier": 0.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "butter", "display_name": "Butter", "price_modifier": 0.55, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "tomatoes", "display_name": "Tomatoes", "price_modifier": 1.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "lettuce", "display_name": "Lettuce", "price_modifier": 0.6, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "onions", "display_name": "Onions", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "red_onions", "display_name": "Red Onions", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "capers", "display_name": "Capers", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "roasted_peppers", "display_name": "Roasted Peppers", "price_modifier": 1.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "pickles", "display_name": "Pickles", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "cucumber", "display_name": "Cucumber", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "sauteed_mushrooms", "display_name": "Sauteed Mushrooms", "price_modifier": 1.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "sauteed_onions", "display_name": "Sauteed Onions", "price_modifier": 1.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "hash_browns", "display_name": "Hash Browns", "price_modifier": 2.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "latke", "display_name": "Breakfast Potato Latke", "price_modifier": 2.8, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "avocado", "display_name": "Avocado", "price_modifier": 3.5, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "hot_sauce", "display_name": "Hot Sauce", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "tomato", "display_name": "Tomato", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "onion", "display_name": "Onion", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "jalapeño", "display_name": "Jalapeno", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "jalapenos", "display_name": "Jalapeno", "price_modifier": 0.75, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 0},
    {"global_attribute_id": 26, "slug": "beefsteak_tomatoes", "display_name": "Beefsteak Tomatoes", "price_modifier": 1.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 1},
    {"global_attribute_id": 26, "slug": "egg_sandwich_onion_pepper_caper_relish", "display_name": "Onion, Pepper & Caper Relish", "price_modifier": 0.85, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 2},
    {"global_attribute_id": 26, "slug": "egg_sandwich_ketchup", "display_name": "Ketchup", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 3},
    {"global_attribute_id": 26, "slug": "egg_sandwich_salt", "display_name": "Salt", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 4},
    {"global_attribute_id": 26, "slug": "egg_sandwich_pepper", "display_name": "Pepper", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 5},
    {"global_attribute_id": 26, "slug": "egg_sandwich_grape_jelly", "display_name": "Grape Jelly", "price_modifier": 0.55, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 6},
    {"global_attribute_id": 26, "slug": "egg_sandwich_strawberry_jelly", "display_name": "Strawberry Jelly", "price_modifier": 0.55, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 7},
    {"global_attribute_id": 26, "slug": "egg_sandwich_mayo", "display_name": "Mayo", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 8},
    {"global_attribute_id": 26, "slug": "egg_sandwich_mustard", "display_name": "Mustard", "price_modifier": 0.0, "iced_price_modifier": None, "is_default": False, "is_available": True, "display_order": 9},
]

ITEM_TYPE_GLOBAL_ATTRIBUTE_LINKS = [
    # sized_beverage (item_type_id: 1)
    {"item_type_id": 1, "global_attribute_id": 21, "display_order": 1, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": "What size?", "min_selections": None, "max_selections": None},
    {"item_type_id": 1, "global_attribute_id": 24, "display_order": 2, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": "Hot or iced?", "min_selections": None, "max_selections": None},
    {"item_type_id": 1, "global_attribute_id": 15, "display_order": 3, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "Any milk, sweetener, or syrup?", "min_selections": None, "max_selections": None},
    {"item_type_id": 1, "global_attribute_id": 23, "display_order": 4, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 1, "global_attribute_id": 18, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 1, "global_attribute_id": 6, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},

    # bagel (item_type_id: 2)
    {"item_type_id": 2, "global_attribute_id": 3, "display_order": 1, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": "What kind of bagel would you like?", "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 25, "display_order": 2, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "Would you like it toasted?", "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 17, "display_order": 3, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 22, "display_order": 4, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "Any spread on that?", "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 1, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 4, "display_order": 6, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 10, "display_order": 7, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 2, "global_attribute_id": 26, "display_order": 8, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},

    # egg_sandwich (item_type_id: 6)
    {"item_type_id": 6, "global_attribute_id": 3, "display_order": 1, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": "What kind of bread would you like?", "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 25, "display_order": 2, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "Would you like it toasted?", "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 17, "display_order": 3, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 8, "display_order": 4, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "How would you like your eggs?", "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 7, "display_order": 5, "is_required": False, "allow_none": False, "ask_in_conversation": False, "question_text": "How many eggs would you like?", "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 10, "display_order": 6, "is_required": False, "allow_none": False, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 9, "display_order": 7, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 22, "display_order": 8, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 6, "global_attribute_id": 26, "display_order": 9, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},

    # fish_sandwich (item_type_id: 7)
    {"item_type_id": 7, "global_attribute_id": 3, "display_order": 1, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 7, "global_attribute_id": 25, "display_order": 2, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 7, "global_attribute_id": 22, "display_order": 3, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 7, "global_attribute_id": 10, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 7, "global_attribute_id": 9, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 7, "global_attribute_id": 26, "display_order": 6, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},

    # omelette (item_type_id: 8)
    {"item_type_id": 8, "global_attribute_id": 19, "display_order": 1, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": "Would you like a bagel or fruit salad with it?", "min_selections": None, "max_selections": None},
    {"item_type_id": 8, "global_attribute_id": 22, "display_order": 2, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 8, "global_attribute_id": 2, "display_order": 3, "is_required": False, "allow_none": False, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 8, "global_attribute_id": 9, "display_order": 4, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 8, "global_attribute_id": 10, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 8, "global_attribute_id": 26, "display_order": 6, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 8, "global_attribute_id": 7, "display_order": 7, "is_required": False, "allow_none": False, "ask_in_conversation": False, "question_text": "How many eggs would you like?", "min_selections": None, "max_selections": None},

    # spread_sandwich (item_type_id: 13)
    {"item_type_id": 13, "global_attribute_id": 3, "display_order": 2, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 13, "global_attribute_id": 25, "display_order": 3, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 13, "global_attribute_id": 11, "display_order": 4, "is_required": False, "allow_none": False, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 13, "global_attribute_id": 9, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 13, "global_attribute_id": 10, "display_order": 6, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 13, "global_attribute_id": 26, "display_order": 7, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},

    # deli_sandwich (item_type_id: 17)
    {"item_type_id": 17, "global_attribute_id": 3, "display_order": 1, "is_required": True, "allow_none": False, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 25, "display_order": 2, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 17, "display_order": 3, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": "Would you like the bagel scooped?", "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 22, "display_order": 4, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": "Any spread on that?", "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 1, "display_order": 5, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 9, "display_order": 6, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 10, "display_order": 7, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},
    {"item_type_id": 17, "global_attribute_id": 26, "display_order": 8, "is_required": False, "allow_none": True, "ask_in_conversation": False, "question_text": None, "min_selections": None, "max_selections": None},

    # espresso (item_type_id: 30)
    {"item_type_id": 30, "global_attribute_id": 18, "display_order": 1, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "How many shots?", "min_selections": None, "max_selections": None},
    {"item_type_id": 30, "global_attribute_id": 15, "display_order": 2, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": "Any milk, sweetener, or syrup?", "min_selections": None, "max_selections": None},
    {"item_type_id": 30, "global_attribute_id": 6, "display_order": 3, "is_required": False, "allow_none": True, "ask_in_conversation": True, "question_text": None, "min_selections": None, "max_selections": None},
]


def upgrade() -> None:
    """Seed item types, global attributes, options, and links."""
    conn = op.get_bind()

    # Check if tables exist and have data
    result = conn.execute(sa.text("SELECT COUNT(*) FROM item_types"))
    item_types_count = result.scalar()

    result = conn.execute(sa.text("SELECT COUNT(*) FROM global_attributes"))
    global_attrs_count = result.scalar()

    # Only seed if tables are empty (fresh database)
    if item_types_count == 0:
        # Insert item types
        for it in ITEM_TYPES:
            conn.execute(sa.text("""
                INSERT INTO item_types (id, slug, display_name, display_name_plural, aliases, expands_to, name_filter, is_virtual)
                VALUES (:id, :slug, :display_name, :display_name_plural, :aliases, :expands_to, :name_filter, :is_virtual)
            """), it)

    if global_attrs_count == 0:
        # Insert global attributes
        for ga in GLOBAL_ATTRIBUTES:
            conn.execute(sa.text("""
                INSERT INTO global_attributes (id, slug, display_name, input_type, description)
                VALUES (:id, :slug, :display_name, :input_type, :description)
            """), ga)

        # Insert global attribute options
        for gao in GLOBAL_ATTRIBUTE_OPTIONS:
            conn.execute(sa.text("""
                INSERT INTO global_attribute_options (global_attribute_id, slug, display_name, price_modifier, iced_price_modifier, is_default, is_available, display_order)
                VALUES (:global_attribute_id, :slug, :display_name, :price_modifier, :iced_price_modifier, :is_default, :is_available, :display_order)
            """), gao)

        # Insert item type -> global attribute links
        for link in ITEM_TYPE_GLOBAL_ATTRIBUTE_LINKS:
            conn.execute(sa.text("""
                INSERT INTO item_type_global_attributes (item_type_id, global_attribute_id, display_order, is_required, allow_none, ask_in_conversation, question_text, min_selections, max_selections)
                VALUES (:item_type_id, :global_attribute_id, :display_order, :is_required, :allow_none, :ask_in_conversation, :question_text, :min_selections, :max_selections)
            """), link)


def downgrade() -> None:
    """Remove seeded data (only if tables contain exactly seeded data)."""
    conn = op.get_bind()

    # Delete links first (foreign key constraints)
    conn.execute(sa.text("DELETE FROM item_type_global_attributes"))

    # Delete options
    conn.execute(sa.text("DELETE FROM global_attribute_options"))

    # Delete global attributes
    conn.execute(sa.text("DELETE FROM global_attributes"))

    # Don't delete item_types as they may be referenced by menu_items
