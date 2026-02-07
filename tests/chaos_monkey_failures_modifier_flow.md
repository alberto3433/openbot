# Chaos Monkey Test Failures

**Generated:** 2026-02-07T12:37:40.959424
**Session Start:** 2026-02-07T11:49:27.169905
**Total Tests:** 225
**Passed:** 90
**Failed:** 135

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 118 |
| Item Recognition | 17 |

## Menu Item Not Found

### Order Side of Tomato, Espresso then modify

**Type:** modifier_flow
**Session:** `0f52180c-dd16-45bb-adab-f5d7be4ae04f`

**Failure:** Item not found: Sorry, we don't have Hold regular sugar. We have Shot.

**Conversation:**
```
User: I'll have well a Side of Tomato and a Espresso
Bot: Got it, for the Espresso. Any extra shots?
User: add onions
Bot: Sure, I've added Onion. Any extra shots?
User: Hold regular sugar
Bot: Sorry, we don't have Hold regular sugar. We have Shot.
[FAILED: Item not found: Sorry, we don't have Hold regular sugar. We have Shot.]
User: Instead of croissant, make it wild pacific salmon
```

### Order Joyva Marble Halva, Olipop Classic Grape then modify

**Type:** modifier_flow
**Session:** `79923a7b-eb22-42f6-951f-94c8669014f9`

**Failure:** Item not found: I'm sorry, we don't have honevarti cheese on that. Is there something else I can help you with?

**Conversation:**
```
User: CAn I gEt a JoYVa MARBle hAlVA AnD A oliPop claSsic gRApe
Bot: Got it, Joyva Marble Halva and Olipop Classic Grape. Anything else?
User: I'd like honevarti cheese on that
Bot: I'm sorry, we don't have honevarti cheese on that. Is there something else I can help you with?
[FAILED: Item not found: I'm sorry, we don't have honevarti cheese on that. Is there something else I can help you with?]
User: No jalapeno cc pls
User: INSTEAD OF CREAM CHEESE, MAKE IT EVERYTHING WHEAT BAGEL
```

### Order Grape Jelly Sandwich, Provolone Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `3de66cd5-8c16-46a9-bc17-720ae144842f`

**Failure:** Item not found: I couldn't find pepperoni in your order. What would you like to do?

**Conversation:**
```
User: Grape Jelly Sandwich and Provolone Cheese Sandwich please
Bot: Got it, Grape Jelly Sandwich and Provolone Cheese. For the grape jelly sandwich, what kind of bagel would you like?
User: With almond please
Bot: Let's finish with your Grape Jelly Sandwich, Grape Jelly, Grape Jelly first. What kind of bagel would you like?
User: Take off the pepperoni
Bot: I couldn't find pepperoni in your order. What would you like to do?
[FAILED: Item not found: I couldn't find pepperoni in your order. What would you like to do?]
User: Actually avocado instead of cherry tomatoes
```

### Order Dr. Brown's Cream Soda, Chocolate Chip Muffin then modify

**Type:** modifier_flow
**Session:** `ef769c4c-b72b-4532-a645-fb05dbc3cf39`

