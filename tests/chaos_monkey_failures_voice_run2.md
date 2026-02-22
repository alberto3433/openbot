# Chaos Monkey Test Failures

**Generated:** 2026-02-21T23:49:17.033479
**Session Start:** 2026-02-21T23:38:32.161532
**Total Tests:** 40
**Passed:** 39
**Failed:** 1

---

## Summary by Category

| Category | Count |
|----------|-------|
| STT-Induced Failure | 1 |

## STT-Induced Failure (1 failures, 1 distinct patterns)

### Tricky (repeat_item): Avocado Spread Sandwich

**Count:** 1
**Pattern:** `tricky | repeat_item | item_not_recognized`
**Type:** tricky
**Session:** `fbf428a8-ca53-40c4-a780-70db0fb6edd6`

**Failure:** STT-induced not found (original: 'Can I get a Avocado Spread Sandwich'): We don't have have a cado Spread Sandwich. For healthy sandwiches, we have The Health Nut, The Lexin

**Conversation:**
```
User: Can I get a have a cado Spread Sandwich
Bot: We don't have have a cado Spread Sandwich. For healthy sandwiches, we have The Health Nut, The Lexington, or The Columbus BEC. Would you like any of those, or can I help you find something else?
[FAILED: STT-induced not found (original: 'Can I get a Avocado Spread Sandwich'): We don't have have a cado Spread Sandwich. For healthy sandwiches, we have The Health Nut, The Lexin]
User: add another Avocado add another Avocado Spread Sandwich
```

## STT Resilience Summary

**1 failures** were caused by STT-simulated input corruption (not real parser bugs).

| Original Input | Corrupted Input | Bot Response |
|----------------|-----------------|--------------|
| Can I get a Avocado Spread Sandwich | Can I get a have a cado Spread Sandwich | We don't have have a cado Spread Sandwich. For healthy sandwiches, we have The H... |
