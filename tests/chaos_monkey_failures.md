# Chaos Monkey Test Failures

**Generated:** 2026-02-10T10:58:49.042156
**Session Start:** 2026-02-10T10:51:39.137290
**Total Tests:** 50
**Passed:** 34
**Failed:** 16

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 16 |

## Menu Item Not Found

### Order Grilled Cheese then modify

**Type:** modifier_flow
**Session:** `e644b4b7-eefe-4e81-bbbe-350cecc703de`

**Failure:** Item not found: Sorry, we don't have Skip the horseradish. We have Gluten Free Everything Bagel, Sesame Bagel, Frenc

**Conversation:**
```
User: I'd like a Grilled Cheese
Bot: Got it, for the Grilled Cheese. What kind of bagel would you like?
User: Add horseradish to that
Bot: Sure, I've added Horseradish. What kind of bagel would you like?
User: Skip the horseradish
Bot: Sorry, we don't have Skip the horseradish. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear mor...
[FAILED: Item not found: Sorry, we don't have Skip the horseradish. We have Gluten Free Everything Bagel, Sesame Bagel, Frenc]
User: I'd like spinach on that
```

### Order Peanut Butter & Jelly Sandwich, Mozzarella Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `1d0c37f7-09f2-47f7-8157-7244a74e9a97`

**Failure:** Item not found: Sorry, we don't have No jalapeño spread. We have Gluten Free Everything Bagel, Sesame Bagel, French 

**Conversation:**
```
User: Peanut Butter & Jelly Sandwich and Mozzarella Cheese Sandwich please
Bot: Got it, Peanut Butter & Jelly Sandwich and Swiss Cheese. For the peanut butter & jelly sandwich, what kind of bagel would you like?
User: I'd like jalapeño spread on that
Bot: Let's finish with your Peanut Butter & Jelly Sandwich, Strawberry Jelly, Peanut Butter, Grape Jelly, Grape Jelly, Strawberry Jelly first. What kind of bagel would you like?
User: No jalapeño spread please
Bot: Sorry, we don't have No jalapeño spread. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more ...
[FAILED: Item not found: Sorry, we don't have No jalapeño spread. We have Gluten Free Everything Bagel, Sesame Bagel, French ]
User: Put plain spread on it
```

### Order Nova Cream Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `96de9733-eca5-4b8a-a939-bfed9136c8fe`

**Failure:** Item not found: Sorry, we don't have Also add sausage. We have Gluten Free Everything Bagel, Sesame Bagel, French To

**Conversation:**
```
User: Can I get a Nova Cream Cheese Sandwich
Bot: Got it, for the Nova Cream Cheese Sandwich. What kind of bagel would you like?
User: Also add sausage
Bot: Sorry, we don't have Also add sausage. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more op...
[FAILED: Item not found: Sorry, we don't have Also add sausage. We have Gluten Free Everything Bagel, Sesame Bagel, French To]
User: No sausage please
User: Can you add breakfast sausage
```

### Order The Pizza BEC with Pepperoni, Macchiato then modify

**Type:** modifier_flow
**Session:** `9c13c9db-9b67-4d8d-ba25-465922b3c76a`

**Failure:** Item not found: Sorry, we don't have Skip the wild coho salmon. We have Gluten Free Everything Bagel, Sesame Bagel, 

**Conversation:**
```
User: I'll have a The Pizza BEC with Pepperoni and a Macchiato
Bot: Got it, The Pizza BEC with Pepperoni and Macchiato. For the the pizza bec with pepperoni, what kind of bagel would you like?
User: I'd like wild coho salmon on that
Bot: Let's finish with your The Pizza BEC with Pepperoni, Pepperoni, Mozzarella Cheese, Tomato Sauce, 2x Eggs, Pepper first. What kind of bagel would you like?
User: Skip the wild coho salmon
Bot: Sorry, we don't have Skip the wild coho salmon. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hea...
[FAILED: Item not found: Sorry, we don't have Skip the wild coho salmon. We have Gluten Free Everything Bagel, Sesame Bagel, ]
User: Put ham on it
```

### Order Hot Chocolate then modify

**Type:** modifier_flow
**Session:** `a82f4f26-bcc0-4848-a776-f2a883f87296`

**Failure:** Item not found: Sorry, we don't have Can you add sugar raw. We have Small or Large.

