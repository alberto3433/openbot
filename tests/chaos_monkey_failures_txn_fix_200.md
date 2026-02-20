# Chaos Monkey Test Failures

**Generated:** 2026-02-19T18:36:37.139813
**Session Start:** 2026-02-19T18:22:01.350201
**Total Tests:** 180
**Passed:** 163
**Failed:** 17

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 13 |
| Other | 2 |
| Item Recognition | 2 |

## Menu Item Not Found (13 failures, 5 distinct patterns)

### Corpus [correction]: Change the size after ordering (+8 similar)

**Count:** 9
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `bba00efc-8ccd-47af-840b-d39370a6e4c9`

**Failure:** Item not found: Sorry, we don't have wait, make that a Large. We have French Toast Bagel, Plain Bagel, Sesame Bagel,

**Conversation:**
```
User: a Small The RB Prime
Bot: Heads up, the The RB Prime only comes in one size. Got it, for the The RB Prime. What kind of bread?
User: wait, make that a Large
Bot: Sorry, we don't have wait, make that a Large. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more — do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have wait, make that a Large. We have French Toast Bagel, Plain Bagel, Sesame Bagel,]
```

**Other instances:**
- Corpus [shorthand]: Modifier on a bread type
- Corpus [batch_order]: Two items with 'also' connector
- Corpus [inline_spec]: Order a specific item with a modifier inline
- Corpus [addon_during_config]: Answer size question with iced preference
- Corpus [addon_during_config]: Answer bread question with modifier attached
- Corpus [addon_during_config]: Answer bread question with modifier attached
- Corpus [correction]: Change the size after ordering
- Corpus [addon_during_config]: Decline current question but add something else

### Order The Pizza BEC with Pepperoni then modify

**Count:** 1
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `eac8f4b7-999e-4cea-b3d0-2ae138a14566`

**Failure:** Item not found: Sorry, we don't carry Pepperoni.

**Conversation:**
```
User: One The Pizza BEC with Pepperoni please
Bot: Sorry, we don't carry Pepperoni.
[FAILED: Item not found: Sorry, we don't carry Pepperoni.]
User: With everything salmon please
User: Actually no everything salmon
User: Add egg salad
```

### Corpus [addon_during_config]: Answer bread question with toasted in same breath

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `02929687-3e40-4ad4-ab48-c59c80a0a3cc`

**Failure:** Item not found: I couldn't find bread toasted in your order. What would you like to do?

**Conversation:**
```
User: I'll have a bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: No Bread toasted
Bot: I couldn't find bread toasted in your order. What would you like to do?
[FAILED: Item not found: I couldn't find bread toasted in your order. What would you like to do?]
```

### Change The Classic BEC quantity to 4

**Count:** 1
**Pattern:** `cart_ops | item_not_recognized`
**Type:** cart_ops
**Session:** `a3b87b5c-03c2-42ce-b93d-06447d0e896a`

**Failure:** Item not found: Sorry, we don't have actually I'll take four of those. We have French Toast Bagel, Plain Bagel, Sesa

**Conversation:**
```
User: I'll have a oh The Classic BEC
Bot: Got it, for the The Classic BEC. What kind of bread?
User: actually I'll take four of those
Bot: Sorry, we don't have actually I'll take four of those. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more — do you want one of these or do you want to hear more options...
[FAILED: Item not found: Sorry, we don't have actually I'll take four of those. We have French Toast Bagel, Plain Bagel, Sesa]
```

### Tricky (multi_attribute): Bialy

**Count:** 1
**Pattern:** `tricky | multi_attribute | item_not_recognized`
**Type:** tricky
**Session:** `6474b88b-3b5b-4b19-a855-65b513758a37`

**Failure:** Item not found: We don't carry Cream, but for milks we have Half N Half, Whole Milk, or Oat Milk. Would you like any

**Conversation:**
```
User: I'll have a toasted Vegetable Cream Cheese Bialy
Bot: We don't carry Cream, but for milks we have Half N Half, Whole Milk, or Oat Milk. Would you like any of those?
[FAILED: Item not found: We don't carry Cream, but for milks we have Half N Half, Whole Milk, or Oat Milk. Would you like any]
```

## Other (2 failures, 1 distinct patterns)

### Corpus [addon_during_config]: Answer size question with iced preference (+1 similar)

**Count:** 2
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `fa038227-b109-42db-9704-47b0d87f5aee`

**Failure:** Failed to send message

**Conversation:**
```
User: a Chocolate Dipped Macaroons please
Bot: Got it, Chocolate Dipped Macaroons. Anything else?
User: Large iced
Bot: Got it, for the Amercano with Large. Any extra shots?
User: no
[FAILED: Failed to send message]
```

**Other instances:**
- Corpus [addon_during_config]: Answer size question with iced preference

## Item Recognition (2 failures, 2 distinct patterns)

### Corpus [shorthand]: Just the item name, no preamble

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `e1888932-ca63-474a-b3dd-0f8035d3e51f`

**Failure:** Expected item 'Peanut Butter Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: Peanut Butter actually Sandwich
Bot: What can I get for you?
[FAILED: Expected item 'Peanut Butter Sandwich' not in cart. Cart contains: []]
```

### Order Baked Salmon Salad Sandwich then modify

**Count:** 1
**Pattern:** `modifier_flow | modifier_not_in_order`
**Type:** modifier_flow
**Session:** `4a2505e5-ee19-49ba-815c-505d271e7c62`

**Failure:** Expected item 'Baked Salmon Salad Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: One Baked Salmon just Salad Sandwich please
Bot: What can I get for you?
[FAILED: Expected item 'Baked Salmon Salad Sandwich' not in cart. Cart contains: []]
User: Add pastrami salmon to that thanks
User: hi, No pastrami salmon please
User: I'd like olive like pimento cream cheese on that
```
