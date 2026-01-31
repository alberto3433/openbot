"""
Utility classes extracted from handler modules.

This package contains focused, reusable utilities:
- OptionMatcher: Unified option matching with multi-phase algorithm
- OptionMatchingOrchestrator: Higher-level orchestrator for option matching with disambiguation
- InputNormalizer: Text normalization for option matching
- format_english_list: Format lists as human-readable English
- Cache helpers: Validation utilities for menu data access
- Constants: Shared constants for attribute processing (import from .constants directly)
- Pricing utils: Safe pricing operations (import from .pricing_utils directly)

Note: Constants and pricing_utils are NOT re-exported here to avoid circular imports.
Import directly: from .utils.constants import PRICE_SUFFIXES
Import directly: from .utils.pricing_utils import safe_recalculate_price
"""

from .option_matcher import OptionMatcher, MultiMatchResult
from .option_matching_orchestrator import OptionMatchingOrchestrator, MatchResult
from .input_normalizer import InputNormalizer
from .text import format_english_list, format_numbered_list
from .cache_helpers import (
    ensure_menu_data_loaded,
    ensure_item_types_loaded,
    get_item_type_config,
    get_item_type_attributes,
)

# Note: constants are NOT imported here to avoid circular imports when
# models.py imports from utils.constants. Import directly instead:
# from .utils.constants import PRICE_SUFFIXES, is_price_metadata_key

__all__ = [
    "OptionMatcher",
    "MultiMatchResult",
    "OptionMatchingOrchestrator",
    "MatchResult",
    "InputNormalizer",
    "format_english_list",
    "format_numbered_list",
    "ensure_menu_data_loaded",
    "ensure_item_types_loaded",
    "get_item_type_config",
    "get_item_type_attributes",
]
