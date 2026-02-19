# Chaos Monkey Test Failures

**Generated:** 2026-02-19T00:42:55.000588
**Session Start:** 2026-02-19T00:27:06.608410
**Total Tests:** 200
**Passed:** 169
**Failed:** 31

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 15 |
| Menu Item Not Found | 10 |
| Item Recognition | 5 |
| Other | 1 |

## System Error (15 failures, 4 distinct patterns)

### Corpus [correction]: Add a modifier after the initial order (+8 similar)

**Count:** 9
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `6682c06c-2b22-4e16-bba3-374534fd8fe8`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd like a Cinnamon Babka
Bot: Got it, Cinnamon Babka. Anything else?
User: oh and can you add sour cream
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline
- Corpus [addon_during_config]: Decline current question but add something else
- Corpus [quantity]: Add one more of the same item
- Corpus [discovery]: Ask about spreads, then order a bagel with one
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline
- Corpus [batch_order]: Two different bagels by bread type
- Corpus [shorthand]: Bread type with modifier, no verb
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline

### General menu inquiry (+2 similar)

**Count:** 3
**Pattern:** `menu_inquiry | system_error`
**Type:** menu_inquiry
**Session:** `465a3e5d-7378-4473-9499-9a66a505bbb6`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: Can you tell me what you have?
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Ask for recommendations
- General menu inquiry

### Realistic order: Joyva Halva Chocolate (+1 similar)

**Count:** 2
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `9fd717f6-0686-41e7-84e9-8efc42e1255e`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: One Joyva Halva just Chocolate please
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Realistic order: Tuna Salad

### Cancel order

**Count:** 1
**Pattern:** `cart_ops | system_error`
**Type:** cart_ops
**Session:** `c4709bc2-fd10-4c55-a2c4-c0723e146558`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'll have a Bottled Water
Bot: Got it, Bottled Water. Anything else?
User: I changed my mind, cancel
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Menu Item Not Found (10 failures, 6 distinct patterns)

### Corpus [correction]: Change the size after ordering (+4 similar)

**Count:** 5
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `1283816b-bdc2-4c7e-a1e9-97f260355fe0`

**Failure:** Item not found: Sorry, we don't have hello, wait, make that a Small. We have French Toast Bagel, Plain Bagel, Sesame

**Conversation:**
```
User: a just Small Bialy
Bot: Got it, for the Bialy. What kind of bagel?
User: hello, wait, make that a Small
Bot: Sorry, we don't have hello, wait, make that a Small. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Poppy Bagel, and Onion Bagel, and more. Do you want one of these or do you want to hear more...
[FAILED: Item not found: Sorry, we don't have hello, wait, make that a Small. We have French Toast Bagel, Plain Bagel, Sesame]
```

**Other instances:**
- Corpus [correction]: Change the size after ordering
- Corpus [correction]: Switch to a different item entirely
- Corpus [correction]: Switch to a different item entirely
- Corpus [addon_during_config]: Decline current question but add something else

### Tricky (context_switch): The Reuben

**Count:** 1
**Pattern:** `tricky | context_switch | item_not_recognized`
**Type:** tricky
**Session:** `691577ea-1071-4ea9-be01-6bbaac1b54ef`

**Failure:** Item not found: Sorry, we don't have make the Jelly Rings toasted and American Cheese. We have French Toast Bagel, P

**Conversation:**
```
User: I'll have a The Reuben and a Jelly Rings
Bot: Got it, for the The Reuben with Corned Beef, Pastrami, Swiss Cheese, Turkey, and Sauerkraut. What kind of bread?
User: make the Jelly Rings toasted and American Cheese
Bot: Sorry, we don't have make the Jelly Rings toasted and American Cheese. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to he...
[FAILED: Item not found: Sorry, we don't have make the Jelly Rings toasted and American Cheese. We have French Toast Bagel, P]
```

### Order Muenster Cheese Sandwich then modify

