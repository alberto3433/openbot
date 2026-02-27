# Chaos Monkey Test Failures

**Generated:** 2026-02-27T00:13:38.483778
**Session Start:** 2026-02-26T23:43:26.253733
**Total Tests:** 220
**Passed:** 194
**Failed:** 26

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 12 |
| Other | 10 |
| Menu Item Not Found | 2 |
| System Error | 2 |

## Item Recognition (12 failures, 1 distinct patterns)

### Complex order: Vegetable Tofu Spread Sandwich (+11 similar)

**Count:** 12
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `488b8fd1-f1f5-4fed-964f-e3bd3e8fa773`

**Failure:** Expected item 'Vegetable Tofu Spread Sandwich' not in cart. Cart contains: ['spread sandwich toasted with a little pepper jack cheese', 'jalapeño spread to go']

**Conversation:**
```
User: I'd like a vegetable tofu spread sandwich toasted with a little pepper jack cheese and jalapeño spread to go
Bot: Got it, a little pepper jack spread sandwich toasted with a little pepper jack cheese and jalapeño spread to go. For the spread sandwich toasted with a little pepper jack cheese, how much? 1/4 lb? 1 l...
[FAILED: Expected item 'Vegetable Tofu Spread Sandwich' not in cart. Cart contains: ['spread sandwich toasted with a little pepper jack cheese', 'jalapeño spread to go']]
```

**Other instances:**
- Complex order: Sun-Dried Tomato Cream Cheese Sandwich
- Complex order: Lemon Chicken Salad Sandwich
- Complex order: Whitefish Salad Sandwich
- Complex order: Green Tea
- Complex order: The Traditional
- Complex order: Blueberry Cream Cheese Sandwich
- Complex order: The Pizza BEC with Pepperoni
- Complex order: Lemon Blueberry Cream Cheese Sandwich
- Complex order: The Max Borough
- Complex order: The Mulberry
- Complex order: Baked Salmon Salad Sandwich

## Other (10 failures, 1 distinct patterns)

### Complex order: Swiss Cheese Sandwich (+9 similar)

**Count:** 10
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `ccff5be4-e3f3-402c-9bf8-322be32b89f2`

**Failure:** Failed to send message

**Conversation:**
```
User: Give me a swiss cheese sandwich toasted with extra muenster and provolone to go if you don't mind
Bot: Got it, extra muenster Swiss Cheese and to go if you don't mind. For the Swiss Cheese, how much? 1/4 lb? 1 lb?
User: no
Bot: Got it, extra muenster Swiss Cheese and to go if you don't mind. For the to go if you don't mind, what kind of bread?
User: Wrap
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: The Lexington
- Complex order: Tofu Scallion Sandwich
- Complex order: The BLT
- Complex order: Pepperoni Pizza Bagel
- Complex order: Egg Salad Sandwich
- Complex order: Grape Jelly Sandwich
- Complex order: Plain Cream Cheese Sandwich
- Complex order: The Chelsea Club
- Complex order: Pastrami Salmon Sandwich

## Menu Item Not Found (2 failures, 1 distinct patterns)

### Complex order: Green Tea (+1 similar)

**Count:** 2
**Pattern:** `complex_order | item_not_recognized`
**Type:** complex_order
**Session:** `a2ecf157-0857-458f-809a-4b3756b165ca`

**Failure:** Item not found: We don't have green tea with skim milk. Would you like to hear what drinks we have?

**Conversation:**
```
User: I'd like a green tea with skim milk
Bot: We don't have green tea with skim milk. Would you like to hear what drinks we have?
[FAILED: Item not found: We don't have green tea with skim milk. Would you like to hear what drinks we have?]
```

**Other instances:**
- Complex order: Green Tea

## System Error (2 failures, 1 distinct patterns)

### Complex order: Maple Raisin Walnut Cream Cheese Sandwich (+1 similar)

**Count:** 2
**Pattern:** `complex_order | system_error`
**Type:** complex_order
**Session:** `af2dd6d6-3ded-461f-ba87-cdfdc745be80`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd like a maple raisin walnut cream cheese sandwich with extra everything salmon and red onion to go
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Complex order: The Max Borough
