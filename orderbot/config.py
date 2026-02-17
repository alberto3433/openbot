"""
Configuration Module for Orderbot
=====================================

This module centralizes all configuration settings, environment variables, and
constants used throughout the Orderbot application. By consolidating
configuration in one place, we achieve:

1. **Single Source of Truth**: All environment variables and defaults are defined
   here, making it easy to see what configuration options exist.

2. **Easy Environment Management**: Different environments (dev, staging, prod)
   can override settings via environment variables without code changes.

3. **Type Safety**: Configuration values are parsed and typed at module load time,
   catching configuration errors early.

Configuration Categories:
-------------------------
- **Store Configuration**: Default store IDs, store name mappings for multi-tenant
  support. Stores represent physical restaurant locations.

- **Rate Limiting**: Controls API request throttling to prevent abuse. Configurable
  per-endpoint with sensible defaults for chat interactions.

- **Session Management**: TTL and cache size settings for the in-memory session
  cache that improves performance while maintaining database persistence.

- **Input Validation**: Maximum lengths and constraints for user input to prevent
  abuse and manage LLM token usage.

- **CORS Settings**: Cross-Origin Resource Sharing configuration for frontend
  integration. Defaults allow all origins for development.

Environment Variables:
----------------------
- RATE_LIMIT_CHAT: Chat endpoint rate limit (default: "30 per minute")
- RATE_LIMIT_ENABLED: Enable/disable rate limiting (default: "true")
- SESSION_TTL_SECONDS: Session cache TTL (default: 3600)
- SESSION_MAX_CACHE_SIZE: Max cached sessions (default: 1000)
- MAX_MESSAGE_LENGTH: Max user message length (default: 2000)
- CORS_ORIGINS: Comma-separated allowed origins (default: "*")
- ADMIN_USERNAME: Admin panel username (default: "admin")
- ADMIN_PASSWORD: Admin panel password (required for admin access)

Usage:
------
    from orderbot.config import (
        DEFAULT_STORE_IDS,
        RATE_LIMIT_CHAT,
        SESSION_TTL_SECONDS,
        MAX_MESSAGE_LENGTH,
    )
"""

import os
import random

# =============================================================================
# Store Configuration
# =============================================================================
# Multi-tenant support: Each store represents a physical restaurant location.
# Orders, inventory (86'd items), and analytics are tracked per-store.

# Default store IDs used when no specific store is requested
# These are Zucker's NYC locations used as defaults
DEFAULT_STORE_IDS: list[str] = [
    "zuckers_tribeca",
    "zuckers_grandcentral",
    "zuckers_bryantpark",
]

def get_random_store_id() -> str:
    """
    Get a random store ID for session/order assignment.

    Used when a session is started without specifying a store,
    typically for testing or demo purposes.

    Returns:
        A randomly selected store ID from DEFAULT_STORE_IDS
    """
    return random.choice(DEFAULT_STORE_IDS)


# =============================================================================
# Rate Limiting Configuration
# =============================================================================
# Protects the API from abuse and manages costs (especially LLM API calls).
# Uses slowapi library with in-memory storage (use Redis for multi-worker prod).

# Rate limit format: "X per Y" where Y is second, minute, hour, or day
# Examples: "20 per minute", "100 per hour", "5 per second"
RATE_LIMIT_CHAT: str = os.getenv("RATE_LIMIT_CHAT", "30 per minute")
RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"


def get_rate_limit_chat() -> str:
    """
    Return the current chat rate limit.

    This function allows dynamic override in tests without modifying
    the module-level constant.

    Returns:
        Rate limit string in "X per Y" format
    """
    return RATE_LIMIT_CHAT


# =============================================================================
# Session Management Configuration
# =============================================================================
# The session cache improves performance by reducing database queries.
# Sessions are persisted to the database and cached in memory with TTL/LRU eviction.

# How long sessions stay in the cache before being evicted (seconds)
# Sessions are still persisted in the database and can be restored
SESSION_TTL_SECONDS: int = int(os.getenv("SESSION_TTL_SECONDS", "3600"))  # 1 hour

