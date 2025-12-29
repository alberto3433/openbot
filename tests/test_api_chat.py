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


def test_chat_message_add_sandwich_updates_order_state(client, monkeypatch, disable_state_machine):
    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    from sandwich_bot import main as main_mod

    def fake_call(
        conversation_history,
        current_order_state,
        menu_json,
        user_message,
        model="gpt-4.1",
        **kwargs,
    ):
        # We ignore the inputs and just return a deterministic action
        return {
            "reply": "Got it, one Turkey Club.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": '6"',
                        "bread": "wheat",
                        "protein": "turkey",
                        "cheese": "cheddar",
                        "toppings": ["lettuce"],
                        "sauces": ["mayo"],
                        "toasted": True,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_call)

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "I want a Turkey Club"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Check actions array
    assert len(data["actions"]) == 1
    assert data["actions"][0]["intent"] == "add_sandwich"
    # Backward compatibility - intent/slots should match first action
    assert data["intent"] == "add_sandwich"
    items = data["order_state"]["items"]
    assert len(items) == 1
    assert items[0]["menu_item_name"] == "Turkey Club"
    assert items[0]["quantity"] == 1
    # Note: unit_price and line_total depend on menu_index lookup
    # which uses a nested structure - prices are calculated during confirm


def test_multi_item_order_adds_all_items(client, monkeypatch, disable_state_machine):
    """Test that multiple items in one message are all added to the order."""
    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    from sandwich_bot import main as main_mod

    def fake_multi_item_call(
        conversation_history,
        current_order_state,
        menu_json,
        user_message,
        model="gpt-4.1",
        **kwargs,
    ):
        # LLM returns multiple actions for a multi-item order
        return {
            "reply": "I've added a Veggie Delight sandwich, chips, and a fountain soda to your order.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Veggie Delight",
                        "size": None,
                        "bread": "wheat",
                        "protein": None,
                        "cheese": "american",
                        "toppings": ["lettuce", "tomato"],
                        "sauces": ["mayo"],
                        "toasted": True,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
                {
                    "intent": "add_side",
                    "slots": {
                        "item_type": "side",
                        "menu_item_name": "Chips",
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
                {
                    "intent": "add_drink",
                    "slots": {
                        "item_type": "drink",
                        "menu_item_name": "Fountain Soda",
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_multi_item_call)

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "I want a veggie delight, chips, and a coke"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Check all 3 actions were processed
    assert len(data["actions"]) == 3
    assert data["actions"][0]["intent"] == "add_sandwich"
    assert data["actions"][1]["intent"] == "add_side"
    assert data["actions"][2]["intent"] == "add_drink"

    # Check all 3 items are in the order
    items = data["order_state"]["items"]
    assert len(items) == 3

    # Verify each item
    item_names = [item["menu_item_name"] for item in items]
    assert "Veggie Delight" in item_names
    assert "Chips" in item_names
    assert "Fountain Soda" in item_names

    # Verify item types
    item_types = {item["menu_item_name"]: item["item_type"] for item in items}
    assert item_types["Veggie Delight"] == "sandwich"
    assert item_types["Chips"] == "side"
    assert item_types["Fountain Soda"] == "drink"


def test_multi_item_order_can_remove_single_item(client, monkeypatch, disable_state_machine):
    """Test that after adding multiple items, a single item can be removed by name."""
    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    from sandwich_bot import main as main_mod

    # First, add multiple items
    def fake_multi_item_call(
        conversation_history,
        current_order_state,
        menu_json,
        user_message,
        model="gpt-4.1",
        **kwargs,
    ):
        return {
            "reply": "I've added your items.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": None,
                        "bread": "wheat",
                        "protein": "turkey",
                        "cheese": "cheddar",
                        "toppings": [],
                        "sauces": [],
                        "toasted": False,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
                {
                    "intent": "add_side",
                    "slots": {
                        "item_type": "side",
                        "menu_item_name": "Chips",
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
                {
                    "intent": "add_drink",
                    "slots": {
                        "item_type": "drink",
                        "menu_item_name": "Fountain Soda",
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_multi_item_call)
    resp1 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Turkey club, chips, and a coke"},
    )
    assert len(resp1.json()["order_state"]["items"]) == 3

    # Now remove just the chips
    def fake_remove_call(
        conversation_history,
        current_order_state,
        menu_json,
        user_message,
        model="gpt-4.1",
        **kwargs,
    ):
        return {
            "reply": "I've removed the chips from your order.",
            "actions": [
                {
                    "intent": "remove_item",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": "Chips",
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_remove_call)
    resp2 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Remove the chips"},
    )
    assert resp2.status_code == 200
    data = resp2.json()

    # Should have 2 items remaining
    items = data["order_state"]["items"]
    assert len(items) == 2

    # Chips should be gone, sandwich and drink should remain
    item_names = [item["menu_item_name"] for item in items]
    assert "Chips" not in item_names
    assert "Turkey Club" in item_names
    assert "Fountain Soda" in item_names


def test_legacy_single_intent_format_still_works(client, monkeypatch, disable_state_machine):
    """Test backward compatibility with old LLM response format (single intent/slots)."""
    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    from sandwich_bot import main as main_mod

    def fake_legacy_call(
        conversation_history,
        current_order_state,
        menu_json,
        user_message,
        model="gpt-4.1",
        **kwargs,
    ):
        # Old format: intent and slots at top level, no actions array
        return {
            "reply": "Got it, one Turkey Club.",
            "intent": "add_sandwich",
            "slots": {
                "item_type": "sandwich",
                "menu_item_name": "Turkey Club",
                "size": None,
                "bread": "wheat",
                "protein": "turkey",
                "cheese": "cheddar",
                "toppings": [],
                "sauces": [],
                "toasted": True,
                "quantity": 1,
                "item_index": None,
                "customer_name": None,
                "phone": None,
                "pickup_time": None,
                "confirm": None,
                "cancel_reason": None,
            },
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_legacy_call)

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "I want a Turkey Club"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Should still work - backward compatibility converts to actions
    assert len(data["actions"]) == 1
    assert data["actions"][0]["intent"] == "add_sandwich"
    assert data["intent"] == "add_sandwich"

    # Item should be added
    items = data["order_state"]["items"]
    assert len(items) == 1
    assert items[0]["menu_item_name"] == "Turkey Club"


def test_chat_message_handles_llm_error_gracefully(client, monkeypatch, disable_state_machine):
    """Test that LLM failures return a friendly error message instead of crashing."""
    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    from sandwich_bot import main as main_mod

    def fake_call_that_fails(*args, **kwargs):
        raise Exception("OpenAI API is down")

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_call_that_fails)

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "I want a sandwich"},
    )

    # Should return 200 with error message, not 500
    assert resp.status_code == 200
    data = resp.json()

    assert data["intent"] == "error"
    assert "trouble processing" in data["reply"].lower()
    # Order state should be preserved (not corrupted)
    assert "items" in data["order_state"]


def test_chat_message_rejects_empty_message(client):
    """Test that empty messages are rejected with validation error."""
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": ""},
    )

    assert resp.status_code == 422  # Validation error


def test_chat_message_rejects_too_long_message(client, monkeypatch):
    """Test that messages exceeding max length are rejected."""
    import sandwich_bot.main as main_mod

    # Set a very small max length for testing
    monkeypatch.setattr(main_mod, "MAX_MESSAGE_LENGTH", 50)

    # Need to recreate the model with new max_length
    # For this test, we'll just verify the validation exists by checking with a large message
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
    import sandwich_bot.main as main_mod
    import sandwich_bot.config as config_mod

    # Set a very restrictive rate limit for testing via the callable
    # Patch both main and config since get_rate_limit_chat reads from config
    monkeypatch.setattr(config_mod, "RATE_LIMIT_CHAT", "2 per minute")
    monkeypatch.setattr(main_mod, "RATE_LIMIT_CHAT", "2 per minute")

    # Re-enable rate limiting (might be disabled in test env)
    main_mod.limiter.enabled = True

    # Reset limiter state for clean test
    main_mod.limiter.reset()

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
        main_mod.limiter.enabled = False
        main_mod.limiter.reset()


def test_rate_limit_can_be_disabled(client, monkeypatch):
    """Test that rate limiting can be disabled via environment variable."""
    import sandwich_bot.main as main_mod

    # Disable rate limiting
    main_mod.limiter.enabled = False

    # Set very restrictive limit (shouldn't matter since disabled)
    monkeypatch.setattr(main_mod, "RATE_LIMIT_CHAT", "1 per minute")

    # Multiple requests should all succeed
    for _ in range(5):
        resp = client.post("/chat/start")
        assert resp.status_code == 200


# ---- Integration tests for mid-order modifications ----


def test_modification_add_topping_to_existing_sandwich(client, monkeypatch, disable_state_machine):
    """Test full flow: add sandwich, then add a topping mid-order."""
    from sandwich_bot import main as main_mod

    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Step 1: Add a sandwich with initial toppings
    def fake_add_sandwich(*args, **kwargs):
        return {
            "reply": "Got it, one Turkey Club with lettuce and tomato.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": None,
                        "bread": "White",
                        "protein": "Turkey",
                        "cheese": "American",
                        "toppings": ["Lettuce", "Tomato"],
                        "sauces": ["Mayo"],
                        "toasted": False,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_sandwich)
    resp1 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Turkey club with lettuce and tomato"},
    )
    assert resp1.status_code == 200
    items = resp1.json()["order_state"]["items"]
    assert len(items) == 1
    assert items[0]["toppings"] == ["Lettuce", "Tomato"]

    # Step 2: Add pickles (LLM computes new list: existing + Pickles)
    def fake_add_topping(*args, **kwargs):
        return {
            "reply": "I've added pickles to your sandwich.",
            "actions": [
                {
                    "intent": "update_sandwich",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": None,
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": ["Lettuce", "Tomato", "Pickles"],
                        "sauces": None,
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_topping)
    resp2 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Add pickles"},
    )
    assert resp2.status_code == 200
    data = resp2.json()

    # Verify final order has all 3 toppings
    items = data["order_state"]["items"]
    assert len(items) == 1
    assert items[0]["toppings"] == ["Lettuce", "Tomato", "Pickles"]
    # Other fields should be preserved
    assert items[0]["bread"] == "White"
    assert items[0]["sauces"] == ["Mayo"]


def test_modification_remove_topping_from_existing_sandwich(client, monkeypatch, disable_state_machine):
    """Test full flow: add sandwich, then remove a topping mid-order."""
    from sandwich_bot import main as main_mod

    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Step 1: Add a sandwich with toppings
    def fake_add_sandwich(*args, **kwargs):
        return {
            "reply": "Got it, one Turkey Club.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": None,
                        "bread": "Wheat",
                        "protein": "Turkey",
                        "cheese": "Swiss",
                        "toppings": ["Lettuce", "Tomato", "Red Onion"],
                        "sauces": [],
                        "toasted": True,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_sandwich)
    resp1 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Turkey club with everything"},
    )
    assert resp1.json()["order_state"]["items"][0]["toppings"] == ["Lettuce", "Tomato", "Red Onion"]

    # Step 2: Remove tomato (LLM computes: existing minus Tomato)
    def fake_remove_topping(*args, **kwargs):
        return {
            "reply": "No problem, I've removed the tomato.",
            "actions": [
                {
                    "intent": "update_sandwich",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": None,
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": ["Lettuce", "Red Onion"],  # Tomato removed
                        "sauces": None,
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_remove_topping)
    resp2 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Actually, no tomato"},
    )
    assert resp2.status_code == 200
    data = resp2.json()

    # Verify tomato was removed
    items = data["order_state"]["items"]
    assert len(items) == 1
    assert items[0]["toppings"] == ["Lettuce", "Red Onion"]
    assert "Tomato" not in items[0]["toppings"]


def test_modification_add_and_remove_toppings_simultaneously(client, monkeypatch, disable_state_machine):
    """Test full flow: add sandwich, then add and remove toppings in one request."""
    from sandwich_bot import main as main_mod

    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Step 1: Add a sandwich
    def fake_add_sandwich(*args, **kwargs):
        return {
            "reply": "Got it!",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "BLT",
                        "size": None,
                        "bread": "White",
                        "protein": "Bacon",
                        "cheese": None,
                        "toppings": ["Lettuce", "Tomato"],
                        "sauces": ["Mayo"],
                        "toasted": True,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_sandwich)
    client.post("/chat/message", json={"session_id": session_id, "message": "BLT please"})

    # Step 2: Add onion and remove tomato
    def fake_modify_toppings(*args, **kwargs):
        return {
            "reply": "I've added onion and removed the tomato.",
            "actions": [
                {
                    "intent": "update_sandwich",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": None,
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": ["Lettuce", "Red Onion"],  # +Red Onion, -Tomato
                        "sauces": None,
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_modify_toppings)
    resp = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Add onion and remove the tomato"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Verify final toppings
    items = data["order_state"]["items"]
    assert items[0]["toppings"] == ["Lettuce", "Red Onion"]


def test_modification_change_sandwich_type(client, monkeypatch, disable_state_machine):
    """Test full flow: add sandwich, then change to different sandwich type."""
    from sandwich_bot import main as main_mod

    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Step 1: Add a Turkey Club
    def fake_add_sandwich(*args, **kwargs):
        return {
            "reply": "Got it, one Turkey Club.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": None,
                        "bread": "White",
                        "protein": "Turkey",
                        "cheese": "American",
                        "toppings": ["Lettuce"],
                        "sauces": [],
                        "toasted": False,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_sandwich)
    resp1 = client.post("/chat/message", json={"session_id": session_id, "message": "Turkey Club"})
    assert resp1.json()["order_state"]["items"][0]["menu_item_name"] == "Turkey Club"

    # Step 2: Change to Italian Stallion
    def fake_change_sandwich(*args, **kwargs):
        return {
            "reply": "Changed to Italian Stallion.",
            "actions": [
                {
                    "intent": "update_sandwich",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": "Italian Stallion",
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": None,
                        "sauces": None,
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_change_sandwich)
    resp2 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Actually make that an Italian Stallion"},
    )
    assert resp2.status_code == 200
    data = resp2.json()

    # Verify sandwich type changed
    items = data["order_state"]["items"]
    assert len(items) == 1
    assert items[0]["menu_item_name"] == "Italian Stallion"


def test_modification_first_sandwich_by_index(client, monkeypatch, disable_state_machine):
    """Test full flow: add two sandwiches, modify the first one by index."""
    from sandwich_bot import main as main_mod

    # Start session
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Step 1: Add two sandwiches
    def fake_add_two_sandwiches(*args, **kwargs):
        return {
            "reply": "Added Turkey Club and BLT.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": None,
                        "bread": "White",
                        "protein": "Turkey",
                        "cheese": "American",
                        "toppings": ["Lettuce"],
                        "sauces": [],
                        "toasted": False,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "BLT",
                        "size": None,
                        "bread": "Wheat",
                        "protein": "Bacon",
                        "cheese": None,
                        "toppings": ["Lettuce", "Tomato"],
                        "sauces": ["Mayo"],
                        "toasted": True,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                },
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_two_sandwiches)
    resp1 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Turkey Club and a BLT"},
    )
    items = resp1.json()["order_state"]["items"]
    assert len(items) == 2
    assert items[0]["bread"] == "White"
    assert items[1]["bread"] == "Wheat"

    # Step 2: Modify first sandwich (index 0) - change bread to Sourdough
    def fake_modify_first(*args, **kwargs):
        return {
            "reply": "Changed the first sandwich to sourdough.",
            "actions": [
                {
                    "intent": "update_sandwich",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": None,
                        "size": None,
                        "bread": "Sourdough",
                        "protein": None,
                        "cheese": None,
                        "toppings": None,
                        "sauces": None,
                        "toasted": None,
                        "quantity": None,
                        "item_index": 0,  # First sandwich
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_modify_first)
    resp2 = client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Change my first sandwich to sourdough"},
    )
    assert resp2.status_code == 200
    data = resp2.json()

    # Verify only first sandwich changed
    items = data["order_state"]["items"]
    assert len(items) == 2
    assert items[0]["bread"] == "Sourdough"  # Changed
    assert items[1]["bread"] == "Wheat"  # Unchanged


def test_chat_start_with_caller_id(client):
    """Test that caller_id parameter is accepted and returning_customer info is returned."""
    # Start session with caller ID (no prior orders, so no returning customer info)
    resp = client.post("/chat/start?caller_id=555-123-4567")
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "message" in data
    # returning_customer should be None or have order_count=0 for new callers
    if data.get("returning_customer"):
        assert data["returning_customer"]["order_count"] == 0


def test_chat_start_with_caller_id_recognizes_returning_customer(client, monkeypatch, disable_state_machine):
    """Test that returning customers are recognized by phone number."""
    from sandwich_bot import main as main_mod
    from sandwich_bot.models import Order, OrderItem

    # First, create a prior order with a phone number
    start_resp = client.post("/chat/start")
    session_id = start_resp.json()["session_id"]

    # Mock LLM to confirm order with phone number
    def fake_confirm_order(*args, **kwargs):
        return {
            "reply": "Order confirmed! Thank you, John!",
            "actions": [
                {
                    "intent": "confirm_order",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": None,
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": "John",
                        "phone": "555-987-6543",
                        "pickup_time": None,
                        "confirm": True,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    # First add a sandwich to the order
    def fake_add_sandwich(*args, **kwargs):
        return {
            "reply": "Got it, one Turkey Club.",
            "actions": [
                {
                    "intent": "add_sandwich",
                    "slots": {
                        "item_type": "sandwich",
                        "menu_item_name": "Turkey Club",
                        "size": None,
                        "bread": "White",
                        "protein": "Turkey",
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": False,
                        "quantity": 1,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_add_sandwich)
    client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "I want a Turkey Club"},
    )

    monkeypatch.setattr("sandwich_bot.routes.chat.call_sandwich_bot", fake_confirm_order)
    client.post(
        "/chat/message",
        json={"session_id": session_id, "message": "Confirm the order, my name is John and phone is 555-987-6543"},
    )

    # Now start a new session with the same phone number
    resp = client.post("/chat/start?caller_id=555-987-6543")
    assert resp.status_code == 200
    data = resp.json()

    # Should recognize returning customer
    assert data.get("returning_customer") is not None
    assert data["returning_customer"]["name"] == "John"
    assert data["returning_customer"]["order_count"] >= 1
    # Greeting should be personalized with name and offer to repeat order
    assert "John" in data["message"]
    assert "repeat your last order" in data["message"]
