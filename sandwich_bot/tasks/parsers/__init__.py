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
)

from .deterministic import (
    # Compiled regex patterns
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    BAGEL_QUANTITY_PATTERN,
    SIMPLE_BAGEL_PATTERN,
    COFFEE_ORDER_PATTERN,
    # Modifier extraction
    extract_modifiers_from_input,
    extract_coffee_modifiers_from_input,
    extract_notes_from_input,
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
    SODA_DRINK_TYPES,
    COFFEE_BEVERAGE_TYPES,
    is_soda_drink,
    # Number mapping
    WORD_TO_NUM,
    # Bagel and spread types
    BAGEL_TYPES,
    SPREADS,
    SPREAD_TYPES,
    # Speed menu items
    SPEED_MENU_BAGELS,
    # By-the-pound items and prices
    BY_POUND_ITEMS,
    BY_POUND_CATEGORY_NAMES,
    BY_POUND_PRICES,
    # Bagel modifiers
    BAGEL_PROTEINS,
    BAGEL_CHEESES,
    BAGEL_TOPPINGS,
    BAGEL_SPREADS,
    MODIFIER_NORMALIZATIONS,
    # Regex patterns - basic
    QUALIFIER_PATTERNS,
    GREETING_PATTERNS,
    DONE_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    # Side items
    SIDE_ITEM_MAP,
    SIDE_ITEM_TYPES,
    # Menu item recognition
    KNOWN_MENU_ITEMS,
    NO_THE_PREFIX_ITEMS,
    MENU_ITEM_CANONICAL_NAMES,
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
)

__all__ = [
    # Validators
    "validate_email_address",
    "validate_phone_number",
    "extract_zip_code",
    "validate_delivery_zip_code",
    # Deterministic parsers - Compiled patterns
    "REPLACE_ITEM_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "TAX_QUESTION_PATTERN",
    "ORDER_STATUS_PATTERN",
    "BAGEL_QUANTITY_PATTERN",
    "SIMPLE_BAGEL_PATTERN",
    "COFFEE_ORDER_PATTERN",
    # Deterministic parsers - Modifier extraction
    "extract_modifiers_from_input",
    "extract_coffee_modifiers_from_input",
    "extract_notes_from_input",
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
    "SODA_DRINK_TYPES",
    "COFFEE_BEVERAGE_TYPES",
    "is_soda_drink",
    # Constants - Number mapping
    "WORD_TO_NUM",
    # Constants - Bagel and spread types
    "BAGEL_TYPES",
    "SPREADS",
    "SPREAD_TYPES",
    # Constants - Speed menu items
    "SPEED_MENU_BAGELS",
    # Constants - By-the-pound items and prices
    "BY_POUND_ITEMS",
    "BY_POUND_CATEGORY_NAMES",
    "BY_POUND_PRICES",
    # Constants - Bagel modifiers
    "BAGEL_PROTEINS",
    "BAGEL_CHEESES",
    "BAGEL_TOPPINGS",
    "BAGEL_SPREADS",
    "MODIFIER_NORMALIZATIONS",
    # Constants - Regex patterns (basic)
    "QUALIFIER_PATTERNS",
    "GREETING_PATTERNS",
    "DONE_PATTERNS",
    "REPEAT_ORDER_PATTERNS",
    # Constants - Side items
    "SIDE_ITEM_MAP",
    "SIDE_ITEM_TYPES",
    # Constants - Menu item recognition
    "KNOWN_MENU_ITEMS",
    "NO_THE_PREFIX_ITEMS",
    "MENU_ITEM_CANONICAL_NAMES",
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
]
