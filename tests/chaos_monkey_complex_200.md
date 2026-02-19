# Chaos Monkey Test Failures

**Generated:** 2026-02-17T21:36:16.940370
**Session Start:** 2026-02-17T21:20:38.457366
**Total Tests:** 300
**Passed:** 294
**Failed:** 6
**False Positives (not reproduced):** 1

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 5 |
| Item Recognition | 1 |

## Menu Item Not Found (5 failures, 3 distinct patterns)

### Order Flagel then modify (+2 similar)

**Count:** 3
**Pattern:** `modifier_flow | modifier_not_in_order`
**Type:** modifier_flow
**Session:** `317c052a-2a78-4040-8251-159002c9c761`

**Failure:** Item not found: I couldn't find veggie in your order. What would you like to do?

**Conversation:**
```
User: I'll have a Flagel
Bot: Got it, for the Flagel. What kind of bagel?
User: Also add veggie
Bot: We have Scrambled Egg, Fried Egg (Sunny Side Up), Over Easy Egg, Over Medium Egg, Over Hard Egg, and Egg Whites. How would you like your Eggs?
User: Take off the veggie
Bot: I couldn't find veggie in your order. What would you like to do?
[FAILED: Item not found: I couldn't find veggie in your order. What would you like to do?]
User: Put scallion cream cheese on it
```

**Other instances:**
- Order Hot Pastrami Sandwich then modify
- Order Green Tea, Flagel then modify

### Order Iced Americano then modify

**Count:** 1
**Pattern:** `modifier_flow | item_not_recognized`
**Type:** modifier_flow
**Session:** `e65b71cd-e743-46a3-9303-075a54c5f562`

**Failure:** Item not found: Sorry, we don't have Can you add oat thank you. We have Small or Large.

**Conversation:**
```
User: I'll have a Iced Americano please and thank you
Bot: Got it, for the Iced Americano. What size?
User: hey, Add soy milk
Bot: Sure, I've added Soy Milk. What size?
User: Hold the soy milk please
Bot: OK, I've removed the Soy Milk. What size?
User: Can you add oat thank you
Bot: Sorry, we don't have Can you add oat thank you. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Can you add oat thank you. We have Small or Large.]
```

### Change Muenster Cheese Sandwich quantity to 1

**Count:** 1
**Pattern:** `cart_ops | item_not_recognized`
**Type:** cart_ops
**Session:** `06d1be21-1ecc-42d6-b913-d8c32c3b9d45`

**Failure:** Item not found: Sorry, we don't have one of those. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and

**Conversation:**
```
User: I'll have a Muenster Cheese Sandwich
Bot: Got it, for the Muenster Cheese Sandwich with Muenster Cheese. What kind of bread?
User: I'll take one of those
Bot: Sorry, we don't have one of those. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have one of those. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and]
```

## Item Recognition (1 failures, 1 distinct patterns)

### Change Snapple Peach Tea quantity to 1

**Count:** 1
**Pattern:** `cart_ops | modifier_not_in_order`
**Type:** cart_ops
**Session:** `be18a649-d6a9-444a-b88c-7b22ad524d61`

**Failure:** Expected item 'Snapple Peach Tea' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Snapple Peach Tea
Bot: Got it, Snapple Peach Tea. Anything else?
User: Actually, make that one
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Snapple Peach Tea' not in cart. Cart contains: []]
```
