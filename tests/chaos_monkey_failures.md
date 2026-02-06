# Chaos Monkey Test Failures

**Generated:** 2026-02-06T00:34:51.014380
**Session Start:** 2026-02-05T23:50:27.630104
**Total Tests:** 400
**Passed:** 325
**Failed:** 75

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 56 |
| Item Recognition | 19 |

## Menu Item Not Found

### Cancel order

**Type:** cart_ops
**Session:** `5a50a7e6-6adf-4ef5-acaf-5ca3c2fc3994`

**Failure:** Item not found: I couldn't find my order in your order. What would you like to do?

**Conversation:**
```
User: give me Snapple Iced Tea
Bot: Got it, for the Hot Tea. What kind of tea flavor would you like?
User: CaNcEl My OrDer
Bot: I couldn't find my order in your order. What would you like to do?
[FAILED: Item not found: I couldn't find my order in your order. What would you like to do?]
```

### Cancel order

**Type:** cart_ops
**Session:** `3b3bb7fb-87f5-4319-8f85-a9c7ffb37ca3`

**Failure:** Item not found: I couldn't find my my order in your order. What would you like to do?

**Conversation:**
```
User: so I'll have a Granola
Bot: Got it, Granola. Anything else?
User: Cancel my my order
Bot: I couldn't find my my order in your order. What would you like to do?
[FAILED: Item not found: I couldn't find my my order in your order. What would you like to do?]
```

### Change Olipop Ginger Lemon quantity to 5

**Type:** cart_ops
**Session:** `3b9c1b7c-09d1-40c0-a7a6-9602ad56f61f`

**Failure:** Item not found: I'm sorry, we don't have five of thsoe. Is there something else I can help you with?

**Conversation:**
```
User: I'll have a Olipop Ginger Lemon
Bot: Got it, Olipop Ginger Lemon. Anything else?
User: i'd like five of thsoe
Bot: I'm sorry, we don't have five of thsoe. Is there something else I can help you with?
[FAILED: Item not found: I'm sorry, we don't have five of thsoe. Is there something else I can help you with?]
```

### Remove Muenster Cheese from cart

**Type:** cart_ops
**Session:** `573dfbba-f273-4e26-8726-25f55977221d`

