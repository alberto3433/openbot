# Chaos Monkey Regression Test Failures — Run 12

**Generated:** 2026-02-13
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --report-path tests/chaos_monkey_failures_run12.md`
**Live Results:** 97/100 passed, 3 failed (up from 94/100 in run 11)

---

## Progress Tracker

| Run | Passed | Failed | Pass Rate |
|-----|--------|--------|-----------|
| 7   | 86     | 14     | 86%       |
| 8   | 94     | 6      | 94%       |
| 9   | 93     | 7      | 93%       |
| 10  | 113/120| 7      | 94%       |
| 11  | 94     | 6      | 94%       |
| **12** | **97** | **3** | **97%** |

## Run 12 Failures (3 total)

### Failure 1: "No soy please" — tries to remove modifier that was never added

**Category:** Removing a never-added modifier
**Test:** `test_failure_modifier_flow_20260213_162236_2fc01a7e.py`

**How to reproduce in UI:**
1. Open the chat at `http://localhost:8000`
2. Say: **"I'd like a Hot Tea"**
3. Bot responds: "Got it, for the Hot Tea. What size?"
4. Say: **"Put soy on it"**
5. Bot responds: "Let's finish with your Hot Tea first. What size?" (soy was NOT added)
6. Say: **"No soy please"**
7. **BUG:** Bot says "I couldn't find soy in your order." — Confusing UX since soy was never added. Should say something like "No worries, soy wasn't added."

**Root cause:** Bot rejected the "Put soy on it" (redirected to finish config first), so soy was never added. When user then says "No soy please", the removal handler looks for "soy" in the item and can't find it. The error message is technically correct but misleading.

---

### Failure 2: "Can you add oat" not recognized during size question

**Category:** Add-modifier pattern not matched during config
**Test:** `test_failure_modifier_flow_20260213_162301_401219e9.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'd like a Chai Tea and also a The Classic BEC"**
3. Bot responds: "For the Chai Tea, what size?"
4. Say: **"With splenda please"**
5. Bot responds: "Sure, I've added Splenda. What size?"
6. Say: **"Without splenda"**
7. Bot responds: "OK, I've removed the Splenda. What size?"
8. Say: **"Can you add oat"**
9. **BUG:** Bot says "Sorry, we don't have Can you add oat. We have Small or Large." — Should recognize "Can you add oat" as an add-modifier request and add Oat Milk.

**Root cause:** The `ADD_MODIFIER_PATTERN` matches "Can you add X" but the input is being intercepted by an earlier code path that treats it as an answer to the pending "What size?" question. The filler stripping fix was applied to `handle_add_modifiers_during_config()` but the add-modifier check may not be running before the config answer handler.

---

### Failure 3: "3 Bagel Package" — numeric prefix item not recognized

**Category:** Item name with leading number
**Test:** `test_failure_single_item_20260213_162404_002b1a1c.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'd like a 3 Bagel Package"**
3. **BUG:** Bot says "We don't have 3 Bagel Package. Did you mean 3 Bagel Package or 6 Bagel Package?" — Shows the exact item name but says it doesn't have it. The "3" is being parsed as a quantity instead of as part of the item name.

**Root cause:** The deterministic parser strips leading numbers as quantities. "3 Bagel Package" → qty=3 + "Bagel Package". "Bagel Package" alone doesn't match any item. The parser needs to handle items where the number is part of the name (e.g., "3 Bagel Package", "6 Bagel Package").

---

## Summary

| # | Failure | Category | Severity |
|---|---------|----------|----------|
| 1 | "No soy" — modifier was never added | UX / error messaging | Low |
| 2 | "Can you add oat" not matched during size question | Pattern matching priority | Medium |
| 3 | "3 Bagel Package" number parsed as quantity | Item recognition | Medium |

### Key Improvement
The two **high severity** bugs from run 11 (modifier removal deleting entire items) did NOT appear in run 12. The fixes are working. The remaining 3 failures are lower severity edge cases.
