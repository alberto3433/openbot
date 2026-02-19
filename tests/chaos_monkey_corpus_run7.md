# Chaos Monkey Test Failures

**Generated:** 2026-02-19T15:42:45.476831
**Session Start:** 2026-02-19T15:12:03.384085
**Total Tests:** 400
**Passed:** 358
**Failed:** 42

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 26 |
| Menu Item Not Found | 13 |
| Other | 3 |

## System Error (26 failures, 3 distinct patterns)

### Corpus [discovery]: Ask if a specific item exists, then order (+17 similar)

**Count:** 18
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `d0d2fabe-fe79-4798-be72-906b5a248075`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: do you have Nova Tofu Spread Sandwich?
Bot: Yes, Nova Tofu Spread Sandwich is available! Would you like to add it to your order?
User: great, I'll take one
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline
- Corpus [correction]: Switch bread type after ordering a bagel
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [correction]: Add a modifier after the initial order
- Corpus [inline_spec]: Fully specified bagel in one shot
- Corpus [inline_spec]: Fully specified bagel in one shot
- Corpus [quantity]: Add one more of the same item
- Corpus [correction]: Add a modifier after the initial order
- Corpus [discovery]: Ask about spreads, then order a bagel with one
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [correction]: Add a modifier after the initial order
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline
- Corpus [addon_during_config]: Answer bread question with modifier attached
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [correction]: Add a modifier after the initial order
- Corpus [addon_during_config]: Decline current question but add something else
- Corpus [quantity]: Add one more of the same item

### Ask for recommendations (+6 similar)

**Count:** 7
**Pattern:** `menu_inquiry | system_error`
**Type:** menu_inquiry
**Session:** `2e7d2a66-7df5-4a2a-892b-bdfb160c8dc9`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: What do people usually order?
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Ask about dietary options
- General menu inquiry
- Ask about beverages
- Ask about spreads
- General menu inquiry
- General menu inquiry

### Realistic order: The Delancey Omelette with Corned Beef

**Count:** 1
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `06e79063-0662-4ae9-ba16-34e239596e88`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd like a The Delancey Omelette with Corned Beef
Bot: Got it, for the The Delancey Omelette with Corned Beef with Swiss Cheese, Sauteed Onions, Breakfast Potato Latke, Corned Beef, Egg, and Corned Beef. Would you like a bagel or fruit salad with it?
User: bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: everything
Bot: I found a few options matching that. Did you mean Everything Bagel, Whole Wheat Everything Bagel, or Everything Sourdough Bagel?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Menu Item Not Found (13 failures, 6 distinct patterns)

### Corpus [quantity]: Change quantity after ordering (+5 similar)

**Count:** 6
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `84de00ed-8940-44d1-9f4b-e03791d99f5b`

**Failure:** Item not found: Sorry, we don't have actually make it two thank you. We have French Toast Bagel, Plain Bagel, Sesame

**Conversation:**
```
User: a so Provolone Cheese Sandwich
Bot: Got it, for the Provolone Cheese Sandwich with Provolone Cheese. What kind of bread?
User: actually make it two thank you
Bot: Sorry, we don't have actually make it two thank you. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have actually make it two thank you. We have French Toast Bagel, Plain Bagel, Sesame]
```

**Other instances:**
- Corpus [correction]: Change the size after ordering
- Corpus [addon_during_config]: Decline current question but add something else
- Corpus [correction]: Add a modifier after the initial order
- Corpus [correction]: Add a modifier after the initial order
- Corpus [correction]: Change the size after ordering

### Order Macchiato then modify (+1 similar)

**Count:** 2
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `c064600c-c97d-442e-8dd8-572142e07dec`

**Failure:** Item not found: Sorry, we don't have just Also add peppermint. We have Small or Large.

**Conversation:**
```
User: hello, Can I get a Macchiato
Bot: Got it, for the Macchiato. What size?
User: excuse me, Add regular sugar
Bot: Sure, I've added Domino Sugar. What size?
User: hey, Without regular sugar
Bot: OK, I've removed the Domino Sugar. What size?
User: just Also add peppermint
Bot: Sorry, we don't have just Also add peppermint. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have just Also add peppermint. We have Small or Large.]
```

