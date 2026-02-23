# Chaos Monkey Test Failures

**Generated:** 2026-02-22T23:33:19.510163
**Session Start:** 2026-02-22T23:01:23.589226
**Total Tests:** 260
**Passed:** 258
**Failed:** 2

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 1 |
| Item Recognition | 1 |

## Menu Item Not Found (1 failures, 1 distinct patterns)

### Regression: qualifier persistence (hot 3 Bagel Package)

**Count:** 1
**Pattern:** `regression | item_not_recognized`
**Type:** regression
**Session:** `f22ac95a-20bb-43db-a393-ea8195409bf8`

**Failure:** Item not found: We don't have hot 3 Bagel Package. Did you mean 3 Bagel Package? Would you like that, or can I help 

**Conversation:**
```
User: I'd like a hot 3 Bagel Package
Bot: We don't have hot 3 Bagel Package. Did you mean 3 Bagel Package? Would you like that, or can I help you find something else?
[FAILED: Item not found: We don't have hot 3 Bagel Package. Did you mean 3 Bagel Package? Would you like that, or can I help ]
User: 1
```

## Item Recognition (1 failures, 1 distinct patterns)

### Regression: instruction leak (6 Bagel Package)

**Count:** 1
**Pattern:** `regression | modifier_not_in_order`
**Type:** regression
**Session:** `3cb52ab0-0107-4306-9ff5-e5e9579d14d1`

**Failure:** Expected item '6 Bagel Package' not in cart. Cart contains: []

**Conversation:**
```
User: 6 Bagel Package on the side
Bot: What can I get for you?
[FAILED: Expected item '6 Bagel Package' not in cart. Cart contains: []]
```
