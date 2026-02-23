"""Order Management Patterns - store change, order type change."""

import re

STORE_CHANGE_PATTERN = re.compile(
    r'\b(?:change|switch|update)\s+store\b',
    re.IGNORECASE,
)

ORDER_TYPE_CHANGE_PATTERN = re.compile(
    r'(?:change|switch|make)\s+(?:it|that|the\s+order)?\s*(?:to|for)\s+'
    r'(delivery|deliver(?:ed)?|pickup|pick\s*up)',
    re.IGNORECASE,
)
