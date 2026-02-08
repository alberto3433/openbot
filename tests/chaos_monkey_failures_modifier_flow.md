# Chaos Monkey Test Failures

**Generated:** 2026-02-07T19:07:50.249131
**Session Start:** 2026-02-07T18:56:41.391543
**Total Tests:** 50
**Passed:** 28
**Failed:** 22

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 21 |
| Item Recognition | 1 |

## Menu Item Not Found

### Order Tuna Salad Sandwich, Cinnamon Sugar Butter Sandwich then modify

**Type:** modifier_flow
**Session:** `e8a0791d-f490-4c44-bcb4-95b43371534c`

**Failure:** Item not found: Sorry, we don't have No nova scotia salmon. We have Gluten Free Everything Bagel, Sesame Bagel, Fren

**Conversation:**
```
User: Tuna Salad Sandwich and Cinnamon Sugar Butter Sandwich please
Bot: Got it, Tuna Salad Sandwich and Cinnamon Sugar Butter Sandwich. For the tuna salad sandwich, what kind of bagel would you like?
User: I'd like nova scotia salmon on that
Bot: Let's finish with your Tuna Salad Sandwich, Lettuce, Beefsteak Tomatoes, Tuna Salad first. What kind of bagel would you like?
User: No nova scotia salmon please
Bot: Sorry, we don't have No nova scotia salmon. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear mo...
[FAILED: Item not found: Sorry, we don't have No nova scotia salmon. We have Gluten Free Everything Bagel, Sesame Bagel, Fren]
User: Can you add blueberry cream cheese
```

### Order Truffle Cream Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `5ca6c8ff-1319-4993-93f2-084582ee0b07`

**Failure:** Item not found: Sorry, we don't have Also add pepper jack cheese. We have Gluten Free Everything Bagel, Sesame Bagel

**Conversation:**
```
User: One Truffle Cream Cheese Sandwich please
Bot: Got it, for the Truffle Cream Cheese Sandwich. What kind of bagel would you like?
User: Also add pepper jack cheese
Bot: Sorry, we don't have Also add pepper jack cheese. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to h...
[FAILED: Item not found: Sorry, we don't have Also add pepper jack cheese. We have Gluten Free Everything Bagel, Sesame Bagel]
User: Hold the pepper jack cheese
User: Add sour cream to that
```

### Order The BLT, Hot Cappuccino then modify

**Type:** modifier_flow
**Session:** `9efed28f-3657-4913-b27a-24d9cf658c1e`

**Failure:** Item not found: Sorry, we don't have Can you add honey walnut cream cheese. We have Gluten Free Everything Bagel, Se

**Conversation:**
```
User: The BLT and Hot Cappuccino please
Bot: Got it, The BLT and Hot Cappuccino. For the the blt, what kind of bagel would you like?
User: Can you add honey walnut cream cheese
Bot: Sorry, we don't have Can you add honey walnut cream cheese. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you...
[FAILED: Item not found: Sorry, we don't have Can you add honey walnut cream cheese. We have Gluten Free Everything Bagel, Se]
User: Actually no honey walnut cream cheese
User: I'd like everything sourdough bagel on that
```

### Order Smoked Trout Sandwich then modify

**Type:** modifier_flow
**Session:** `c7de0c1f-ed97-4086-b7a2-16279fb88727`

**Failure:** Item not found: Sorry, we don't have Skip the muenster cheese. We have Gluten Free Everything Bagel, Sesame Bagel, F

**Conversation:**
```
User: Can I get a Smoked Trout Sandwich
Bot: Got it, for the Smoked Trout Sandwich. What kind of bagel would you like?
User: With muenster cheese please
Bot: Let's finish with your Smoked Trout Sandwich, Smoked Trout, Plain Cream Cheese first. What kind of bagel would you like?
User: Skip the muenster cheese
Bot: Sorry, we don't have Skip the muenster cheese. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear...
[FAILED: Item not found: Sorry, we don't have Skip the muenster cheese. We have Gluten Free Everything Bagel, Sesame Bagel, F]
User: Also add sun dried tomato bagel
```

### Order Hot Cappuccino, Scottish Salmon Sandwich then modify

**Type:** modifier_flow
**Session:** `23ad2c95-d6d0-4ab5-aa0e-f71a2f11f84c`

**Failure:** Item not found: Sorry, we don't have Without um regular sugar. We have Small or Large.

**Conversation:**
```
User: hi there Can I get a Hot Cappuccino and a Scottish Salmon Sandwich
Bot: Got it, Hot Cappuccino and Scottish Salmon Sandwich. For the hot cappuccino, what size?
User: With regular sugar please thank you
Bot: Let's finish with your Hot Cappuccino first. What size?
User: Without um regular sugar
Bot: Sorry, we don't have Without um regular sugar. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Without um regular sugar. We have Small or Large.]
User: Also add sugar in the um raw
```

