"""
Custom exceptions for the orderbot application.

These exceptions provide clear, actionable error messages when
configuration or data loading issues occur.
"""


class MenuDataNotLoadedError(RuntimeError):
    """
    Raised when menu data is accessed before loading or when required data is missing.

    This exception indicates a configuration problem that must be fixed:
    - The menu cache was not loaded at startup
    - Required data (ingredients, modifiers, item types) is missing from the database
    - A database migration may not have run

    The error message should include:
    1. What data was expected
    2. Where to look to fix it (which table, which column)
    3. Any relevant context (item type slug, attribute name, etc.)

    Example usage:
        if not self._is_loaded:
            raise MenuDataNotLoadedError(
                "Menu cache not loaded. Ensure menu_cache.load_from_db() "
                "is called at server startup."
            )

        if not self._proteins:
            raise MenuDataNotLoadedError(
                "No proteins found in database. "
                "Check that ingredients table has records with category='protein'."
            )
    """

    pass
