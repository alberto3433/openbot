"""
Parsers Package.

This package contains all parsing functions and constants used by the
state machine for interpreting user input.

Exports:
- Validators: Email, phone, ZIP code validation functions
- Constants: Menu items, regex patterns, price data, modifier lists
- Deterministic Parsers: Regex-based parsing functions
- LLM Parsers: OpenAI/instructor-based parsing functions
"""

from .validators import (
    validate_email_address,
    validate_phone_number,
    extract_zip_code,
    validate_delivery_zip_code,
    # Deterministic yes/no parsing
    parse_yes_no_deterministic,
    # Note: parse_toasted_deterministic was removed - toasted preference is now
    # parsed via data-driven boolean attribute lookup. See deterministic.py.
)

from .deterministic import (
    # Compiled regex patterns
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    # Unified data-driven pattern for detecting new item orders
    _get_configurable_item_pattern,
    ORDERING_LANGUAGE_PATTERN,
    # Attribute/modifier extraction (data-driven)
    extract_attribute_values,  # Generic data-driven extractor returning dict
    extract_special_instructions_from_input,
    extract_notes_from_input,  # Backwards compatibility alias
    # Generic item builder
    build_parsed_item,
    # Internal helpers (needed by state_machine)
    _parse_configurable_item,
    _parse_soda_deterministic,
    _parse_price_inquiry_deterministic,
    _parse_recommendation_inquiry,
    _parse_store_info_inquiry,
    _parse_item_description_inquiry,
    _parse_multi_item_order,
    parse_open_input_deterministic,
    # Internal helpers (used by tests)
    _extract_quantity,
    _extract_toasted,
    _extract_spread,
)

from .llm_parsers import (
    get_instructor_client,
    parse_side_choice,
    parse_open_input,
    parse_delivery_choice,
    parse_name,
    parse_confirmation,
    parse_payment_method,
    parse_email,
    parse_phone,
)

from .constants import (
    # Number mapping
    WORD_TO_NUM,
    # Signature items (loaded from database via dynamic function)
    get_signature_item_aliases,
    # Generic unit type item lookup (data-driven, replaces find_by_pound_item)
    find_item_by_unit_type,
    # Legacy alias for backward compatibility (DEPRECATED: use find_item_by_unit_type instead)
    find_by_pound_item,
    # Note: get_spreads(), get_spread_types(), get_bagel_spreads() were removed - dead code
    # - use menu_cache.get_global_attribute_options("spread") instead
    # Note: get_by_pound_items(), get_by_pound_category_names(), find_by_pound_item() were removed
    # - use menu_cache.get_menu_items_by_unit_type() or find_item_by_unit_type() instead
    # Note: get_proteins(), get_cheeses(), get_toppings() were removed
    # - use menu_cache.get_ingredients("protein"), etc. instead
    # Note: MODIFIER_NORMALIZATIONS was moved to the database - use menu_cache.normalize_modifier()
    # Regex patterns - basic
    QUALIFIER_PATTERNS,
    # Note: GREETING_PATTERNS and DONE_PATTERNS moved to database
    # - use menu_cache.is_greeting() / menu_cache.is_done() instead
    REPEAT_ORDER_PATTERNS,
    # Menu item recognition
    get_known_menu_items,
    # Note: NO_THE_PREFIX_ITEMS and MENU_ITEM_CANONICAL_NAMES were moved to the database
    # - use menu_cache.resolve_menu_item_alias() instead
    # Note: COFFEE_TYPO_MAP was moved to the database as aliases on coffee items
    # - see migration d4e5f6g7h8i9_add_coffee_typo_aliases.py
    # Note: MENU_CATEGORY_KEYWORDS was moved to the database
    # - use menu_cache.get_category_keyword_mapping() instead
    # - see migration g7h8i9j0k1l2_add_category_keywords_to_item_types.py
    # Price inquiry patterns
    PRICE_INQUIRY_PATTERNS,
    # Store info patterns
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    # Note: NYC_NEIGHBORHOOD_ZIPS moved to database - use menu_data["neighborhood_zip_codes"]
    # Recommendation patterns
    RECOMMENDATION_PATTERNS,
    RECOMMENDATION_GENERAL_PATTERNS,
    RECOMMENDATION_TERM_PATTERNS,
    # Item description patterns
    ITEM_DESCRIPTION_PATTERNS,
    # String normalization utilities
    clean_extracted_text,
    normalize_for_match,
)

