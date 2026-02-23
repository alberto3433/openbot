# Chaos Monkey Test Failures

**Generated:** 2026-02-22T19:09:41.244672
**Session Start:** 2026-02-22T18:48:00.995763
**Total Tests:** 180
**Passed:** 177
**Failed:** 3

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 2 |
| Other | 1 |

## Item Recognition (2 failures, 1 distinct patterns)

### Regression: qualifier persistence (small 3 Bagel Package) (+1 similar)

**Count:** 2
**Pattern:** `regression | modifier_not_in_order`
**Type:** regression
**Session:** `410c75b4-cd18-4e60-ab63-364c139859cb`

**Failure:** Expected item '3 Bagel Package' not in cart. Cart contains: []

**Conversation:**
```
User: small 3 Bagel Package
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item '3 Bagel Package' not in cart. Cart contains: []]
User: 1
```

**Other instances:**
- Regression: phase restoration (Bagel, Potato Chips)

## Other (1 failures, 1 distinct patterns)

### Regression: instruction leak (Flatz)

**Count:** 1
**Pattern:** `regression | special_instruction_flatz_on_the_side_contains_flatz`
**Type:** regression
**Session:** `51aee433-4cc4-490d-ae65-9290a2eb4c99`

**Failure:** Special instruction 'flatz on the side' contains 'flatz'

**Conversation:**
```
User: I'd like a Flatz on the side
Bot: Got it, for the Flatz with flatz on the side. What kind of flatz?
[FAILED: Special instruction 'flatz on the side' contains 'flatz']
```
