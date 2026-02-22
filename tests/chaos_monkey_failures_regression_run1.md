# Chaos Monkey Test Failures

**Generated:** 2026-02-22T17:39:42.482631
**Session Start:** 2026-02-22T17:29:18.348254
**Total Tests:** 160
**Passed:** 88
**Failed:** 72
**False Positives (not reproduced):** 5

---

## Summary by Category

| Category | Count |
|----------|-------|
| Other | 33 |
| Order Type | 32 |
| Item Recognition | 7 |

## Other (33 failures, 1 distinct patterns)

### Regression: order type confusion (The Avocado Toast) (+32 similar)

**Count:** 33
**Pattern:** `regression | failed_to_send_message`
**Type:** regression
**Session:** `979ab8c0-78ff-4b3e-9cd7-709848c92a7c`

**Failure:** Failed to send message

**Conversation:**
```
User: I'd like a The Avocado Toast
[FAILED: Failed to send message]
User: this is for pickup
```

**Other instances:**
- Regression: phase restoration (Naked Blue Machine, Olipop Orange Squeeze)
- Regression: qualifier persistence (iced Essentia Water 700ml)
- Regression: phase restoration (Nova Scotia Salmon, Plain Cream Cheese)
- Regression: qualifier persistence (iced Corned Beef)
- Regression: phase restoration (Maple Raisin Walnut Cream Cheese Sandwich, Tofu Plain Sandwich)
- Regression: attribute decline (Blueberry Cream Cheese Sandwich)
- Regression: qualifier persistence (small Potato Salad)
- Regression: instruction leak (Bagel Chips - BBQ)
- Regression: order type confusion (The Alton Brown)
- Regression: availability inquiry (Mini Black and White Cookie)
- Regression: phase restoration (Vitamin Water Energy, Provolone Cheese)
- Regression: phase restoration (Iced Tea, Tuna Salad)
- Regression: order type mid-order (Salami)
- Regression: availability inquiry (Plain Cream Cheese Sandwich)
- Regression: phase restoration (Naked Strawberry Banana, Pop Daddy Pretzels - Yellow Mustard)
- Regression: instruction leak (Pastrami)
- Regression: qualifier persistence (large Fruit Salad)
- Regression: availability inquiry (Diet Sprite)
- Regression: qualifier persistence (large Potato Salad)
- Regression: qualifier persistence (toasted Double Chocolate Muffin)
- Regression: instruction leak (Diet Coke)
- Regression: qualifier persistence (small Blondie Square)
- Regression: attribute decline (The Truffled Egg)
- Regression: order type mid-order (Oatmeal Raisin Cookie)
- Regression: attribute decline (Hot Pastrami Sandwich)
- Regression: qualifier persistence (toasted Fruit Salad)
- Regression: availability inquiry (Joe's Green Tea)
- Regression: attribute decline (The Delancey Omelette with Pastrami)
- Regression: phase restoration (Snapple Iced Tea, All-Natural Smoked Turkey Sandwich)
- Regression: qualifier persistence (large Side of Chicken Sausage)
- Regression: phase restoration (Baked Salmon Salad Sandwich, Chocolate Croissant)
- Regression: availability inquiry (Joyva Halva Chocolate)

## Order Type (32 failures, 2 distinct patterns)

### Regression: order type mid-order (The Pizza BEC with Pepperoni) (+16 similar)

**Count:** 17
**Pattern:** `regression | expected_order_type_pickup_got_none`
**Type:** regression
**Session:** `9d1cfa53-13dc-4335-b2ea-b28976acffe1`

**Failure:** Expected order_type='pickup', got 'None'

**Conversation:**
```
User: actually I'd like a The Pizza BEC with Pepperoni
Bot: Sorry, we don't carry Pepperoni.
User: hello, let's do pickup instead
Bot: Got it, for the The Pizza BEC with Pepperoni. What kind of bread?
[FAILED: Expected order_type='pickup', got 'None']
```

**Other instances:**
- Regression: order type mid-order (Plain Cream Cheese)
- Regression: order type confusion (Belly Lox)
- Regression: order type confusion (Mozzarella Cheese Sandwich)
- Regression: order type mid-order (Potato Salad)
- Regression: order type confusion (Sable Sandwich)
- Regression: order type confusion (Nova Cream Cheese Sandwich)
- Regression: order type confusion (Tofu Vegetable Sandwich)
- Regression: order type confusion (Bologna)
- Regression: order type confusion (Iced Coffee)
- Regression: order type confusion (Wild Pacific Salmon)
- Regression: order type mid-order (The Tribeca)
- Regression: order type confusion (The Grand Central)
- Regression: order type confusion (Baker's Dozen)
- Regression: order type confusion (Tofu Spread Sandwich)
- Regression: order type mid-order (Vegetable Cream Cheese Sandwich)
- Regression: order type mid-order (Scallion Cream Cheese Sandwich)

### Regression: order type confusion (The Tribeca) (+14 similar)

**Count:** 15
**Pattern:** `regression | expected_order_type_delivery_got_none`
**Type:** regression
**Session:** `0fb0aeb5-ff6b-490b-9339-35c85a123693`

**Failure:** Expected order_type='delivery', got 'None'

**Conversation:**
```
User: I'd like a The Tribeca
Bot: Got it, for the The Tribeca. What kind of bread?
User: make it delivery
Bot: Let's finish with your The Tribeca first. What kind of bread?
[FAILED: Expected order_type='delivery', got 'None']
```

**Other instances:**
- Regression: order type mid-order (Tropicana Orange Juice 46 oz)
- Regression: order type mid-order (Jalapeno Cream Cheese Sandwich)
- Regression: order type mid-order (Dozen Bagels & 2 Cream Cheese)
- Regression: order type confusion (Jalapeno Honey Cream Cheese Sandwich)
- Regression: order type mid-order (Brownie)
- Regression: order type confusion (The Truffled Egg)
- Regression: order type confusion (American Cheese)
- Regression: order type mid-order (Double Chocolate Muffin)
- Regression: order type mid-order (Fruit Salad)
- Regression: order type confusion (Iced Chai Tea)
- Regression: order type mid-order (Mini Black and White Cookie)
- Regression: order type confusion (Peanut Butter Sandwich)
- Regression: order type mid-order (The Delancey with Corned Beef)
- Regression: order type mid-order (Tofu Spread Sandwich)

## Item Recognition (7 failures, 1 distinct patterns)

### Regression: order type mid-order (Potato Salad) (+6 similar)

**Count:** 7
**Pattern:** `regression | modifier_not_in_order`
**Type:** regression
**Session:** `e20eea63-ace4-4fbb-ba44-a3b80217ea33`

**Failure:** Expected item 'Potato Salad' not in cart. Cart contains: []

**Conversation:**
```
User: I'd like a Potato Salad please
Bot: Got it, Potato Salad. Anything else?
User: hello, switch to pickup
Bot: Great, I'll set this up for pickup. What can I get for you?
[FAILED: Expected item 'Potato Salad' not in cart. Cart contains: []]
```

**Other instances:**
- Regression: order type mid-order (Side of Bacon)
- Regression: order type confusion (Tropicana Orange Juice 46 oz)
- Regression: order type confusion (Gatorade Fruit Punch)
- Regression: order type confusion (Vitamin Water Energy)
- Regression: instruction leak (6 Bagel Package)
- Regression: order type confusion (Snapple Lemonade)
