"""Menu index building package.

This package provides functionality to build rich, LLM-friendly menu indexes
from database data.

Main entry points:
- build_menu_index: Build the complete menu index
- get_menu_version: Generate a version hash for change detection
"""

from .orchestrator import build_menu_index, get_menu_version

# Re-export builders for advanced usage
from .builders import (
    build_company_info,
    build_ingredient_to_items,
    build_item_descriptions,
    build_item_keywords,
    build_item_types_data,
    build_modifier_categories,
    build_neighborhood_zip_codes,
)

# Re-export preloaders for advanced usage
from .preloaders import (
    preload_all_ingredients,
    preload_global_attribute_options,
    preload_item_type_config_status,
    preload_item_type_ingredients,
    preload_menu_item_ingredients,
    preload_size_prices,
)

__all__ = [
    # Main entry points
    "build_menu_index",
    "get_menu_version",
    # Builders
    "build_company_info",
    "build_ingredient_to_items",
    "build_item_descriptions",
    "build_item_keywords",
    "build_item_types_data",
    "build_modifier_categories",
    "build_neighborhood_zip_codes",
    # Preloaders
    "preload_all_ingredients",
    "preload_global_attribute_options",
    "preload_item_type_config_status",
    "preload_item_type_ingredients",
    "preload_menu_item_ingredients",
    "preload_size_prices",
]
