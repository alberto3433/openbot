"""
Deterministic Parser Package.

This package contains all deterministic (non-LLM) parsing functions for user input.

Modules:
- patterns: Compiled regex patterns and pattern utilities
- extraction: Attribute/modifier extraction from text
- item_parsing: Single item order parsing (configurable items, sodas, by-pound)
- inquiry: Non-order queries (price, menu, recommendations, store info)
- modification_parsing: Modifications to existing items
- tokenization: Multi-item order tokenization and parsing
- core: Main entry point orchestrating all sub-parsers
"""

# =============================================================================
# Patterns Module Exports
# =============================================================================
from ..intent_patterns import (
    # Main patterns used by state machine and handlers
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    ORDERING_LANGUAGE_PATTERN,
    MAKE_IT_N_PATTERN,
    MAKE_IT_N_CONFIG_PATTERN,
    DUPLICATE_ALL_PATTERN,
    # Internal patterns (may be used by tests)
    FILLER_WORDS_PATTERN,
    REDUCE_TO_ONE_PATTERN,
    ONE_MORE_PATTERN,
    ANOTHER_ITEM_PATTERN,
    ADD_MORE_PATTERN,
    # Pattern utilities
    strip_conversational_fillers,
    _get_configurable_item_pattern,
)

# =============================================================================
# Pipeline Module Exports (new unified API)
# =============================================================================
from .pipeline import ExtractionPipeline, get_pipeline
from .result_types import (
    TextSpan,
    QuantityResult,
    AttributeExtractionResult,
    SpecialInstructionsResult,
    ItemTypeMatch,
    UnavailableSelection,
    UnmatchedToken,
    AmbiguousSelection,
)

# =============================================================================
# Extraction Module Exports
# =============================================================================
from .extraction import (
    # Main extraction function
    extract_modifiers_with_qualifiers,
    # Internal helpers (used by tests)
    _extract_quantity,
    _extract_by_pound_info,
)
from .instructions_extraction import extract_special_instructions_from_input

# =============================================================================
# Item Parsing Module Exports
# =============================================================================
from .item_building import build_parsed_item
from .item_parsing import (
    # Item type detection
    _detect_item_type,
    _is_modifier_chain,
    _detect_configurable_item_type,
    # Main item parsers
    _parse_item_generic,
    _parse_configurable_item,
    _parse_split_quantity_items,
    # Internal helpers
    _match_menu_item_name_for_type,
)
from .simple_item_parsing import _parse_simple_item_deterministic
from .by_pound_parsing import (
    _parse_by_pound_order,
    _find_by_weight_item,
    BY_POUND_PATTERN,
)
from .split_quantity_parsing import (
    _count_split_indicators,
    _get_initial_part,
    _split_into_parts,
)

# =============================================================================
# Inquiry Parsing Module Exports
# =============================================================================
from .inquiry import (
    parse_price_inquiry,
    parse_menu_query,
    parse_signature_menu_inquiry,
    parse_recommendation_inquiry,
    parse_store_info_inquiry,
    parse_item_description_inquiry,
    parse_modifier_inquiry,
    parse_more_menu_items,
    parse_ingredient_search,
    get_order_signals,
)

# =============================================================================
# Modification Parsing Module Exports
# =============================================================================
from .modification_parsing import (
    _extract_menu_item_modifications,
    _parse_modify_existing_item,
    _parse_add_modifier_to_item,
    _extract_menu_item_from_text,
    _parse_add_more_request,
)

# =============================================================================
# Tokenization Module Exports
# =============================================================================
from .tokenization import (
    _parse_multi_item_order,
    # Internal tokenization helpers
    _extract_leading_quantity,
    _has_item_indicator,
    _is_modifier_only,
    _classify_token,
    _smart_split_and_tokenize,
    _recombine_tokens,
)

# =============================================================================
# Core Module Exports
# =============================================================================
from .core import (
    parse_open_input_deterministic,
    parse_open_input,
    _is_inline_attribute_spec_pattern,
)


# =============================================================================
# Public API
# =============================================================================
__all__ = [
    # Main entry points
    "parse_open_input_deterministic",
    "parse_open_input",
    "_is_inline_attribute_spec_pattern",
    # Pipeline (unified API)
    "ExtractionPipeline",
    "get_pipeline",
    "TextSpan",
    "QuantityResult",
    "AttributeExtractionResult",
    "SpecialInstructionsResult",
    "ItemTypeMatch",
    "UnavailableSelection",
    "UnmatchedToken",
    "AmbiguousSelection",
    # Patterns
    "REPLACE_ITEM_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "TAX_QUESTION_PATTERN",
    "ORDER_STATUS_PATTERN",
    "ORDERING_LANGUAGE_PATTERN",
    "MAKE_IT_N_PATTERN",
    "MAKE_IT_N_CONFIG_PATTERN",
    "DUPLICATE_ALL_PATTERN",
    "FILLER_WORDS_PATTERN",
    "REDUCE_TO_ONE_PATTERN",
    "ONE_MORE_PATTERN",
    "ANOTHER_ITEM_PATTERN",
    "ADD_MORE_PATTERN",
    "strip_conversational_fillers",
    "_get_configurable_item_pattern",
    # Extraction
    "extract_special_instructions_from_input",
    "extract_modifiers_with_qualifiers",
    "_extract_quantity",
    "_extract_by_pound_info",
    # Item parsing
    "build_parsed_item",
    "_detect_item_type",
    "_is_modifier_chain",
    "_detect_configurable_item_type",
    "_parse_item_generic",
    "_parse_configurable_item",
    "_parse_simple_item_deterministic",
    "_parse_split_quantity_items",
    "_parse_by_pound_order",
    "_match_menu_item_name_for_type",
    "_count_split_indicators",
    "_get_initial_part",
    "_split_into_parts",
    "_find_by_weight_item",
    "BY_POUND_PATTERN",
    # Inquiry parsing
    "parse_price_inquiry",
    "parse_menu_query",
    "parse_signature_menu_inquiry",
    "parse_recommendation_inquiry",
    "parse_store_info_inquiry",
    "parse_item_description_inquiry",
    "parse_modifier_inquiry",
    "parse_more_menu_items",
    "parse_ingredient_search",
    "get_order_signals",
    # Modification parsing
    "_extract_menu_item_modifications",
    "_parse_modify_existing_item",
    "_parse_add_modifier_to_item",
    "_extract_menu_item_from_text",
    "_parse_add_more_request",
    # Tokenization
    "_parse_multi_item_order",
    "_extract_leading_quantity",
    "_has_item_indicator",
    "_is_modifier_only",
    "_classify_token",
    "_smart_split_and_tokenize",
    "_recombine_tokens",
]
