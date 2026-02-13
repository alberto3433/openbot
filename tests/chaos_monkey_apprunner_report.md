# Chaos Monkey Test Failures

**Generated:** 2026-02-13T14:01:59.457593
**Session Start:** 2026-02-13T13:51:45.143467
**Total Tests:** 65
**Passed:** 63
**Failed:** 2

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 2 |

## Menu Item Not Found

### Order Vegetable Cream Cheese Sandwich, Iced Tea then modify

**Type:** modifier_flow
**Session:** `1673be26-c435-400e-89d7-9306933370c7`

**Failure:** Item not found: I couldn't find jalapeño cheddar bagel in your order. What would you like to do?

**Conversation:**
```
User: Can I get a Vegetable Cream Cheese Sandwich and a Iced Tea
Bot: Got it, Vegetable Cream Cheese Sandwich and Iced Tea. For the Vegetable Cream Cheese Sandwich, what kind of bread would you like?
User: Also add jalapeño cheddar bagel
Bot: Got it, I've added Cheddar Cheese Sandwich. Now, for your Vegetable Cream Cheese Sandwich, what kind of bread would you like?
User: Remove the jalapeño cheddar bagel
Bot: I couldn't find jalapeño cheddar bagel in your order. What would you like to do?
[FAILED: Item not found: I couldn't find jalapeño cheddar bagel in your order. What would you like to do?]
User: I'd like avocado on that
```

### Change Irving Farm Cold Brew quantity to 5

**Type:** cart_ops
**Session:** `c0b3c6d9-2795-42bc-9ef8-4aa5147455bc`

**Failure:** Item not found: I'm sorry, we don't have five of those. We do have Breads, Sandwiches, Omelettes, and Drinks though 

**Conversation:**
```
User: I'll have a Irving Farm Cold Brew
Bot: Got it, Irving Farm Cold Brew. Anything else?
User: I'll take five of those
Bot: I'm sorry, we don't have five of those. We do have Breads, Sandwiches, Omelettes, and Drinks though - would any of those interest you?
[FAILED: Item not found: I'm sorry, we don't have five of those. We do have Breads, Sandwiches, Omelettes, and Drinks though ]
```
