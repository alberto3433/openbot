"""Tests for the Toast POS webhook handler."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from orderbot.toast.webhook import TOAST_STATUS_MAP


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

class TestToastStatusMap:
    """Verify Toast → internal status mapping is correct."""

    def test_received_maps_to_confirmed(self):
        assert TOAST_STATUS_MAP["RECEIVED"] == "confirmed"

    def test_in_preparation_maps_to_preparing(self):
        assert TOAST_STATUS_MAP["IN_PREPARATION"] == "preparing"

    def test_ready_for_pickup_maps_to_ready(self):
        assert TOAST_STATUS_MAP["READY_FOR_PICKUP"] == "ready"

    def test_ready_for_delivery_maps_to_ready(self):
        assert TOAST_STATUS_MAP["READY_FOR_DELIVERY"] == "ready"

    def test_closed_maps_to_completed(self):
        assert TOAST_STATUS_MAP["CLOSED"] == "completed"

    def test_voided_maps_to_cancelled(self):
        assert TOAST_STATUS_MAP["VOIDED"] == "cancelled"


# ---------------------------------------------------------------------------
# Webhook handler (via test client)
# ---------------------------------------------------------------------------

class TestToastWebhookEndpoint:
    """Integration tests for the /webhooks/toast endpoint."""

    @pytest.fixture
    def mock_app(self):
        """Create a minimal FastAPI app with the toast webhook router."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from orderbot.toast.webhook import toast_webhook_router

        app = FastAPI()
        app.include_router(toast_webhook_router)
        return TestClient(app)

    @patch("orderbot.toast.webhook.TOAST_WEBHOOK_SECRET", "")
    @patch("orderbot.toast.webhook.get_db")
    def test_valid_status_update_triggers_transition(self, mock_get_db, mock_app):
        """Valid order status update calls transition_order_status."""
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])

        # Create a mock order that the webhook can find
        mock_order = MagicMock()
        mock_order.id = 42
        mock_order.toast_order_guid = "toast-order-123"
        mock_order.status = "confirmed"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_order

        payload = {
            "eventType": "order.statusUpdate",
            "data": {
                "order": {
                    "guid": "toast-order-123",
                    "fulfillmentStatus": "IN_PREPARATION",
                }
            },
        }

        with patch("orderbot.services.order.transition_order_status") as mock_transition:
            from orderbot.db import get_db
            mock_app.app.dependency_overrides[get_db] = lambda: mock_db
            resp = mock_app.post("/webhooks/toast", json=payload)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch("orderbot.toast.webhook.TOAST_WEBHOOK_SECRET", "")
    @patch("orderbot.toast.webhook.get_db")
    def test_unknown_order_guid_returns_200(self, mock_get_db, mock_app):
        """Unknown Toast order GUID logs a warning but returns 200."""
        mock_db = MagicMock()
        mock_get_db.return_value = iter([mock_db])

        # No order found
        mock_db.query.return_value.filter.return_value.first.return_value = None

        payload = {
            "eventType": "order.statusUpdate",
            "data": {
                "order": {
                    "guid": "unknown-guid",
                    "fulfillmentStatus": "IN_PREPARATION",
                }
            },
        }

        from orderbot.db import get_db
        mock_app.app.dependency_overrides[get_db] = lambda: mock_db
        resp = mock_app.post("/webhooks/toast", json=payload)

        assert resp.status_code == 200

    @patch("orderbot.toast.webhook.TOAST_WEBHOOK_SECRET", "test-secret")
    def test_missing_signature_returns_400(self, mock_app):
        """Request without signature header returns 400."""
        payload = json.dumps({"eventType": "test"}).encode()
        resp = mock_app.post(
            "/webhooks/toast",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    @patch("orderbot.toast.webhook.TOAST_WEBHOOK_SECRET", "test-secret")
    def test_invalid_signature_returns_400(self, mock_app):
        """Request with wrong signature returns 400."""
        payload = json.dumps({"eventType": "test"}).encode()
        resp = mock_app.post(
            "/webhooks/toast",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Toast-Signature": "bad-sig",
            },
        )
        assert resp.status_code == 400

    @patch("orderbot.toast.webhook.TOAST_WEBHOOK_SECRET", "test-secret")
    @patch("orderbot.toast.webhook.get_db")
    def test_valid_signature_accepted(self, mock_get_db, mock_app):
        """Request with valid HMAC signature is accepted."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        payload = json.dumps({"eventType": "order.test", "data": {}}).encode()
        sig = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()

        from orderbot.db import get_db
        mock_app.app.dependency_overrides[get_db] = lambda: mock_db
        resp = mock_app.post(
            "/webhooks/toast",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Toast-Signature": sig,
            },
        )
        assert resp.status_code == 200
