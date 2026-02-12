# Chaos Monkey Regression Test Failures

**Generated:** 2026-02-12
**Test Command:** `python -m pytest tests/chaos_monkey/generated/ -v --tb=short -q`
**Total Tests:** 201
**Passed:** 193
**Failed:** 8

---

## Summary by Category

| Category | Count |
|----------|-------|
| Filler words not stripped in config path | 3 |
| Item name not recognized (numeric prefix / special chars) | 3 |
| Item removed from cart during modifier flow | 2 |

## Filler words not stripped in config path

### Order The Pizza BEC with Sausage, then add The Lexington Omelette

**Test:** `test_failure_multi_item_20260211_212924_384179e7.py`
**Failure:** Expected item 'The Lexington Omelette' in cart

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("Can I get oh a The Pizza BEC with Sausage", order)
sm.process("so Add a The Lexington Omelette", order)
# FAIL: "so" filler not stripped, input treated as config answer instead of add-item
```

### Order Scottish Salmon, then add Maple Raisin Walnut Cream Cheese

**Test:** `test_failure_multi_item_20260211_225400_d9208cb6.py`
**Failure:** Expected item 'Maple Raisin Walnut Cream Cheese' in cart

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll well have a Scottish Salmon", order)
sm.process("excuse me And a Maple Raisin Walnut Cream Cheese", order)
# FAIL: "excuse me" not stripped in config answer path, input treated as config answer
```

### Order Iced Tea and Tofu Nova Sandwich, then modify

**Test:** `test_failure_modifier_flow_20260211_112031_fa264e41.py`
**Failure:** Expected item 'Iced Tea' in cart

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("just Can I get a Iced Tea and a Tofu Nova Sandwich", order)
sm.process("Also add well hazelnut", order)
sm.process("hi there Take off the hazelnut", order)
sm.process("With sweet n low please please", order)
# FAIL: "hi there" filler not stripped before cancel pattern matching
```

**Root cause:** `strip_conversational_fillers()` is applied in `handle_add_modifiers_during_config()` and `check_cancellation_during_config()`, but NOT in the config answer path that processes user input as a response to a configuration question (e.g., "What kind of bagel?" or "How much?"). When the user says "excuse me And a Maple Raisin Walnut Cream Cheese" while being asked "How much?", the filler leaks through and the whole string is treated as an answer to the question.

## Item name not recognized (numeric prefix / special chars)

### Order 6 Bagel Package

**Test:** `test_failure_single_item_20260211_225640_58342e60.py`
**Failure:** Expected item '6 Bagel Package' in cart

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("Just a 6 Bagel Package", order)
# FAIL: "6" is parsed as quantity, leaving "Bagel Package" which doesn't match any item
```

### Order 6 Bagel Package, then remove

**Test:** `test_failure_cart_ops_20260211_111754_3856a994.py`
**Failure:** Expected item '6 Bagel Package' in cart (never added in step 1)

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll um have a 6 Bagel Package", order)
sm.process("hey, I don't want the 6 Bagel Package anymore", order)
# FAIL: Same as above — "6 Bagel Package" not recognized as an item
```

### Order Bagel Chips - Salt, then change quantity

**Test:** `test_failure_cart_ops_20260212_103458_9a5a7fe9.py`
**Failure:** Expected item 'Bagel Chips - Salt' in cart

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll have a Bagel Chips - Salt thanks", order)
sm.process("Actually, make that four if you don't mind", order)
# FAIL: Item with hyphen in name not recognized by parser
```

**Root cause:** The deterministic parser strips leading numbers as quantities ("6 Bagel Package" becomes qty=6 + "Bagel Package"). Items with numeric prefixes in their actual name need special handling. Similarly, items with hyphens ("Bagel Chips - Salt") may not match due to tokenization.

## Item removed from cart during modifier flow

### Order Iced Chai Tea and Pastrami Salmon Sandwich, then modify

**Test:** `test_failure_modifier_flow_20260211_112203_ebbd565b.py`
**Failure:** Expected item 'Iced Chai Tea' in cart

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("Can I get a Iced Chai Tea and a Pastrami Salmon Sandwich", order)
sm.process("Add Soy Milk", order)
sm.process("Hold the Soy Milk", order)
sm.process("With vanilla syrup please", order)
# FAIL: After "Hold the Soy Milk", the Iced Chai Tea item was removed from cart
```

### Order Essentia Water 1L, then cancel

**Test:** `test_failure_cart_ops_20260211_074303_d5cce097.py`
**Failure:** Expected item 'Essentia Water 1L' in cart after step 1

**Steps to reproduce:**
```
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll have a Essentia Water 1L", order)
sm.process("Cancel the Essentia Water 1L", order)
# FAIL: Item not in cart — either never added (recognition issue) or cancel removed it
```

**Root cause:** In the Iced Chai Tea case, "Hold the Soy Milk" may be matching too broadly and removing the entire item instead of just the modifier. In the Essentia Water case, "1L" in the item name may cause recognition failure.
