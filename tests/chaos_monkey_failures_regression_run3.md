# Chaos Monkey Regression Test Failures — Run 11

**Generated:** 2026-02-13
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --report-path tests/chaos_monkey_failures_run11.md`
**Live Results:** 94/100 passed, 6 failed
**Regression Command:** `python -m pytest tests/chaos_monkey/generated/ --tb=short -q`

---

## Run 11 Failures (6 total)

### Failure 1: "Also add almond" not recognized during config

**Category:** Filler/pattern not matched in config
**Test:** `test_failure_modifier_flow_20260213_124116_beeb20d4.py`

**What happened:** User said "Also add almond" while being asked "What size?" for Hot Tea. The bot treated it as an answer to the size question instead of an add-modifier request.

**How to reproduce in UI:**
1. Open the chat at `http://localhost:8000`
2. Say: **"Can I get a Hot Tea and a Avocado Spread Sandwich"**
3. Bot responds: "Got it, Hot Tea and Avocado Spread Sandwich. For the Hot Tea, what size?"
4. Say: **"Also add almond"**
5. **BUG:** Bot says "Sorry, we don't have Also add almond. We have Small or Large." — should have added Almond Milk as a modifier.

**Root cause:** "Also add X" is in the `ADD_MODIFIER_PATTERN` but the pattern isn't matching here. The `also\s+add\s+` prefix should match. Likely the filler stripping or pattern matching is not being reached because an earlier code path intercepts the input as an answer to the pending size question.

---

### Failure 2: "No gluten free plain" removal fails after adding as modifier

**Category:** Modifier removal fails — item was added as modifier, not found for removal
**Test:** `test_failure_modifier_flow_20260213_124147_f82d755c.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'll have a Black Forest Ham Sandwich and a Maple Raisin Walnut Cream Cheese Sandwich"**
3. Bot responds: "For the Black Forest Ham Sandwich, what kind of bread would you like?"
4. Say: **"I'd like gluten free plain on that"**
5. Bot responds: "Sure, I've added Gluten Free Plain Bagel. What kind of bread would you like?"
6. Say: **"No gluten free plain please"**
7. **BUG:** Bot says "I couldn't find gluten free plain in your order." — should remove the Gluten Free Plain Bagel that was just added.

**Root cause:** The modifier was added as "Gluten Free Plain Bagel" but the removal search is looking for "gluten free plain" — the partial name doesn't match the full modifier name in the item's selections.

---

### Failure 3: "Actually no vegetable" removal fails — modifier was never added

**Category:** Attempting to remove modifier that was never added
**Test:** `test_failure_modifier_flow_20260213_123719_7afeaa86.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'd like a The Classic and also a Tuna Salad Sandwich"**
3. Bot responds: "For the The Classic, what kind of bread would you like?"
4. Say: **"Add vegetable to that"**
5. Bot responds: "Let's finish with your The Classic first. What kind of bread would you like?"
6. Say: **"Actually no vegetable"**
7. **BUG:** Bot says "I couldn't find vegetable in your order." — This is technically correct (vegetable was never added because the bot redirected), but the user experience is confusing.

**Root cause:** The bot rejected the "add vegetable" request (said "let's finish first") but the user still tries to undo it. The bot should say something like "No worries, vegetable wasn't added" instead of the generic "I couldn't find X" error.

---

### Failure 4: "I'll take five of those" — quantity change not recognized

**Category:** Quantity change after item completion
**Test:** `test_failure_cart_ops_20260213_124114_719a7366.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'll have a Apple Cinnamon Babka Slice"**
3. Bot responds: "Got it, Apple Cinnamon Babka Slice. Anything else?"
4. Say: **"I'll take five of those"**
5. **BUG:** Bot says "I'm sorry, we don't have five of those." — should change quantity to 5.

**Root cause:** After an item is complete and the bot asks "Anything else?", the system is in TAKING_ITEMS phase. "I'll take five of those" is parsed as a new item order, not a quantity change. The parser doesn't recognize "five of those" as a reference to the last item.

---

### Failure 5: "Hold the walnut raisin cream cheese" removes entire sandwich

**Category:** Modifier removal removes the whole item
**Test:** `test_failure_modifier_flow_20260213_123705_3e4d49bf.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"One Nova Cream Cheese Sandwich please"**
3. Bot responds: "For the Nova Cream Cheese Sandwich. What kind of bread would you like?"
4. Say: **"Also add walnut raisin cream cheese"**
5. Bot responds: "Sure, I've added Walnut Raisin Cream Cheese. What kind of bread would you like?"
6. Say: **"Hold the walnut raisin cream cheese"**
7. **BUG:** Bot says "OK, I've removed the Nova Cream Cheese Sandwich, Nova Cream Cheese, Walnut Raisin Cream Cheese." — removed the ENTIRE sandwich instead of just the added modifier.

**Root cause:** "walnut raisin cream cheese" matches a substring of the sandwich's default ingredients or the sandwich name itself, causing the cancellation handler to remove the whole item instead of just the added modifier.

---

### Failure 6: "Skip the raw sugar" removes entire Hot Latte

**Category:** Modifier removal removes the whole item
**Test:** `test_failure_modifier_flow_20260213_123925_4e0d9545.py`

**How to reproduce in UI:**
1. Open the chat
2. Say: **"I'll have a Hot Latte"**
3. Bot responds: "For the Hot Latte. What size?"
4. Say: **"I'd like raw sugar on that"**
5. Bot responds: "Sure, I've added Sugar in the Raw. What size?"
6. Say: **"Skip the raw sugar"**
7. **BUG:** Bot says "OK, I've removed the Hot Latte, Sugar in the Raw." — removed the ENTIRE latte instead of just the Sugar in the Raw.

**Root cause:** Same as Failure 5. The cancellation handler is matching "raw sugar" too broadly and removing the item instead of just the modifier.

---

## Summary

| # | Failure | Category | Severity |
|---|---------|----------|----------|
| 1 | "Also add almond" not matched during config | Pattern matching | Medium |
| 2 | "No gluten free plain" partial name doesn't match full modifier | Modifier removal | Medium |
| 3 | "Actually no vegetable" — modifier was never added | UX / error messaging | Low |
| 4 | "I'll take five of those" — quantity change not recognized | Quantity handling | Medium |
| 5 | "Hold the walnut raisin cream cheese" removes entire sandwich | Modifier removal (critical) | **High** |
| 6 | "Skip the raw sugar" removes entire Hot Latte | Modifier removal (critical) | **High** |

### High Priority Bugs

**Failures 5 and 6** are the most critical — removing an added modifier should NEVER remove the entire item. This is a recurring pattern across multiple runs where the cancellation handler matches too broadly and removes the parent item instead of just the modifier.