**Failure:** Item not found: Sorry, we don't have like Never mind on the Muenster Muenster Cheese. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: GIVE ME A MUENSTER CHEESE
Bot: Got it, for the Muenster Cheese. How much?
User: like Never mind on the Muenster Muenster Cheese
Bot: Sorry, we don't have like Never mind on the Muenster Muenster Cheese. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have like Never mind on the Muenster Muenster Cheese. We have 1/4 lb or 1 lb.]
```

### Order The Cheesesteak and Blueberry Cream Cheese Sandwich

**Type:** multi_item
**Session:** `9b1d7b86-ae00-4a12-93f7-6315a1b65040`

**Failure:** Item not found: Sorry, we don't have And a Blueberry Cream Cheese Sandwich. We have Gluten Free Everything Bagel, Se

**Conversation:**
```
User: Can I get a The Cheesesteak
Bot: Got it, for the The Cheesesteak. What kind of bread would you like?
User: And a Blueberry Cream Cheese Sandwich
Bot: Sorry, we don't have And a Blueberry Cream Cheese Sandwich. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you...
[FAILED: Item not found: Sorry, we don't have And a Blueberry Cream Cheese Sandwich. We have Gluten Free Everything Bagel, Se]
```

### Remove Pepper Jack Cheese Sandwich from cart

**Type:** cart_ops
**Session:** `4a099f55-0c8c-44e2-9c1f-17552ea47b0b`

**Failure:** Item not found: Sorry, we don't have Actually, Remove The Pepper Jack Cheese Sandwich. We have Gluten Free Everythin

**Conversation:**
```
User: i'd like A PEPPER JACK CHEESE SANDWICH
Bot: Got it, for the Pepper Jack Cheese Sandwich. What kind of bread would you like?
User: Actually, Remove The Pepper Jack Cheese Sandwich
Bot: Sorry, we don't have Actually, Remove The Pepper Jack Cheese Sandwich. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of thes...
[FAILED: Item not found: Sorry, we don't have Actually, Remove The Pepper Jack Cheese Sandwich. We have Gluten Free Everythin]
```

### Cancel order

**Type:** cart_ops
**Session:** `e90c3dc1-e8f0-4174-99b8-bad3c2f78de6`

**Failure:** Item not found: Sorry, we don't have Never mind, c1nel everything. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: i want a The DDelancey with Pastrami
Bot: Got it, for the Pastrami. How much?
User: Never mind, c1nel everything
Bot: Sorry, we don't have Never mind, c1nel everything. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Never mind, c1nel everything. We have 1/4 lb or 1 lb.]
```

### Order The Pizza BEC with Pepperoni and Irving Farm Cold Brew

**Type:** multi_item
**Session:** `591c0597-1300-41c5-b9a6-8a75cf32d02e`

**Failure:** Item not found: Sorry, we don't have And a Irving Farm Cold Brew. We have Gluten Free Everything Bagel, Sesame Bagel

**Conversation:**
```
User: Can I get a The Pizza BEC with Pepperoni
Bot: Got it, for the The Pizza BEC with Pepperoni. What kind of bread would you like?
User: And a Irving Farm Cold Brew
Bot: Sorry, we don't have And a Irving Farm Cold Brew. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to h...
[FAILED: Item not found: Sorry, we don't have And a Irving Farm Cold Brew. We have Gluten Free Everything Bagel, Sesame Bagel]
```

### Order Chicken Salad Sandwich and Bologna

**Type:** multi_item
**Session:** `b51d1005-e12d-4a7f-8d36-04280968388f`

**Failure:** Item not found: Sorry, we don't have And a Bologna. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast

**Conversation:**
```
User: I'll have a Chicken Salad Sandwich
Bot: Got it, for the Chicken Salad Sandwich. What kind of bread would you like?
User: And a Bologna
Bot: Sorry, we don't have And a Bologna. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more optio...
[FAILED: Item not found: Sorry, we don't have And a Bologna. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast]
```

### Change Peanut Butter & Jelly Sandwich quantity to 3

**Type:** cart_ops
**Session:** `f3f29dbe-f003-4c68-af05-9d0a550e865d`

**Failure:** Item not found: I'm sorry, we don't have pb & Jelly Eandwich. Is there something else I can help you with?

**Conversation:**
```
User: I'll have a pb & Jelly Eandwich
Bot: I'm sorry, we don't have pb & Jelly Eandwich. Is there something else I can help you with?
[FAILED: Item not found: I'm sorry, we don't have pb & Jelly Eandwich. Is there something else I can help you with?]
User: actually, make that three three three
```

*... and 46 more failures in this category*

## Item Recognition

### Order Nova Cream Cheese Sandwich

**Type:** single_item
**Session:** `0816e2f6-8c71-403d-8da1-198e27e04e21`

**Failure:** Expected item 'Nova Cream Cheese Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: Just a Nova Cream cc uh Sandwich
Bot: What can I get for you?
[FAILED: Expected item 'Nova Cream Cheese Sandwich' not in cart. Cart contains: []]
```

### Change American Cheese quantity to 1

**Type:** cart_ops
**Session:** `34939988-22d7-420b-ab22-d5e81a964710`

**Failure:** Expected item 'American Cheese' not in cart. Cart contains: []

**Conversation:**
```
User: i'll hae a american ccheese
Bot: What can I get for you?
[FAILED: Expected item 'American Cheese' not in cart. Cart contains: []]
User: I'll take one of those
```

### Order Hummus Sandwich and The Health Nut

**Type:** multi_item
**Session:** `e5704933-afb1-4442-9d13-f83f28cb073f`

**Failure:** Expected item 'Hummus Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: can i i get a hummus sandwcih
Bot: What can I get for you?
[FAILED: Expected item 'Hummus Sandwich' not in cart. Cart contains: []]
User: Also a The Gealtth Nut
```

### Order Strawberry Yogurt Parfait

**Type:** single_item
**Session:** `8b3f9b1f-dec2-4779-a4dc-be39fe4529a8`

**Failure:** Expected item 'Strawberry Yogurt Parfait' not in cart. Cart contains: []

**Conversation:**
```
User: Strawberry Yogurt hmm Parfait please
Bot: What can I get for you?
[FAILED: Expected item 'Strawberry Yogurt Parfait' not in cart. Cart contains: []]
```

### Order Cafe Americano

**Type:** single_item
**Session:** `1d2c9c3c-370f-49e5-9e72-d867523cec1c`

**Failure:** Expected item 'Cafe Americano' not in cart. Cart contains: []

**Conversation:**
```
User: JuST a CAfE WMERiCANO
Bot: What can I get for you?
[FAILED: Expected item 'Cafe Americano' not in cart. Cart contains: []]
```

### Order The Mulberry

**Type:** single_item
**Session:** `946fcf81-0734-4f78-a340-0dc25f1ebce2`

**Failure:** Expected item 'The Mulberry' not in cart. Cart contains: []

**Conversation:**
```
User: One The Umlberry Pllease
Bot: What can I get for you?
[FAILED: Expected item 'The Mulberry' not in cart. Cart contains: []]
```

### Order Tofu Nova Sandwich

**Type:** single_item
**Session:** `cd68926d-e391-44b0-b8c4-a057e1d74d30`

**Failure:** Expected item 'Tofu Nova Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: Just oh a Tofu Tofu Nova Sandwich
Bot: What can I get for you?
[FAILED: Expected item 'Tofu Nova Sandwich' not in cart. Cart contains: []]
```

### Order Nova Scotia Cream Cheese Sandwich

**Type:** single_item
**Session:** `c41c3bc1-82e4-4289-a556-338a030a6a7c`

**Failure:** Expected item 'Nova Scotia Cream Cheese Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: One Nvoa Scotia cc Sandwich please
Bot: What can I get for you?
[FAILED: Expected item 'Nova Scotia Cream Cheese Sandwich' not in cart. Cart contains: []]
```

### Order Apricot Hamantaschen

**Type:** single_item
**Session:** `888a1c3f-b0cf-4ee2-a720-43c5cbdb0617`

**Failure:** Expected item 'Apricot Hamantaschen' not in cart. Cart contains: []

**Conversation:**
```
User: Qpricot Hamantaschen please
Bot: What can I get for you?
[FAILED: Expected item 'Apricot Hamantaschen' not in cart. Cart contains: []]
```

### Order Grape Jelly Sandwich

**Type:** single_item
**Session:** `9ef4bc08-d7f5-4162-9afa-d7adbf3e87d5`

**Failure:** Expected item 'Grape Jelly Sandwich' not in cart. Cart contains: []

**Conversation:**
```
User: grape um jelly sandwich sandwich please
Bot: I didn't catch that. What would you like to order?
[FAILED: Expected item 'Grape Jelly Sandwich' not in cart. Cart contains: []]
```

*... and 9 more failures in this category*