### Order Tofu Vegetable Sandwich then modify

**Type:** modifier_flow
**Session:** `4679f1b3-5ce2-487e-93de-58f9e1240261`

**Failure:** Item not found: I couldn't find plain sourdough if you don't mind in your order. What would you like to do?

**Conversation:**
```
User: Can I get a like Tofu Vegetable Sandwich
Bot: Got it, for the Tofu Vegetable Sandwich. What kind of bagel would you like?
User: With plain sourdough please thanks
Bot: Got it, Plain Sourdough Bagel. Would you like it toasted?
User: Take off the plain sourdough if you don't mind
Bot: I couldn't find plain sourdough if you don't mind in your order. What would you like to do?
[FAILED: Item not found: I couldn't find plain sourdough if you don't mind in your order. What would you like to do?]
User: hi With salt bagel please
```

### Order Vegetable Cream Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `074d9b17-38ef-4f9d-bcc9-26863b40b47f`

**Failure:** Item not found: Sorry, we don't have No belly lox. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast 

**Conversation:**
```
User: I'll have a Vegetable Cream Cheese Sandwich
Bot: Got it, for the Vegetable Cream Cheese Sandwich. What kind of bagel would you like?
User: Also add belly lox
Bot: Got it, I've added Belly Lox. Now, for your Vegetable Cream Cheese Sandwich, what kind of bagel would you like?
User: No belly lox please
Bot: Sorry, we don't have No belly lox. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more option...
[FAILED: Item not found: Sorry, we don't have No belly lox. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast ]
User: Add mayo to that
```

### Order Sun-Dried Tomato Cream Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `614108f0-5dfe-462a-8481-d2638db4e948`

**Failure:** Item not found: Sorry, we don't have Without turkey bacon. We have Gluten Free Everything Bagel, Sesame Bagel, Frenc

**Conversation:**
```
User: Can I get a Sun-Dried Tomato Cream Cheese Sandwich
Bot: Got it, for the Sun-Dried Tomato Cream Cheese Sandwich. What kind of bagel would you like?
User: Add turkey bacon
Bot: Sure, I've added Turkey Bacon. What kind of bagel would you like?
User: Without turkey bacon
Bot: Sorry, we don't have Without turkey bacon. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear mor...
[FAILED: Item not found: Sorry, we don't have Without turkey bacon. We have Gluten Free Everything Bagel, Sesame Bagel, Frenc]
User: Add seeded salmon to that
```

### Order Baked Salmon Salad Sandwich then modify

**Type:** modifier_flow
**Session:** `7258646d-79be-46c7-bacc-786f2d8e1bad`

**Failure:** Item not found: Sorry, we don't have excuse me, Can you add breakfast potato latke. We have Gluten Free Everything B

**Conversation:**
```
User: I'll have hmm a Baked Salmon Salad Sandwich
Bot: Got it, for the Baked Salmon Salad Sandwich. What kind of bagel would you like?
User: excuse me, Can you add breakfast potato latke
Bot: Sorry, we don't have excuse me, Can you add breakfast potato latke. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these o...
[FAILED: Item not found: Sorry, we don't have excuse me, Can you add breakfast potato latke. We have Gluten Free Everything B]
User: so No breakfast potato latke please
User: Can you add pickle please and thank you
```

### Order Iced Cappucino then modify

**Type:** modifier_flow
**Session:** `8a6337c9-de62-4e6f-bf53-256d63000dfb`

**Failure:** Item not found: Sorry, we don't have Actually no skim. We have Small or Large.

**Conversation:**
```
User: I'd like a Iced Cappucino
Bot: Got it, for the Iced Cappucino. What size?
User: Add skim to that
Bot: Let's finish with your Iced Cappucino first. What size?
User: Actually no skim
Bot: Sorry, we don't have Actually no skim. We have Small or Large.
[FAILED: Item not found: Sorry, we don't have Actually no skim. We have Small or Large.]
User: Add regular sugar
```

*... and 11 more failures in this category*

## Item Recognition

### Order Havarti Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `4f4d70d3-f7c4-4cc1-a934-b2d9858819f6`

**Failure:** Expected item 'Havarti Cheese Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: One Havarti um Cheese Sandwich please
Bot: What can I get for you?
[FAILED: Expected item 'Havarti Cheese Sandwich' not in cart. Cart contains: []]
User: hello, Can you add poppy seed bagel
User: Take just off the poppy seed bagel
User: oh I'd like gf plain on that
```
