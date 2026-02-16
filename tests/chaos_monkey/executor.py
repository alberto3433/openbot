"""Test execution via API for Chaos Monkey tests."""

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from tests.chaos_monkey.config import ChaosMonkeyConfig
from tests.chaos_monkey.scenarios.base import BaseScenario, ScenarioResult
from tests.chaos_monkey.verifier import ResponseVerifier

logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Simple rate limiter for API requests."""

    max_requests: int
    window_seconds: float = 60.0
    _request_times: list[float] | None = None

    def __post_init__(self) -> None:
        """Initialize request times list."""
        self._request_times = []

    def wait_if_needed(self) -> None:
        """Wait if we've exceeded the rate limit."""
        now = time.time()
        window_start = now - self.window_seconds

        # Remove old requests outside the window
        self._request_times = [t for t in self._request_times if t > window_start]

        if len(self._request_times) >= self.max_requests:
            # Wait until the oldest request falls outside the window
            oldest = min(self._request_times)
            wait_time = oldest + self.window_seconds - now + 0.1
            if wait_time > 0:
                logger.debug("Rate limit reached, waiting %.2f seconds", wait_time)
                time.sleep(wait_time)

        self._request_times.append(time.time())


class TestExecutor:
    """Executes test scenarios against the API."""

    def __init__(self, config: ChaosMonkeyConfig) -> None:
        """Initialize the executor.

        Args:
            config: Chaos Monkey configuration.
        """
        self.config = config
        self.base_url = config.api_base_url
        self.rate_limiter = RateLimiter(max_requests=config.rate_limit)
        self.request_delay = config.request_delay_seconds
        self.verifier = ResponseVerifier()
        self.client = httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def retry_scenario(self, scenario: BaseScenario) -> ScenarioResult:
        """Retry a failed scenario against a fresh session to confirm reproducibility.

        Resets all turn result fields, then re-executes via execute_scenario().

        Args:
            scenario: The scenario to retry (turns are reset in-place).

        Returns:
            ScenarioResult from the fresh execution.
        """
        for turn in scenario.turns:
            turn.actual_response = None
            turn.actual_actions = None
            turn.actual_order_state = None
            turn.passed = None
            turn.failure_reason = None
            turn.failure_category = None

        return self.execute_scenario(scenario)

    def execute_scenario(self, scenario: BaseScenario) -> ScenarioResult:
        """Execute a complete scenario.

        Args:
            scenario: The scenario to execute.

        Returns:
            ScenarioResult with pass/fail status and details.
        """
        start_time = time.time()

        # Start a new session
        session_id = self._start_session()
        if not session_id:
            return self._create_error_result(
                scenario, "Failed to start session", start_time
            )

        # Get conversation turns
        turns = scenario.get_turns()

        # Execute each turn
        for turn in turns:
            try:
                self.rate_limiter.wait_if_needed()
                response = self._send_message(session_id, turn.user_input)

                if response is None:
                    turn.passed = False
                    turn.failure_reason = "Failed to send message"
                    break

                # Verify the response
                self.verifier.verify_turn(
                    turn,
                    response.get("reply", ""),
                    response.get("actions", []),
                    response.get("order_state", {}),
                )

                if not turn.passed:
                    # Stop on first failure
                    break

            except Exception as e:
                logger.error("Error executing turn: %s", e, exc_info=True)
                turn.passed = False
                turn.failure_reason = f"Execution error: {str(e)}"
                break

        # Build result
        result = scenario.to_result(session_id)
        result.execution_time_ms = (time.time() - start_time) * 1000

        return result

    def _start_session(self) -> str | None:
        """Start a new chat session.

        Returns:
            Session ID or None if failed.
        """
        try:
            self.rate_limiter.wait_if_needed()
            response = self.client.post(f"{self.base_url}/api/v1/chat/start")
            response.raise_for_status()
            data = response.json()
            # Add delay after request to avoid rate limiting
            time.sleep(self.request_delay)
            return data.get("session_id")
        except Exception as e:
            logger.error("Failed to start session: %s", e)
            time.sleep(self.request_delay)  # Also delay on error
            return None

    def _send_message(
        self, session_id: str, message: str
    ) -> dict[str, Any] | None:
        """Send a message to the chat API.

        Args:
            session_id: The session ID.
            message: The message to send.

        Returns:
            API response dict or None if failed.
        """
        try:
            response = self.client.post(
                f"{self.base_url}/api/v1/chat/message",
                json={"session_id": session_id, "message": message},
            )
            response.raise_for_status()
            result = response.json()
            # Add delay after request to avoid rate limiting
            time.sleep(self.request_delay)
            return result
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error sending message: %s", e)
            time.sleep(self.request_delay)  # Also delay on error
            return None
        except Exception as e:
            logger.error("Error sending message: %s", e)
            time.sleep(self.request_delay)
            return None

    def _create_error_result(
        self, scenario: BaseScenario, error: str, start_time: float
    ) -> ScenarioResult:
        """Create an error result for a failed scenario."""
        from tests.chaos_monkey.scenarios.base import FailureCategory

        return ScenarioResult(
            scenario_name=scenario.name,
            scenario_type=scenario.scenario_type,
            turns=scenario.turns,
            passed=False,
            failure_category=FailureCategory.SYSTEM_ERROR,
            failure_summary=error,
            execution_time_ms=(time.time() - start_time) * 1000,
        )
