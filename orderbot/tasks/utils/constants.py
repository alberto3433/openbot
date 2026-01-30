"""
Shared Constants for Order Tasks.

This module contains constants used across multiple task handlers for
attribute processing, price calculations, and data filtering.
"""

# =============================================================================
# Attribute Value Filtering
# =============================================================================

# Suffixes indicating metadata/computed fields that should be skipped when
# processing attribute values (e.g., "bread_price", "size_upcharge")
ATTR_METADATA_SUFFIXES = ("_price", "_upcharge", "_choice")

# Prefix for pending/temporary fields that should be skipped
ATTR_PENDING_PREFIX = "pending_"

# =============================================================================
# Price Metadata
# =============================================================================

# Suffixes used to store price metadata alongside attribute values
# Used when checking if a key is price-related metadata
PRICE_SUFFIXES = ("_price", "_upcharge")


def is_price_metadata_key(key: str) -> bool:
    """Check if a key is price-related metadata (ends with _price or _upcharge)."""
    return any(key.endswith(suffix) for suffix in PRICE_SUFFIXES)


def is_attr_metadata_key(key: str) -> bool:
    """Check if a key is attribute metadata that should be skipped in processing."""
    if key.startswith(ATTR_PENDING_PREFIX):
        return True
    return any(key.endswith(suffix) for suffix in ATTR_METADATA_SUFFIXES)
