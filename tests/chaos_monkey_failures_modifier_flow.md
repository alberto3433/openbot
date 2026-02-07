d# Chaos Monkey Test Failures

**Generated:** 2026-02-06T22:33:03.526705
**Session Start:** 2026-02-06T21:46:25.876757
**Total Tests:** 225
**Passed:** 72
**Failed:** 153

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 140 |
| Item Recognition | 13 |

## Menu Item Not Found

### Order Cinnamon Sugar Butter Sandwich then modify

**Type:** modifier_flow
**Session:** `02b67d64-df86-4ca6-93ab-d70862cab19f`

**Failure:** Item not found: I couldn't find jalapeño cream in your order. What would you like to do?

**Conversation:**
```
User: Can I get a Cinnamon Sugar Butter Sandwich
Bot: Got it, for the Cinnamon Sugar Butter Sandwich. What kind of bagel would you like?
User: Can you add jalapeño cheddar bagel
Bot: Got it, Jalapeno Cheddar Bagel. Would you like it toasted?
User: Remove the jalapeño cream
Bot: I couldn't find jalapeño cream in your order. What would you like to do?
[FAILED: Item not found: I couldn't find jalapeño cream in your order. What would you like to do?]
User: Instead of jalapeño cheddar bagel, make it gluten free cinnamon raisin bagel
```

### Order The RB Prime then modify

**Type:** modifier_flow
**Session:** `098e2264-7aa4-43ba-a032-8c0d42ec9b02`

**Failure:** Item not found: Sorry, we don't have scrambled egg on that. We have Gluten Free Everything Bagel, Sesame Bagel, Fren

**Conversation:**
```
User: I'd like a The RB Prime
Bot: Got it, for the The RB Prime. What kind of bagel would you like?
User: I'd like scrambled egg on that
Bot: Sorry, we don't have scrambled egg on that. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear mo...
[FAILED: Item not found: Sorry, we don't have scrambled egg on that. We have Gluten Free Everything Bagel, Sesame Bagel, Fren]
User: Skip the sausage patty
User: Change the green pepper to sausage patty
```

### Order Russian Coffee Cake, Double Chocolate Muffin then modify

**Type:** modifier_flow
**Session:** `16b1868e-5422-4978-a77d-9dd5ecf0ceb7`

**Failure:** Item not found: I couldn't find muenster in your order. What would you like to do?

**Conversation:**
```
User: Can I get a Russian Coffee Cake and a Double Chocolate Muffin
Bot: Got it, Russian Coffee Cake and Double Chocolate Muffin. Anything else?
User: I'd like pickles on that
Bot: Sure, I've added that to your Double Chocolate Muffin, Pickles. Anything else?
User: Take off the muenster
Bot: I couldn't find muenster in your order. What would you like to do?
[FAILED: Item not found: I couldn't find muenster in your order. What would you like to do?]
User: Change the pickles to feta cheese
```

### Order Bagel Chips - BBQ then modify

**Type:** modifier_flow
**Session:** `fdcda59d-3a61-464b-be75-4774fcb02b2e`

**Failure:** Item not found: I couldn't find caramel in your order. What would you like to do?

**Conversation:**
```
User: I'd like a Bagel Chips - BBQ
Bot: Got it, Bagel Chips - BBQ. Anything else?
User: Put green peppers on it
Bot: Sure, I've added that to your Bagel Chips - BBQ, Green Pepper. Anything else?
User: Take off the caramel
Bot: I couldn't find caramel in your order. What would you like to do?
[FAILED: Item not found: I couldn't find caramel in your order. What would you like to do?]
User: Instead of caramel, make it sun-dried tomato cream cheese
```

### Order Kettle Cooked Jalapeno Potato Chips, Tuna Salad then modify

**Type:** modifier_flow
**Session:** `8a9a59ee-ccd1-4480-810a-3f4d1c827e31`

**Failure:** Item not found: Sorry, we don't have Without lake sturgeon. We have Gluten Free Everything Bagel, Sesame Bagel, Fren

