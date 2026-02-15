# Chaos Monkey Regression Test Failures — Run 17 (Tricky Scenarios)

**Generated:** 2026-02-15
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --mutation-prob 0 --scenario-type tricky --report-path tests/chaos_monkey_failures_run17_tricky.md`
**Live Results:** 91/120 passed, 29 failed (75.8%)

**Focus:** Out-of-place inputs — no filler words, just tricky conversational patterns.

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
| 16  | 85     | 35     | 120   | 70.8%     | tricky |
| **17** | **91** | **29** | **120** | **75.8%** | **tricky** |

---

## Run 17 Failures (29 total)

### Category 1: Change Config Not Recognized (8 failures) — **High Severity**

When a user pre-fills a boolean attribute (e.g., "toasted") and then tries to change it during config, the bot fails. Phrases like "no wait, untoasted", "scratch that, no toasted", and "wait, don't toasted it" are not understood.

**Root cause:** No handler exists for changing a previously-answered attribute during config. These phrases are parsed as removal commands, which fail because "wait, untoasted" isn't a modifier in the order.

#### Failure 1: "scratch that, no toasted"

**Test:** `test_failure_tricky_20260215_121935_c8b37144.py`

**How to reproduce in UI:**
1. Say: **"I'll have a toasted Sable Sandwich"**
2. Bot: "What kind of bread would you like?"
3. Say: **"scratch that, no toasted"**
4. **BUG:** Bot says "I couldn't find that, no toasted in your order."

#### Failure 2: "no wait, untoasted"

**Test:** `test_failure_tricky_20260215_122020_095ce01d.py`

**How to reproduce in UI:**
1. Say: **"I'll have a toasted Pastrami Salmon Sandwich"**
2. Bot: "What kind of bread would you like?"
3. Say: **"no wait, untoasted"**
4. **BUG:** Bot says "I couldn't find wait, untoasted in your order."

#### Failure 3: "wait, don't toasted it"

**Test:** `test_failure_tricky_20260215_122023_412269a3.py`

**How to reproduce in UI:**
1. Say: **"I'll have a toasted Jalapeno Honey Cream Cheese Sandwich"**
2. Bot: "What kind of bread would you like?"
3. Say: **"wait, don't toasted it"**
4. **BUG:** Bot says "Sorry, we don't have wait, don't toasted it."

#### Other change_config failures (same pattern):
- "scratch that, no scooped" on Truffle Cream Cheese Sandwich
- "scratch that, no toasted" on The Pizza BEC with Pepperoni
- "wait, don't toasted it" on Tuna Salad Sandwich
- "scratch that, no toasted" on Nutella Sandwich
- "switch to Skim Milk" on Hot Coffee

---

### Category 2: Add Item During Config Not Recognized (8 failures) — **High Severity**

When configuring an item and the user says "Can I also get a X", "And also a X", or "And a X", the bot treats the entire sentence as a config answer instead of recognizing it as an add-item command.

**Root cause:** `handle_add_item_during_config()` doesn't match patterns like "Can I also get a X", "And also a X".

#### Failure 9: "Can I also get a Joyva Halva Chocolate" during Iced Chai Tea config

**Test:** `test_failure_tricky_20260215_121903_48d13502.py`

**How to reproduce in UI:**
1. Say: **"One Iced Chai Tea"**
2. Bot: "What size?"
3. Say: **"Can I also get a Joyva Halva Chocolate"**
4. **BUG:** Bot says "Sorry, we don't have Can I also get a Joyva Halva Chocolate. We have Small or Large."

#### Failure 10: "And also a Hot Tea" during Hot Cappuccino config

**Test:** `test_failure_tricky_20260215_122034_84c1da24.py`

**How to reproduce in UI:**
1. Say: **"Can I get a Hot Cappuccino"**
2. Bot: "What size?"
3. Say: **"And also a Hot Tea"**
4. **BUG:** Bot says "Sorry, we don't have And also a Hot Tea. We have Small or Large."

#### Failure 11: "Can I also get a Peanut Butter Cookie"

**Test:** `test_failure_tricky_20260215_122204_2623187d.py`

#### Failure 12: "Can I also get a Bjorn Qorn Popcorn"

**Test:** `test_failure_tricky_20260215_122206_4e93a5ad.py`

#### Failure 13: "And also a Side of Tomato"

**Test:** `test_failure_tricky_20260215_122234_e2f4e21b.py`

#### Failure 14: "Can I also get a Chocolate Babka"

**Test:** `test_failure_tricky_20260215_122309_63c8374b.py`

#### Failure 15: "Can I also get a Salami"

**Test:** `test_failure_tricky_20260215_122359_4b5adb39.py`

#### Failure 16: "And also a Tropicana Orange Juice 46 oz" (also 500 error)

**Test:** `test_failure_tricky_20260215_122221_3b249b31.py`

---

### Category 3: Repeat Item During Config Not Recognized (2 failures) — **Medium Severity**

Same root cause as Category 2 — "I'll also have a X" not caught as add-item.

#### Failure 17: "I'll also have a The Truffled Egg"

**Test:** `test_failure_tricky_20260215_122018_d0a2b713.py`

**How to reproduce in UI:**
1. Say: **"Can I get a The Truffled Egg"**
2. Bot: "What kind of bread would you like?"
3. Say: **"I'll also have a The Truffled Egg"**
4. **BUG:** Bot says "Sorry, we don't have I'll also have a The Truffled Egg."

#### Failure 18: "I'll also have a The Mulberry"

**Test:** `test_failure_tricky_20260215_122344_1c3c2f2d.py`

---

### Category 4: System Errors / 500s (5 failures) — **Critical Severity**

Server 500 errors — unhandled exceptions. All involve omelettes or items with a "side choice" attribute (the "bagel or fruit salad?" question).

**Root cause:** The handler for the omelette side-choice question crashes when it receives:
- A specific bagel name (e.g., "provolone cheese" when asked about bagel/fruit salad)
- An add-item command ("And also a X")
- A context-switch ("for the X I want Y")

#### Failure 19: "provolone cheese" to omelette side question

**Test:** `test_failure_tricky_20260215_121926_d92d53f3.py`

**How to reproduce in UI:**
1. Say: **"Pepper Jack Cheese The Mulberry Omelette with breakfast potato latke"**
2. Bot: "Would you like a bagel or fruit salad with it?"
3. Say: **"provolone cheese"**
4. **BUG:** Server 500 error.

#### Failure 20: "And also a Tropicana Orange Juice 46 oz" to omelette side question

**Test:** `test_failure_tricky_20260215_122221_3b249b31.py`

**How to reproduce in UI:**
1. Say: **"One The Delancey Omelette with Pastrami"**
2. Bot: "Would you like a bagel or fruit salad with it?"
3. Say: **"And also a Tropicana Orange Juice 46 oz"**
4. **BUG:** Server 500 error.

#### Failure 21: "for the Turkey Breast I want American Cheese" to omelette side question

**Test:** `test_failure_tricky_20260215_122238_a0a86f63.py`

**How to reproduce in UI:**
1. Say: **"Can I get a The Delancey Omelette with Pastrami and a Turkey Breast"**
2. Bot: "Would you like a bagel or fruit salad with it?"
3. Say: **"for the Turkey Breast I want American Cheese"**
4. **BUG:** Server 500 error.

#### Failure 22: "for the Bagel I want Rainbow Bagel" to omelette side question

**Test:** `test_failure_tricky_20260215_122402_f9be2372.py`

#### Failure 23: "And also a Iced Cappucino" to omelette side question

**Test:** `test_failure_tricky_20260215_122424_e67ed9ba.py`

---

### Category 5: Modifier as Config Answer (3 failures) — **Low Severity**

Giving a modifier name when asked a different config question (e.g., saying "strawberry jam" when asked about bread).

#### Failure 24: "strawberry jam" when asked about bread

**Test:** `test_failure_tricky_20260215_122029_60aae3bf.py`

#### Failure 25: "splenda" when asked about espresso shots

**Test:** `test_failure_tricky_20260215_122059_daf87491.py`

#### Failure 26: "oat milk" when asked about size

**Test:** `test_failure_tricky_20260215_121917_c835871e.py`

---

### Category 6: Multi-Attribute Modifier Not Parsed During Config (5 failures) — **Low Severity**

During config, the bot doesn't recognize some modifiers or attribute options given as answers.

#### Failure 27: "beefsteak tomatoes" not recognized

**Test:** `test_failure_tricky_20260215_122436_ea749edf.py`

#### Failure 28: "blueberry bagel" not recognized as egg_style answer

**Test:** `test_failure_tricky_20260215_122210_ece6136b.py`

#### Failure 29: "bread" causes "I couldn't find bread"

**Test:** `test_failure_tricky_20260215_122325_8624d6d0.py`

---

## Summary

| # | Category | Count | Severity |
|---|----------|-------|----------|
| 1 | Change config not recognized | 8 | **High** |
| 2 | Add item during config not recognized | 8 | **High** |
| 3 | Repeat item during config not recognized | 2 | **Medium** |
| 4 | System errors / 500s (omelette side-choice handler) | 5 | **Critical** |
| 5 | Modifier as config answer | 3 | Low |
| 6 | Multi-attribute modifier not parsed | 3 | Low |
| **Total** | | **29** | |

### Key Findings

**Run 16 vs Run 17 comparison:**
- Run 16: 85/120 (70.8%) — Run 17: 91/120 (75.8%)
- Slightly fewer failures in run 17 due to random scenario variation, but same root causes

**Top 3 issues to fix (by impact):**

1. **500 errors on omelette side-choice question (5 failures, Critical):** The omelette "Would you like a bagel or fruit salad?" handler crashes on unexpected input. ANY non-standard answer causes a server error. This is the most urgent fix.

2. **Add item during config missing patterns (10 failures, High):** `handle_add_item_during_config()` doesn't recognize "Can I also get a X", "And also a X", or "I'll also have a X". These are extremely common real-user phrases.

3. **Change config not supported (8 failures, High):** No handler exists for phrases like "no wait, untoasted", "scratch that, no toasted", "switch to X". Users need to be able to change their mind about a previously-given config answer.
