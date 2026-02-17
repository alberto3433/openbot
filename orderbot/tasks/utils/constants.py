"""
Shared Constants for Order Tasks.

This module re-exports constants from shared_constants.py for backward
compatibility. New code should import directly from shared_constants.py
when the import needs to avoid triggering package __init__.py files.

All canonical definitions now live in orderbot/tasks/shared_constants.py.
"""

from orderbot.tasks.shared_constants import (
    ATTR_METADATA_SUFFIXES,
    ATTR_PENDING_PREFIX,
    PRICE_SUFFIXES,
    is_price_metadata_key,
    is_attr_metadata_key,
)

__all__ = [
    "ATTR_METADATA_SUFFIXES",
    "ATTR_PENDING_PREFIX",
    "PRICE_SUFFIXES",
    "is_price_metadata_key",
    "is_attr_metadata_key",
]
