# Chaos Monkey Test Failures

**Generated:** 2026-02-22T18:31:49.914830
**Session Start:** 2026-02-22T18:20:03.979577
**Total Tests:** 100
**Passed:** 99
**Failed:** 1

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 1 |

## Item Recognition (1 failures, 1 distinct patterns)

### Regression: qualifier persistence (iced 3 Bagel Package)

**Count:** 1
**Pattern:** `regression | modifier_not_in_order`
**Type:** regression
**Session:** `f401b8b3-ba7d-4671-8d20-045c44475c4a`

**Failure:** Expected item '3 Bagel Package' not in cart. Cart contains: []

**Conversation:**
```
User: iced 3 Bagel Package
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item '3 Bagel Package' not in cart. Cart contains: []]
User: 1
```
