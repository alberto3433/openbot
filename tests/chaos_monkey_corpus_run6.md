# Chaos Monkey Test Failures

**Generated:** 2026-02-19T12:34:59.558350
**Session Start:** 2026-02-19T12:03:12.760120
**Total Tests:** 200
**Passed:** 166
**Failed:** 34

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 19 |
| Menu Item Not Found | 10 |
| Other | 3 |
| Item Recognition | 2 |

## System Error (19 failures, 4 distinct patterns)

### Corpus [discovery]: Ask if a specific item exists, then order (+11 similar)

**Count:** 12
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `a76b78cc-cb15-4635-98aa-9a3e972dedc2`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: do you have Chipotle Cream Cheese Sandwich?
Bot: Yes, Chipotle Cream Cheese Sandwich is available! Would you like to add it to your order?
User: great, I'll take one
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [inline_spec]: Order a sized drink with size and hot inline
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [batch_order]: A food item and a drink together
- Corpus [inline_spec]: Fully specified bagel in one shot
- Corpus [batch_order]: Two items with 'also' connector
- Corpus [addon_during_config]: Answer yes and add a modifier in the same turn
- Corpus [context_reference]: Order the same as a previous item
- Corpus [shorthand]: Modifier on a bread type
- Corpus [context_reference]: Order the same as a previous item

### General menu inquiry (+4 similar)

**Count:** 5
**Pattern:** `menu_inquiry | system_error`
**Type:** menu_inquiry
**Session:** `ac82d110-4724-4af0-a2b3-fe8265a4ed6a`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: What are my options?
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Ask about soups
- Ask about dietary options
- Ask about cream cheese
- General menu inquiry

### Order Pepper Jack Cheese Sandwich

**Count:** 1
**Pattern:** `single_item | system_error`
**Type:** single_item
**Session:** `dca4b4d5-f59f-4f6d-b5ba-554485f02ebc`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: One Pepper Jack just Cheese Sandwich please
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

### Realistic order: The Health Nut Omelette

**Count:** 1
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `53ca8dd7-f5ba-440d-9784-c93b7768dbbe`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd like a The Health Nut Omelette
Bot: Got it, for the The Health Nut Omelette with Beefsteak Tomatoes, Mushrooms, Egg White, Red Pepper, Green Pepper, and Spinach. Would you like a bagel or fruit salad with it?
User: bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: sesame
Bot: I found a few options matching that. Did you mean Sesame Bagel or Sesame Sourdough Bagel?
User: no
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Menu Item Not Found (10 failures, 6 distinct patterns)

### Corpus [context_reference]: Order the same as a previous item (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `8a20753b-704f-440a-b005-4fb4146db7a7`

