# Chaos Monkey Regression Test Failures — Run 13

**Generated:** 2026-02-13
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --report-path tests/chaos_monkey_failures_run13.md`
**Live Results:** 117/120 passed, 3 failed (97.5%)

---

## Progress Tracker

| Run | Passed | Failed | Total | Pass Rate |
|-----|--------|--------|-------|-----------|
| 7   | 86     | 14     | 100   | 86%       |
| 8   | 94     | 6      | 100   | 94%       |
| 9   | 93     | 7      | 100   | 93%       |
| 10  | 113    | 7      | 120   | 94%       |
| 11  | 94     | 6      | 100   | 94%       |
| 12  | 97     | 3      | 100   | 97%       |
| **13** | **117** | **3** | **120** | **97.5%** |

## Run 13 Failures (3 total)

### Failure 1: "Also add sweet oh n low" — filler "oh" inside modifier name breaks matching

**Category:** Filler word injected mid-phrase
**Test:** `test_failure_modifier_flow_20260213_170627_25aa3ef9.py`

**How to reproduce in UI:**
1. Open the chat at `http://localhost:8000`
2. Say: **"I'd like a Iced Cappucino and also a Tofu Spread Sandwich"**
3. Bot responds: "For the Iced Cappucino, what size?"
4. Say: **"Also add sweet oh n low"**
5. **BUG:** Bot says "Sorry, we don't have Also add sweet oh n low." — The filler "oh" is in the middle of "sweet n low", corrupting the modifier name. Filler stripping only removes from the start.

**Root cause:** `strip_conversational_fillers()` strips fillers from the **beginning** of input only. When the chaos monkey injects "oh" in the middle ("sweet oh n low"), the modifier name becomes unrecognizable. This is a mutation artifact — real users rarely insert fillers mid-word. Low priority.

---

### Failure 2: "Can uh you add skim" — filler "uh" inside pattern breaks regex

**Category:** Filler word injected inside regex pattern
**Test:** `test_failure_modifier_flow_20260213_170638_8d2d5a87.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'd like a Iced Cappucino and also a Kalamata Olive Feta Cream Cheese Sandwich"**
3. Bot responds: "For the Iced Cappucino, what size?"
4. Say: **"Can uh you add skim"**
5. **BUG:** Bot says "Sorry, we don't have Can uh you add skim." — The filler "uh" between "Can" and "you" breaks the `ADD_MODIFIER_PATTERN` regex which expects `can\s+you\s+add`.

**Root cause:** Same as above — filler stripping only removes from the start. "Can uh you add" doesn't match `^can\s+you\s+add` because "uh" is between "can" and "you". A mid-phrase filler strip would fix this, but it's a mutation artifact.

---

### Failure 3: "Side well of Cucumbers" — filler "well" breaks item name

**Category:** Filler word injected inside item name
**Test:** `test_failure_single_item_20260213_170810_ac164eb2.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"One Side well of Cucumbers please"**
3. **BUG:** Bot says "What can I get for you?" — doesn't recognize the item. The filler "well" inserted between "Side" and "of Cucumbers" breaks the item name match.

**Root cause:** Same pattern — filler "well" injected mid-phrase. "Side well of Cucumbers" doesn't match "Side of Cucumbers". Filler stripping only removes from the start.

---

## Summary

| # | Failure | Category | Severity |
|---|---------|----------|----------|
| 1 | "sweet oh n low" — filler mid-modifier | Mid-phrase filler | Low |
| 2 | "Can uh you add" — filler mid-pattern | Mid-phrase filler | Low |
| 3 | "Side well of Cucumbers" — filler mid-item name | Mid-phrase filler | Low |

### Analysis

All 3 failures are caused by the chaos monkey injecting filler words **in the middle** of phrases, not at the beginning. The current `strip_conversational_fillers()` only strips from the start. These are mutation artifacts — real users are unlikely to say "Can uh you add" or "sweet oh n low".

**Options:**
1. **Do nothing** — these are unrealistic inputs, 97.5% pass rate is good
2. **Add mid-phrase filler stripping** — strip known fillers from anywhere in the input before parsing. Risk: could accidentally strip valid words (e.g., "well done" → "done")
3. **Adjust chaos monkey** — don't inject fillers inside known patterns or item names
