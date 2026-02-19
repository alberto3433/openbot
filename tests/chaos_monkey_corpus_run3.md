# Chaos Monkey Test Failures

**Generated:** 2026-02-18T17:49:57.333447
**Session Start:** 2026-02-18T17:33:56.593475
**Total Tests:** 200
**Passed:** 171
**Failed:** 29

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 12 |
| Menu Item Not Found | 10 |
| System Error | 5 |
| Other | 2 |

## Item Recognition (12 failures, 2 distinct patterns)

### Corpus [discovery]: Ask what's in a category, then order (+10 similar)

**Count:** 11
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `de7df77f-0071-4bd4-ace7-644f4b62c596`

**Failure:** Expected item 'Joe's Peach Tea' not in cart. Cart contains: []

**Conversation:**
```
User: what drinks do you have?
Bot: Our drinks include: Chocolate Milk, Boxed Coffee, Irving Farm Cold Brew, Snapple Iced Tea, Snapple Lemonade, and 63 more. Would you like any of these?
[FAILED: Expected item 'Joe's Peach Tea' not in cart. Cart contains: []]
User: I'll do a Joe's Peach Tea
```

**Other instances:**
- Corpus [correction]: Switch to a different item entirely
- Corpus [discovery]: Ask what's in a category, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask what's in a category, then order
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [discovery]: Ask if a specific item exists, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask what's in a category, then order

### Change Apple Juice quantity to 1

**Count:** 1
**Pattern:** `cart_ops | modifier_not_in_order`
**Type:** cart_ops
**Session:** `de2b79d0-884b-4c92-8349-c4ae79ce72e6`

