# Chaos Monkey Regression Test Failures

**Generated:** 2026-02-12
**Test Command:** `python -m pytest tests/chaos_monkey/generated/ --tb=short -q`
**Total Tests:** 208
**Passed:** 200
**Failed:** 8

---

## Summary by Category

| Category | Count |
|----------|-------|
| Filler words not stripped in config path | 3 |
| Item name not recognized (numeric prefix / special chars) | 3 |
| Item removed from cart during modifier flow | 2 |

Note: These are the same 8 failures as regression_run1. No new regressions from live run 10.

## Filler words not stripped in config path

### Order The Pizza BEC with Sausage, then add The Lexington Omelette

**Test:** `test_failure_multi_item_20260211_212924_384179e7.py`
**Failure:** Expected item 'The Lexington Omelette' in cart

**Steps to reproduce:**
```python
from orderbot.tasks.models import OrderTask
from orderbot.tasks.state_machine import OrderStateMachine

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
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll well have a Scottish Salmon", order)
sm.process("excuse me And a Maple Raisin Walnut Cream Cheese", order)
# FAIL: "excuse me" not stripped in config answer path
```

### Order Kalamata Olive Feta CC Sandwich, then add Strawberry CC Sandwich

**Test:** `test_failure_multi_item_20260212_212340_f4b1cc59.py`
**Failure:** Expected item 'Strawberry Cream Cheese Sandwich' in cart

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("excuse me, Can I get a Kalamata Olive Feta Cream Cheese Sandwich", order)
sm.process("hi Also a Strawberry Cream Cheese Sandwich", order)
# FAIL: "hi" filler not stripped in config answer path
```

**Root cause:** `strip_conversational_fillers()` is applied in `handle_add_modifiers_during_config()` and `check_cancellation_during_config()`, but NOT in the main config answer path that routes user input when a configuration question is pending. Fillers like "so", "excuse me", "hi" cause the input to be treated as a literal answer to the config question.

## Item name not recognized (numeric prefix / special chars)

### Order 6 Bagel Package

**Test:** `test_failure_single_item_20260211_225640_58342e60.py`
**Failure:** Expected item '6 Bagel Package' in cart

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("Just a 6 Bagel Package", order)
# FAIL: "6" parsed as quantity, "Bagel Package" doesn't match any item
```

### Order 6 Bagel Package, then remove

**Test:** `test_failure_cart_ops_20260211_111754_3856a994.py`
**Failure:** Expected item '6 Bagel Package' in cart (never added in step 1)

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll um have a 6 Bagel Package", order)
# FAIL: Same — "6 Bagel Package" not recognized
```

### Order Bagel Chips - Salt, then change quantity

**Test:** `test_failure_cart_ops_20260212_103458_9a5a7fe9.py`
**Failure:** Expected item 'Bagel Chips - Salt' in cart

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll have a Bagel Chips - Salt thanks", order)
# FAIL: Item with hyphen in name not recognized by parser
```

**Root cause:** The deterministic parser strips leading numbers as quantities. "6 Bagel Package" becomes qty=6 + "Bagel Package" which doesn't match. Items with hyphens ("Bagel Chips - Salt") also fail tokenization.

## Item removed from cart during modifier flow

### Order Iced Tea and Tofu Nova Sandwich, then modify

**Test:** `test_failure_modifier_flow_20260211_112031_fa264e41.py`
**Failure:** Expected item 'Iced Tea' in cart

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("just Can I get a Iced Tea and a Tofu Nova Sandwich", order)
sm.process("Also add well hazelnut", order)
sm.process("hi there Take off the hazelnut", order)
sm.process("With sweet n low please please", order)
# FAIL: After modifier operations, Iced Tea no longer in cart
```

### Order Iced Chai Tea and Pastrami Salmon Sandwich, then modify

**Test:** `test_failure_modifier_flow_20260211_112203_ebbd565b.py`
**Failure:** Expected item 'Iced Chai Tea' in cart

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("Can I get a Iced Chai Tea and a Pastrami Salmon Sandwich", order)
sm.process("Add Soy Milk", order)
sm.process("Hold the Soy Milk", order)
sm.process("With vanilla syrup please", order)
# FAIL: After modifier operations, Iced Chai Tea no longer in cart
```

### Order Essentia Water 1L, then cancel

**Test:** `test_failure_cart_ops_20260211_074303_d5cce097.py`
**Failure:** Expected item 'Essentia Water 1L' in cart after step 1

**Steps to reproduce:**
```python
sm = OrderStateMachine()
order = OrderTask(); order.phase = "taking_items"

sm.process("I'll have a Essentia Water 1L", order)
# FAIL: Item never added — "1L" in name causes recognition failure
```

**Root cause:** Modifier removal patterns ("Hold the X", "Take off the X") may be matching too broadly and removing the entire item. For Essentia Water, "1L" suffix causes item recognition failure.
