# Chaos Monkey Test Failures

**Generated:** 2026-02-25T00:46:08.352379
**Session Start:** 2026-02-25T00:15:54.894904
**Total Tests:** 260
**Passed:** 239
**Failed:** 21

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 11 |
| Other | 8 |
| System Error | 1 |
| Menu Item Not Found | 1 |

## Item Recognition (11 failures, 1 distinct patterns)

### Complex order: Sun-Dried Tomato Cream Cheese Sandwich (+10 similar)

**Count:** 11
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `52677c8e-a42d-4f51-8b6a-9d6919f67482`

**Failure:** Expected item 'Sun-Dried Tomato Cream Cheese Sandwich' not in cart. Cart contains: ['sandwich not scooped with whitefish salad', 'little veggie cream cheese']

**Conversation:**
```
User: I'll have a sun-dried tomato cream cheese sandwich not scooped with whitefish salad and a little veggie cream cheese
Bot: Got it, sandwich not scooped with whitefish salad and a little veggie cream little veggie cream cheese. For the sandwich not scooped with whitefish salad, how much? 1/4 lb? 1 lb?
[FAILED: Expected item 'Sun-Dried Tomato Cream Cheese Sandwich' not in cart. Cart contains: ['sandwich not scooped with whitefish salad', 'little veggie cream cheese']]
```

**Other instances:**
- Complex order: Black Forest Ham Sandwich
- Complex order: The Old School Tuna Sandwich
- Complex order: Tofu Spread Sandwich
- Complex order: Sable Sandwich
- Complex order: Scallion Tofu Spread Sandwich
- Complex order: Strawberry Cream Cheese Sandwich
- Complex order: Havarti Cheese Sandwich
- Complex order: Nutella Sandwich
- Complex order: Lemon Chicken Salad Sandwich
- Complex order: Lemon Blueberry Cream Cheese Sandwich

## Other (8 failures, 1 distinct patterns)

### Complex order: The Mulberry Omelette (+7 similar)

**Count:** 8
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `c070e237-e249-4883-ba89-3ad4959f065f`

**Failure:** Failed to send message

**Conversation:**
```
User: One the mulberry omelette with spinach and a little roasted peppers please
Bot: Got it, The Mulberry Omelette and a little roasted peppers little roasted peppers. For the The Mulberry Omelette, would you like a bagel or fruit salad with it?
User: fruit salad
Bot: Got it, The Mulberry Omelette and a little roasted peppers little roasted peppers. For the The Mulberry Omelette, what kind of cheese?
User: no
Bot: Got it, The Mulberry Omelette and a little roasted peppers little roasted peppers. For the little roasted peppers, what kind of bread?
User: sesame
Bot: I found a few options matching that. Did you mean Sesame Bagel or Sesame Sourdough Bagel?
User: no
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: All-Natural Smoked Turkey Sandwich
- Complex order: Butter Sandwich
- Complex order: Jalapeno Honey Cream Cheese Sandwich
- Complex order: Hot Chocolate
- Complex order: Hummus Sandwich
- Complex order: Hot Corned Beef Sandwich
- Complex order: The Chelsea Club

## System Error (1 failures, 1 distinct patterns)

### Complex order: Plain Cream Cheese Sandwich

**Count:** 1
**Pattern:** `complex_order | system_error`
**Type:** complex_order
**Session:** `d5d5eb38-feb6-4c6a-9478-6da230e38d7e`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd like a plain cream cheese sandwich toasted with extra seeded salmon and black pepper to go
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Menu Item Not Found (1 failures, 1 distinct patterns)

### Complex order: Green Tea

**Count:** 1
**Pattern:** `complex_order | item_not_recognized`
**Type:** complex_order
**Session:** `b05d0f99-3397-40db-9f1f-70f1ba9eed7c`

**Failure:** Item not found: We don't have large green tea with a little equal to go. For teas, we have Hot Tea or Green Tea. Wou

**Conversation:**
```
User: I'll have a large green tea with a little equal to go
Bot: We don't have large green tea with a little equal to go. For teas, we have Hot Tea or Green Tea. Would you like any of those, or can I help you find something else?
[FAILED: Item not found: We don't have large green tea with a little equal to go. For teas, we have Hot Tea or Green Tea. Wou]
```
