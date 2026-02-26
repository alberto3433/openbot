# Chaos Monkey Test Failures

**Generated:** 2026-02-26T12:23:36.977765
**Session Start:** 2026-02-26T11:53:06.868456
**Total Tests:** 240
**Passed:** 214
**Failed:** 26

---

## Summary by Category

| Category | Count |
|----------|-------|
| Other | 16 |
| Item Recognition | 8 |
| System Error | 1 |
| Menu Item Not Found | 1 |

## Other (16 failures, 1 distinct patterns)

### Complex order: Tofu Scallion Sandwich (+15 similar)

**Count:** 16
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `6aa75ca6-6550-483c-bf8e-bca525ea4377`

**Failure:** Failed to send message

**Conversation:**
```
User: Give me a tofu scallion sandwich toasted with a little avocado
Bot: Got it, Tofu Scallion Sandwich and a little avocado little avocado. For the Tofu Scallion Sandwich, what kind of bread?
User: French Toast Bagel
Bot: Got it, French Toast Bagel. For the Tofu Scallion Sandwich, scoop it? Yes or no?
User: yes
Bot: Any more changes? No? Any condiments?
User: no thanks
Bot: For the little avocado, what kind of bread?
User: Everything Bagel
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: The Leo Omelette
- Complex order: The Delancey with Pastrami
- Complex order: The Lexington
- Complex order: Egg and Cheese Sandwich
- Complex order: Jalapeno Cream Cheese Sandwich
- Complex order: The Lexington
- Complex order: Sable Sandwich
- Complex order: Open Face Traditional
- Complex order: Ham Egg and Cheese Sandwich
- Complex order: The Columbus BEC Omelette
- Complex order: The Flatiron Traditional
- Complex order: Kalamata Olive Feta Cream Cheese Sandwich
- Complex order: The Latke BEC
- Complex order: The Max Borough
- Complex order: Plain Cream Cheese Sandwich

## Item Recognition (8 failures, 1 distinct patterns)

### Complex order: Nova Cream Cheese Sandwich (+7 similar)

**Count:** 8
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `fcf217fa-99bb-4680-9c82-7af5e5c371c9`

**Failure:** Expected item 'Nova Cream Cheese Sandwich' not in cart. Cart contains: ['little baked salmon', 'sandwich not scooped with extra tomato cream cheese']

**Conversation:**
```
User: Can I get a nova cream cheese sandwich not scooped with extra tomato cream cheese and a little baked salmon please
Bot: Got it, extra tomato cream sandwich not scooped with extra tomato cream cheese and a little baked salmon little baked salmon. For the sandwich not scooped with extra tomato cream cheese, how much? 1/4...
[FAILED: Expected item 'Nova Cream Cheese Sandwich' not in cart. Cart contains: ['little baked salmon', 'sandwich not scooped with extra tomato cream cheese']]
```

**Other instances:**
- Complex order: The Alton Brown
- Complex order: The Reuben
- Complex order: The Traditional
- Complex order: Pepper Jack Cheese Sandwich
- Complex order: Blueberry Cream Cheese Sandwich
- Complex order: Green Tea
- Complex order: The Classic

## System Error (1 failures, 1 distinct patterns)

### Complex order: Plain Cream Cheese Sandwich

**Count:** 1
**Pattern:** `complex_order | system_error`
**Type:** complex_order
**Session:** `1f1d3593-ed81-4b87-81f8-bcb4efe5db56`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: plain cream cheese sandwich with extra baked salmon and scallion cc to go
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Menu Item Not Found (1 failures, 1 distinct patterns)

### Complex order: Vegetable Tofu Spread Sandwich

**Count:** 1
**Pattern:** `complex_order | item_not_recognized`
**Type:** complex_order
**Session:** `34b4d293-acfa-4e8a-83d6-81486efe2f0b`

**Failure:** Item not found: We don't have vegetable tofu spread well sandwich with salt. For healthy sandwiches, we have The Hea

**Conversation:**
```
User: I'd like a vegetable tofu spread well sandwich with salt
Bot: We don't have vegetable tofu spread well sandwich with salt. For healthy sandwiches, we have The Health Nut, The Lexington, or The Columbus BEC. Would you like any of those, or can I help you find som...
[FAILED: Item not found: We don't have vegetable tofu spread well sandwich with salt. For healthy sandwiches, we have The Hea]
```
