# Chaos Monkey Test Failures

**Generated:** 2026-02-26T23:21:55.872692
**Session Start:** 2026-02-26T22:49:06.202510
**Total Tests:** 220
**Passed:** 193
**Failed:** 27

---

## Summary by Category

| Category | Count |
|----------|-------|
| Other | 15 |
| Item Recognition | 8 |
| Menu Item Not Found | 4 |

## Other (15 failures, 1 distinct patterns)

### Complex order: Tuna Salad Sandwich (+14 similar)

**Count:** 15
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `c7cbb786-980b-410b-9c89-fa4b2540bdf3`

**Failure:** Failed to send message

**Conversation:**
```
User: hello, One tuna salad sandwich toasted with a little gluten-free everything
Bot: Got it, Tuna Salad Sandwich and a little gluten little gluten-free everything. For the Tuna Salad Sandwich, what kind of bread?
User: Plain Bagel
Bot: Got it, Plain Bagel. Any more changes? No? Any cheese? Any condiments?
User: no thanks
Bot: Got it, Tuna Salad Sandwich and a little gluten little gluten-free everything. For the little gluten-free everything, how much? 1/4 lb? 1 lb?
User: no
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: Swiss Cheese Sandwich
- Complex order: The Truffled Egg
- Complex order: Scallion Cream Cheese Sandwich
- Complex order: Gravlax Sandwich
- Complex order: The Leo Omelette
- Complex order: Chicken Salad Sandwich
- Complex order: Truffle Cream Cheese Sandwich
- Complex order: The Truffled Egg Omelette
- Complex order: Sable Sandwich
- Complex order: Tofu Scallion Sandwich
- Complex order: Kalamata Olive Feta Cream Cheese Sandwich
- Complex order: Nova Cream Cheese Sandwich
- Complex order: The Classic BEC
- Complex order: The Truffled Egg Omelette

## Item Recognition (8 failures, 1 distinct patterns)

### Complex order: The Latke BEC (+7 similar)

**Count:** 8
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `b248a7ee-5fd2-4120-955f-550563c5cd2e`

**Failure:** Expected item 'The Latke BEC' not in cart. Cart contains: ['baked salmon salad sandwich']

**Conversation:**
```
User: the latke bec with tomatoes and extra baked salmon salad please
Bot: Sorry, we don't carry Tomatoes.
[FAILED: Expected item 'The Latke BEC' not in cart. Cart contains: ['baked salmon salad sandwich']]
```

**Other instances:**
- Complex order: Blueberry Cream Cheese Sandwich
- Complex order: The Max Borough
- Complex order: Hot Pastrami Sandwich
- Complex order: The Leo
- Complex order: The Reuben
- Complex order: The BLT
- Complex order: Truffle Cream Cheese Sandwich

## Menu Item Not Found (4 failures, 1 distinct patterns)

### Complex order: Green Tea (+3 similar)

**Count:** 4
**Pattern:** `complex_order | item_not_recognized`
**Type:** complex_order
**Session:** `a5f04f88-7290-4533-afaf-f75cd3abe046`

**Failure:** Item not found: We don't have small green tea with almond and whole milk. For teas, we have Hot Tea or Green Tea. Wo

**Conversation:**
```
User: I'll have a small green tea with almond and whole milk
Bot: We don't have small green tea with almond and whole milk. For teas, we have Hot Tea or Green Tea. Would you like any of those, or can I help you find something else?
[FAILED: Item not found: We don't have small green tea with almond and whole milk. For teas, we have Hot Tea or Green Tea. Wo]
```

**Other instances:**
- Complex order: Green Tea
- Complex order: The Max Borough
- Complex order: The Max Borough
