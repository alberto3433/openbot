"""
Parsers Package.

This package contains all parsing functions and constants used by the
state machine for interpreting user input.

Main Entry Points:
    parse_open_input_deterministic() - Primary parser for user input (regex-based, fast)
    parse_open_input()               - LLM fallback parser (slower, handles ambiguity)

Validators:
    validate_email_address()         - Email format validation
    validate_phone_number()          - Phone number validation
    extract_zip_code()               - ZIP code extraction
    validate_delivery_zip_code()     - Delivery zone validation

Patterns (compiled regex):
    ORDER_STATUS_PATTERN             - Detect "what's in my order" requests
    CANCEL_ITEM_PATTERN              - Detect item cancellation requests
    TAX_QUESTION_PATTERN             - Detect tax questions
    ORDERING_LANGUAGE_PATTERN        - Detect ordering phrases

Internal parsers (prefixed with _):
    These are used internally by parse_open_input_deterministic and
    are exported for testing purposes.

Usage:
    from orderbot.tasks.parsers import parse_open_input_deterministic
    result = parse_open_input_deterministic(user_input, menu_data)
"""

from .validators import (
    validate_email_address,
    validate_phone_number,
    extract_zip_code,
    validate_delivery_zip_code,
)

from .deterministic import (
    CANCEL_ITEM_PATTERN,
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
    _get_configurable_item_pattern,
    ORDERING_LANGUAGE_PATTERN,
    extract_special_instructions_from_input,
    _parse_configurable_item,
    _parse_simple_item_deterministic,
    parse_price_inquiry,
    parse_recommendation_inquiry,
    parse_store_info_inquiry,
    parse_item_description_inquiry,
    _parse_multi_item_order,
    parse_open_input_deterministic,
    _extract_quantity,
    strip_conversational_fillers,
)

from .llm_parsers import (
    parse_side_choice,
    parse_open_input,
    parse_confirmation,
)

from .constants import (
    WORD_TO_NUM,
)

from ..normalization import normalize_for_match

__all__ = [
    # === Main Entry Points ===
    "parse_open_input_deterministic",  # Primary parser (fast, regex-based)
    "parse_open_input",                # LLM fallback parser
    "parse_confirmation",              # Confirmation parsing
    "parse_side_choice",               # Side choice parsing

    # === Validators ===
    "validate_email_address",
    "validate_phone_number",
    "extract_zip_code",
    "validate_delivery_zip_code",

    # === Compiled Patterns ===
    "ORDER_STATUS_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "TAX_QUESTION_PATTERN",
    "ORDERING_LANGUAGE_PATTERN",
    "_get_configurable_item_pattern",  # Dynamic pattern builder

    # === Extractors ===
    "extract_special_instructions_from_input",
    "_extract_quantity",

    # === Internal Parsers (exported for testing) ===
    "_parse_configurable_item",
    "_parse_simple_item_deterministic",
    "parse_price_inquiry",
    "parse_recommendation_inquiry",
    "parse_store_info_inquiry",
    "parse_item_description_inquiry",
    "_parse_multi_item_order",

    # === Constants ===
    "WORD_TO_NUM",
    "normalize_for_match",

    # === Pattern Utilities ===
    "strip_conversational_fillers",
]
