"""
Services Package for Orderbot
=================================

This package contains service modules that encapsulate business logic and
infrastructure concerns.

Available Services:
-------------------
- **session**: Session cache management with database persistence
- **order**: Order persistence functions (pending and confirmed orders)
- **helpers**: Shared utility functions used across routes

Usage:
------
Import services directly from submodules:

    from orderbot.services.session import get_or_create_session, save_session
    from orderbot.services.order import persist_confirmed_order
    from orderbot.services.helpers import get_or_create_company
"""
