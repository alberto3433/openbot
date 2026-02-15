# Chaos Monkey Regression Test Failures — Run 16 (Tricky Scenarios)

**Generated:** 2026-02-14
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --mutation-prob 0 --scenario-type tricky --report-path tests/chaos_monkey_failures_run16_tricky.md`
**Live Results:** 85/120 passed, 35 failed (70.8%)

**Focus:** Out-of-place inputs — no filler words, just tricky conversational patterns that try to confuse the bot (config answer for wrong item, multi-attribute orders, context switching mid-config, changing answered config, repeat ordering during config, early answers).

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
| 15  | 115    | 5      | 120   | 95.8%     | multi-item + mixed |
| **16** | **85** | **35** | **120** | **70.8%** | **tricky (out-of-place inputs)** |

---

## Run 16 Failures by Category (35 total)

### Category 1: Change Config Not Recognized (11 failures) — **High Severity**

When a user pre-fills an attribute (e.g., "toasted" in "toasted Pepper Jack Cheese Sandwich") and then tries to change it during config, the bot interprets "no wait, untoasted" or "scratch that, no toasted" as a removal command and fails.

**Root cause:** The config handler has no concept of "change a previously-answered attribute." Phrases like "no wait, X", "scratch that, no X", and "actually X instead" are parsed as cancel/removal patterns. The text after "no" or "scratch that" is extracted as a cancel target, but it doesn't match any modifier or ingredient in the order.

#### Failure 1: "no wait, untoasted" — change_config on toasted attribute

**Test:** `test_failure_tricky_20260214_221016_6c5b0986.py`

**How to reproduce in UI:**
1. Open the chat at `http://localhost:8000`
2. Say: **"toasted The Lexington"**
3. Bot responds: "Got it, for the The Lexington. What kind of bread would you like?"
4. Say: **"no wait, untoasted"**
5. **BUG:** Bot says "I couldn't find wait, untoasted in your order." — Bot interprets "no wait, untoasted" as a removal command.

#### Failure 2: "no wait, Provolone Cheese instead" — change_config on cheese attribute

**Test:** `test_failure_tricky_20260214_221020_e364882a.py`

**How to reproduce in UI:**
1. Say: **"I'll have a Pepper Jack Cheese The Classic BEC Omelette"**
2. Bot responds: "Got it, for the The Classic BEC Omelette. Would you like a bagel or fruit salad with it?"
3. Say: **"no wait, Provolone Cheese instead"**
4. **BUG:** Bot says "I couldn't find wait, provolone cheese instead in your order."

#### Failure 3: "scratch that, no toasted" — change_config on toasted

**Test:** `test_failure_tricky_20260214_221053_631faa11.py`

**How to reproduce in UI:**
1. Say: **"I'll have a toasted Pepper Jack Cheese Sandwich"**
2. Bot responds: "What kind of bread would you like?"
3. Say: **"scratch that, no toasted"**
4. **BUG:** Bot says "I couldn't find that, no toasted in your order."

#### Other change_config failures (same pattern):
- "no wait, unscooped" on Nova Cream Cheese Sandwich (Failure 4)
- "scratch that, no toasted" on Maple Raisin Walnut Cream Cheese Sandwich (Failure 5)
- "no wait, Pepper Jack Cheese instead" on The Chipotle Egg Omelette (Failure 6)
- "scratch that, no toasted" on The Columbus BEC (Failure 7)
- "wait, don't toasted it" on Egg and Cheese Sandwich (Failure 8)
- "no wait, unscooped" on Grape Jelly Sandwich (Failure 9)
- "no wait, untoasted" on The Tuna Melt (Failure 10)
- "scratch that, no scooped" on Scallion Tofu Spread Sandwich (Failure 11)
- "switch to Havarti Cheese" on The Lexington Omelette (Failure 12, System Error)

---

### Category 2: Add Item During Config Not Recognized (5 failures) — **High Severity**

When a configurable item is being configured (bot asking about bread), phrases like "Can I also get a X" and "And also a X" are not recognized as add-item commands. The bot treats the entire input as a config answer.

**Root cause:** The `handle_add_item_during_config()` function doesn't match all add-item patterns. Specifically, "Can I also get a X" and "And also a X" are not recognized.

#### Failure 13: "Can I also get a Chai Tea" during Pepperoni Pizza Bagel config

**Test:** `test_failure_tricky_20260214_220941_20588cb8.py`

**How to reproduce in UI:**
1. Say: **"Can I get a Pepperoni Pizza Bagel"**
2. Bot responds: "What kind of bread would you like?"
3. Say: **"Can I also get a Chai Tea"**
4. **BUG:** Bot says "Sorry, we don't have Can I also get a Chai Tea." — Entire input treated as bread answer.

#### Failure 14: "And also a Vitamin Water Focus" during config

**Test:** `test_failure_tricky_20260214_221249_6f3d5246.py`