**Failure:** Item not found: Sorry, we don't have so I'll have the same. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: hi there a Strawberry Cream Cheese
Bot: Got it, for the Strawberry Cream Cheese with 1/4 lb. How much? 1/4 lb? 1 lb?
User: so I'll have the same
Bot: Sorry, we don't have so I'll have the same. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have so I'll have the same. We have 1/4 lb or 1 lb.]
```

**Other instances:**
- Corpus [correction]: Change the size after ordering
- Corpus [context_reference]: Order the same as a previous item

### Order Hot Cappuccino then modify (+1 similar)

**Count:** 2
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `e96347b8-e4bd-40d6-b273-8dfe5576de33`

**Failure:** Item not found: Sorry, we don't have hi there, Add almond to that. We have Small or Large.

**Conversation:**
```
User: One Hot Cappuccino please please
Bot: Got it, for the Hot Cappuccino. What size?
User: Put basically lactose free on it
Bot: Sure, I've added Lactose Free Milk. What size?
User: hi there, Actually no lactose free
Bot: OK, I've removed the Lactose Free Milk. What size?
User: hi there, Add almond to that
Bot: Sorry, we don't have hi there, Add almond to that. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have hi there, Add almond to that. We have Small or Large.]
```

**Other instances:**
- Order Lemon Blueberry Cream Cheese Sandwich, The Leo then modify

### Order Macchiato, Kalamata Olive Feta Cream Cheese Sandwich then modify (+1 similar)

**Count:** 2
**Pattern:** `modifier_flow | modifier_not_in_order`
**Type:** modifier_flow
**Session:** `be06d81f-8911-49ca-9ba9-a2c040e5b5e8`

**Failure:** Item not found: I couldn't find almond in your order. What would you like to do?

**Conversation:**
```
User: Can I get a Macchiato and a Kalamata Olive Feta Cream Cheese Sandwich
Bot: Got it, Macchiato and Kalamata Olive Feta Cream Cheese Sandwich. For the Macchiato, what size?
User: With almond please
Bot: Let's finish with your Macchiato first. What size?
User: Remove the almond
Bot: I couldn't find almond in your order. What would you like to do?
[FAILED: Item not found: I couldn't find almond in your order. What would you like to do?]
User: With half and half please
```

**Other instances:**
- Order Iced Coffee then modify

### Tricky (multi_attr_modifier): Iced Cappucino

**Count:** 1
**Pattern:** `tricky | multi_attr_modifier | item_not_recognized`
**Type:** tricky
**Session:** `013948c5-60fa-4983-8978-7b9d1d0a6edb`

**Failure:** Item not found: Sorry, we don't have The Health Nut Omelette decaf and Whole Milk. We have Small or Large.

**Conversation:**
```
User: Hazelnut Syrup decaf Iced Cappucino with caramel
Bot: Got it, for the Iced Cappucino with Decaf, Hazelnut Syrup, and Caramel Syrup. What size?
User: half n half
Bot: Got it, Half N Half. What size?
User: The Health Nut Omelette decaf and Whole Milk
Bot: Sorry, we don't have The Health Nut Omelette decaf and Whole Milk. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have The Health Nut Omelette decaf and Whole Milk. We have Small or Large.]
```

### Corpus [correction]: Remove a modifier after adding it

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `70a515ec-5abf-41dc-96c5-d2056b017a4d`

**Failure:** Item not found: I couldn't find honey walnut cc in your order. What would you like to do?

**Conversation:**
```
User: a Essentia Water 700ml with basically honey walnut cc
Bot: Got it, Essentia Water 700ml. Anything else?
User: uh actually, no honey walnut cc
Bot: I couldn't find honey walnut cc in your order. What would you like to do?
[FAILED: Item not found: I couldn't find honey walnut cc in your order. What would you like to do?]
```

### Order Iced Chai Tea and Maple Raisin Walnut Cream Cheese Sandwich

**Count:** 1
**Pattern:** `multi_item | item_not_recognized`
**Type:** multi_item
**Session:** `d780d5cb-a1d6-4869-8777-c1f58a37c087`

**Failure:** Item not found: Sorry, we don't have Also a Maple basically Raisin Walnut Cream Cheese Sandwich. We have Small or La

**Conversation:**
```
User: basically I'll have a Iced Chai Tea
Bot: Got it, for the Chai Tea. What size?
User: Also a Maple basically Raisin Walnut Cream Cheese Sandwich
Bot: Sorry, we don't have Also a Maple basically Raisin Walnut Cream Cheese Sandwich. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Also a Maple basically Raisin Walnut Cream Cheese Sandwich. We have Small or La]
```

## Other (3 failures, 1 distinct patterns)

### Corpus [quantity]: Order a large quantity shorthand (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `3e8cb23b-3be6-48c0-8862-2859c492bb98`

**Failure:** Failed to send message

**Conversation:**
```
User: half dozen Jalapeno Bagel bagels
[FAILED: Failed to send message]
```

**Other instances:**
- Corpus [quantity]: Order a large quantity shorthand
- Corpus [quantity]: Multiple bagels of a specific bread

## Item Recognition (2 failures, 2 distinct patterns)

### Change Joyva Marble Halva quantity to 1

**Count:** 1
**Pattern:** `cart_ops | modifier_not_in_order`
**Type:** cart_ops
**Session:** `6e6df8d2-1d77-47b2-8cf9-e60781030dc7`

**Failure:** Expected item 'Joyva Marble Halva' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Joyva Marble Halva
Bot: Got it, Joyva Marble Halva. Anything else?
User: Actually, make that one
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Joyva Marble Halva' not in cart. Cart contains: []]
```

### Realistic order: Ham

**Count:** 1
**Pattern:** `realistic_order | modifier_not_in_order`
**Type:** realistic_order
**Session:** `e39b1e70-2bcd-4218-afd8-07b9cc4d81f8`

**Failure:** Expected item 'Ham' not in cart. Cart contains: []

**Conversation:**
```
User: hello, One Ham please
Bot: For ham, we have the Side of Ham. Would you like one?
[FAILED: Expected item 'Ham' not in cart. Cart contains: []]
```
