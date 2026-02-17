"""
Shared Pure Constants for Order Tasks.

This module contains constants that are needed by multiple modules across the
tasks package. It is intentionally kept free of any project imports to break
circular dependency chains.

Previously these constants were duplicated (e.g., ARTICLES in normalization.py
and parsers/constants.py) or defined in cache/base.py and re-exported through
parsers/constants.py. Consolidating them here allows every module to import
from a single, dependency-free location.

Moved here from:
- orderbot/tasks/normalization.py (local _ARTICLES, _ORDERING_PREFIXES, _POLITENESS_WORDS)
- orderbot/tasks/parsers/constants.py (ARTICLES, ORDERING_PREFIXES, POLITENESS_WORDS)
- orderbot/cache/base.py (SKIP_WORDS_BASIC, SKIP_WORDS_CONJUNCTIONS, SKIP_WORDS_PREPOSITIONS)
"""

# =============================================================================
# Articles and Connectors
# =============================================================================

# Canonical article set - used for stripping leading/trailing articles
ARTICLES = frozenset({'the', 'a', 'an', 'some'})

# Connectors between items or modifiers
CONNECTORS = frozenset({'and', 'or', 'with', 'plus'})

# Prepositions commonly appearing in food orders
PREPOSITIONS = frozenset({'on', 'in', 'to', 'of', 'for'})

# =============================================================================
# Ordering Prefixes
# =============================================================================

# Phrases that begin orders but don't add meaning
ORDERING_PREFIXES = frozenset({
    "i want", "i'd like", "i need", "i'll have", "i'll take",
    "can i get", "can i have", "could i get", "could i have",
    "give me", "gimme", "get me", "make it", "let's go with", "let's do",
    "just", "some",
})

# =============================================================================
# Politeness Words
# =============================================================================

# Strip anywhere in input
POLITENESS_WORDS = frozenset({'please', 'thanks', 'thank you', 'thx'})

# =============================================================================
# Basic Skip Words
# =============================================================================
# Minimal skip-word sets for text processing. Larger, context-specific sets
# are built in parsers/constants.py by combining these with additional words.

SKIP_WORDS_BASIC = frozenset({'the', 'a', 'an'})
SKIP_WORDS_CONJUNCTIONS = frozenset({'and', 'or', 'with'})
SKIP_WORDS_PREPOSITIONS = frozenset({'on', 'in', 'to', 'of'})

# =============================================================================
# Attribute Value Metadata
# =============================================================================
# Constants and helpers for identifying metadata keys in attribute_values dicts.
# Moved here from utils/constants.py so that models/utilities.py can import
# without triggering the utils/__init__.py package (which creates a circular chain).

# Suffixes indicating metadata/computed fields that should be skipped when
# processing attribute values (e.g., "bread_price", "size_upcharge")
ATTR_METADATA_SUFFIXES = ("_price", "_upcharge", "_choice")

# Prefix for pending/temporary fields that should be skipped
ATTR_PENDING_PREFIX = "pending_"

# Suffixes used to store price metadata alongside attribute values
PRICE_SUFFIXES = ("_price", "_upcharge")


def is_price_metadata_key(key: str) -> bool:
    """Check if a key is price-related metadata (ends with _price or _upcharge)."""
    return any(key.endswith(suffix) for suffix in PRICE_SUFFIXES)


def is_attr_metadata_key(key: str) -> bool:
    """Check if a key is attribute metadata that should be skipped in processing."""
    if key.startswith(ATTR_PENDING_PREFIX):
        return True
    return any(key.endswith(suffix) for suffix in ATTR_METADATA_SUFFIXES)
