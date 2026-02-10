# Chaos Monkey Test Failures

**Generated:** 2026-02-07T14:38:15.606448
**Session Start:** 2026-02-07T14:37:05.829105
**Total Tests:** 5
**Passed:** 2
**Failed:** 3

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 3 |

## Menu Item Not Found

### Order The Mulberry then modify

**Type:** modifier_flow
**Session:** `a2f1bd60-3ea7-4cc6-8e69-4a0ab495a439`

**Failure:** Item not found: Sorry, we don't have Replace wheat flatz with smoked trout. We have Egg Whites, Scrambled, Fried, Ov

**Conversation:**
```
User: I'll have a The Mulberry
Bot: Got it, for the The Mulberry. What kind of bagel would you like?
User: With cinnamon bagel please
Bot: Got it, Cinnamon Raisin Bagel. Would you like it toasted?
User: No smoked trout please
Bot: How would you like your eggs?
User: Replace wheat flatz with smoked trout
Bot: Sorry, we don't have Replace wheat flatz with smoked trout. We have Egg Whites, Scrambled, Fried, Over Easy, and Over Medium, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have Replace wheat flatz with smoked trout. We have Egg Whites, Scrambled, Fried, Ov]
```

### Order The BLT, The Pizza BEC with Bacon then modify

**Type:** modifier_flow
**Session:** `a0207721-6d0b-4ee9-bc01-c683d446ee90`

**Failure:** Item not found: Sorry, we don't have Skip the wild coho sonelmon. We have Gluten Free Everything Bagel, Sesame Bagel

**Conversation:**
```
User: I'll have a The BLT and a The Pizza BEC uh with Bacon
Bot: Got it, The BLT and The Classic BEC. For the the blt, what kind of bagel would you like?
User: add wild coho salmon
Bot: Sure, I've added Wild Coho Salmon. What kind of bagel would you like?
User: Skip the wild coho sonelmon
Bot: Sorry, we don't have Skip the wild coho sonelmon. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to h...
[FAILED: Item not found: Sorry, we don't have Skip the wild coho sonelmon. We have Gluten Free Everything Bagel, Sesame Bagel]
User: Replace Jalapeno Bagel With Scottish Salmon
```

### Order Bagel, Iced Coffee then modify

**Type:** modifier_flow
**Session:** `ffe636aa-08d1-4b5c-8dc2-f9f45550fd27`

**Failure:** Item not found: Sorry, we don't have Without ketchup. We have Gluten Free Everything Bagel, Sesame Bagel, French Toa

**Conversation:**
```
User: Can I get a Bagel and a Iced Coffee
Bot: Got it, Bagel and Iced Coffee. For the bagel, what kind of bagel would you like?
User: Also add chicken sausage
Bot: Got it, I've added Side of Chicken Sausage. Now, for your Bagel, what kind of bagel would you like?
User: Without ketchup
Bot: Sorry, we don't have Without ketchup. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more opt...
[FAILED: Item not found: Sorry, we don't have Without ketchup. We have Gluten Free Everything Bagel, Sesame Bagel, French Toa]
User: Actually ketchup instead of whole wheat wrap
```