**Count:** 1
**Pattern:** `modifier_flow | modifier_not_in_order`
**Type:** modifier_flow
**Session:** `7ab8a9a4-2eff-4bd0-966b-e536f57d4c0f`

**Failure:** Item not found: I couldn't find american cheese and in your order. What would you like to do?

**Conversation:**
```
User: Can I get a Muenster Cheese hmm Sandwich
Bot: Got it, for the Muenster Cheese Sandwich with Muenster Cheese. What kind of bread?
User: Also add american just cheese
Bot: Got it, I've added Gouda Cheese. Now, for your Muenster Cheese Sandwich, what kind of bread?
User: Skip the american cheese please and thank you
Bot: I couldn't find american cheese and in your order. What would you like to do?
[FAILED: Item not found: I couldn't find american cheese and in your order. What would you like to do?]
User: actually I'd like whole wheat bread on that
```

### Corpus [correction]: Remove a modifier after adding it

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `2846577c-53cc-4089-82ba-b46d0e7cdb37`

**Failure:** Item not found: I couldn't find turkey in your order. What would you like to do?

**Conversation:**
```
User: a Whole Whitefish with turkey
Bot: Got it, for the Whole Whitefish. How much? 1/4 lb? 1 lb?
User: actually, no turkey
Bot: I couldn't find turkey in your order. What would you like to do?
[FAILED: Item not found: I couldn't find turkey in your order. What would you like to do?]
```

### Tricky (multi_attr_modifier): Cafe Americano

**Count:** 1
**Pattern:** `tricky | multi_attr_modifier | item_not_recognized`
**Type:** tricky
**Session:** `26826ed9-a664-43d7-9bab-d0b88a4430d1`

**Failure:** Item not found: Sorry, we don't have Gravlax Sweet N Low and decaf. We have Small or Large.

**Conversation:**
```
User: Equal decaf Cafe Americano with almond
Bot: Got it, for the Cafe Americano with Decaf and Equal. What size?
User: skim
Bot: Got it, Skim Milk. What size?
User: Gravlax Sweet N Low and decaf
Bot: Sorry, we don't have Gravlax Sweet N Low and decaf. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Gravlax Sweet N Low and decaf. We have Small or Large.]
```

### Order The Old School Tuna Sandwich then modify

**Count:** 1
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `f8c7a3f4-0387-42b9-8a0a-3e9afd7dbd22`

**Failure:** Item not found: Sorry, we don't have just Put red onion on it. We have French Toast Bagel, Plain Bagel, Sesame Bagel

**Conversation:**
```
User: I'd like a The Old School Tuna Sandwich please and thank you
Bot: Got it, for the The Old School Tuna Sandwich with Beefsteak Tomatoes, Lettuce, and Tuna Salad. What kind of bread?
User: just Put red onion on it
Bot: Sorry, we don't have just Put red onion on it. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have just Put red onion on it. We have French Toast Bagel, Plain Bagel, Sesame Bagel]
User: uh Without red onion
User: hey, Can you add strawberry cc
```

## Item Recognition (5 failures, 1 distinct patterns)

### Corpus [discovery]: Ask for recommendations, then order (+4 similar)

**Count:** 5
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `d49d7117-58eb-468c-b913-c30ab9790984`

**Failure:** Expected item 'Ham Egg and Cheese Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: what's popular?
Bot: Our signature items are: The Classic BEC, The Leo, The Avocado Toast, The Delancey with Corned Beef, The Health Nut, and 24 more. Would you like any of these?
[FAILED: Expected item 'Ham Egg and Cheese Sandwich' not in cart. Cart contains: []]
User: I'll try a Ham Egg and Cheese Sandwich
```

**Other instances:**
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask what's in a category, then order

## Other (1 failures, 1 distinct patterns)

### Corpus [quantity]: Order multiple of the same item

**Count:** 1
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `43bde765-4ba9-4057-970d-ed0a6565a12f`

**Failure:** Failed to send message

**Conversation:**
```
User: three Bologna please
[FAILED: Failed to send message]
```
