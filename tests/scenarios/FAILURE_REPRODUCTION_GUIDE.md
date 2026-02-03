# Test Failure Reproduction Guide

This guide shows how to manually reproduce the 7 failing tests from the scenario test suite using the chatbot UI.

**Last updated:** Removed empty/whitespace tests (not an issue in UI)

**How to use this guide:**
1. Start the chatbot UI (or use the API endpoint)
2. Start a new conversation
3. Type the exact input shown in the "You Type" column
4. Compare the bot's response to the "Expected" behavior

---

## Category 1: Informal/Slang Language (3 failures)

The system doesn't parse very casual or slang ordering language.

| # | You Type | Expected | Actual Issue |
|---|----------|----------|--------------|
| 1 | `yo lemme get an everything with cream cheese` | Bot adds everything bagel with cream cheese | No item recognized |
| 2 | `everything toasted cream cheese` | Bot adds everything bagel toasted with cream cheese | No item recognized |
| 3 | `gimme a lox` | Bot adds a lox bagel | No item recognized |

**Root Cause:** The parser expects more formal ordering phrases like "I'd like" or "Can I get". Very terse or slang inputs aren't matched.

**Test commands:**
```bash
python -m pytest tests/scenarios/test_natural_language.py::TestPoliteVariations::test_casual_order -v
python -m pytest tests/scenarios/test_natural_language.py::TestPoliteVariations::test_terse_order -v
python -m pytest tests/scenarios/test_natural_language.py::TestSlangAndAbbreviations::test_lox_slang -v
```

---

## Category 2: Complex Parsing Issues (3 failures)

These inputs have complex structures that confuse the parser.

| # | You Type | Expected | Actual Issue |
|---|----------|----------|--------------|
| 4 | `Lox on everything, but no capers please` | Bot adds lox bagel on everything, excludes capers | No item recognized |
| 5 | `Egg and cheese on plain, eggs scrambled well done` | Bot adds egg & cheese sandwich | No item recognized |
| 6 | `A few chocolate chip cookies` | Bot adds ~3 cookies | No item recognized |

**Root Cause:**
- "Lox on everything" - word order confuses parser (expects "everything bagel with lox")
- "Egg and cheese" - may not match menu item name exactly
- "A few" - vague quantity not parsed

**Test commands:**
```bash
python -m pytest tests/scenarios/test_complex_single_items.py::TestComplexBagelOrders::test_bagel_with_lox_no_capers -v
python -m pytest tests/scenarios/test_complex_single_items.py::TestComplexSandwichOrders::test_egg_sandwich_specific_cook -v
python -m pytest tests/scenarios/test_multi_item_orders.py::TestQuantityOrders::test_few_items -v
```

---

## Category 3: Context Switch (1 failure)

| # | You Type | Expected | Actual Issue |
|---|----------|----------|--------------|
| 7 | First: `What bagels do you have?` | Bot lists available bagels | *(works)* |
|   | Then: `I'll have an everything toasted with cream cheese` | Bot adds everything bagel | No item recognized |

**Root Cause:** After answering a menu question, the system may not properly transition back to order-taking mode.

**Test command:**
```bash
python -m pytest tests/scenarios/test_edge_cases.py::TestContextSwitches::test_return_to_order_after_question -v
```

---

## Quick Test Script

Copy these inputs to test all 7 failures quickly:

```
# Slang/Terse (3 failures)
yo lemme get an everything with cream cheese
everything toasted cream cheese
gimme a lox

# Complex parsing (3 failures)
Lox on everything, but no capers please
Egg and cheese on plain, eggs scrambled well done
A few chocolate chip cookies

# Context switch (1 failure)
What bagels do you have?
[then after bot responds:]
I'll have an everything toasted with cream cheese
```

---

## Run All 7 Failing Tests

```bash
python -m pytest \
  tests/scenarios/test_natural_language.py::TestPoliteVariations::test_casual_order \
  tests/scenarios/test_natural_language.py::TestPoliteVariations::test_terse_order \
  tests/scenarios/test_natural_language.py::TestSlangAndAbbreviations::test_lox_slang \
  tests/scenarios/test_complex_single_items.py::TestComplexBagelOrders::test_bagel_with_lox_no_capers \
  tests/scenarios/test_complex_single_items.py::TestComplexSandwichOrders::test_egg_sandwich_specific_cook \
  tests/scenarios/test_multi_item_orders.py::TestQuantityOrders::test_few_items \
  tests/scenarios/test_edge_cases.py::TestContextSwitches::test_return_to_order_after_question \
  -v
```

---

## Summary by Priority

**High Priority (Common customer phrases):**
- Terse ordering without verbs: `everything toasted cream cheese` (1 test)
- "gimme", "lemme" slang (2 tests)

**Medium Priority (Edge cases):**
- Context switch after menu question (1 test)
- "A few" quantity parsing (1 test)

**Lower Priority (Unusual requests):**
- Complex word order like "Lox on everything" (1 test)
- Specific cook instructions "eggs scrambled well done" (1 test)

---

## Previously Flaky Tests (Now Passing)

These 8 tests failed on the first run but pass on rerun - likely due to test parallelization or cache state:

- `test_western_omelette` ✅
- `test_omelette_with_side` ✅
- `test_basic_omelette` ✅
- `test_omelette_and_coffee` ✅
- `test_omelette_with_extra_fillings` ✅
- `test_iced_coffee_no_ice` ✅
- `test_remove_ice_from_coffee` ✅
- `test_tea_with_specific_temperature` ✅