# Maximum number of sessions to keep in memory
# When exceeded, oldest sessions (by last access) are evicted
SESSION_MAX_CACHE_SIZE: int = int(os.getenv("SESSION_MAX_CACHE_SIZE", "1000"))


# =============================================================================
# Input Validation Configuration
# =============================================================================
# Constraints on user input to prevent abuse and manage LLM token costs.

# Maximum allowed message length in characters
# Prevents excessive LLM token usage from very long messages
MAX_MESSAGE_LENGTH: int = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))


# =============================================================================
# CORS Configuration
# =============================================================================
# Cross-Origin Resource Sharing settings for frontend integration.
# In production, restrict to specific domains for security.

# Parse CORS origins from environment variable
# Format: comma-separated list of origins, e.g., "https://myshop.com,https://admin.myshop.com"
# Default "*" allows all origins (suitable for development only)
_cors_origins_env = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in _cors_origins_env.split(",")
    if origin.strip()
] or ["*"]


# =============================================================================
# Admin Authentication Configuration
# =============================================================================
# Credentials for HTTP Basic Auth on admin endpoints.
# ADMIN_PASSWORD must be set in production for admin access to work.

ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")


# =============================================================================
# Stripe Payment Configuration
# =============================================================================
# Stripe is used for processing customer payments via Checkout Sessions.
# In test mode, use Stripe test keys (sk_test_..., whsec_test_...).

# Stripe secret API key for server-side operations
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")

# Webhook signing secret for verifying Stripe webhook signatures
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Base URL of the application (used for Stripe success/cancel redirect URLs)
# Example: "https://order.zuckersbagels.com" or "http://localhost:8000" for dev
BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")


# =============================================================================
# AWS Messaging Configuration (SNS for SMS, SES for Email)
# =============================================================================
# AWS SNS sends SMS notifications; AWS SES sends emails.
# Leave credentials empty to disable (graceful degradation).

AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
AWS_SNS_FROM_NUMBER: str = os.getenv("AWS_SNS_FROM_NUMBER", "")
AWS_SES_FROM_EMAIL: str = os.getenv("AWS_SES_FROM_EMAIL", "")


# =============================================================================
# Toast POS Configuration
# =============================================================================
# Toast POS integration for pushing confirmed orders to the kitchen display.
# Leave all empty to disable Toast (graceful degradation, zero impact on orders).

TOAST_CLIENT_ID: str = os.getenv("TOAST_CLIENT_ID", "")
TOAST_CLIENT_SECRET: str = os.getenv("TOAST_CLIENT_SECRET", "")
TOAST_RESTAURANT_GUID: str = os.getenv("TOAST_RESTAURANT_GUID", "")
TOAST_API_BASE_URL: str = os.getenv("TOAST_API_BASE_URL", "https://ws-sandbox-api.eng.toasttab.com")
TOAST_WEBHOOK_SECRET: str = os.getenv("TOAST_WEBHOOK_SECRET", "")


# =============================================================================
# Admin UI Page Mappings
# =============================================================================
# Maps URL paths to HTML files for the protected admin interface.
# Admin pages require authentication and are served via /admin-ui/{page}

ADMIN_PAGES = {
    "menu": "admin_menu.html",
    "orders": "admin_orders.html",
    "ingredients": "admin_ingredients.html",
    "analytics": "admin_analytics.html",
    "stores": "admin_stores.html",
    "company": "admin_company.html",
    "modifiers": "admin_modifiers.html",
    "item_types": "admin_item_types.html",
    "modifier_categories": "admin_modifier_categories.html",
    "modifier_qualifiers": "admin_modifier_qualifiers.html",
    "global_attributes": "admin_global_attributes.html",
    "ingredient_categories": "admin_ingredient_categories.html",
    "size_categories": "admin_size_categories.html",
    "response_patterns": "admin_response_patterns.html",
    "overall_categories": "admin_overall_categories.html",
    "unrecognized_suggestions": "admin_unrecognized_suggestions.html",
    "menu_display_groups": "admin_menu_display_groups.html",
}