**Conversation:**
```
User: I'll have a Hot Chocolate
Bot: Got it, for the Hot Chocolate. What size?
User: Can you add sugar raw
Bot: Sorry, we don't have Can you add sugar raw. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Can you add sugar raw. We have Small or Large.]
User: No sugar raw please
User: I'd like caramel on that
```

### Order Green Tea, Baked Salmon Salad Sandwich then modify

**Type:** modifier_flow
**Session:** `1a77d943-a04f-4387-8bc0-27ff0468b278`

**Failure:** Item not found: I couldn't find a that in your order. Would you like to add one?

**Conversation:**
```
User: Can I get a Green Tea and a Baked Salmon Salad Sandwich
Bot: Got it, Green Tea and Baked Salmon Salad Sandwich. For the green tea, any milk, sweetener, or syrup?
User: Put peppermint on it
Bot: Got it, Peppermint Syrup. Got it, Green Tea and Baked Salmon Salad Sandwich. For the baked salmon salad sandwich, what kind of bagel would you like?
User: Remove the peppermint
Bot: OK, I've removed the Green Tea, Green Tea, Peppermint Syrup. Anything else?
User: Add sugar to that
Bot: I couldn't find a that in your order. Would you like to add one?
[FAILED: Item not found: I couldn't find a that in your order. Would you like to add one?]
```

### Order The Margherita Pizza Bagel then modify

**Type:** modifier_flow
**Session:** `88a5c4f5-1729-42be-b956-112a0e80be36`

**Failure:** Item not found: I couldn't find plain spread in your order. What would you like to do?

**Conversation:**
```
User: One The Margherita Pizza Bagel please
Bot: Got it, for the The Margherita Pizza Bagel. What kind of bagel would you like?
User: Also add plain spread
Bot: We have GF Plain Bagel, Plain Bagel, Plain Sourdough Bagel, or Plain Sourdough Bagel Flatz. Which would you like?
User: Take off the plain spread
Bot: I couldn't find plain spread in your order. What would you like to do?
[FAILED: Item not found: I couldn't find plain spread in your order. What would you like to do?]
User: Add jalapeno to that
```

### Order The Classic then modify

**Type:** modifier_flow
**Session:** `fb375470-d647-45d4-afa6-c974bc7659ac`

**Failure:** Item not found: Sorry, we don't have hmm Skip the roasted peppers. We have Gluten Free Everything Bagel, Sesame Bage

**Conversation:**
```
User: basically I'd like a The Classic
Bot: Got it, for the The Classic. What kind of bagel would you like?
User: With roasted uh peppers please
Bot: Let's finish with your The Classic, 2x Eggs first. What kind of bagel would you like?
User: hmm Skip the roasted peppers
Bot: Sorry, we don't have hmm Skip the roasted peppers. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to ...
[FAILED: Item not found: Sorry, we don't have hmm Skip the roasted peppers. We have Gluten Free Everything Bagel, Sesame Bage]
User: Can you add jalapeno cheddar bagel thank you
```

### Order Hot Cappuccino then modify

**Type:** modifier_flow
**Session:** `f3ba0865-f5e7-412c-a343-baf12d90a41e`

**Failure:** Item not found: Sorry, we don't have No whole milk. We have Small or Large.

**Conversation:**
```
User: I'll have a Hot Cappuccino
Bot: Got it, for the Hot Cappuccino. What size?
User: Add whole milk to that
Bot: Sure, I've added Whole Milk. What size?
User: No whole milk please
Bot: Sorry, we don't have No whole milk. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have No whole milk. We have Small or Large.]
User: Can you add oat
```

### Order Egg and Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `b39312c9-0341-45c3-98fd-53b2c35bcf3e`

**Failure:** Item not found: Sorry, we don't have well Add jalapeño spread to that. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: I'd like a Egg and Cheese Sandwich please
Bot: Got it, for the Swiss Cheese. How much?
User: I'd like provolone cheese on that if you don't mind
Bot: Let's finish with your Swiss Cheese, 1/4 lb first. How much?
User: Actually no provolone cheese thanks
Bot: Sure, I've changed the cheese to Provolone Cheese. How much?
User: well Add jalapeño spread to that
Bot: Sorry, we don't have well Add jalapeño spread to that. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have well Add jalapeño spread to that. We have 1/4 lb or 1 lb.]
```

*... and 6 more failures in this category*