**Failure:** Item not found: Sorry, we don't have Replace swiss with hash browns. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: I'll have a Dr. Brown's Cream Soda and a Chocolate Chip Muffin
Bot: Got it, Dr. Brown's Cream Soda and Chocolate Chip Muffin. Anything else?
User: Add muenster cheese to that
Bot: Sure, I've added that to your Chocolate Chip Muffin, Muenster Cheese. Anything else?
User: Hold the muenster cheese
Bot: Got it, for the Muenster Cheese with no muenster cheese. How much?
User: Replace swiss with hash browns
Bot: Sorry, we don't have Replace swiss with hash browns. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Replace swiss with hash browns. We have 1/4 lb or 1 lb.]
```

### Order Lentil Soup then modify

**Type:** modifier_flow
**Session:** `7e0f80f7-1a71-42de-afd3-ef8c95a8835b`

**Failure:** Item not found: I'm sorry, we don't have raisin walnut on that. Is there something else I can help you with?

**Conversation:**
```
User: Can I get a Lentil Soup
Bot: Got it, Lentil Soup. Anything else?
User: I'd like raisin walnut on that
Bot: I'm sorry, we don't have raisin walnut on that. Is there something else I can help you with?
[FAILED: Item not found: I'm sorry, we don't have raisin walnut on that. Is there something else I can help you with?]
User: Hold the raisin walnut
User: Switch raisin walnut for eggs
```

### Order Maple Raisin Walnut Cream Cheese Sandwich, Cheddar Cheese then modify

**Type:** modifier_flow
**Session:** `a51fb7b6-dbf4-486f-abef-30a072f66043`

**Failure:** Item not found: I couldn't find sugar raw in your order. What would you like to do?

**Conversation:**
```
User: Maple Raisin Walnut Cream Cheese Sandwich and Cheddar Cheese please
Bot: Got it, for the Maple Raisin Walnut Cream Cheese Sandwich. What kind of bagel would you like?
User: Put whole milk on it
Bot: We have Whole Wheat Bagel, Whole Wheat Everything Bagel, Whole Wheat Flatz, Whole Wheat Everything Flatz, Whole Wheat Bread, or Whole Wheat Wrap. Which would you like?
User: Remove the sugar raw
Bot: I couldn't find sugar raw in your order. What would you like to do?
[FAILED: Item not found: I couldn't find sugar raw in your order. What would you like to do?]
User: Change the sugar raw to red peppers
```

### Order Roast Beef then modify

**Type:** modifier_flow
**Session:** `7acabd8c-77fa-4ebd-a236-b2b76e5b55b2`

**Failure:** Item not found: I couldn't find peppermint syrup in your order. What would you like to do?

**Conversation:**
```
User: I'd like Roast Beef
Bot: Got it, for the Roast Beef. How much?
User: Add gouda cheese to that
Bot: Sure, I've added Gouda Cheese. How much?
User: um Take off the peppermint syrup
Bot: I couldn't find peppermint syrup in your order. What would you like to do?
[FAILED: Item not found: I couldn't find peppermint syrup in your order. What would you like to do?]
User: Replace um tofu cc with gouda cheese
```

### Order Scallion Cream Cheese Sandwich, Sun-Dried Tomato Cream Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `439e07db-0de1-4d1a-af74-b8edfe5564fb`

**Failure:** Item not found: Sorry, we don't have Instead of jalapeno, make it cucumbers. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: I'd like a Scallion Cream Cheese Sandwich and also a Sun-Dried Tomato Cream Cheese Sandwich
Bot: Got it, two swiss cheeses. For the first swiss cheese, how much?
User: With corned beef please
Bot: Let's finish with your Swiss Cheese, 1/4 lb first. How much?
User: Actually no half and half
Bot: Sure, I've changed the milk to Half N Half. How much?
User: Instead of jalapeno, make it cucumbers
Bot: Sorry, we don't have Instead of jalapeno, make it cucumbers. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Instead of jalapeno, make it cucumbers. We have 1/4 lb or 1 lb.]
```

### Order Whitefish Salad Sandwich, Nova Scotia Salmon on Bagel then modify

**Type:** modifier_flow
**Session:** `70304252-21cc-4c6e-9f65-9c684750a837`

**Failure:** Item not found: Sorry, we don't have Hold the grilled chicken. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: I'll have a Whitefish Salad Sandwich and a Nova Scotia Salmon on Bagel
Bot: Got it, Tuna Salad and Nova Scotia Salmon on Bagel. For the tuna salad, how much?
User: Add tofu cc to that
Bot: Sure, I've added Tofu Cream Cheese. How much?
User: Hold the grilled chicken
Bot: Sorry, we don't have Hold the grilled chicken. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Hold the grilled chicken. We have 1/4 lb or 1 lb.]
User: Actually sweet n low instead of grilled chicken
```

### Order Strawberry Cream Cheese then modify

**Type:** modifier_flow
**Session:** `c436b9cf-2956-4186-b0a7-3a627ddcd814`

**Failure:** Item not found: Sorry, we don't have Also add sauteed peppers. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: Can I get a Strawberry Cream Cheese
Bot: Got it, for the Strawberry Cream Cheese. How much?
User: Also add sauteed peppers
Bot: Sorry, we don't have Also add sauteed peppers. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Also add sauteed peppers. We have 1/4 lb or 1 lb.]
User: Remove the breakfast potato latke
User: Instead of breakfast potato latke, make it lactose free milk
```

*... and 108 more failures in this category*

## Item Recognition

### Order Side of Turkey Bacon, The Reuben then modify

**Type:** modifier_flow
**Session:** `d8c61115-0943-4651-a834-78f3bcafd781`

**Failure:** Expected item 'Side of Turkey Bacon' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Side of Turkey Bacon and a The Reuben
Bot: Got it, for the The Reuben. What kind of bagel would you like?
User: With jalapeño spread please
Bot: Let's finish with your The Reuben, Corned Beef, Pastrami, Swiss Cheese, Turkey, Sauerkraut first. What kind of bagel would you like?
User: Take off the kalamata olive feta cream cheese
Bot: OK, I've removed the The Reuben, Corned Beef, Pastrami, Swiss Cheese, Turkey, Sauerkraut. Anything else?
User: Replace wheat flatz with jalapeño spread
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Side of Turkey Bacon' not in cart. Cart contains: []]
```

### Order Bagel Package - Dozen Bagels & 2 Cream Cheese then modify

**Type:** modifier_flow
**Session:** `532aa1c0-7fcb-4c07-8f2c-983fdffc51aa`

**Failure:** Expected item 'Bagel Package - Dozen Bagels & 2 Cream Cheese' not in cart. Cart contains: []

**Conversation:**
```
User: One Bagel Package - Dozen Bagels & 2 Cream Cheese please
Bot: What can I get for you?
[FAILED: Expected item 'Bagel Package - Dozen Bagels & 2 Cream Cheese' not in cart. Cart contains: []]
User: I'd like vanilla on that
User: No vegetable cream cheese please
User: Replace vanilla with gluten-free everything
```

### Order Two Hard Boiled Eggs then modify

**Type:** modifier_flow
**Session:** `726bc178-b9be-46c1-a3be-5d48eb9bdc2f`

**Failure:** Expected item 'Two Hard Boiled Eggs' not in cart. Cart contains: []

**Conversation:**
```
User: One Two Hard Boiled Eggs please
Bot: Got it, Two Hard Boiled Eggs. Anything else?
User: Add pepper to that
Bot: Sure, I've added that to your Two Hard Boiled Eggs, Black Pepper. Anything else?
User: Skip the pepper
Bot: What can I get for you?
User: Switch pepper for black pepper
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Two Hard Boiled Eggs' not in cart. Cart contains: []]
```

### Order Poppy Hamantaschen, Fruit Salad then modify

**Type:** modifier_flow
**Session:** `87845448-df9e-4290-8c1a-686f71584961`

**Failure:** Expected item 'Poppy Hamantaschen' not in cart. Cart contains: []

**Conversation:**
```
User: Poppy Hamantaschen and Fruit Salad please
Bot: Got it, Poppy Hamantaschen. Anything else?
User: Can you add pico de gallo
Bot: Sure, I've added that to your Poppy Hamantaschen, Pico de Gallo. Anything else?
User: Actually no pico de gallo
Bot: This item doesn't have a Unknown to change.
User: Switch whole wheat flatz for dill
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Poppy Hamantaschen' not in cart. Cart contains: []]
```

### Order Diet Sprite then modify

**Type:** modifier_flow
**Session:** `01f4f5f2-6be8-498f-833c-60d3f43c4000`

**Failure:** Expected item 'Diet Sprite' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Diet Sprite
Bot: Got it, Diet Sprite. Anything else?
User: Add caramel
Bot: Sure, I've added that to your Diet Sprite, Caramel Syrup. Anything else?
User: No persian cucumber please
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Diet Sprite' not in cart. Cart contains: []]
User: Switch salt bagel for oat milk
```

### Order Rugelach then modify

**Type:** modifier_flow
**Session:** `b985a904-b828-4bc7-bf29-81d0401c03f2`

**Failure:** Expected item 'Rugelach' not in cart. Cart contains: []

**Conversation:**
```
User: One Rugelach please
Bot: Got it, Rugelach. Anything else?
User: Add broccoli to that
Bot: Sure, I've added that to your Rugelach (3 pack), Broccoli. Anything else?
User: Hold the lactose free
Bot: What can I get for you?
User: Replace egg salad with lactose free
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Rugelach' not in cart. Cart contains: []]
```

### Order Rice Krispy Treat, Scallion Tofu Spread Sandwich then modify

**Type:** modifier_flow
**Session:** `58f34455-c0c7-443c-9e8a-6c2e99fb7119`

**Failure:** Expected item 'Rice Krispy Treat' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Rice Krispy Treat and a Scallion Tofu Spread Sandwich
Bot: Got it, for the Scallion Tofu Spread Sandwich. What kind of bagel would you like?
User: With walnut raisin please
Bot: We have Cinnamon Raisin Bagel or Gluten Free Cinnamon Raisin Bagel. Which would you like?
User: Take off the scallion cc
Bot: OK, I've removed the Scallion Tofu Spread Sandwich, Tofu Scallion Cream Cheese, Scallion Tofu Spread. Anything else?
User: Switch sauerkraut for walnut raisin
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Rice Krispy Treat' not in cart. Cart contains: []]
```

### Order Cole Slaw then modify

**Type:** modifier_flow
**Session:** `eb495a51-f074-415b-b384-23c959f4ebda`

**Failure:** Expected item 'Cole Slaw' not in cart. Cart contains: []

**Conversation:**
```
User: I'd like a Cole Slaw
Bot: Got it, Cole Slaw. Anything else?
User: Put tofu vegetable cream cheese on it
Bot: Sure, I've added that to your Cole Slaw, Vegetable Cream Cheese. Anything else?
User: Skip the strawberry jam
Bot: What can I get for you?
User: Replace everything seeded salmon with soy
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Cole Slaw' not in cart. Cart contains: []]
```

### Order Danish then modify

**Type:** modifier_flow
**Session:** `cfd81f1a-59a5-4479-8099-6df23a34066d`

**Failure:** Expected item 'Danish' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Danish
Bot: Got it, Danish. Anything else?
User: I'd like eggs on that
Bot: Sure, I've added that to your Danish, Egg. Anything else?
User: Actually no persian cucumber
Bot: This item doesn't have a Unknown to change.
User: Swap honey walnut cc for eggs
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Danish' not in cart. Cart contains: []]
```

### Order Dr. Brown's Cream Soda then modify

**Type:** modifier_flow
**Session:** `a79cb2d0-7293-4c6d-babd-4998ddd08d49`

**Failure:** Expected item 'Dr. Brown's Cream Soda' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Dr. Brown's Cream Soda
Bot: Got it, Dr. Brown's Cream Soda. Anything else?
User: Put cinnamon sugar butter on it
Bot: Sure, I've added that to your Dr. Brown's Cream Soda, Domino Sugar. Anything else?
User: Actually no cinnamon sugar butter
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Dr. Brown's Cream Soda' not in cart. Cart contains: []]
User: Instead of persian cucumber, make it avocado spread
```

*... and 7 more failures in this category*
