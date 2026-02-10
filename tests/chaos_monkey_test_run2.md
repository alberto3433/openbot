# Chaos Monkey Test Failures

**Generated:** 2026-02-07T14:41:39.264415
**Session Start:** 2026-02-07T14:39:25.616743
**Total Tests:** 10
**Passed:** 6
**Failed:** 4

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 3 |
| Item Recognition | 1 |

## Menu Item Not Found

### Order The Tribeca then modify

**Type:** modifier_flow
**Session:** `072894e0-e7c2-4c3d-9dd5-dd113eb47f2a`

**Failure:** Item not found: Sorry, we don't have Also add lox cream cheese. We have Gluten Free Everything Bagel, Sesame Bagel, 

**Conversation:**
```
User: One The Tribeca please
Bot: Got it, for the The Tribeca. What kind of bagel would you like?
User: Also add lox cream cheese
Bot: Sorry, we don't have Also add lox cream cheese. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hea...
[FAILED: Item not found: Sorry, we don't have Also add lox cream cheese. We have Gluten Free Everything Bagel, Sesame Bagel, ]
User: Without lox cream cheese
User: With veggie please
```

### Order Peanut Butter & Jelly Sandwich then modify

**Type:** modifier_flow
**Session:** `36953a73-06ef-4fc1-8b3a-345892f0b374`

**Failure:** Item not found: I couldn't find swiss cheese in your order. What would you like to do?

**Conversation:**
```
User: One Peanut Butter & Jelly Sandwich please
Bot: Got it, for the Peanut Butter & Jelly Sandwich. What kind of bagel would you like?
User: Put swiss cheese on it
Bot: Let's finish with your Peanut Butter & Jelly Sandwich, Strawberry Jelly, Peanut Butter, Grape Jelly, Grape Jelly, Strawberry Jelly first. What kind of bagel would you like?
User: Take off the swiss cheese
Bot: I couldn't find swiss cheese in your order. What would you like to do?
[FAILED: Item not found: I couldn't find swiss cheese in your order. What would you like to do?]
User: Also add esposito's sausage
```

### Order Jalapeno Cream Cheese Sandwich, Sausage Egg and Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `90539e94-ac09-4976-96bb-4200971f6cdf`

**Failure:** Item not found: Sorry, we don't have Without honey walnut cream cheese. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: I'd like a Jalapeno Cream Cheese Sandwich and also a Sausage Egg and Cheese Sandwich
Bot: Got it, cheese, sausage, and cheese sandwich. We have a few options for sausage:
1. Side of Sausage
2. Side of Chicken Sausage
3. Applewood Chicken Sausage
Which would you like?
User: With honey walnut cream cheese please
Bot: Got it, for the Swiss Cheese. How much?
User: Without honey walnut cream cheese
Bot: Sorry, we don't have Without honey walnut cream cheese. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Without honey walnut cream cheese. We have 1/4 lb or 1 lb.]
User: Add strawberry cc
```

## Item Recognition

### Order Tofu Spread Sandwich, Avocado Spread Sandwich then modify

**Type:** modifier_flow
**Session:** `f2146924-0e6b-47f5-a9c4-1373b5dba89e`

**Failure:** Expected item 'Tofu Spread Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: Tofu Spread Sandwich and Avocado Spread Sandwich please
Bot: Got it, for the Tofu Spread Sandwich. What kind of bagel would you like?
User: Add lox spread
Bot: Sure, I've added Nova Scotia Salmon. What kind of bagel would you like?
User: Remove the lox spread
Bot: OK, I've removed the Tofu Spread Sandwich, Tofu Cream Cheese, Scallion Tofu Spread, Avocado Spread, Nova Scotia Salmon. What would you like to order?
[FAILED: Expected item 'Tofu Spread Sandwich' not in cart. Cart contains: []]
User: Can you add blueberry cream cheese
```
