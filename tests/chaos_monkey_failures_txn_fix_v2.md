# Chaos Monkey Test Failures

**Generated:** 2026-02-19T16:43:17.427132
**Session Start:** 2026-02-19T16:36:52.207398
**Total Tests:** 80
**Passed:** 76
**Failed:** 4

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 4 |

## Menu Item Not Found (4 failures, 2 distinct patterns)

### Corpus [addon_during_config]: Decline current question but add something else (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `56a1db60-38f3-4e2b-91ae-e837d49b599d`

**Failure:** Item not found: Sorry, we don't have no, but add american cheese. We have French Toast Bagel, Plain Bagel, Sesame Ba

**Conversation:**
```
User: I'll have a Provolone Cheese Sandwich
Bot: Got it, for the Provolone Cheese Sandwich. What kind of bread?
User: no, but add american cheese
Bot: Sorry, we don't have no, but add american cheese. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more — do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have no, but add american cheese. We have French Toast Bagel, Plain Bagel, Sesame Ba]
```

**Other instances:**
- Corpus [addon_during_config]: Answer size question with iced preference
- Corpus [addon_during_config]: Answer size question with iced preference

### Order The Pizza BEC with Pepperoni then modify

**Count:** 1
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `6e48a9d5-0ba5-4056-a82b-458c20588609`

**Failure:** Item not found: Sorry, we don't carry Pepperoni.

**Conversation:**
```
User: Can I get a The Pizza BEC with Pepperoni
Bot: Sorry, we don't carry Pepperoni.
[FAILED: Item not found: Sorry, we don't carry Pepperoni.]
User: Can you add jalapeño cheddar bagel
User: Hold the jalapeño cheddar bagel
User: I'd like pepper on that
```
