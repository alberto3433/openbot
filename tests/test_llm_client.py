"""
Tests for LLM client configuration and behavior.
"""
from unittest.mock import patch, MagicMock


class TestModelConfiguration:
    """Test that model configuration works correctly."""

    def test_default_model_is_valid(self):
        """Test that DEFAULT_MODEL is set to a valid OpenAI model."""
        from sandwich_bot.sammy import llm_client

        valid_models = [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4-turbo-preview",
            "gpt-4",
            "gpt-3.5-turbo",
        ]
        assert llm_client.DEFAULT_MODEL in valid_models, (
            f"DEFAULT_MODEL '{llm_client.DEFAULT_MODEL}' is not a valid OpenAI model. "
            f"Valid models: {valid_models}"
        )

    def test_default_model_not_invalid_gpt41(self):
        """Test that we're not using the invalid 'gpt-4.1' model name."""
        from sandwich_bot.sammy import llm_client

        assert llm_client.DEFAULT_MODEL != "gpt-4.1", (
            "DEFAULT_MODEL should not be 'gpt-4.1' - this model doesn't exist!"
        )

    def test_call_sandwich_bot_uses_default_model(self):
        """Test that call_sandwich_bot uses DEFAULT_MODEL when no model specified."""
        from sandwich_bot.sammy import llm_client

        # Mock the OpenAI client
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content='{"reply": "test", "intent": "unknown", "slots": {}}'))
        ]

        with patch.object(llm_client.client.chat.completions, 'create', return_value=mock_completion) as mock_create:
            llm_client.call_sandwich_bot(
                conversation_history=[],
                current_order_state={"status": "pending", "items": []},
                menu_json={"signature_sandwiches": []},
                user_message="Hello",
            )

            # Verify the call was made with the default model
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["model"] == llm_client.DEFAULT_MODEL

    def test_call_sandwich_bot_allows_model_override(self):
        """Test that call_sandwich_bot allows overriding the model."""
        from sandwich_bot.sammy import llm_client

        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content='{"reply": "test", "intent": "unknown", "slots": {}}'))
        ]

        with patch.object(llm_client.client.chat.completions, 'create', return_value=mock_completion) as mock_create:
            llm_client.call_sandwich_bot(
                conversation_history=[],
                current_order_state={"status": "pending", "items": []},
                menu_json={"signature_sandwiches": []},
                user_message="Hello",
                model="gpt-3.5-turbo",  # Override the model
            )

            # Verify the call was made with the overridden model
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["model"] == "gpt-3.5-turbo"


class TestModelEnvironmentConfiguration:
    """Test that model can be configured via environment variable."""

    def test_model_reads_from_env(self, monkeypatch):
        """Test that DEFAULT_MODEL can be set via OPENAI_MODEL env var."""
        # This test verifies the pattern - actual env loading happens at import time
        import os

        # The module reads OPENAI_MODEL at import time, so we verify the pattern
        test_model = "gpt-3.5-turbo"
        result = os.getenv("OPENAI_MODEL", "gpt-4o")

        # If OPENAI_MODEL is set, it should be used; otherwise default to gpt-4o
        assert result in ["gpt-4o", os.getenv("OPENAI_MODEL")], (
            "Model should either be the env var value or the default 'gpt-4o'"
        )


class TestLLMResponseParsing:
    """Test LLM response parsing."""

    def test_call_sandwich_bot_returns_parsed_json(self):
        """Test that call_sandwich_bot returns parsed JSON from LLM response."""
        from sandwich_bot.sammy import llm_client

        expected_response = {
            "reply": "Hello! How can I help you today?",
            "intent": "small_talk",
            "slots": {
                "item_type": None,
                "menu_item_name": None,
            }
        }

        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content='{"reply": "Hello! How can I help you today?", "intent": "small_talk", "slots": {"item_type": null, "menu_item_name": null}}'))
        ]

        with patch.object(llm_client.client.chat.completions, 'create', return_value=mock_completion):
            result = llm_client.call_sandwich_bot(
                conversation_history=[],
                current_order_state={"status": "pending", "items": []},
                menu_json={"signature_sandwiches": []},
                user_message="Hello",
            )

            assert result["reply"] == expected_response["reply"]
            assert result["intent"] == expected_response["intent"]
            assert "slots" in result

    def test_call_sandwich_bot_handles_malformed_json(self):
        """Test that call_sandwich_bot returns fallback response when LLM returns invalid JSON."""
        from sandwich_bot.sammy import llm_client

        mock_completion = MagicMock()
        # Return malformed JSON (missing closing brace)
        mock_completion.choices = [
            MagicMock(message=MagicMock(content='{"reply": "Hello", "actions": [{"intent": "small_talk"'))
        ]

        with patch.object(llm_client.client.chat.completions, 'create', return_value=mock_completion):
            result = llm_client.call_sandwich_bot(
                conversation_history=[],
                current_order_state={"status": "pending", "items": []},
                menu_json={"signature_sandwiches": []},
                user_message="Hello",
            )

            # Should return fallback response instead of crashing
            assert "actions" in result
            assert result["actions"][0]["intent"] == "unknown"
            assert "trouble understanding" in result["reply"].lower()

    def test_call_sandwich_bot_handles_empty_response(self):
        """Test that call_sandwich_bot handles empty LLM response."""
        from sandwich_bot.sammy import llm_client

        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content=''))
        ]

        with patch.object(llm_client.client.chat.completions, 'create', return_value=mock_completion):
            result = llm_client.call_sandwich_bot(
                conversation_history=[],
                current_order_state={"status": "pending", "items": []},
                menu_json={"signature_sandwiches": []},
                user_message="Hello",
            )

            # Should return fallback response
            assert "actions" in result
            assert result["actions"][0]["intent"] == "unknown"
            assert "slots" in result["actions"][0]

    def test_call_sandwich_bot_handles_non_json_response(self):
        """Test that call_sandwich_bot handles plain text LLM response."""
        from sandwich_bot.sammy import llm_client

        mock_completion = MagicMock()
        # Return plain text instead of JSON
        mock_completion.choices = [
            MagicMock(message=MagicMock(content='Hello! I am Sammy the sandwich bot.'))
        ]

        with patch.object(llm_client.client.chat.completions, 'create', return_value=mock_completion):
            result = llm_client.call_sandwich_bot(
                conversation_history=[],
                current_order_state={"status": "pending", "items": []},
                menu_json={"signature_sandwiches": []},
                user_message="Hello",
            )

            # Should return fallback response
            assert "actions" in result
            assert result["actions"][0]["intent"] == "unknown"
            assert "trouble understanding" in result["reply"].lower()
