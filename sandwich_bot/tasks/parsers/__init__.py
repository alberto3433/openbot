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
    parse_toasted_deterministic,
    parse_hot_iced_deterministic,
)

from .deterministic import (
    # Compiled regex patterns
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    BAGEL_QUANTITY_PATTERN,
    SIMPLE_BAGEL_PATTERN,
    _get_coffee_order_pattern,
    # Modifier extraction
    extract_modifiers_from_input,
    extract_coffee_modifiers_from_input,
    extract_special_instructions_from_input,
    extract_notes_from_input,  # Backwards compatibility alias
    # Internal helpers (needed by state_machine)
    _extract_quantity,
    _extract_bagel_type,
    _extract_toasted,
    _build_spread_types_from_menu,
    _extract_spread,
    _extract_side_item,
    _extract_menu_item_from_text,
    _parse_speed_menu_bagel_deterministic,
    _parse_coffee_deterministic,
    _parse_soda_deterministic,
    _parse_price_inquiry_deterministic,
    _parse_recommendation_inquiry,
    _parse_store_info_inquiry,
    _parse_item_description_inquiry,
    _parse_multi_item_order,
    parse_open_input_deterministic,
)

from .llm_parsers import (
    get_instructor_client,
    parse_side_choice,
    parse_bagel_choice,
    parse_multi_bagel_choice,
    parse_multi_toasted,
    parse_multi_spread,
    parse_spread_choice,
    parse_toasted_choice,
    parse_coffee_size,
    parse_coffee_style,
    parse_by_pound_category,
    parse_open_input,
    parse_delivery_choice,
    parse_name,
    parse_confirmation,
    parse_payment_method,
    parse_email,
    parse_phone,
)

from .constants import (
    # Drink categories
    get_coffee_types,
    is_soda_drink,
    get_soda_types,
    # Number mapping
    WORD_TO_NUM,
    # Bagel and spread types (loaded from database via dynamic functions)
    get_bagel_types,
    get_spreads,
    get_spread_types,
    get_bagel_spreads,
    # Modifier classification (computed from bagel/spread types)
    get_bagel_only_types,
    get_spread_only_types,
    get_ambiguous_modifiers,
    # Speed menu items (loaded from database via dynamic function)
    get_speed_menu_bagels,
    # By-the-pound items and categories (loaded from database via dynamic functions)
    get_by_pound_items,
    find_by_pound_item,
    get_by_pound_category_names,
    # Bagel modifiers (loaded from database via dynamic functions)
    get_proteins,
    get_cheeses,
    get_toppings,
    # Note: MODIFIER_NORMALIZATIONS was moved to the database - use menu_cache.normalize_modifier()
    # Regex patterns - basic
    QUALIFIER_PATTERNS,
    GREETING_PATTERNS,
    DONE_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    # Menu item recognition
    get_known_menu_items,
    # Note: NO_THE_PREFIX_ITEMS and MENU_ITEM_CANONICAL_NAMES were moved to the database
    # - use menu_cache.resolve_menu_item_alias() instead
    # Coffee typos
    COFFEE_TYPO_MAP,
    # Price inquiry patterns
    PRICE_INQUIRY_PATTERNS,
    MENU_CATEGORY_KEYWORDS,
    # Store info patterns
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    NYC_NEIGHBORHOOD_ZIPS,
    # Recommendation patterns
    RECOMMENDATION_PATTERNS,
    # Item description patterns
    ITEM_DESCRIPTION_PATTERNS,
    # String normalization utilities
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
    "parse_toasted_deterministic",
    "parse_hot_iced_deterministic",
    # Deterministic parsers - Compiled patterns
    "REPLACE_ITEM_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "TAX_QUESTION_PATTERN",
    "ORDER_STATUS_PATTERN",
    "BAGEL_QUANTITY_PATTERN",
    "SIMPLE_BAGEL_PATTERN",
    "_get_coffee_order_pattern",
    # Deterministic parsers - Modifier extraction
    "extract_modifiers_from_input",
    "extract_coffee_modifiers_from_input",
    "extract_special_instructions_from_input",
    "extract_notes_from_input",  # Backwards compatibility alias
    # Deterministic parsers - Internal helpers
    "_extract_quantity",
    "_extract_bagel_type",
    "_extract_toasted",
    "_build_spread_types_from_menu",
    "_extract_spread",
    "_extract_side_item",
    "_extract_menu_item_from_text",
    "_parse_speed_menu_bagel_deterministic",
    "_parse_coffee_deterministic",
    "_parse_soda_deterministic",
    "_parse_price_inquiry_deterministic",
    "_parse_recommendation_inquiry",
    "_parse_store_info_inquiry",
    "_parse_item_description_inquiry",
    "_parse_multi_item_order",
    "parse_open_input_deterministic",
    # LLM parsers
    "get_instructor_client",
    "parse_side_choice",
    "parse_bagel_choice",
    "parse_multi_bagel_choice",
    "parse_multi_toasted",
    "parse_multi_spread",
    "parse_spread_choice",
    "parse_toasted_choice",
    "parse_coffee_size",
    "parse_coffee_style",
    "parse_by_pound_category",
    "parse_open_input",
    "parse_delivery_choice",
    "parse_name",
    "parse_confirmation",
    "parse_payment_method",
    "parse_email",
    "parse_phone",
    # Constants - Drink categories
    "get_coffee_types",
    "is_soda_drink",
    "get_soda_types",
    # Constants - Number mapping
    "WORD_TO_NUM",
    # Constants - Bagel and spread types (loaded from database via dynamic functions)
    "get_bagel_types",
    "get_spreads",
    "get_spread_types",
    "get_bagel_spreads",
    # Modifier classification (computed from bagel/spread types)
    "get_bagel_only_types",
    "get_spread_only_types",
    "get_ambiguous_modifiers",
    # Constants - Speed menu items (loaded from database via dynamic function)
    "get_speed_menu_bagels",
    # Constants - By-the-pound items and categories (loaded from database via dynamic functions)
    "get_by_pound_items",
    "find_by_pound_item",
    "get_by_pound_category_names",
    # Constants - Bagel modifiers (loaded from database via dynamic functions)
    "get_proteins",
    "get_cheeses",
    "get_toppings",
    # Note: MODIFIER_NORMALIZATIONS was moved to the database - use menu_cache.normalize_modifier()
    # Constants - Regex patterns (basic)
    "QUALIFIER_PATTERNS",
    "GREETING_PATTERNS",
    "DONE_PATTERNS",
    "REPEAT_ORDER_PATTERNS",
    # Constants - Menu item recognition
    "get_known_menu_items",
    # Note: NO_THE_PREFIX_ITEMS and MENU_ITEM_CANONICAL_NAMES were moved to the database
    # - use menu_cache.resolve_menu_item_alias() instead
    # Constants - Coffee typos
    "COFFEE_TYPO_MAP",
    # Constants - Price inquiry patterns
    "PRICE_INQUIRY_PATTERNS",
    "MENU_CATEGORY_KEYWORDS",
    # Constants - Store info patterns
    "STORE_HOURS_PATTERNS",
    "STORE_LOCATION_PATTERNS",
    "DELIVERY_ZONE_PATTERNS",
    "NYC_NEIGHBORHOOD_ZIPS",
    # Constants - Recommendation patterns
    "RECOMMENDATION_PATTERNS",
    # Constants - Item description patterns
    "ITEM_DESCRIPTION_PATTERNS",
    # String normalization utilities
    "normalize_for_match",
]