**Other instances:**
- Order Seasonal Matcha Latte then modify

### Order The Margherita Pizza Bagel, Tofu Plain Sandwich then modify (+1 similar)

**Count:** 2
**Pattern:** `modifier_flow | modifier_not_in_order`
**Type:** modifier_flow
**Session:** `c767892d-6ff3-4ff9-a1f5-e6f56ce63121`

**Failure:** Item not found: I couldn't find plain spread in your order. What would you like to do?

**Conversation:**
```
User: I'll have a The Margherita Pizza Bagel and a Tofu Plain Sandwich
Bot: Got it, The Margherita Pizza Bagel and Tofu Plain Sandwich. For the The Margherita Pizza Bagel, what kind of bagel?
User: I'd like plain spread on that
Bot: We have Plain Bagel, Gluten Free Plain Bagel, or Plain Sourdough Bagel. Which would you like?
User: Take off the plain spread
Bot: I couldn't find plain spread in your order. What would you like to do?
[FAILED: Item not found: I couldn't find plain spread in your order. What would you like to do?]
User: With walnut raisin cream cheese please
```

**Other instances:**
- Order Iced Tea then modify

### Cancel order

**Count:** 1
**Pattern:** `cart_ops | item_not_recognized`
**Type:** cart_ops
**Session:** `a668f9aa-95af-4fe9-a5e9-c9d546a3316d`

**Failure:** Item not found: Sorry, we don't have Start over if you don't mind. We have French Toast Bagel, Plain Bagel, Sesame B

**Conversation:**
```
User: hi there, I'll have a Hot Corned Beef Sandwich
Bot: Got it, for the Hot Corned Beef Sandwich with Corned Beef. What kind of bread?
User: Start over if you don't mind
Bot: Sorry, we don't have Start over if you don't mind. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have Start over if you don't mind. We have French Toast Bagel, Plain Bagel, Sesame B]
```

### Tricky (context_switch): The Delancey with Pastrami

**Count:** 1
**Pattern:** `tricky | context_switch | item_not_recognized`
**Type:** tricky
**Session:** `83ae2389-2590-4923-8c15-84f6b0799a0c`

**Failure:** Item not found: Sorry, we don't have toasted and Pepper Jack Cheese for the Lemon Chicken Salad Sandwich. We have Fr

**Conversation:**
```
User: Can I get a The Delancey with Pastrami and a Lemon Chicken Salad Sandwich
Bot: Got it, The Delancey with Pastrami and Lemon Chicken Salad Sandwich. For the The Delancey with Pastrami, what kind of bread?
User: toasted and Pepper Jack Cheese for the Lemon Chicken Salad Sandwich
Bot: Sorry, we don't have toasted and Pepper Jack Cheese for the Lemon Chicken Salad Sandwich. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these o...
[FAILED: Item not found: Sorry, we don't have toasted and Pepper Jack Cheese for the Lemon Chicken Salad Sandwich. We have Fr]
```

### Corpus [correction]: Remove a modifier after adding it

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `b4a9f0ba-0c20-471d-ba11-e806b52c6376`

**Failure:** Item not found: I couldn't find maple raisin walnut cream cheese in your order. What would you like to do?

**Conversation:**
```
User: a Coca-Cola with maple raisin walnut cream cheese
Bot: Got it, Coca-Cola. Anything else?
User: actually, no maple raisin walnut cream cheese
Bot: I couldn't find maple raisin walnut cream cheese in your order. What would you like to do?
[FAILED: Item not found: I couldn't find maple raisin walnut cream cheese in your order. What would you like to do?]
```

## Other (3 failures, 1 distinct patterns)

### Corpus [quantity]: Multiple bagels of a specific bread (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `69cfbd48-78d5-4b0e-ac2b-36ae4b1fd6b2`

**Failure:** Failed to send message

**Conversation:**
```
User: 3 Artisan Bread bagels
[FAILED: Failed to send message]
```

**Other instances:**
- Corpus [quantity]: Order a large quantity shorthand
- Corpus [quantity]: Order multiple of the same item
