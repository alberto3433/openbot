# Chaos Monkey Regression Test Failures — Run 15

**Generated:** 2026-02-13
**Live Runs:**
- Multi-item focused: `python -m tests.chaos_monkey.cli -d 150 -b 20 -r 60 --request-delay 0.5 --scenario-type multi_item --report-path tests/chaos_monkey_failures_run15_multi.md`
- Mixed scenarios: `python -m tests.chaos_monkey.cli -d 150 -b 20 -r 60 --request-delay 0.5 --report-path tests/chaos_monkey_failures_run15_mixed.md`

**Combined Results:** 115/120 passed, 5 failed (95.8%)
- Multi-item focused: 58/60 passed, 2 failed (96.7%)
- Mixed scenarios: 57/60 passed, 3 failed (95%)

---

## Progress Tracker

| Run | Passed | Failed | Total | Pass Rate | Focus |
|-----|--------|--------|-------|-----------|-------|
| 7   | 86     | 14     | 100   | 86%       | mixed |
| 8   | 94     | 6      | 100   | 94%       | mixed |
| 9   | 93     | 7      | 100   | 93%       | mixed |
| 10  | 113    | 7      | 120   | 94%       | mixed |
| 11  | 94     | 6      | 100   | 94%       | mixed |
| 12  | 97     | 3      | 100   | 97%       | mixed |
| 13  | 117    | 3      | 120   | 97.5%     | mixed |
| 14  | 119    | 1      | 120   | 99.2%     | mixed |
| **15** | **115** | **5** | **120** | **95.8%** | **multi-item + mixed** |

## Run 15 Failures (5 total)

### Failure 1: "well Add a Joe's Lemonade" — filler "well" not stripped during config

**Category:** Filler not stripped in config add-item path
**Test:** `test_failure_multi_item_20260213_221006_48b4d289.py`

**How to reproduce in UI:**
1. Open the chat at `http://localhost:8000`
2. Say: **"Can I get a The Reuben"**
3. Bot responds: "Got it, for the The Reuben. What kind of bread would you like?"
4. Say: **"well Add a Joe's Lemonade"**
5. **BUG:** Bot says "Sorry, we don't have well Add a Joe's Lemonade." — Filler "well" at the start is not being stripped, so the add-item pattern doesn't match.

**Root cause:** Filler stripping is applied in `handle_add_modifiers_during_config()` but not in the code path that checks for adding a new item during config (i.e., `handle_add_item_during_config()`). "well" stays in the input, breaking the pattern match.

---

### Failure 2: "um And a Peanut Butter Sandwich" — filler "um" not stripped during config

**Category:** Filler not stripped in config add-item path
**Test:** `test_failure_multi_item_20260213_221209_10bb0e44.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'll have a Kalamata Olive Feta Cream Cheese Sandwich"**
3. Bot responds: "What kind of bread would you like?"
4. Say: **"um And a Peanut Butter Sandwich"**
5. **BUG:** Bot says "Sorry, we don't have um And a Peanut Butter Sandwich." — Same as above. "um" not stripped.

**Root cause:** Same as Failure 1. The add-item-during-config code path doesn't strip fillers.

---

### Failure 3: "Skip the hmm gf wrap" — filler "hmm" inside cancel target

**Category:** Mid-phrase filler in removal target
**Test:** `test_failure_modifier_flow_20260213_221316_e61d10f2.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"Swiss Cheese Sandwich and The Health Nut please"**
3. Bot responds: "For the Swiss Cheese Sandwich, what kind of bread would you like?"
4. Say: **"Can you add gf wrap"**
5. Bot responds: "Got it, Gluten Free Wrap. Toast it?"
6. Say: **"Skip the hmm gf wrap"**
7. **BUG:** Bot says "I couldn't find hmm gf wrap." — "hmm" between "the" and "gf wrap" corrupts the removal target.

**Root cause:** `check_cancellation_during_config()` does strip fillers from the start of input, but "hmm" appears inside the extracted cancel target ("hmm gf wrap"). The filler is injected after the "Skip the" prefix is stripped. The cancel target extraction doesn't strip fillers from the extracted modifier name.

---

### Failure 4: "Remove the smoked trout please and thank you" — trailing "please and" not stripped

**Category:** Trailing filler in removal target
**Test:** `test_failure_modifier_flow_20260213_221402_e47eae03.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"Can I get a The Pizza BEC with Bacon and a The Lexington"**
3. Bot responds: "For the Pizza BEC, what kind of bread would you like?"
4. Say: **"I'd like smoked trout on that"**
5. Bot responds: "Let's finish with your Pizza BEC first."
6. Say: **"Remove the smoked trout please and thank you"**
7. **BUG:** Bot says "I couldn't find smoked trout please and." — The trailing "please and thank you" is partially stripped (only "thank you" removed), leaving "smoked trout please and" as the cancel target.

**Root cause:** The trailing filler stripping in `check_cancellation_during_config()` uses `TRAILING_FILLERS` to strip suffixes, but "please and thank you" is being partially matched — "thank you" is stripped but "please and" remains.

---

### Failure 5: "Hold the gluten-free everything" — disambiguation answer treated as modifier

**Category:** Removing item that was never added (disambiguation pending)
**Test:** `test_failure_modifier_flow_20260213_221510_363dd4dd.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"Can I get a The Latke BEC"**
3. Bot responds: "What kind of bread would you like?"
4. Say: **"Add gluten-free everything to that"**
5. Bot responds with disambiguation: "We have Gluten Free Everything Bagel, Everything Bagel, ... Which would you like?"
6. Say: **"Hold the gluten-free everything"**
7. **BUG:** Bot says "I couldn't find gluten-free everything." — The item was never added because disambiguation was pending. User changed their mind but the bot treats it as a removal.

**Root cause:** When disambiguation is pending and the user says "Hold the X", it's interpreted as a removal request. But X was never added to the order (user hadn't picked from the disambiguation list yet). Should cancel the disambiguation instead.

---

## Summary

| # | Failure | Category | Severity |
|---|---------|----------|----------|
| 1 | "well Add a Joe's Lemonade" — filler not stripped in add-item-during-config | Filler stripping gap | **Medium** |
| 2 | "um And a Peanut Butter Sandwich" — same | Filler stripping gap | **Medium** |
| 3 | "Skip the hmm gf wrap" — filler inside cancel target | Mid-phrase filler | Low |
| 4 | "smoked trout please and thank you" — partial trailing strip | Trailing filler stripping | Low |
| 5 | "Hold the gluten-free everything" — disambiguation not cancelled | Disambiguation UX | Low |

### Key Finding
Failures 1 and 2 reveal a new filler stripping gap: `handle_add_item_during_config()` doesn't call `strip_conversational_fillers()`. This is the same pattern we fixed earlier for `handle_add_modifiers_during_config()` — the fix just needs to be applied to the add-item path too.
