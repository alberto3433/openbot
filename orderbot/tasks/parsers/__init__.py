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
    parse_yes_no_deterministic,
)

from .deterministic import (
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    _get_configurable_item_pattern,
    ORDERING_LANGUAGE_PATTERN,
    extract_attribute_values,
    extract_special_instructions_from_input,
    build_parsed_item,
    _parse_configurable_item,
    _parse_soda_deterministic,
    _parse_price_inquiry_deterministic,
    _parse_recommendation_inquiry,
    _parse_store_info_inquiry,
    _parse_item_description_inquiry,
    _parse_multi_item_order,
    parse_open_input_deterministic,
    _extract_quantity,
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
    WORD_TO_NUM,
    get_signature_item_aliases,
    find_item_by_unit_type,
    QUALIFIER_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    get_known_menu_items,
    PRICE_INQUIRY_PATTERNS,
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    RECOMMENDATION_GENERAL_PATTERNS,
    RECOMMENDATION_TERM_PATTERNS,
    ITEM_DESCRIPTION_PATTERNS,
    clean_extracted_text,
)

from ..normalization import normalize_for_match

__all__ = [
    # Validators
    "validate_email_address",
    "validate_phone_number",
    "extract_zip_code",
    "validate_delivery_zip_code",
    "parse_yes_no_deterministic",
    # Deterministic parsers - patterns
    "REPLACE_ITEM_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "TAX_QUESTION_PATTERN",
    "ORDER_STATUS_PATTERN",
    "_get_configurable_item_pattern",
    "ORDERING_LANGUAGE_PATTERN",
    # Deterministic parsers - extractors
    "extract_attribute_values",
    "extract_special_instructions_from_input",
    "build_parsed_item",
    "_parse_configurable_item",
    "_parse_soda_deterministic",
    "_parse_price_inquiry_deterministic",
    "_parse_recommendation_inquiry",
    "_parse_store_info_inquiry",
    "_parse_item_description_inquiry",
    "_parse_multi_item_order",
    "parse_open_input_deterministic",
    "_extract_quantity",
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
    # Constants
    "WORD_TO_NUM",
    "get_signature_item_aliases",
    "find_item_by_unit_type",
    "QUALIFIER_PATTERNS",
    "REPEAT_ORDER_PATTERNS",
    "get_known_menu_items",
    "PRICE_INQUIRY_PATTERNS",
    "STORE_HOURS_PATTERNS",
    "STORE_LOCATION_PATTERNS",
    "DELIVERY_ZONE_PATTERNS",
    "RECOMMENDATION_GENERAL_PATTERNS",
    "RECOMMENDATION_TERM_PATTERNS",
    "ITEM_DESCRIPTION_PATTERNS",
    "clean_extracted_text",
    "normalize_for_match",
]