**How to reproduce in UI:**
1. Say: **"I'd like a Cinnamon Sugar Butter Sandwich"**
2. Bot responds: "What kind of bread would you like?"
3. Say: **"And also a Vitamin Water Focus"**
4. **BUG:** Bot says "Sorry, we don't have And also a Vitamin Water Focus."

#### Failure 15: "Can I also get a Hummus Sandwich" during config

**Test:** `test_failure_tricky_20260214_221413_a09716d7.py`

**How to reproduce in UI:**
1. Say: **"One The RB Prime"**
2. Bot responds: "What kind of bread would you like?"
3. Say: **"Can I also get a Hummus Sandwich"**
4. **BUG:** Bot says "Sorry, we don't have Can I also get a Hummus Sandwich."

#### Failure 16: "And also a Scottish Salmon" during config

**Test:** `test_failure_tricky_20260214_221342_afb7a959.py`

Same pattern — "And also a X" not recognized during config.

#### Failure 17: "And a Fluffernutter Sandwich" during config

Same pattern.

---

### Category 3: Repeat Item During Config Not Recognized (3 failures) — **Medium Severity**

When ordering the same item again during config ("I'll also have a X"), the bot treats it as a config answer instead of an add-item command.

**Root cause:** Same as Category 2 — the add-item-during-config handler doesn't recognize "I'll also have a X" or "also one X" patterns.

#### Failure 18: "I'll also have a Black Forest Ham Sandwich" during config

**Test:** `test_failure_tricky_20260214_221235_572641b6.py`

**How to reproduce in UI:**
1. Say: **"Can I get a Black Forest Ham Sandwich"**
2. Bot responds: "What kind of bread would you like?"
3. Say: **"I'll also have a Black Forest Ham Sandwich"**
4. **BUG:** Bot says "Sorry, we don't have I'll also have a Black Forest Ham Sandwich."

#### Failure 19: "I'll also have a Pastrami Salmon Sandwich"

**Test:** `test_failure_tricky_20260214_221244_c338bf1c.py`

Same pattern.

#### Failure 20: "I'll also have a Tofu Vegetable Sandwich"

**Test:** `test_failure_tricky_20260214_221440_a315b49e.py`

Same pattern.

---

### Category 4: System Errors / 500s (4 failures) — **Critical Severity**

The bot returns "I'm sorry, I'm having trouble processing your request right now" — this indicates a server-side exception (500 error).

**Root cause:** Unhandled exceptions in the state machine when processing certain input patterns during omelette/item configuration.

#### Failure 21: "Blueberry Bagel for the Chocolate Babka Slice" causes 500

**Test:** `test_failure_tricky_20260214_220939_f62f16ec.py`

**How to reproduce in UI:**
1. Say: **"I'll have a The Columbus BEC Omelette and a Chocolate Babka Slice"**
2. Bot responds: "Would you like a bagel or fruit salad with it?"
3. Say: **"Blueberry Bagel for the Chocolate Babka Slice"**
4. **BUG:** Bot says "I'm sorry, I'm having trouble processing your request right now." — Server 500 error.

#### Failure 22: "blueberry bagel" for omelette side question causes 500

**Test:** `test_failure_tricky_20260214_221348_3a5e5e58.py`

**How to reproduce in UI:**
1. Say: **"One The Delancey Omelette with Corned Beef"**
2. Bot responds: "Would you like a bagel or fruit salad with it?"
3. Say: **"blueberry bagel"**
4. **BUG:** Server 500 error.

#### Failure 23: "switch to Havarti Cheese" for omelette causes 500

**Test:** `test_failure_tricky_20260214_221420_6b38a577.py`

**How to reproduce in UI:**
1. Say: **"I'll have a Cheddar Cheese The Lexington Omelette"**
2. Bot responds: "Would you like a bagel or fruit salad with it?"
3. Say: **"switch to Havarti Cheese"**
4. **BUG:** Server 500 error.

#### Failure 24: "sesame sourdough bagel" for omelette side causes 500

**Test:** `test_failure_tricky_20260214_221434_bbe83d12.py`

**How to reproduce in UI:**
1. Say: **"Blueberry Bagel The Health Nut Omelette with sausage patty"**
2. Bot responds: "Would you like a bagel or fruit salad with it?"
3. Say: **"sesame sourdough bagel"**
4. **BUG:** Server 500 error.

---

### Category 5: Context Switch Not Parsed (3 failures) — **Low Severity**

When the user tries to direct a config answer to a different item ("for the Danish I want toasted and Scallion Cream Cheese"), the bot treats the entire input as a config answer for the current item.

**Root cause:** The config handler doesn't parse "for the X" redirections. The entire input is treated as a single config value.

#### Failure 25: "for the Danish I want toasted and Scallion Cream Cheese"

**Test:** `test_failure_tricky_20260214_221130_f1c97701.py`

