# Chaos Monkey Test Failures

**Generated:** 2026-02-18T17:14:27.006826
**Session Start:** 2026-02-18T17:09:10.470600
**Total Tests:** 60
**Passed:** 46
**Failed:** 14

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 6 |
| Item Recognition | 4 |
| System Error | 3 |
| Other | 1 |

## Menu Item Not Found (6 failures, 3 distinct patterns)

### Corpus [addon_during_config]: Answer bread question with modifier attached (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `51e05687-6468-4f03-b3a2-3ad8f3c883e2`

**Failure:** Item not found: Sorry, we don't have Bialy with english breakfast. We have French Toast Bagel, Plain Bagel, Sesame B

**Conversation:**
```
User: a bagel please
Bot: Got it, for the Bagel. What kind of bagel?
User: Bialy with english breakfast
Bot: Sorry, we don't have Bialy with english breakfast. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Poppy Bagel, and Onion Bagel, and more. Do you want one of these or do you want to hear more o...
[FAILED: Item not found: Sorry, we don't have Bialy with english breakfast. We have French Toast Bagel, Plain Bagel, Sesame B]
```

**Other instances:**
- Corpus [addon_during_config]: Answer size question with iced preference
- Corpus [addon_during_config]: Answer size question with iced preference

### Order Chai Tea then modify (+1 similar)

**Count:** 2
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `8240d0a8-657e-400c-ae6c-f57368400370`

**Failure:** Item not found: Sorry, we don't have Can like you add oat milk. We have Small or Large.

**Conversation:**
```
User: One um Chai Tea please
Bot: Got it, for the Chai Tea. What size?
User: Can like you add oat milk
Bot: Sorry, we don't have Can like you add oat milk. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Can like you add oat milk. We have Small or Large.]
User: hello, Remove the oat milk
User: Also add skim if you don't mind
```

**Other instances:**
- Order Espresso, The Classic then modify

### Change Whitefish Salad Sandwich quantity to 1

**Count:** 1
**Pattern:** `cart_ops | item_not_recognized`
**Type:** cart_ops
**Session:** `874af804-9fb3-4ef7-b5ad-55d022d1cc4d`

**Failure:** Item not found: Sorry, we don't have Change that to um one. We have French Toast Bagel, Plain Bagel, Sesame Bagel, B

**Conversation:**
```
User: I'll have well a Whitefish Salad Sandwich
Bot: Got it, for the Whitefish Salad Sandwich with Beefsteak Tomatoes, Lettuce, and Whitefish Salad. What kind of bread?
User: Change that to um one
Bot: Sorry, we don't have Change that to um one. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have Change that to um one. We have French Toast Bagel, Plain Bagel, Sesame Bagel, B]
```

## Item Recognition (4 failures, 1 distinct patterns)

### Corpus [discovery]: Ask what's in a category, then order (+3 similar)

**Count:** 4
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `778bdf46-0372-4203-ac98-75976dfeed3d`

**Failure:** Expected item 'Swiss Cheese Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: what sandwiches do you have?
Bot: Our sandwiches include: The Health Nut, The Lexington, The Columbus BEC, The Classic BEC, The Leo, and 88 more. Would you like any of these?
[FAILED: Expected item 'Swiss Cheese Sandwich' not in cart. Cart contains: []]
User: I'll do a Swiss Cheese Sandwich
```

**Other instances:**
- Corpus [discovery]: Ask what's in a category, then order
- Corpus [discovery]: Ask for recommendations, then order
- Corpus [discovery]: Ask for recommendations, then order

## System Error (3 failures, 1 distinct patterns)

### Corpus [context_reference]: Order another of the same item (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `6de98666-7554-4bc3-8efc-2a506cb871f2`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: a Chicken Salad please
Bot: Got it, for the Cranberry Pecan Chicken Salad Sandwich with Cranberry Pecan Chicken Salad, Lettuce, and Beefsteak Tomatoes. What kind of bread?
User: another one
Bot: Let's finish customizing the Cranberry Pecan Chicken Salad Sandwich. What kind of bread?
User: everything
Bot: I found a few options matching that. Did you mean Everything Bagel, Whole Wheat Everything Bagel, Whole Wheat Everything Flatz, Everything Sourdough Bagel, or Everything Sourdough Bagel Flatz?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [addon_during_config]: Answer bread question with toasted in same breath
- Corpus [addon_during_config]: Answer bread question with toasted in same breath

## Other (1 failures, 1 distinct patterns)

### Corpus [quantity]: Multiple bagels of a specific bread

**Count:** 1
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `8fa5f3d9-9843-4ccc-aca4-13b39a8c0a6d`

**Failure:** Failed to send message

**Conversation:**
```
User: 2 White Bread bagels
[FAILED: Failed to send message]
```
