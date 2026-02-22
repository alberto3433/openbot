# Chaos Monkey Test Failures

**Generated:** 2026-02-21T23:37:45.374992
**Session Start:** 2026-02-21T23:31:58.640313
**Total Tests:** 80
**Passed:** 53
**Failed:** 27
**False Positives (not reproduced):** 4

---

## Summary by Category

| Category | Count |
|----------|-------|
| Other | 25 |
| Item Recognition | 1 |
| STT-Induced Failure | 1 |

## Other (25 failures, 7 distinct patterns)

### Corpus [addon_during_config]: Decline current question but add something else (+12 similar)

**Count:** 13
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `87d28781-408c-4f49-8974-72562d2766c0`

**Failure:** Failed to send message

**Conversation:**
```
User: aisle have a Cafe au Lait
[FAILED: Failed to send message]
User: no, but add sugar
User: Small
User: nope
```

**Other instances:**
- Corpus [context_reference]: Order another of the same item
- Corpus [inline_spec]: Order a sized drink with size and iced inline
- Corpus [correction]: Switch bread type after ordering a bagel
- Corpus [batch_order]: Quantity of bagels with different bread types
- Corpus [batch_order]: Three items in a single turn
- Corpus [quantity]: Multiple bagels of a specific bread
- Corpus [shorthand]: Bread type with modifier, no verb
- Corpus [batch_order]: Quantity of bagels with different bread types
- Corpus [correction]: Change the size after ordering
- Corpus [batch_order]: A food item and a drink together
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline
- Corpus [context_reference]: Request toasting via context reference

### Order Belly Lox Sandwich then modify (+2 similar)

**Count:** 3
**Pattern:** `modifier_flow | failed_to_send_message`
**Type:** modifier_flow
**Session:** `d74fb7a7-c624-4ced-ad49-b3024d1f975c`

**Failure:** Failed to send message

**Conversation:**
```
User: I'd like a Belly Lox Sandwich
[FAILED: Failed to send message]
User: Add kalamata olive feta cream cheese
User: No kalamata olive feta cream cheese please
User: I'd like scallion cc on that
```

**Other instances:**
- Order Lemon Blueberry Cream Cheese Sandwich, Tofu Spread Sandwich then modify
- Order Open Face Traditional then modify

### Realistic order: 3 Bagel Package (+2 similar)

**Count:** 3
**Pattern:** `realistic_order | failed_to_send_message`
**Type:** realistic_order
**Session:** `7f766d96-cc20-43de-9a6a-a01956ebdd3b`

**Failure:** Failed to send message

**Conversation:**
```
User: One 3 Bagel Package please
[FAILED: Failed to send message]
```

**Other instances:**
- Realistic order: Vitamin Water Focus, Cafe au Lait
- Realistic order: Blueberry Cream Cheese Sandwich, Truffle Cream Cheese Sandwich

### Order Green Tea and Mozzarella Cheese Sandwich (+1 similar)

**Count:** 2
**Pattern:** `multi_item | failed_to_send_message`
**Type:** multi_item
**Session:** `7ee8b18e-2681-49f4-abb8-97420824c68e`

**Failure:** Failed to send message

**Conversation:**
```
User: Can I get a Green Tea and also a Mozzarella Cheese Sandwich
[FAILED: Failed to send message]
```

**Other instances:**
- Order Jalapeno Honey Cream Cheese Sandwich and Blueberry Cream Cheese

### Cancel order (+1 similar)

**Count:** 2
**Pattern:** `cart_ops | failed_to_send_message`
**Type:** cart_ops
**Session:** `affd917b-4e05-4ad0-a073-9f251487374e`

**Failure:** Failed to send message

**Conversation:**
```
User: I'll have a Scallion Cream Cheese Sandwich
[FAILED: Failed to send message]
User: I changed my mind, cancel
```

**Other instances:**
- Cancel order

### Tricky (add_item_during_config): Chipotle Cream Cheese Sandwich

**Count:** 1
**Pattern:** `tricky | add_item_during_config | failed_to_send_message`
**Type:** tricky
**Session:** `db14f028-6635-4502-a4e9-9212da470411`

**Failure:** Failed to send message

**Conversation:**
```
User: One chipoltay Cream Cheese Sandwich
[FAILED: Failed to send message]
User: And a Vegetable Cream Cheese Sandwi
```

### Order Sausage Egg and Cheese Sandwich

**Count:** 1
**Pattern:** `single_item | failed_to_send_message`
**Type:** single_item
**Session:** `a03284a6-1ef3-4621-9910-714c4e3b992c`

**Failure:** Failed to send message

**Conversation:**
```
User: Just a Sausage Egg and Cheese Sandwich
[FAILED: Failed to send message]
```

## Item Recognition (1 failures, 1 distinct patterns)

### Corpus [shorthand]: Just the item name, no preamble

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `3758562e-9b5f-4717-b070-88b2fd33ac4a`

**Failure:** Expected item 'Cinnamon Babka Slice' not in cart. Cart contains: []

**Conversation:**
```
User: Cinnam Babka Slice
Bot: What can I get for you?
[FAILED: Expected item 'Cinnamon Babka Slice' not in cart. Cart contains: []]
```

## STT-Induced Failure (1 failures, 1 distinct patterns)

### Order Espresso then modify

**Count:** 1
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `6c3127bb-918e-48d1-a4e8-47bf625df466`

**Failure:** STT-induced not found (original: 'I'll have a Espresso'): We don't have Espre. For espresso based beverages, we have Hot Latte, Hot Cappuccino, Cafe Americano

**Conversation:**
```
User: I'll have Espre
Bot: We don't have Espre. For espresso based beverages, we have Hot Latte, Hot Cappuccino, Cafe Americano, or Macchiato. Would you like any of those, or can I help you find something else?
[FAILED: STT-induced not found (original: 'I'll have a Espresso'): We don't have Espre. For espresso based beverages, we have Hot Latte, Hot Cappuccino, Cafe Americano]
User: Also add peppermint
User: Skip peppermint
User: Add caramel syrup to caramel syrup to that
```

## STT Resilience Summary

**1 failures** were caused by STT-simulated input corruption (not real parser bugs).

| Original Input | Corrupted Input | Bot Response |
|----------------|-----------------|--------------|
| I'll have a Espresso | I'll have Espre | We don't have Espre. For espresso based beverages, we have Hot Latte, Hot Cappuc... |
