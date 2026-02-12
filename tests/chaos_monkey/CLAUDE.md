# Chaos Monkey Testing

## Rules

- **Always create a failure report** (`chaos_monkey_failures_runN.md`) for every chaos monkey run, showing how to recreate each failure.
- Report files go in `tests/` (e.g., `tests/chaos_monkey_failures_run9.md`).
- Generated regression test files go in `tests/chaos_monkey/generated/`.
- When fixing generated test files, use `order.items.get_active_items()` to check cart contents, NOT `order.items.to_dict()` (which doesn't exist).
- Menu inquiry tests should not use `assert False` — remove the assertion or add a meaningful check.

## Running the Chaos Monkey (Live API Tests)

The chaos monkey generates random scenarios and runs them against a live API server.

### Prerequisites

1. Start the dev server with rate limiting disabled:
   ```bash
   python -c "import os; os.environ['RATE_LIMIT_ENABLED'] = 'false'; import uvicorn; uvicorn.run('orderbot.main:app', host='127.0.0.1', port=8000, reload=False)"
   ```

2. On Windows, `set VAR=value && command` does NOT reliably propagate env vars. Use the Python wrapper above.

### Run 100 Tests

```bash
python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --report-path tests/chaos_monkey_failures_runN.md
```

- `-d 300` — run for 300 seconds (5 min), produces ~100 tests
- `-b 20` — batch size of 20 scenarios
- `-r 60` — 60 requests/min rate limit
- `--request-delay 0.5` — 0.5s between requests
- `--report-path` — where to save the failure report

### Other Options

```bash
# Focus on a specific scenario type
python -m tests.chaos_monkey.cli -d 300 --scenario-type modifier_flow

# Enable aggressive mutations (typos, word doubling)
python -m tests.chaos_monkey.cli -d 300 --aggressive

# Enable LLM-generated phrasings (requires API key)
python -m tests.chaos_monkey.cli -d 300 --use-llm

# Full help
python -m tests.chaos_monkey.cli --help
```

## Running Generated Regression Tests (Offline)

After chaos monkey runs, failed scenarios are saved as pytest files in `tests/chaos_monkey/generated/`.

```bash
# Run all generated regression tests
python -m pytest tests/chaos_monkey/generated/ -v --tb=short -q

# Run a specific test
python -m pytest tests/chaos_monkey/generated/test_failure_modifier_flow_20260211_212949_2d1d59e3.py -v -s --tb=long
```

## Failure Report Format

Each run produces a markdown report with this structure:

```
# Chaos Monkey Test Failures

**Total Tests:** 100
**Passed:** 93
**Failed:** 7

## Summary by Category
| Category | Count |
|----------|-------|
| Menu Item Not Found | 5 |
| Item Recognition | 2 |

## Menu Item Not Found

### Order X then modify
**Type:** modifier_flow
**Session:** `uuid`
**Failure:** description

**Conversation:**
    User: ...
    Bot: ...
    [FAILED: reason]
```

## Common Failure Categories

- **Menu Item Not Found** — Bot says "sorry, we don't have X" when it should recognize the input
- **Item Recognition** — Item not added to cart or removed unexpectedly
- **System Error** — 500 errors, timeouts, or crashes
- **Cart Ops** — Quantity changes, item removal not working

## Generated Test Code Pattern

Regression tests should use this pattern for cart assertions:

```python
from orderbot.tasks.models import OrderTask
from orderbot.tasks.state_machine import OrderStateMachine

order = OrderTask()
order.phase = "taking_items"
sm = OrderStateMachine()

result = sm.process("One BLT please", order)

# Check item is in cart
assert any("the blt" in (item.menu_item_name or "").lower()
           for item in order.items.get_active_items()), \
    f"Expected item 'The BLT' in cart"
```
