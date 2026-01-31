"""
Inquiry Parsing Functions for Deterministic Parsing.

This module re-exports from the inquiry package for backward compatibility.
New code should import directly from orderbot.tasks.parsers.deterministic.inquiry.

This module contains functions for parsing non-order queries including:
- Price inquiries
- Menu category queries
- Recommendation questions
- Store information inquiries (hours, location, delivery zone)
- Item description inquiries
- Modifier/add-on inquiries
- Ingredient-based menu search
"""

# Re-export everything from the inquiry package
from .inquiry import (
    get_order_signals,
    parse_ingredient_search,
    parse_item_description_inquiry,
    parse_menu_query,
    parse_modifier_inquiry,
    parse_more_menu_items,
    parse_price_inquiry,
    parse_recommendation_inquiry,
    parse_store_info_inquiry,
)

# Backward compatibility aliases (old names with underscore prefix)
_parse_price_inquiry_deterministic = parse_price_inquiry
_parse_menu_query_deterministic = parse_menu_query
_parse_recommendation_inquiry = parse_recommendation_inquiry
_parse_store_info_inquiry = parse_store_info_inquiry
_parse_item_description_inquiry = parse_item_description_inquiry
_parse_modifier_inquiry = parse_modifier_inquiry
_parse_more_menu_items = parse_more_menu_items
_parse_ingredient_search = parse_ingredient_search
_get_order_signals = get_order_signals

__all__ = [
    # New names (without underscore)
    "parse_price_inquiry",
    "parse_menu_query",
    "parse_recommendation_inquiry",
    "parse_store_info_inquiry",
    "parse_item_description_inquiry",
    "parse_modifier_inquiry",
    "parse_more_menu_items",
    "parse_ingredient_search",
    "get_order_signals",
    # Backward compatibility (old names with underscore)
    "_parse_price_inquiry_deterministic",
    "_parse_menu_query_deterministic",
    "_parse_recommendation_inquiry",
    "_parse_store_info_inquiry",
    "_parse_item_description_inquiry",
    "_parse_modifier_inquiry",
    "_parse_more_menu_items",
    "_parse_ingredient_search",
    "_get_order_signals",
]