**Failure:** Expected item 'Apple Juice' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Apple Juice
Bot: Got it, Apple Juice. Anything else?
User: Actually, make that one
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Apple Juice' not in cart. Cart contains: []]
```

## Menu Item Not Found (10 failures, 6 distinct patterns)

### Corpus [correction]: Switch to a different item entirely (+4 similar)

**Count:** 5
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `b8ef451c-4480-4cf4-964c-9a2882e75d6a`

**Failure:** Item not found: Sorry, we don't have actually, switch that to a Chocolate Chip Cookie. We have French Toast Bagel, P

**Conversation:**
```
User: I'll have a All-Natural Smoked Turkey Sandwich
Bot: Got it, for the All-Natural Smoked Turkey Sandwich with Smoked Turkey. What kind of bread?
User: actually, switch that to a Chocolate Chip Cookie
Bot: Sorry, we don't have actually, switch that to a Chocolate Chip Cookie. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to he...
[FAILED: Item not found: Sorry, we don't have actually, switch that to a Chocolate Chip Cookie. We have French Toast Bagel, P]
```

**Other instances:**
- Corpus [quantity]: Add one more of the same item
- Corpus [addon_during_config]: Decline current question but add something else
- Corpus [correction]: Change the size after ordering
- Corpus [correction]: Change the size after ordering

### Order Hot Coffee then modify

**Count:** 1
**Pattern:** `modifier_flow | modifier_not_in_order`
**Type:** modifier_flow
**Session:** `92e4c23a-7aff-4fdd-a745-019b2e86fa71`

**Failure:** Item not found: I couldn't find almond in your order. What would you like to do?

**Conversation:**
```
User: I'd like a Hot Coffee
Bot: Got it, for the Hot Coffee. What size?
User: Add almond to that
Bot: Let's finish with your Hot Coffee first. What size?
User: No almond please
Bot: I couldn't find almond in your order. What would you like to do?
[FAILED: Item not found: I couldn't find almond in your order. What would you like to do?]
User: With raw sugar please
```

### Tricky (context_switch): Egg Salad Sandwich

**Count:** 1
**Pattern:** `tricky | context_switch | item_not_recognized`
**Type:** tricky
**Session:** `71263e39-818c-4adf-a166-c1796caa7c93`

**Failure:** Item not found: Sorry, we don't have make the Smoked Trout Sandwich toasted and Havarti Cheese. We have French Toast

**Conversation:**
```
User: I'll have a Egg Salad Sandwich and a Smoked Trout Sandwich
Bot: Got it, Egg Salad Sandwich and Smoked Trout Sandwich. For the Egg Salad Sandwich, what kind of bread?
User: make the Smoked Trout Sandwich toasted and Havarti Cheese
Bot: Sorry, we don't have make the Smoked Trout Sandwich toasted and Havarti Cheese. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you w...
[FAILED: Item not found: Sorry, we don't have make the Smoked Trout Sandwich toasted and Havarti Cheese. We have French Toast]
```

### Tricky (multi_attr_modifier): Sausage Egg and Cheese Sandwich

**Count:** 1
**Pattern:** `tricky | multi_attr_modifier | item_not_recognized`
**Type:** tricky
**Session:** `641f6417-5d53-420a-9789-3eebd87067a1`

**Failure:** Item not found: Sorry, we don't have make the Boxed Coffee Rainbow Bagel and toasted. We have Over Easy, Over Medium

**Conversation:**
```
User: Cheddar Cheese toasted Sausage Egg and Cheese Sandwich with pumpernickel bagel
Bot: Got it, for the Sausage Egg and Cheese Sandwich with Sausage Patty, Egg, Cheddar Cheese, and Toasted. Any eggs?
User: poppy seed bagel
Bot: Got it, Poppy Bagel. How would you like your eggs?
User: make the Boxed Coffee Rainbow Bagel and toasted
Bot: Sorry, we don't have make the Boxed Coffee Rainbow Bagel and toasted. We have Over Easy, Over Medium, Over Hard, Egg Whites, and Scrambled, and more. Do you want one of these or do you want to hear mo...
[FAILED: Item not found: Sorry, we don't have make the Boxed Coffee Rainbow Bagel and toasted. We have Over Easy, Over Medium]
```

### Corpus [addon_during_config]: Answer bread question with toasted in same breath

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `36dc2e6e-ca2d-449e-8fbf-56167eda67e2`

**Failure:** Item not found: I couldn't find bread toasted in your order. What would you like to do?

**Conversation:**
```
User: hey, I'll have a bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: No Bread toasted if you don't mind
Bot: I couldn't find bread toasted in your order. What would you like to do?
[FAILED: Item not found: I couldn't find bread toasted in your order. What would you like to do?]
```

### Order Butter Sandwich, Muenster Cheese Sandwich then modify

**Count:** 1
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `0ef89846-f316-4690-97c6-9e133149b19d`

**Failure:** Item not found: Sorry, we don't have just Also add grape jam. We have French Toast Bagel, Plain Bagel, Sesame Bagel,

**Conversation:**
```
User: just I'll have a Butter Sandwich and a Muenster Cheese Sandwich
Bot: Got it, Butter Sandwich and Muenster Cheese Sandwich. For the Butter Sandwich, what kind of bread?
User: just Also add grape jam
Bot: Sorry, we don't have just Also add grape jam. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have just Also add grape jam. We have French Toast Bagel, Plain Bagel, Sesame Bagel,]
User: Remove the grape jam if you don't mind
User: basically Also add jalapeno-honey
```

## System Error (5 failures, 2 distinct patterns)

### Corpus [inline_spec]: Fully specified bagel in one shot (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `4cb1633d-fda3-4cad-b652-7562905c7d92`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: White Bread like bagel toasted with corned beef
Bot: Got it, for the Bagel with Toasted and Corned Beef. What kind of bagel?
User: everything
Bot: I found a few options matching that. Did you mean Everything Bagel, Whole Wheat Everything Bagel, or Everything Sourdough Bagel?
User: no
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [discovery]: Ask about spreads, then order a bagel with one
- Corpus [quantity]: Add one more of the same item

### Realistic order: Corned Beef (+1 similar)

**Count:** 2
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `5d1e910b-15a8-4b5b-85aa-b0332994f391`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd like a Corned Beef
Bot: Got it, for the The Delancey with Corned Beef with Swiss Cheese, Sauteed Onions, Breakfast Potato Latke, Corned Beef, and Egg. What kind of bread?
User: sesame
Bot: I found a few options matching that. Did you mean Sesame Bagel or Sesame Sourdough Bagel?
User: no
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Realistic order: Gravlax

## Other (2 failures, 1 distinct patterns)

### Corpus [quantity]: Multiple bagels of a specific bread (+1 similar)

**Count:** 2
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `8d70519a-1b47-48e0-bcc2-9e6d4bae306f`

**Failure:** Failed to send message

**Conversation:**
```
User: 2 Poppy Bagel bagels
[FAILED: Failed to send message]
```

**Other instances:**
- Corpus [quantity]: Multiple bagels of a specific bread
