"""
Custom exceptions for the orderbot application.

These exceptions provide clear, actionable error messages when
configuration or data loading issues occur. Domain exceptions
(OrderBotError hierarchy) replace raw HTTPException usage in business
logic, letting the HTTP layer map them to appropriate status codes.
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


# Exception tuple for catching transient errors from notification services
# (email, SMS, payment webhooks). These are non-fatal — the order proceeds
# even if the notification fails.
NOTIFICATION_ERRORS = (
    ImportError, ConnectionError, TimeoutError, OSError, ValueError, KeyError,
)


# =============================================================================
# Domain Exceptions (mapped to HTTP status codes in main.py)
# =============================================================================

class OrderBotError(Exception):
    """Base exception for all Orderbot domain errors."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class ResourceNotFoundError(OrderBotError):
    """Raised when a requested resource does not exist."""
    pass


class ValidationError(OrderBotError):
    """Raised when input fails business-rule validation (e.g., duplicate slug)."""
    pass


class ReferentialIntegrityError(OrderBotError):
    """Raised when an operation would violate referential integrity."""
    pass
