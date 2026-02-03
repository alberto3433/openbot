"""
Configuration for realistic order scenario tests.

These tests are NOT part of the default test suite.
Run with: pytest tests/scenarios/ -v

They inherit fixtures from the parent tests/conftest.py.
"""

import pytest


# The menu_cache_loaded fixture is inherited from tests/conftest.py
# which is autouse=True, so it will automatically load for these tests


@pytest.fixture(autouse=True)
def ensure_menu_loaded(menu_cache_loaded):
    """Ensure menu cache is loaded for all scenario tests."""
    # The menu_cache_loaded fixture from parent conftest does the work
    pass
