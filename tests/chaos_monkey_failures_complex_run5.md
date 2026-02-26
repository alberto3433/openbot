# Chaos Monkey Test Failures

**Generated:** 2026-02-26T13:25:40.353128
**Session Start:** 2026-02-26T12:54:53.089685
**Total Tests:** 280
**Passed:** 260
**Failed:** 20

---

## Summary by Category

| Category | Count |
|----------|-------|
| Other | 10 |
| Item Recognition | 5 |
| Menu Item Not Found | 4 |
| System Error | 1 |

## Other (10 failures, 1 distinct patterns)

### Complex order: Tofu Scallion Sandwich (+9 similar)

**Count:** 10
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `da4a53cf-8af0-4179-bda7-e3eb1b0efdb1`

**Failure:** Failed to send message

**Conversation:**
```
User: One tofu scallion sandwich not scooped with extra esposito's sausage and tomato cream cheese to go
Bot: Got it, extra esposito Tofu Scallion Sandwich and tomato cream cheese to go. For the Tofu Scallion Sandwich, what kind of bread?
User: Cinnamon Raisin Bagel
Bot: Got it, Cinnamon Raisin Bagel. For the Tofu Scallion Sandwich, toast it? Yes or no?
User: yes
Bot: Any more changes? No? Any condiments?
User: no
Bot: Got it, extra esposito Tofu Scallion Sandwich and tomato cream cheese to go. For the tomato cream cheese to go, how much? 1/4 lb? 1 lb?
User: no
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: The Chelsea Club
- Complex order: The Old School Tuna Sandwich
- Complex order: Roasted Scallion Shallot Caper & Garlic Cream Cheese Sandwich
- Complex order: Nutella Sandwich
- Complex order: Cinnamon Sugar Butter Sandwich
- Complex order: The Flatiron Traditional
- Complex order: Jalapeno Honey Cream Cheese Sandwich
- Complex order: Chipotle Cream Cheese Sandwich
- Complex order: Avocado Spread Sandwich

## Item Recognition (5 failures, 1 distinct patterns)

### Complex order: Tofu Spread Sandwich (+4 similar)

**Count:** 5
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `342622be-f797-4b82-8eee-1ead838595a3`

**Failure:** Expected item 'Tofu Spread Sandwich' not in cart. Cart contains: ['roast beef', 'spread sandwich not toasted with extra strawberry jelly packet']

**Conversation:**
```
User: tofu spread sandwich not toasted with extra strawberry jelly packet and roast beef to go
Bot: Got it, extra strawberry jelly spread sandwich not toasted with extra strawberry jelly packet and Roast Beef. For the spread sandwich not toasted with extra strawberry jelly packet, how much? 1/4 lb? ...
[FAILED: Expected item 'Tofu Spread Sandwich' not in cart. Cart contains: ['roast beef', 'spread sandwich not toasted with extra strawberry jelly packet']]
```

**Other instances:**
- Complex order: Lemon Chicken Salad Sandwich
- Complex order: Nova Cream Cheese Sandwich
- Complex order: The RB Prime
- Complex order: The BLT

## Menu Item Not Found (4 failures, 1 distinct patterns)

### Complex order: Chai Tea (+3 similar)

**Count:** 4
**Pattern:** `complex_order | item_not_recognized`
**Type:** complex_order
**Session:** `51fcb6e2-9921-4fc8-9d2a-3e998831c3a0`

**Failure:** Item not found: We don't have just a small chai tea with domino sugar and vanilla chai. For chai drinks, we have Cha

**Conversation:**
```
User: Give me just a small chai tea with domino sugar and vanilla chai please
Bot: We don't have just a small chai tea with domino sugar and vanilla chai. For chai drinks, we have Chai Tea or Iced Chai Tea. Would you like any of those, or can I help you find something else?
[FAILED: Item not found: We don't have just a small chai tea with domino sugar and vanilla chai. For chai drinks, we have Cha]
```

**Other instances:**
- Complex order: Green Tea
- Complex order: Green Tea
- Complex order: Green Tea

## System Error (1 failures, 1 distinct patterns)

### Complex order: Nova Cream Cheese Sandwich

**Count:** 1
**Pattern:** `complex_order | system_error`
**Type:** complex_order
**Session:** `5b459e20-bd5b-48f7-ae13-43b674acb37d`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: One nova cream cheese sandwich with scottish salmon and extra sausage to go
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```
