"""
Services Package for Sandwich Bot
=================================

This package contains service modules that encapsulate business logic and
infrastructure concerns. Services are stateful or stateless components that
provide reusable functionality across the application.

Available Services:
-------------------
- **session**: Session cache management with database persistence
- **order**: Order persistence functions (pending and confirmed orders)
- **helpers**: Shared utility functions used across routes

Design Philosophy:
------------------
Services in this package follow these principles:

1. **Single Responsibility**: Each service handles one concern (sessions,
   caching, external integrations, etc.)

2. **Dependency Injection**: Services receive their dependencies (database
   sessions, configuration) rather than creating them internally.

3. **Testability**: Services are designed to be easily mocked or replaced
   in tests without modifying application code.

4. **Stateless When Possible**: Most services are stateless functions.
   When state is required (like the session cache), it's explicitly managed
   and documented.

Usage:
------
Import services directly from the package:

    from sandwich_bot.services.session import get_or_create_session, save_session
    from sandwich_bot.services.order import persist_confirmed_order
    from sandwich_bot.services.helpers import get_or_create_company

Or import the entire module:

    from sandwich_bot.services import session, order, helpers
"""

from . import session
from . import order
from . import helpers

__all__ = ["session", "order", "helpers"]
