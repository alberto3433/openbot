# Chaos Monkey Test Failures

**Generated:** 2026-02-18T17:04:24.392997
**Session Start:** 2026-02-18T17:02:17.741614
**Total Tests:** 20
**Passed:** 14
**Failed:** 6

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 3 |
| System Error | 2 |
| Menu Item Not Found | 1 |

## Item Recognition (3 failures, 1 distinct patterns)

### Corpus [discovery]: Ask what's in a category, then order (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `2345a888-a11d-4829-84b3-944847d8425b`

**Failure:** Expected item 'Bagel Package - Dozen Bagels & 2 Cream Cheese' not in cart. Cart contains: []

**Conversation:**
```
User: what bagels just do you have?
Bot: We don't have bagels justs, but we do have Breads, Sandwiches, Omelettes, Drinks, and Pastries, and more. What are you in the mood for?
[FAILED: Expected item 'Bagel Package - Dozen Bagels & 2 Cream Cheese' not in cart. Cart contains: []]
User: I'll do a Bagel Package just - Dozen Bagels & 2 Cream Cheese
```

**Other instances:**
- Corpus [discovery]: Ask what's in a category, then order
- Corpus [discovery]: Ask for recommendations, then order

## System Error (2 failures, 1 distinct patterns)

### Corpus [inline_spec]: Order a bagel with bread and modifier inline (+1 similar)

**Count:** 2
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `b4cd43cc-21a2-4093-b4a0-901a1bdb0619`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: Flagel toasted with hmm tomato cc
Bot: Got it, for the Flagel with Toasted and Sun-Dried Tomato Cream Cheese. What kind of bagel?
User: sesame
Bot: I found a few options matching that. Did you mean Sesame Bagel or Sesame Sourdough Bagel?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [context_reference]: Order the same as a previous item

## Menu Item Not Found (1 failures, 1 distinct patterns)

### Corpus [correction]: Change the size after ordering

**Count:** 1
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `2afafaf2-2883-44e6-9711-8c3d302ea24c`

**Failure:** Item not found: Sorry, we don't have wait, make that a Large. We have French Toast Bagel, Plain Bagel, Sesame Bagel,

**Conversation:**
```
User: a Small The Tribeca
Bot: Got it, for the The Tribeca with Turkey, Havarti Cheese, Lettuce, and Beefsteak Tomatoes. What kind of bread?
User: wait, make that a Large
Bot: Sorry, we don't have wait, make that a Large. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have wait, make that a Large. We have French Toast Bagel, Plain Bagel, Sesame Bagel,]
```
