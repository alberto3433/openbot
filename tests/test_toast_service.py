"""Tests for the Toast POS service module."""

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Configuration checks
# ---------------------------------------------------------------------------

class TestIsToastConfigured:
    """Tests for is_toast_configured()."""

    @patch("orderbot.toast.service.TOAST_CLIENT_ID", "")
    @patch("orderbot.toast.service.TOAST_CLIENT_SECRET", "")
    @patch("orderbot.toast.service.TOAST_RESTAURANT_GUID", "")
    def test_returns_false_when_all_empty(self):
        from orderbot.toast.service import is_toast_configured
        assert is_toast_configured() is False

    @patch("orderbot.toast.service.TOAST_CLIENT_ID", "my_id")
    @patch("orderbot.toast.service.TOAST_CLIENT_SECRET", "")
    @patch("orderbot.toast.service.TOAST_RESTAURANT_GUID", "my_guid")
    def test_returns_false_when_secret_missing(self):
        from orderbot.toast.service import is_toast_configured
        assert is_toast_configured() is False

    @patch("orderbot.toast.service.TOAST_CLIENT_ID", "my_id")
    @patch("orderbot.toast.service.TOAST_CLIENT_SECRET", "my_secret")
    @patch("orderbot.toast.service.TOAST_RESTAURANT_GUID", "my_guid")
    def test_returns_true_when_all_set(self):
        from orderbot.toast.service import is_toast_configured
        assert is_toast_configured() is True


# ---------------------------------------------------------------------------
# Submit order — unconfigured
# ---------------------------------------------------------------------------

class TestSubmitOrderUnconfigured:
    """submit_order returns None gracefully when Toast is not configured."""

    @patch("orderbot.toast.service.is_toast_configured", return_value=False)
    def test_returns_none_when_unconfigured(self, _mock_cfg):
        from orderbot.toast.service import submit_order
        db = MagicMock()
        result = submit_order(db, {"db_order_id": 1, "items": []})
        assert result is None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    """Tests for Toast auth token caching and refresh."""

    @patch("orderbot.toast.service.TOAST_API_BASE_URL", "http://fake-toast")
    @patch("orderbot.toast.service.TOAST_CLIENT_ID", "id")
    @patch("orderbot.toast.service.TOAST_CLIENT_SECRET", "secret")
    def test_auth_token_is_cached(self):
        """Verify only 1 auth call is made for multiple requests."""
        import orderbot.toast.service as svc

        # Reset cached token
        svc._auth_token = None
        svc._token_expires_at = 0.0

        mock_httpx = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "fake-jwt", "expiresIn": 86400}
        mock_response.raise_for_status.return_value = None
        mock_httpx.post.return_value = mock_response

        with patch.object(svc, "_get_httpx", return_value=mock_httpx):
            token1 = svc._authenticate()
            token2 = svc._authenticate()

        assert token1 == "fake-jwt"
        assert token2 == "fake-jwt"
        # Only one POST call (second call uses cache)
        assert mock_httpx.post.call_count == 1

    @patch("orderbot.toast.service.TOAST_API_BASE_URL", "http://fake-toast")
    @patch("orderbot.toast.service.TOAST_CLIENT_ID", "id")
    @patch("orderbot.toast.service.TOAST_CLIENT_SECRET", "secret")
    def test_expired_token_triggers_reauth(self):
        """Token past expiry should trigger a fresh auth call."""
        import orderbot.toast.service as svc

        svc._auth_token = "old-token"
        svc._token_expires_at = time.time() - 100  # Expired

        mock_httpx = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"token": "new-jwt", "expiresIn": 86400}
        mock_response.raise_for_status.return_value = None
        mock_httpx.post.return_value = mock_response

        with patch.object(svc, "_get_httpx", return_value=mock_httpx):
            token = svc._authenticate()

        assert token == "new-jwt"
        assert mock_httpx.post.call_count == 1


# ---------------------------------------------------------------------------
# Successful order submission
# ---------------------------------------------------------------------------

class TestSubmitOrderSuccess:
    """Tests for successful order submission flow."""

    @patch("orderbot.toast.service.is_toast_configured", return_value=True)
    @patch("orderbot.toast.service._update_toast_status")
    def test_successful_submission(self, mock_update_status, _mock_cfg):
        from orderbot.toast.service import submit_order

        mock_db = MagicMock()
        order_state = {
            "db_order_id": 42,
            "items": [{"menu_item_id": 1, "menu_item_name": "Test Bagel"}],
            "customer": {"name": "Jane Doe"},
        }

        fake_toast_response = {"guid": "toast-order-guid-123"}
        mock_payload = {"entityType": "Order", "checks": []}

        with patch("orderbot.toast.service._make_request", return_value=fake_toast_response), \
             patch("orderbot.toast.order_builder.build_toast_order", return_value=mock_payload):
            result = submit_order(mock_db, order_state)

        assert result is not None
        assert result["guid"] == "toast-order-guid-123"

        # Should have been called with pending_sync first, then submitted
        assert mock_update_status.call_count == 2
        calls = mock_update_status.call_args_list
        assert calls[0].args[2] == "pending_sync"
        assert calls[1].args[2] == "submitted"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestSubmitOrderErrors:
    """Tests for error handling during order submission."""

    @patch("orderbot.toast.service.is_toast_configured", return_value=True)
    @patch("orderbot.toast.service._update_toast_status")
    def test_build_failure_marks_failed(self, mock_update_status, _mock_cfg):
        """When payload build returns None, order is marked failed."""
        from orderbot.toast.service import submit_order

        mock_db = MagicMock()
        order_state = {"db_order_id": 42, "items": []}

        with patch("orderbot.toast.order_builder.build_toast_order", return_value=None):
            result = submit_order(mock_db, order_state)

        assert result is None
        # pending_sync then failed
        assert mock_update_status.call_count == 2
        assert mock_update_status.call_args_list[1].args[2] == "failed"

    @patch("orderbot.toast.service.is_toast_configured", return_value=True)
    @patch("orderbot.toast.service._update_toast_status")
    def test_api_failure_marks_failed(self, mock_update_status, _mock_cfg):
        """When Toast API returns None, order is marked failed."""
        from orderbot.toast.service import submit_order

        mock_db = MagicMock()
        order_state = {"db_order_id": 42, "items": []}
        mock_payload = {"entityType": "Order", "checks": []}

        with patch("orderbot.toast.order_builder.build_toast_order", return_value=mock_payload), \
             patch("orderbot.toast.service._make_request", return_value=None):
            result = submit_order(mock_db, order_state)

        assert result is None
        assert mock_update_status.call_args_list[-1].args[2] == "failed"

    def test_no_db_order_id_returns_none(self):
        """submit_order returns None when order_state has no db_order_id."""
        from orderbot.toast.service import submit_order

        with patch("orderbot.toast.service.is_toast_configured", return_value=True):
            result = submit_order(MagicMock(), {"items": []})
        assert result is None
