# Chaos Monkey Test Failures

**Generated:** 2026-02-23T14:33:11.804500
**Session Start:** 2026-02-23T14:10:55.809599
**Total Tests:** 160
**Passed:** 100
**Failed:** 60

---

## Summary by Category

| Category | Count |
|----------|-------|
| Item Recognition | 44 |
| Other | 10 |
| Menu Item Not Found | 3 |
| System Error | 3 |

## Item Recognition (44 failures, 1 distinct patterns)

### Complex order: Peanut Butter & Jelly Sandwich (+43 similar)

**Count:** 44
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `86668a18-12ad-44c3-a651-dd8631bf5f5f`

**Failure:** Expected item 'Peanut Butter & Jelly Sandwich' not in cart. Cart contains: ['little hot sauce', 'bagel']

**Conversation:**
```
User: excuse me whole wheat bagel toasted scooped peanut butter & jelly sandwich with extra olive pimento cream cheese and a little hot sauce
Bot: Got it, for the Whole Wheat Bagel. Which jelly? Strawberry Jelly or Grape Jelly?
[FAILED: Expected item 'Peanut Butter & Jelly Sandwich' not in cart. Cart contains: ['little hot sauce', 'bagel']]
```

**Other instances:**
- Complex order: Havarti Cheese Sandwich
- Complex order: Sausage Egg and Cheese Sandwich
- Complex order: The BLT
- Complex order: The Flatiron Traditional
- Complex order: The Delancey with Pastrami
- Complex order: Grape Jelly Sandwich
- Complex order: Hot Corned Beef Sandwich
- Complex order: Sweet & Spicy Traditional
- Complex order: The Alton Brown
- Complex order: Truffle Cream Cheese Sandwich
- Complex order: Whitefish Salad Sandwich
- Complex order: Nova Tofu Spread Sandwich
- Complex order: Nova Tofu Spread Sandwich
- Complex order: The Mulberry
- Complex order: Chipotle Cream Cheese Sandwich
- Complex order: Chipotle Cream Cheese Sandwich
- Complex order: Tuna Salad Sandwich
- Complex order: The Max Borough
- Complex order: Tofu Spread Sandwich
- Complex order: Lemon Blueberry Cream Cheese Sandwich
- Complex order: The Health Nut Omelette
- Complex order: The Tribeca
- Complex order: The Reuben
- Complex order: The Columbus BEC
- Complex order: Cheddar Cheese Sandwich
- Complex order: The Tribeca
- Complex order: Hot Corned Beef Sandwich
- Complex order: Grilled Cheese
- Complex order: Butter Sandwich
- Complex order: Cheddar Cheese Sandwich
- Complex order: The Tribeca
- Complex order: The Leo Omelette
- Complex order: The Alton Brown
- Complex order: Plain Cream Cheese Sandwich
- Complex order: The Cheesesteak
- Complex order: The Classic Omelette
- Complex order: Peanut Butter & Jelly Sandwich
- Complex order: The Delancey with Corned Beef
- Complex order: The Delancey Omelette with Corned Beef
- Complex order: Lemon Blueberry Cream Cheese Sandwich
- Complex order: The Lexington
- Complex order: Hummus Sandwich
- Complex order: The RB Prime

## Other (10 failures, 1 distinct patterns)

### Complex order: Hot Corned Beef Sandwich (+9 similar)

**Count:** 10
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `6300adca-4565-4645-96e0-7c457798110d`

**Failure:** Failed to send message

**Conversation:**
```
User: One havarti cheese hmm toasted flagel hot corned beef sandwich with a little blueberry cc, extra tomatoes, and light asiago bagel on the side
Bot: Got it, extra tomatoes, a little blueberry cc one havarti cheese toasted flagel hot corned beef sandwich with a little blueberry cc extra tomatoes and light asiago bagel, bagel on the side Asiago Bage...
User: no
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: The Tuna Melt
- Complex order: Chicken Salad Sandwich
- Complex order: The Delancey with Corned Beef
- Complex order: The Traditional
- Complex order: Nutella Sandwich
- Complex order: Nova Cream Cheese Sandwich
- Complex order: Scallion Tofu Spread Sandwich
- Complex order: The Avocado Toast
- Complex order: Plain Cream Cheese Sandwich

## Menu Item Not Found (3 failures, 1 distinct patterns)

### Complex order: Green Tea (+2 similar)

**Count:** 3
**Pattern:** `complex_order | item_not_recognized`
**Type:** complex_order
**Session:** `460bfc17-7fc1-4847-a071-8f15d9baef29`

**Failure:** Item not found: We don't have english breakfast vanilla syrup green tea with light peppermin and light oat milk to g

**Conversation:**
```
User: Can I get a english breakfast vanilla syrup green tea with light peppermin and light oat milk to go
Bot: We don't have english breakfast vanilla syrup green tea with light peppermin and light oat milk to go. Would you like to hear what drinks we have?
[FAILED: Item not found: We don't have english breakfast vanilla syrup green tea with light peppermin and light oat milk to g]
```

**Other instances:**
- Complex order: Green Tea
- Complex order: Green Tea

## System Error (3 failures, 1 distinct patterns)

### Complex order: Baked Salmon Salad Sandwich (+2 similar)

**Count:** 3
**Pattern:** `complex_order | system_error`
**Type:** complex_order
**Session:** `9c39ee44-67d3-4db6-a7f8-a70992c39050`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: Give me a toasted baked salmon salad sandwich with extra everything salmon and tofu scallion on the side
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Complex order: Vegetable Tofu Spread Sandwich
- Complex order: The Tuna Melt
