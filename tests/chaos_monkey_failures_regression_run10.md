# Chaos Monkey Regression Test Failures — Run 18 (Tricky Scenarios)

**Generated:** 2026-02-15
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --mutation-prob 0 --scenario-type tricky --report-path tests/chaos_monkey_failures_run18_tricky.md`
**Live Results:** 90/120 passed, 30 failed (75%)

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
| 17  | 91     | 29     | 120   | 75.8%     | tricky |
| **18** | **90** | **30** | **120** | **75%** | **tricky** |

---

## Run 18 Failures (30 total)

### Category 1: Change Config Not Recognized (8 failures) — **High Severity**

User pre-fills a boolean/select attribute then tries to change it during config. Bot interprets "no wait, X" / "scratch that, X" / "wait, don't X" as a removal command and fails.

**Root cause:** No handler for changing a previously-answered attribute during config.

#### Failure 1: "wait, don't toasted it"

**Test:** `test_failure_tricky_20260215_171405_9d97ad4c.py`

**How to reproduce in UI:**
1. Say: **"toasted The Classic"**
2. Bot: "What kind of bread would you like?"
3. Say: **"wait, don't toasted it"**
4. **BUG:** Bot says "Sorry, we don't have wait, don't toasted it."

#### Failure 2: "scratch that, no toasted"

**Test:** `test_failure_tricky_20260215_171415_26843cb5.py`

**How to reproduce in UI:**
1. Say: **"toasted The Delancey with Pastrami"**
2. Bot: "What kind of bread?"
3. Say: **"scratch that, no toasted"**
4. **BUG:** Bot says "I couldn't find that, no toasted in your order."

#### Other change_config failures (same pattern):
- "no wait, untoasted" on Mozzarella Cheese Sandwich (Failure 3)
- "no wait, untoasted" on The Traditional (Failure 4)
- "scratch that, no toasted" on Gravlax Sandwich (Failure 5)
- "no wait, untoasted" on The Margherita Pizza Bagel (Failure 6)
- "scratch that, no decaf" on Hot Cappuccino (Failure 7)
- "no wait, small instead" on Iced Chai Tea (Failure 8)

---

### Category 2: Add Item During Config Not Recognized (6 failures) — **High Severity**

Bot treats "And also a X", "Can I also get a X" as config answers instead of add-item commands.

**Root cause:** `handle_add_item_during_config()` missing these patterns.

#### Failure 9: "And also a Belly Lox Sandwich"

**Test:** `test_failure_tricky_20260215_171432_0c5c270b.py`

**How to reproduce in UI:**
1. Say: **"I'd like a The Max Borough"**
2. Bot: "What kind of bread?"
3. Say: **"And also a Belly Lox Sandwich"**
4. **BUG:** Bot says "Sorry, we don't have And also a Belly Lox Sandwich."

#### Failure 10: "Can I also get a American Cheese Sandwich"

**Test:** `test_failure_tricky_20260215_171443_a7666020.py`

#### Other add_item failures:
- "And also a The Tuna Melt" (Failure 11)
- "And also a Nova Cream Cheese Sandwich" (Failure 12)
- "And also a Side of Onion" (Failure 13)
- "Can I also get a Apricot Hamantaschen" on omelette (Failure 14, also 500 error)

---

### Category 3: Repeat Item During Config (3 failures) — **Medium Severity**

"I'll also have a X" not recognized as add-item during config.

#### Failure 15: "I'll also have a Cranberry Pecan Chicken Salad Sandwich"

**Test:** `test_failure_tricky_20260215_171408_c8752537.py`

#### Failure 16: "I'll also have a Iced Latte"

**Test:** `test_failure_tricky_20260215_171434_05531e38.py`

#### Failure 17: "I'll also have a Provolone Cheese Sandwich"

**Test:** `test_failure_tricky_20260215_171446_44dbb798.py`

---

### Category 4: System Errors / 500s (2 failures) — **Critical Severity**

Both involve omelettes — the "bagel or fruit salad?" side-choice handler crashes on unexpected input.

**Improvement from run 17:** Down from 5 system errors to 2.

#### Failure 18: "Can I also get a Apricot Hamantaschen" to omelette side question

**Test:** `test_failure_tricky_20260215_171530_1c29a7f4.py`

**How to reproduce in UI:**
1. Say: **"One The Classic BEC Omelette"**
2. Bot: "Would you like a bagel or fruit salad with it?"
3. Say: **"Can I also get a Apricot Hamantaschen"**
4. **BUG:** Server 500 error.

#### Failure 19: "Plain Bagel for the Chocolate Dipped Macaroons" to omelette side question

**Test:** `test_failure_tricky_20260215_171811_be2f10d5.py`

**How to reproduce in UI:**
1. Say: **"I'll have a The Columbus BEC Omelette and a Chocolate Dipped Macaroons"**
2. Bot: "Would you like a bagel or fruit salad with it?"
3. Say: **"Plain Bagel for the Chocolate Dipped Macaroons"**
4. **BUG:** Server 500 error.

---

### Category 5: Context Switch Not Parsed (3 failures) — **Low Severity**

Bot doesn't parse "for the X I want Y" or "make the X Y" as directing a config answer to a different item.

#### Failure 20: "make the Vitamin Water Dragonfruit toasted and Peanut Butter"

**Test:** `test_failure_tricky_20260215_171528_aca75bca.py`

#### Failure 21: "make the Side of Turkey Bacon Whole Milk"

**Test:** `test_failure_tricky_20260215_171545_f8eff249.py`

#### Failure 22: "Skim Milk for the Bagel Chips - Salt"

**Test:** `test_failure_tricky_20260215_171825_5390219c.py`

---

### Category 6: Modifier / Early Answer as Config Answer (4 failures) — **Low Severity**

Modifier names given in response to a different config question not recognized.

#### Failure 23: "regular cream cheese" when asked about bread

**Test:** `test_failure_tricky_20260215_171426_9f309890.py`

#### Failure 24: "russian dressing" when asked about bread

**Test:** `test_failure_tricky_20260215_171437_358c584e.py`

#### Failure 25: "pico de gallo" when asked about bread

**Test:** `test_failure_tricky_20260215_171847_1d76dbe6.py`

#### Failure 26: "lemon blueberry cream cheese" when asked about bread

**Test:** `test_failure_tricky_20260215_171941_dee4a1df.py`

---

### Category 7: Multi-Attribute Modifier Not Parsed (4 failures) — **Low Severity**

Some modifiers or attribute options not recognized during config context.

#### Failure 27: "white bread" when asked about egg style

**Test:** `test_failure_tricky_20260215_171419_61b98560.py`

#### Failure 28: "walnut raisin cream cheese" not recognized during egg_sandwich config

**Test:** `test_failure_tricky_20260215_171705_7f8e2f10.py`

#### Failure 29: "artisan bread" not recognized during spread_sandwich config

**Test:** `test_failure_tricky_20260215_171735_a8877910.py`

#### Failure 30: "domino sugar" not recognized during chai config

**Test:** `test_failure_tricky_20260215_171939_032989a0.py`

---

## Summary

| # | Category | Count | Severity | Run 17 | Run 18 | Trend |
|---|----------|-------|----------|--------|--------|-------|
| 1 | Change config not recognized | 8 | **High** | 8 | 8 | Same |
| 2 | Add item during config not recognized | 6 | **High** | 8 | 6 | Slight improvement |
| 3 | Repeat item during config | 3 | **Medium** | 2 | 3 | Same |
| 4 | System errors / 500s | 2 | **Critical** | 5 | 2 | **Improved** |
| 5 | Context switch not parsed | 3 | Low | -- | 3 | -- |
| 6 | Modifier as config answer | 4 | Low | 3 | 4 | Same |
| 7 | Multi-attr modifier not parsed | 4 | Low | 5 | 4 | Same |
| **Total** | | **30** | | **29** | **30** | Stable |

### Key Findings

**Improvement:** System errors dropped from 5 (run 17) to 2 (run 18). The omelette side-choice handler is still crashing but less frequently — some inputs may have been fixed.

**Still broken (same root causes as runs 16-17):**
1. **Change config (8):** "no wait, untoasted" / "scratch that, no X" still completely unsupported
2. **Add item during config (9 total with repeat):** "Can I also get a X" / "And also a X" / "I'll also have a X" still not matched
3. **Omelette 500s (2):** Side-choice handler still crashes on add-item commands and context switches
