# Chaos Monkey Test Failures

**Generated:** 2026-02-22T22:19:37.392685
**Session Start:** 2026-02-22T21:59:15.841561
**Total Tests:** 160
**Passed:** 157
**Failed:** 3

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 3 |

## Item Recognition (3 failures, 1 distinct patterns)

### Regression: instruction leak (Side of Avocado) (+2 similar)

**Count:** 3
**Pattern:** `regression | modifier_not_in_order`
**Type:** regression
**Session:** `1d6ddb5e-686b-4dd4-89a0-d7a9c57cac72`

**Failure:** Expected item 'Side of Avocado' not in cart. Cart contains: ['nova tofu spread sandwich']

**Conversation:**
```
User: Side of Avocado on the side
Bot: Got it, for the Nova Tofu Spread Sandwich with Avocado (on the side). What kind of bread?
[FAILED: Expected item 'Side of Avocado' not in cart. Cart contains: ['nova tofu spread sandwich']]
```

**Other instances:**
- Regression: instruction leak (Side of Chicken Sausage)
- Regression: qualifier persistence (iced Side of Onion)
