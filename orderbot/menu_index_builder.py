"""
Menu Index Builder.

This module re-exports from the menu_index package for backward compatibility.
New code should import directly from orderbot.menu_index.

Build a rich, LLM-friendly menu JSON structure from database data.
"""

# Re-export main entry points
from .menu_index import build_menu_index, get_menu_version

# Re-export preloaders with original underscore-prefixed names for backward compatibility
from .menu_index.preloaders import (
    preload_all_ingredients as _preload_all_ingredients,
    preload_global_attribute_options as _preload_global_attribute_options,
    preload_item_type_config_status as _preload_item_type_config_status,
    preload_item_type_ingredients as _preload_item_type_ingredients,
    preload_menu_item_ingredients as _preload_menu_item_ingredients,
    preload_size_prices as _preload_size_prices,
)

# Re-export builders with original underscore-prefixed names for backward compatibility
from .menu_index.builders import (
    build_company_info as _build_company_info,
    build_ingredient_to_items as _build_ingredient_to_items,
    build_item_descriptions as _build_item_descriptions,
    build_item_keywords as _build_item_keywords,
    build_item_types_data as _build_item_types_data,
    build_modifier_categories as _build_modifier_categories,
    build_neighborhood_zip_codes as _build_neighborhood_zip_codes,
)

__all__ = [
    # Main entry points
    "build_menu_index",
    "get_menu_version",
    # Backward compatibility (underscore-prefixed)
    "_preload_all_ingredients",
    "_preload_global_attribute_options",
    "_preload_item_type_config_status",
    "_preload_item_type_ingredients",
    "_preload_menu_item_ingredients",
    "_preload_size_prices",
    "_build_company_info",
    "_build_ingredient_to_items",
    "_build_item_descriptions",
    "_build_item_keywords",
    "_build_item_types_data",
    "_build_modifier_categories",
    "_build_neighborhood_zip_codes",
]
