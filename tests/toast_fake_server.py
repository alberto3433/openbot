"""
Fake Toast API Server
=========================

A minimal FastAPI app that mimics the Toast POS API for local integration testing.
Validates request structure and returns realistic fake responses.

Usage:
    uvicorn tests.toast_fake_server:app --port 9999

Then point the orderbot at it:
    TOAST_CLIENT_ID=fake_id \\
    TOAST_CLIENT_SECRET=fake_secret \\
    TOAST_RESTAURANT_GUID=fake-restaurant-guid \\
    TOAST_API_BASE_URL=http://localhost:9999 \\
    uvicorn orderbot.main:app --reload --port 8000
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("toast_fake_server")

app = FastAPI(title="Fake Toast API", description="Mock Toast POS API for testing")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

FAKE_TOKEN = "fake-jwt-token-for-testing"


@app.post("/authentication/v1/authentication/login")
async def authenticate(request: Request) -> Dict[str, Any]:
    """Fake Toast authentication — accepts any credentials."""
    body = await request.json()
    client_id = body.get("clientId", "")
    logger.info("Auth request from client: %s", client_id)

    return {
        "token": FAKE_TOKEN,
        "expiresIn": 86400,
        "tokenType": "Bearer",
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@app.get("/config/v2/diningOptions")
async def get_dining_options(request: Request):
    """Return fake dining options (pickup + delivery)."""
    _verify_auth(request)
    return [
        {
            "guid": "fake-pickup-guid",
            "name": "Pickup",
            "behavior": "TAKE_OUT",
        },
        {
            "guid": "fake-delivery-guid",
            "name": "Delivery",
            "behavior": "DELIVERY",
        },
    ]


@app.get("/config/v2/menus")
async def get_menus(request: Request):
    """Return a fake menu with a few items."""
    _verify_auth(request)
    return [
        {
            "guid": "fake-menu-guid",
            "name": "Main Menu",
            "groups": [
                {
                    "guid": "fake-group-bagels",
                    "name": "Bagels",
                    "items": [
                        {"guid": "fake-item-plain-bagel", "name": "Plain Bagel", "price": 3.50},
                        {"guid": "fake-item-everything-bagel", "name": "Everything Bagel", "price": 3.50},
                    ],
                },
                {
                    "guid": "fake-group-beverages",
                    "name": "Beverages",
                    "items": [
                        {"guid": "fake-item-iced-latte", "name": "Iced Latte", "price": 5.25},
                        {"guid": "fake-item-drip-coffee", "name": "Drip Coffee", "price": 3.00},
                    ],
                },
            ],
        }
    ]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@app.post("/orders/v2/orders")
async def create_order(request: Request) -> Dict[str, Any]:
    """Accept an order and return a fake order GUID."""
    _verify_auth(request)
    body = await request.json()

    # Basic validation
    entity_type = body.get("entityType")
    if entity_type != "Order":
        raise HTTPException(status_code=400, detail=f"Expected entityType 'Order', got '{entity_type}'")

    checks = body.get("checks", [])
    if not checks:
        raise HTTPException(status_code=400, detail="Order must have at least one check")

    total_selections = sum(len(c.get("selections", [])) for c in checks)

    order_guid = str(uuid.uuid4())
    logger.info(
        "Order received: guid=%s, checks=%d, selections=%d",
        order_guid, len(checks), total_selections,
    )

    # Log each selection for visibility
    for i, check in enumerate(checks):
        for j, sel in enumerate(check.get("selections", [])):
            item_guid = sel.get("item", {}).get("guid", "?")
            qty = sel.get("quantity", 1)
            mods = len(sel.get("modifiers", []))
            logger.info(
                "  Check %d, Selection %d: item=%s qty=%d modifiers=%d",
                i, j, item_guid, qty, mods,
            )

    return {
        "guid": order_guid,
        "entityType": "Order",
        "status": "RECEIVED",
        "createdDate": datetime.now(timezone.utc).isoformat(),
        "checks": [
            {
                "guid": str(uuid.uuid4()),
                "entityType": "Check",
                "totalAmount": 0.0,
            }
            for _ in checks
        ],
    }


@app.post("/orders/v2/prices")
async def calculate_prices(request: Request) -> Dict[str, Any]:
    """Echo back prices (simplified — real Toast would calculate taxes etc.)."""
    _verify_auth(request)
    body = await request.json()

    return {
        "guid": str(uuid.uuid4()),
        "entityType": "Order",
        "checks": body.get("checks", []),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_auth(request: Request) -> None:
    """Check for Bearer token in Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "fake-toast-api"}
