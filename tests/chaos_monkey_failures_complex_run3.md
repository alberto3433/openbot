# Chaos Monkey Test Failures

**Generated:** 2026-02-25T23:29:15.529032
**Session Start:** 2026-02-25T22:57:14.525811
**Total Tests:** 180
**Passed:** 151
**Failed:** 29

---

## Summary by Category

| Category | Count |
|----------|-------|
| Other | 22 |
| Item Recognition | 7 |

## Other (22 failures, 1 distinct patterns)

### Complex order: The Chelsea Club (+21 similar)

**Count:** 22
**Pattern:** `complex_order | failed_to_send_message`
**Type:** complex_order
**Session:** `1056b7e7-0713-4554-a7bb-94b89807c185`

**Failure:** Failed to send message

**Conversation:**
```
User: the chelsea club with a little tomato cream cheese
Bot: Got it, The Chelsea Club and a little tomato cream little tomato cream cheese. For the The Chelsea Club, what kind of bread?
User: Poppy Bagel
Bot: Got it, Poppy Bagel. For the The Chelsea Club, toast it? Yes or no?
User: yes
Bot: For the The Chelsea Club, what kind of cheese?
User: no
Bot: Any more changes? No? Scoop it? Any condiments?
User: yes
Bot: You can add: Scooped or Condiments. What would you like?
User: yes
Bot: You can add: Scooped or Condiments. What would you like?
User: yes
Bot: You can add: Scooped or Condiments. What would you like?
User: no
Bot: Got it, The Chelsea Club and a little tomato cream little tomato cream cheese. For the little tomato cream cheese, how much? 1/4 lb? 1 lb?
User: no thanks
[FAILED: Failed to send message]
```

**Other instances:**
- Complex order: Scallion Tofu Spread Sandwich
- Complex order: The Cheesesteak
- Complex order: The Traditional
- Complex order: The Delancey Omelette with Pastrami
- Complex order: Egg and Cheese Sandwich
- Complex order: Gravlax Sandwich
- Complex order: The Delancey Omelette with Pastrami
- Complex order: Strawberry Jelly Sandwich
- Complex order: Hummus Sandwich
- Complex order: Pastrami Salmon Sandwich
- Complex order: Cheddar Cheese Sandwich
- Complex order: The Pizza BEC with Bacon
- Complex order: Grilled Cheese
- Complex order: The Old School Tuna Sandwich
- Complex order: Cinnamon Sugar Butter Sandwich
- Complex order: The Classic BEC
- Complex order: Smoked Trout Sandwich
- Complex order: Sable Sandwich
- Complex order: B&W Truffle Cream Cheese Sandwich
- Complex order: Hot Corned Beef Sandwich
- Complex order: Egg and Cheese Sandwich

## Item Recognition (7 failures, 1 distinct patterns)

### Complex order: Peanut Butter Sandwich (+6 similar)

**Count:** 7
**Pattern:** `complex_order | modifier_not_in_order`
**Type:** complex_order
**Session:** `58741fcc-be72-4a7a-8b9c-1987836a3dd0`

**Failure:** Expected item 'Peanut Butter Sandwich' not in cart. Cart contains: ['nova tofu spread sandwich']

**Conversation:**
```
User: peanut butter like sandwich with salsa
Bot: Got it, for the Nova Tofu Spread Sandwich with Peanut Butter and Salsa. What kind of bread?
[FAILED: Expected item 'Peanut Butter Sandwich' not in cart. Cart contains: ['nova tofu spread sandwich']]
```

**Other instances:**
- Complex order: The Leo
- Complex order: Black Forest Ham Sandwich
- Complex order: Chipotle Cream Cheese Sandwich
- Complex order: Vegetable Tofu Spread Sandwich
- Complex order: Tofu Vegetable Sandwich
- Complex order: Pepper Jack Cheese Sandwich
