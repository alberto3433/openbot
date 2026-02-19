# Chaos Monkey Test Failures

**Generated:** 2026-02-19T17:19:12.106385
**Session Start:** 2026-02-19T17:12:25.345054
**Total Tests:** 80
**Passed:** 77
**Failed:** 3

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 3 |

## Menu Item Not Found (3 failures, 1 distinct patterns)

### Corpus [quantity]: Change quantity after ordering (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `a59b3176-a874-41d8-ae1b-8e180c7df89f`

**Failure:** Item not found: Sorry, we don't have excuse me actually make it two. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: hi, a Bologna
Bot: Got it, for the Bologna. How much? 1/4 lb? 1 lb?
User: excuse me actually make it two
Bot: Sorry, we don't have excuse me actually make it two. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have excuse me actually make it two. We have 1/4 lb or 1 lb.]
```

**Other instances:**
- Corpus [correction]: Change the size after ordering
- Corpus [quantity]: Change quantity after ordering
