"""
Test Helpers Package.

This package contains helper functions for tests. These are domain-specific
utilities that encode knowledge about specific menu items, categories, etc.

IMPORTANT: These helpers are ONLY for tests. They must NOT be imported
by any code in orderbot/ - production code must be data-driven.
"""

from .menu_helpers import test_is_soda_drink

__all__ = [
    "test_is_soda_drink",
]