**Conversation:**
```
User: I'll have a Kettle Cooked Jalapeno Potato Chips and a Tuna Salad
Bot: Got it, for the Tuna Salad Sandwich. What kind of bagel would you like?
User: Also add lake sturgeon
Bot: Got it, I've added Lake Sturgeon. Now, for your Tuna Salad Sandwich, what kind of bagel would you like?
User: Without lake sturgeon
Bot: Sorry, we don't have Without lake sturgeon. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear mo...
[FAILED: Item not found: Sorry, we don't have Without lake sturgeon. We have Gluten Free Everything Bagel, Sesame Bagel, Fren]
User: Change the lake sturgeon to lemon chicken salad
```

### Order Muenster Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `9ee8da18-db30-4d8d-92f4-1c3ba7d3bb94`

**Failure:** Item not found: Sorry, we don't have Also add camomile. We have Gluten Free Everything Bagel, Sesame Bagel, French T

**Conversation:**
```
User: I'll have a Muenster Cheese Sandwich
Bot: Got it, for the Muenster Cheese Sandwich. What kind of bagel would you like?
User: Also add camomile
Bot: Sorry, we don't have Also add camomile. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more o...
[FAILED: Item not found: Sorry, we don't have Also add camomile. We have Gluten Free Everything Bagel, Sesame Bagel, French T]
User: Without cherry tomatoes
User: Instead of camomile, make it domino sugar
```

### Order Nova Scotia Salmon, Nova Scotia Cream Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `72b81b96-fdbf-48ad-865a-b80e95a0c651`

**Failure:** Item not found: I couldn't find gluten free bagel in your order. What would you like to do?

**Conversation:**
```
User: I'd like a Nova Scotia Salmon and also a Nova Scotia Cream Cheese Sandwich
Bot: Got it, Nova Scotia Salmon and Swiss Cheese. For the nova scotia salmon, how much?
User: Put everything wheat bagel on it
Bot: Let's finish with your Nova Scotia Salmon, 1/4 lb first. How much?
User: Remove the gluten free bagel
Bot: I couldn't find gluten free bagel in your order. What would you like to do?
[FAILED: Item not found: I couldn't find gluten free bagel in your order. What would you like to do?]
User: Change the everything wheat bagel to half & half
```

### Order Lemon Blueberry Cream Cheese Sandwich, Tropicana Orange Juice 46 oz then modify

**Type:** modifier_flow
**Session:** `b12d5c0b-cb12-4c83-900c-0e313a3d7d72`

**Failure:** Item not found: I couldn't find nova scotia salmon in your order. What would you like to do?

**Conversation:**
```
User: Can I get a Lemon Blueberry Cream Cheese Sandwich and a Tropicana Orange Juice 46 oz
Bot: Got it, for the Swiss Cheese. How much?
User: Add whitefish salad
Bot: Sure, I've added Whitefish Salad. How much?
User: Take off the nova scotia salmon
Bot: I couldn't find nova scotia salmon in your order. What would you like to do?
[FAILED: Item not found: I couldn't find nova scotia salmon in your order. What would you like to do?]
User: Swap nova scotia salmon for whole wheat bagel
```

### Order Vitamin Water Focus, Iced Chai Tea then modify

**Type:** modifier_flow
**Session:** `b3fa0171-2f13-4ceb-bfbf-36339899b660`

**Failure:** Item not found: Sorry, we don't have Can you add sauerkraut. We have English Breakfast, Green Tea, Earl Gray, Rasber

**Conversation:**
```
User: I'd like a Vitamin Water Focus and also a Iced Chai Tea
Bot: Got it, for the Hot Tea. What kind of tea flavor would you like?
User: Can you add sauerkraut
Bot: Sorry, we don't have Can you add sauerkraut. We have English Breakfast, Green Tea, Earl Gray, Rasberry Tea, and Camomile, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have Can you add sauerkraut. We have English Breakfast, Green Tea, Earl Gray, Rasber]
User: Without sauerkraut
User: Actually sprouts instead of sauerkraut
```

### Order Whitefish Salad Sandwich then modify

