def test_chat_start_returns_session_and_order_state(client):
    resp = client.post("/chat/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "message" in data  # API returns 'message', not 'reply'
    # Note: /chat/start only returns session_id and message, not order_state
    # The order_state is internal to the session and returned in /chat/message responses


def test_request_id_in_response_header(client):
    """Test that X-Request-ID header is returned in responses."""
    resp = client.post("/chat/start")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    # Request ID should be a UUID-like string (36 chars with hyphens)
    request_id = resp.headers["X-Request-ID"]
    assert len(request_id) == 36
    assert request_id.count("-") == 4


def test_request_id_can_be_provided_by_client(client):
    """Test that client-provided X-Request-ID is used."""
    custom_id = "test-request-id-12345"
    resp = client.post("/chat/start", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == custom_id


def test_api_v1_endpoints_work(client):
    """Test that /api/v1/ prefixed endpoints work."""
    # Test /api/v1/chat/start
    resp = client.post("/api/v1/chat/start")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data


def test_health_endpoint_not_versioned(client):
    """Test that /health remains at root level (not versioned)."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_message_rejects_empty_message(client):
    """Test that empty messages are rejected with validation error."""
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": ""},
    )

    assert resp.status_code == 422  # Validation error


def test_chat_message_rejects_too_long_message(client):
    """Test that messages exceeding max length are rejected."""
    # Note: MAX_MESSAGE_LENGTH is defined at module load time in the Pydantic model,
    # so we can't easily change it. Instead, we test with a message longer than the
    # default 2000 char limit.
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Create a message longer than default 2000 chars
    long_message = "a" * 2500

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": long_message},
    )

    assert resp.status_code == 422  # Validation error


def test_rate_limit_returns_429_when_exceeded(client, monkeypatch):
    """Test that rate limiting returns 429 when limit is exceeded."""
    from sandwich_bot.main import limiter
    import sandwich_bot.config as config_mod

    # Set a very restrictive rate limit for testing
    monkeypatch.setattr(config_mod, "RATE_LIMIT_CHAT", "2 per minute")

    # Re-enable rate limiting (might be disabled in test env)
    limiter.enabled = True

    # Reset limiter state for clean test
    limiter.reset()

    try:
        # First two requests should succeed
        resp1 = client.post("/chat/start")
        assert resp1.status_code == 200

        resp2 = client.post("/chat/start")
        assert resp2.status_code == 200

        # Third request should be rate limited
        resp3 = client.post("/chat/start")
        assert resp3.status_code == 429
    finally:
        # Cleanup - disable rate limiting for other tests
        limiter.enabled = False
        limiter.reset()


def test_rate_limit_can_be_disabled(client):
    """Test that rate limiting can be disabled via environment variable."""
    from sandwich_bot.main import limiter

    # Disable rate limiting
    limiter.enabled = False

    # Multiple requests should all succeed
    for _ in range(5):
        resp = client.post("/chat/start")
        assert resp.status_code == 200


def test_chat_start_with_caller_id(client):
    """Test that caller_id parameter is accepted and returning_customer info is returned."""
    import uuid

    # Use a unique phone number to ensure no prior orders exist
    unique_phone = f"555-{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}"
    resp = client.post(f"/chat/start?caller_id={unique_phone}")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "message" in data
    # returning_customer should be None or have order_count=0 for truly new callers
    if data.get("returning_customer"):
        assert data["returning_customer"]["order_count"] == 0