__all__ = [
    # Validators
    "validate_email_address",
    "validate_phone_number",
    "extract_zip_code",
    "validate_delivery_zip_code",
    # Deterministic yes/no parsing
    "parse_yes_no_deterministic",
    # Note: parse_toasted_deterministic removed - now data-driven via _extract_toasted
    # Deterministic parsers - Compiled patterns
    "REPLACE_ITEM_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "TAX_QUESTION_PATTERN",
    "ORDER_STATUS_PATTERN",
    # Unified data-driven pattern for detecting new item orders
    "_get_configurable_item_pattern",
    "ORDERING_LANGUAGE_PATTERN",
    # Deterministic parsers - Attribute/modifier extraction (data-driven)
    "extract_attribute_values",  # Generic data-driven extractor returning dict
    "extract_special_instructions_from_input",
    "extract_notes_from_input",  # Backwards compatibility alias
    # Generic item builder
    "build_parsed_item",
    # Deterministic parsers - Internal helpers
    "_parse_configurable_item",
    "_parse_soda_deterministic",
    "_parse_price_inquiry_deterministic",
    "_parse_recommendation_inquiry",
    "_parse_store_info_inquiry",
    "_parse_item_description_inquiry",
    "_parse_multi_item_order",
    "parse_open_input_deterministic",
    # Internal helpers (used by tests)
    "_extract_quantity",
    "_extract_toasted",
    "_extract_spread",
    # LLM parsers
    "get_instructor_client",
    "parse_side_choice",
    "parse_open_input",
    "parse_delivery_choice",
    "parse_name",
    "parse_confirmation",
    "parse_payment_method",
    "parse_email",
    "parse_phone",
    # Constants - Number mapping
    "WORD_TO_NUM",
    # Constants - Signature items (loaded from database via dynamic function)
    "get_signature_item_aliases",
    # Constants - Generic unit type item lookup (data-driven)
    "find_item_by_unit_type",
    # Constants - Legacy alias (DEPRECATED: use find_item_by_unit_type instead)
    "find_by_pound_item",
    # Note: get_spreads(), get_spread_types(), get_bagel_spreads() were removed - dead code
    # Note: get_by_pound_items(), get_by_pound_category_names(), find_by_pound_item() were removed
    # Note: get_proteins(), get_cheeses(), get_toppings() were removed - dead code
    # - use menu_cache or find_item_by_unit_type() instead for all of these
    # Note: MODIFIER_NORMALIZATIONS was moved to the database - use menu_cache.normalize_modifier()
    # Constants - Regex patterns (basic)
    "QUALIFIER_PATTERNS",
    # Note: GREETING_PATTERNS and DONE_PATTERNS moved to database
    # - use menu_cache.is_greeting() / menu_cache.is_done() instead
    "REPEAT_ORDER_PATTERNS",
    # Constants - Menu item recognition
    "get_known_menu_items",
    # Note: NO_THE_PREFIX_ITEMS and MENU_ITEM_CANONICAL_NAMES were moved to the database
    # - use menu_cache.resolve_menu_item_alias() instead
    # Note: COFFEE_TYPO_MAP was moved to the database as aliases on coffee items
    # Note: MENU_CATEGORY_KEYWORDS was moved to the database
    # - use menu_cache.get_category_keyword_mapping() instead
    # Constants - Price inquiry patterns
    "PRICE_INQUIRY_PATTERNS",
    # Constants - Store info patterns
    "STORE_HOURS_PATTERNS",
    "STORE_LOCATION_PATTERNS",
    "DELIVERY_ZONE_PATTERNS",
    # Note: NYC_NEIGHBORHOOD_ZIPS moved to database - use menu_data["neighborhood_zip_codes"]
    # Constants - Recommendation patterns
    "RECOMMENDATION_PATTERNS",
    "RECOMMENDATION_GENERAL_PATTERNS",
    "RECOMMENDATION_TERM_PATTERNS",
    # Constants - Item description patterns
    "ITEM_DESCRIPTION_PATTERNS",
    # String normalization utilities
    "clean_extracted_text",
    "normalize_for_match",
]
