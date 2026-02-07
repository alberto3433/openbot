"""
Pytest plugin: captures full conversation transcripts from failing tests.

Monkey-patches OrderStateMachine.process() to record every
(user_input, bot_response) turn per test. On failure, prints the
full conversation so you can replay it in the chatbot UI.

Activated by:  pytest --capture-convos
Output on failure looks like:

    === CONVERSATION REPLAY: test_latte_ordering_flow ===

    Step 1:
      YOU:  I'd like a latte
      BOT:  Which would you like? 1) Hot Latte  2) Iced Latte

    Step 2:
      YOU:  Hot Latte
      BOT:  Got it, for the Hot Latte. What size?

    FAILED AT STEP 4:
      YOU:  whole milk
      BOT:  Did you mean Whole Milk, Skim Milk, or Oat Milk?
      EXPECTED: Response should contain 'decaf'

    --- Paste the YOU: lines into chatbot UI to replicate ---
    =============================================
"""
from __future__ import annotations

import sys

import pytest

# Per-process global: test nodeid -> list of (user_input, bot_response)
_conversations: dict[str, list[tuple[str, str]]] = {}

# Which test is currently running in this worker process
_current_test_id: str | None = None

_original_process = None
_patched = False


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--capture-convos",
        action="store_true",
        default=False,
        help="Capture conversation transcripts for failing tests",
    )


def _patched_process(self, user_input, order=None, **kwargs):
    """Wrapper that records each (input, response) turn."""
    result = _original_process(self, user_input, order, **kwargs)
    if _current_test_id is not None:
        bot_msg = getattr(result, "message", "<no message>") if result else "<no result>"
        _conversations.setdefault(_current_test_id, []).append((user_input, bot_msg))
    return result


def _ensure_patched() -> None:
    """Patch OrderStateMachine.process if not already done."""
    global _original_process, _patched
    if _patched:
        return
    try:
        from orderbot.tasks.state_machine import OrderStateMachine
        _original_process = OrderStateMachine.process
        OrderStateMachine.process = _patched_process
        _patched = True
    except ImportError:
        pass


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Restore original process method at session end."""
    global _original_process, _patched
    if _original_process is not None:
        try:
            from orderbot.tasks.state_machine import OrderStateMachine
            OrderStateMachine.process = _original_process
        except ImportError:
            pass
        _original_process = None
        _patched = False


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    if not item.config.getoption("--capture-convos", default=False):
        return
    _ensure_patched()
    global _current_test_id
    _current_test_id = item.nodeid
    _conversations[item.nodeid] = []


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item) -> None:
    global _current_test_id
    _current_test_id = None


@pytest.hookimpl(trylast=True, wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    """On test failure, emit the captured conversation transcript."""
    report = yield
    if call.when != "call":
        return report
    if not item.config.getoption("--capture-convos", default=False):
        return report
    if not report.failed:
        return report

    turns = _conversations.get(item.nodeid, [])
    if not turns:
        return report

    # Extract first line of assertion error
    assertion_msg = ""
    if call.excinfo:
        try:
            assertion_msg = str(call.excinfo.value).split("\n")[0]
        except Exception:
            assertion_msg = str(call.excinfo.value)

    lines: list[str] = [
        "",
        f"=== CONVERSATION REPLAY: {item.name} ===",
        "",
    ]

    for i, (user_input, bot_response) in enumerate(turns, 1):
        is_last = i == len(turns)
        if is_last:
            lines.append(f"  FAILED AT STEP {i}:")
            lines.append(f"    YOU:  {user_input}")
            lines.append(f"    BOT:  {bot_response}")
            if assertion_msg:
                lines.append(f"    EXPECTED: {assertion_msg}")
        else:
            lines.append(f"  Step {i}:")
            lines.append(f"    YOU:  {user_input}")
            lines.append(f"    BOT:  {bot_response}")
        lines.append("")

    lines.append("  --- Paste the YOU: lines into chatbot UI to replicate ---")
    lines.append("=" * 55)
    lines.append("")

    # Append to the report's longrepr so it shows in pytest output
    transcript = "\n".join(lines)
    if report.longrepr:
        report.sections.append(("Conversation Replay", transcript))
    else:
        report.sections.append(("Conversation Replay", transcript))

    return report
