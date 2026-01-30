"""
Utility classes extracted from handler modules.

This package contains focused, reusable utilities:
- OptionMatcher: Unified option matching with multi-phase algorithm
- InputNormalizer: Text normalization for option matching
- format_english_list: Format lists as human-readable English
- Cache helpers: Validation utilities for menu data access
"""

from .option_matcher import OptionMatcher
from .input_normalizer import InputNormalizer
from .text import format_english_list
from .cache_helpers import (
    ensure_menu_data_loaded,
    ensure_item_types_loaded,
    get_item_type_config,
    get_item_type_attributes,
)

__all__ = [
    "OptionMatcher",
    "InputNormalizer",
    "format_english_list",
    "ensure_menu_data_loaded",
    "ensure_item_types_loaded",
    "get_item_type_config",
    "get_item_type_attributes",
]