**Type:** modifier_flow
**Session:** `61b8561b-1212-4d6a-a14c-c7c3b7b9624b`

**Failure:** Item not found: Sorry, we don't have Hold the nova. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast

**Conversation:**
```
User: One Whitefish Salad Sandwich please
Bot: Got it, for the Whitefish Salad Sandwich. What kind of bagel would you like?
User: Put caramel syrup on it
Bot: Let's finish with your Whitefish Salad Sandwich, Beefsteak Tomatoes, Lettuce, Whitefish Salad first. What kind of bagel would you like?
User: Hold the nova
Bot: Sorry, we don't have Hold the nova. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more optio...
[FAILED: Item not found: Sorry, we don't have Hold the nova. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast]
User: Change the kippered salmon to cranberry pecan chicken salad
```

*... and 130 more failures in this category*

## Item Recognition

### Order Dr. Brown's Cream Soda then modify

**Type:** modifier_flow
**Session:** `ecac07ec-fdf9-4f47-ac7d-df48f10fa549`

**Failure:** Expected item 'Dr. Brown's Cream Soda' not in cart. Cart contains: []

**Conversation:**
```
User: I'd like 1 Dr. Brown's Cream Soda
Bot: Got it, Dr. Brown's Cream Soda. Anything else?
User: WITH TOFU CC PLEASE
Bot: I didn't catch that. What would you like to order?
User: No tofu cc actually please
Bot: This item doesn't have a Unknown to change.
User: RePlAce tOFU cC WIth PopPy seED BaGEL
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Dr. Brown's Cream Soda' not in cart. Cart contains: []]
```

### Order Apricot Hamantaschen then modify

**Type:** modifier_flow
**Session:** `3979e002-5227-425c-a1f1-173f1b22dbf0`

**Failure:** Expected item 'Apricot Hamantaschen' not in cart. Cart contains: []

**Conversation:**
```
User: One Apricot Hamantaschen please
Bot: Got it, Apricot Hamantaschen. Anything else?
User: Can you add scallion
Bot: Sure, I've added that to your Apricot Hamantaschen, Scallion Cream Cheese. Anything else?
User: No tofu cream cheese please
Bot: Sure, I've removed the spread. Your order is now Apricot Hamantaschen. Anything else?
User: Switch wheat for tofu cream cheese
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Apricot Hamantaschen' not in cart. Cart contains: []]
```

### Order Bjorn Qorn Popcorn then modify

**Type:** modifier_flow
**Session:** `80735fa1-f588-43ea-a5e4-374daffe9a96`

**Failure:** Expected item 'Bjorn Qorn Popcorn' not in cart. Cart contains: []

**Conversation:**
```
User: One Bjorn Qorn Popcorn please
Bot: Got it, Bjorn Qorn Popcorn. Anything else?
User: With challah roll please
Bot: Sure, I've added that to your Challah Roll. Anything else?
User: Take off the challah roll
Bot: OK, I've removed the Challah Roll. Your order is now Bjorn Qorn Popcorn. Anything else?
User: Replace jalapeno honey cc with ketchup
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Bjorn Qorn Popcorn' not in cart. Cart contains: []]
```

### Order Apple Cinnamon Babka then modify

**Type:** modifier_flow
**Session:** `42134117-3f84-408e-a4cc-1f1df5babe92`

