"""
Patterns Package.

Re-exports all public symbols from pattern submodules for convenient access.
This allows `from orderbot.tasks.parsers.patterns import X` to work for any
symbol defined in any submodule.

Submodules:
- item_actions: Replace, cancel, and modifier change request patterns
- quantity: Quantity change, duplicate, and add-more patterns
- filler: Filler word detection and stripping utilities
- config_flow: Configuration request patterns, done-ordering, configurable item detection
- status: Tax question and order status inquiry patterns
"""

# Item action patterns
from .item_actions import (
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    CHANGE_REQUEST_PATTERNS,
)

# Quantity patterns
from .quantity import (
    MAKE_IT_N_PATTERN,
    MAKE_IT_N_CONFIG_PATTERN,
    REDUCE_TO_ONE_PATTERN,
    ONE_MORE_PATTERN,
    ANOTHER_ITEM_PATTERN,
    DUPLICATE_ALL_PATTERN,
    MORE_OF_SAME_PATTERN,
    MAKE_IT_N_WITH_ITEM_PATTERN,
    ADD_MORE_PATTERN,
    ADD_N_MORE_PATTERN,
)

# Filler patterns and utilities
from .filler import (
    FILLER_WORDS_PATTERN,
    MID_SENTENCE_FILLER_PATTERN,
    strip_leading_fillers,
    strip_conversational_fillers,
    ORDERING_LANGUAGE_PATTERN,
)

# Configuration flow patterns
from .config_flow import (
    CAN_YOU_MAKE_IT_PATTERN,
    parse_can_you_make_it,
    MAKE_NAMED_ITEM_PATTERN,
    parse_make_named_item,
    DONE_ORDERING_DURING_CONFIG_PATTERN,
    ADD_ITEM_DURING_CONFIG_PREFIX,
    _get_configurable_item_pattern,
    warmup_patterns,
)

# Status/inquiry patterns
from .status import (
    TAX_QUESTION_PATTERN,
    ORDER_STATUS_PATTERN,
)

__all__ = [
    # Item actions
    "REPLACE_ITEM_PATTERN",
    "CANCEL_ITEM_PATTERN",
    "CHANGE_REQUEST_PATTERNS",
    # Quantity
    "MAKE_IT_N_PATTERN",
    "MAKE_IT_N_CONFIG_PATTERN",
    "REDUCE_TO_ONE_PATTERN",
    "ONE_MORE_PATTERN",
    "ANOTHER_ITEM_PATTERN",
    "DUPLICATE_ALL_PATTERN",
    "MORE_OF_SAME_PATTERN",
    "MAKE_IT_N_WITH_ITEM_PATTERN",
    "ADD_MORE_PATTERN",
    "ADD_N_MORE_PATTERN",
    # Filler
    "FILLER_WORDS_PATTERN",
    "MID_SENTENCE_FILLER_PATTERN",
    "strip_leading_fillers",
    "strip_conversational_fillers",
    "ORDERING_LANGUAGE_PATTERN",
    # Config flow
    "CAN_YOU_MAKE_IT_PATTERN",
    "parse_can_you_make_it",
    "MAKE_NAMED_ITEM_PATTERN",
    "parse_make_named_item",
    "DONE_ORDERING_DURING_CONFIG_PATTERN",
    "ADD_ITEM_DURING_CONFIG_PREFIX",
    "_get_configurable_item_pattern",
    "warmup_patterns",
    # Status
    "TAX_QUESTION_PATTERN",
    "ORDER_STATUS_PATTERN",
]