**How to reproduce in UI:**
1. Say: **"Can I get a Whitefish Salad Sandwich and a Danish"**
2. Bot responds: "For the Whitefish Salad Sandwich, what kind of bread would you like?"
3. Say: **"for the Danish I want toasted and Scallion Cream Cheese"**
4. **BUG:** Bot says "Sorry, we don't have for the Danish I want toasted and Scallion Cream Cheese."

#### Failure 26: "Kettle Cooked Smokehouse BBQ Potato Chips Vanilla Chai"

**Test:** `test_failure_tricky_20260214_221137_aa767a53.py`

Context switch with incorrect attribute application.

#### Failure 27: "make the Sun-Dried Tomato Cream Cheese toasted and Vegetable Cream Cheese"

**Test:** `test_failure_tricky_20260214_221330_a123dd35.py`

Context switch where "make the X Y" isn't parsed.

---

### Category 6: Early Answer / Modifier as Config Answer (5 failures) — **Low Severity**

When the bot asks a config question (e.g., "What kind of bread?") and the user gives a modifier name that's valid for the item but doesn't answer the specific question, the bot says "not found."

**Root cause:** The config handler tries to match user input against the current question's valid options. Modifier names (ingredients) aren't in the bread options list, so they fail.

#### Failure 28: "breakfast potato latke" when asked about bread

**Test:** `test_failure_tricky_20260214_220914_1c745a00.py`

**How to reproduce in UI:**
1. Say: **"Can I get a Nutella Sandwich"**
2. Bot responds: "What kind of bread would you like?"
3. Say: **"breakfast potato latke"**
4. **BUG:** Bot says "Sorry, we don't have breakfast potato latke." — This IS a valid ingredient but not a bread type. Bot should either add it as a modifier or say "that's not a bread option."

#### Failure 29: "sable" when asked about config question

**Test:** `test_failure_tricky_20260214_221251_84f65329.py`

#### Failure 30: "soy" when asked about size

**Test:** `test_failure_tricky_20260214_221417_13b5f4f3.py`

#### Failure 31: "regular cream cheese" when asked about bread

**Test:** `test_failure_tricky_20260214_221448_9b14d92b.py`

---

### Category 7: Multi-Attribute Modifier Order Not Parsed (3 failures) — **Low Severity**

When modifiers are given as standalone answers during config, some aren't recognized.

#### Failure 32: "nova" not recognized during config

**Test:** `test_failure_tricky_20260214_221218_859d929e.py`

#### Failure 33: "wild coho salmon" not recognized during config

**Test:** `test_failure_tricky_20260214_221258_79445267.py`

#### Failure 34: "asiago bagel" treated as modifier, not bread answer

**Test:** `test_failure_tricky_20260214_221337_1747b5c4.py`

---

### Category 8: Disambiguation Causes Cart Empty (1 failure) — **Low Severity**

#### Failure 35: "Bagel" triggers disambiguation, cart is empty

**Test:** `test_failure_tricky_20260214_221454_951e93dc.py`

**How to reproduce in UI:**
1. Say: **"I'd like a Bagel"**
2. Bot responds with disambiguation: "Which kind? We have 3 Bagel Package, 6 Bagel Package..."
3. Cart is empty because disambiguation hasn't resolved yet.
4. **Expected behavior** — not really a bug, but the test expects item in cart immediately.

---

## Summary

| # | Category | Count | Severity |
|---|----------|-------|----------|
| 1 | Change config not recognized ("no wait, X", "scratch that, X") | 11 | **High** |
| 2 | Add item during config not recognized ("Can I also get", "And also") | 5 | **High** |
| 3 | Repeat item during config not recognized ("I'll also have a X") | 3 | **Medium** |
| 4 | System errors / 500s (omelette side question handling) | 4 | **Critical** |
| 5 | Context switch not parsed ("for the X I want Y") | 3 | Low |
| 6 | Early answer / modifier as config answer | 5 | Low |
| 7 | Multi-attribute modifier not parsed during config | 3 | Low |
| 8 | Disambiguation cart empty (test issue) | 1 | Low |
| **Total** | | **35** | |

### Key Findings

**Critical (fix immediately):**
- **4 Server 500 errors** when answering omelette side question with specific bagel names ("blueberry bagel", "sesame sourdough bagel") or switching cheese. These are unhandled exceptions that crash the request.

**High priority:**
- **11 "change config" failures** — The bot has no way to handle "no wait, X" or "scratch that, X" to change a previously-answered attribute. This is a missing feature: users need to be able to change their mind about a config answer.
- **8 "add item during config" failures** (Categories 2+3) — The add-item-during-config handler is missing patterns: "Can I also get a X", "And also a X", "I'll also have a X". These are common phrases real users would use.

**Low priority:**
- Context switch parsing ("for the X I want Y") — Complex feature, not commonly needed
- Early answers (giving modifiers when asked about bread) — Edge case behavior
- Multi-attribute modifier parsing — Some modifier names not recognized in config context
