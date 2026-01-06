"""
Authentication Module for Sandwich Bot
======================================

This module handles authentication for protected endpoints in the Sandwich Bot
application. Currently implements HTTP Basic Authentication for admin endpoints,
with security best practices to prevent common vulnerabilities.

Authentication Methods:
-----------------------
1. **HTTP Basic Auth (Admin)**: Used for all /admin/* endpoints and the admin UI.
   Credentials are configured via environment variables (ADMIN_USERNAME, ADMIN_PASSWORD).
   Uses constant-time comparison to prevent timing attacks.

Security Features:
------------------
- **Timing Attack Prevention**: Uses `secrets.compare_digest()` for credential
  comparison, which takes constant time regardless of how many characters match.
  This prevents attackers from guessing passwords character-by-character.

- **Shared Realm**: All admin endpoints share the same HTTP Basic Auth realm,
  allowing browsers to cache and reuse credentials across admin pages.

- **Graceful Degradation**: If ADMIN_PASSWORD is not configured, admin endpoints
  return 503 Service Unavailable rather than allowing unauthenticated access.

Configuration:
--------------
Environment variables (see config.py):
- ADMIN_USERNAME: Username for admin access (default: "admin")
- ADMIN_PASSWORD: Password for admin access (required, no default)

Usage:
------
Add authentication to any endpoint using FastAPI's Depends():

    from sandwich_bot.auth import verify_admin_credentials

    @router.get("/admin/sensitive-data")
    def get_sensitive_data(
        admin_user: str = Depends(verify_admin_credentials),
        db: Session = Depends(get_db),
    ):
        # admin_user contains the authenticated username
        return {"data": "sensitive"}

The dependency will:
- Return 503 if ADMIN_PASSWORD is not configured
- Return 401 with WWW-Authenticate header if credentials are invalid
- Return the username string if authentication succeeds

Browser Behavior:
-----------------
When a 401 response with WWW-Authenticate header is received, browsers
automatically prompt users for credentials. The shared realm ensures
users only need to authenticate once per browser session for all admin pages.

Future Considerations:
----------------------
- JWT tokens for API clients (stateless, scalable)
- OAuth2 integration for SSO
- Role-based access control (RBAC) for granular permissions
- API keys for programmatic access
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import config


# =============================================================================
# HTTP Basic Auth Setup
# =============================================================================
# HTTPBasic security scheme for admin endpoints.
# The realm is shared across all admin routes so browsers cache credentials.

security = HTTPBasic(realm="OrderBot Admin")


# =============================================================================
# Admin Authentication Dependency
# =============================================================================

def verify_admin_credentials(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    """
    Verify HTTP Basic Auth credentials for admin endpoints.

    This is a FastAPI dependency that can be added to any endpoint to require
    admin authentication. It performs constant-time comparison of credentials
    to prevent timing attacks.

    Args:
        credentials: HTTP Basic Auth credentials extracted from the request
                    by FastAPI's security dependency.

    Returns:
        str: The authenticated username if credentials are valid.

    Raises:
        HTTPException (503): If ADMIN_PASSWORD environment variable is not set.
                            This prevents accidental exposure of admin endpoints
                            in misconfigured deployments.
        HTTPException (401): If credentials are invalid. Includes WWW-Authenticate
                            header to trigger browser's native auth prompt.

    Example:
        @router.get("/admin/orders")
        def list_orders(
            admin: str = Depends(verify_admin_credentials),
            db: Session = Depends(get_db),
        ):
            # Only reached if authentication succeeds
            return db.query(Order).all()

    Security Notes:
        - Uses secrets.compare_digest() for constant-time comparison
        - Encodes strings to bytes before comparison for consistent behavior
        - Returns generic "Invalid admin credentials" message (doesn't reveal
          whether username or password was wrong)
    """
    # Fail closed: if password not configured, deny all access
    if not config.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication not configured. Set ADMIN_PASSWORD environment variable.",
        )

    # Constant-time comparison to prevent timing attacks
    # An attacker cannot determine how many characters matched based on response time
    username_correct = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        config.ADMIN_USERNAME.encode("utf-8"),
    )
    password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        config.ADMIN_PASSWORD.encode("utf-8"),
    )

    if not (username_correct and password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