**Failure:** Expected item 'Apple Cinnamon Babka' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Apple Cinnamon Babka
Bot: Got it, Apple Cinnamon Babka. Anything else?
User: Add almond
Bot: Sure, I've updated your Apple Cinnamon Babka, Almond Milk. Anything else?
User: No plain sourdough please
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Apple Cinnamon Babka' not in cart. Cart contains: []]
User: Change the pepper to almond
```

### Order Apricot Hamantaschen then modify

**Type:** modifier_flow
**Session:** `6947fe6c-9ca5-4be5-976f-34a0b61766ab`

**Failure:** Expected item 'Apricot Hamantaschen' not in cart. Cart contains: []

**Conversation:**
```
User: Can I get a Apricot Hamantaschen
Bot: Got it, Apricot Hamantaschen. Anything else?
User: Put maple raisin walnut cream cheese on it
Bot: Sure, I've added that to your Apricot Hamantaschen, Walnut Raisin Cream Cheese. Anything else?
User: Remove the maple raisin walnut cream cheese
Bot: OK, I've removed the Apricot Hamantaschen, Walnut Raisin Cream Cheese. What would you like to order?
[FAILED: Expected item 'Apricot Hamantaschen' not in cart. Cart contains: []]
User: Change the pickles to jalapeño honey cc
```

### Order Dr. Brown's Black Cherry then modify

**Type:** modifier_flow
**Session:** `7a3bf3b7-1581-4f31-890c-a3c8056c943f`

**Failure:** Expected item 'Dr. Brown's Black Cherry' not in cart. Cart contains: []

**Conversation:**
```
User: Can I get a Dr. Brown's Black Cherry
Bot: Got it, Dr. Brown's Black Cherry. Anything else?
User: Add vanilla
Bot: Sure, I've added that to your Dr. Brown's Black Cherry, Vanilla Syrup. Anything else?
User: Actually no half & half
Bot: Got it, half & half. Anything else?
User: Replace walnut raisin with wheat flatz
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Dr. Brown's Black Cherry' not in cart. Cart contains: []]
```

### Order Essentia Water 700ml, Pop Daddy Pretzels - Dill Pickle then modify

**Type:** modifier_flow
**Session:** `f0ad51ac-a047-4c2b-a896-1a10e46805e9`

**Failure:** Expected item 'Essentia Water 700ml' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Essentia Water 700ml and a Pop Daddy Pretzels - Dill Pickle
Bot: Got it, Essentia Water 700ml and Pop Daddy Pretzels - Dill Pickle. Anything else?
User: Also add tofu nova cream cheese
Bot: What can I get for you?
User: No lactose free please
Bot: I didn't catch that. What would you like to order?
User: Swap lactose free for tofu nova cream cheese
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Essentia Water 700ml' not in cart. Cart contains: []]
```

### Order Tofu Scallion Sandwich then modify

**Type:** modifier_flow
**Session:** `f413af50-89ee-455f-962f-b5d64a5c5285`

**Failure:** Expected item 'Tofu Scallion Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: One Tofu Scallion Sandwich please
Bot: Got it, for the Tofu Scallion Sandwich. What kind of bagel would you like?
User: With scallion cc please
Bot: Let's finish with your Tofu Scallion Sandwich, Tofu Scallion Cream Cheese, Scallion Cream Cheese, Scallion Tofu Spread first. What kind of bagel would you like?
User: Take off the scallion cc
Bot: OK, I've removed the Tofu Scallion Sandwich, Tofu Scallion Cream Cheese, Scallion Cream Cheese, Scallion Tofu Spread. What would you like to order?
[FAILED: Expected item 'Tofu Scallion Sandwich' not in cart. Cart contains: []]
User: Actually truffle cream cheese instead of scallion cc
```

### Order Pastrami then modify

**Type:** modifier_flow
**Session:** `b7b37666-ed50-4410-aced-c2a57a79c124`

**Failure:** Expected item 'Pastrami' not in cart. Cart contains: []

**Conversation:**
```
User: I'll have a Pastrami
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Pastrami' not in cart. Cart contains: []]
User: Add pb
User: Actually no kalamata olive
User: Change the pb to egg whites
```

### Order Joe's Green Tea then modify

**Type:** modifier_flow
**Session:** `580ab14e-9a23-41eb-b0ed-fcb956e26840`

**Failure:** Expected item 'Joe's Green Tea' not in cart. Cart contains: []

**Conversation:**
```
User: Can I get a Joe's Green Tea
Bot: Got it, Joe's Green Tea. Anything else?
User: Put nova scotia on it
Bot: Sure, I've updated your Joe's Green Tea, Nova Scotia Salmon. Anything else?
User: Without avocado horseradish
Bot: What can I get for you?
User: Replace hazelnut with nova scotia
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Joe's Green Tea' not in cart. Cart contains: []]
```

*... and 3 more failures in this category*
