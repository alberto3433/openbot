# Chaos Monkey Test Failures

**Generated:** 2026-02-07T18:45:54.082033
**Session Start:** 2026-02-07T18:43:35.266653
**Total Tests:** 10
**Passed:** 7
**Failed:** 3

---

## Summary by Category

| Category | Count |
|----------|-------|
| Menu Item Not Found | 3 |

## Menu Item Not Found

### Order The Alton Brown, Pepper Jack Cheese Sandwich then modify

**Type:** modifier_flow
**Session:** `cea8a2df-8d63-407a-8222-62faf772d959`

**Failure:** Item not found: Sorry, we don't have Hold the swiss. We have Gluten Free Everything Bagel, Sesame Bagel, French Toas

**Conversation:**
```
User: Can I get a The Alton Brown and a Pepper Jack Cheese Sandwich
Bot: Got it, The Alton Brown and Pepper Jack Cheese Sandwich. For the the alton brown, what kind of bagel would you like?
User: I'd like swiss on that
Bot: Let's finish with your The Alton Brown, Smoked Trout, Avocado, Onion Pepper & Caper Relish, Plain Cream Cheese first. What kind of bagel would you like?
User: Hold the swiss
Bot: Sorry, we don't have Hold the swiss. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear more opti...
[FAILED: Item not found: Sorry, we don't have Hold the swiss. We have Gluten Free Everything Bagel, Sesame Bagel, French Toas]
User: With whitefish salad please
```

### Order Sable Sandwich, Chicken Salad Sandwich then modify

**Type:** modifier_flow
**Session:** `49adecbf-d9ea-41ca-a469-0c064fb61696`

**Failure:** Item not found: Sorry, we don't have No grape jelly packet. We have Gluten Free Everything Bagel, Sesame Bagel, Fren

**Conversation:**
```
User: I'll have a Sable Sandwich and a Chicken Salad Sandwich
Bot: Got it, Sable Sandwich and Chicken Salad Sandwich. For the sable sandwich, what kind of bagel would you like?
User: Add grape jelly packet to that
Bot: Sure, I've added Grape Jelly. What kind of bagel would you like?
User: No grape jelly packet please
Bot: Sorry, we don't have No grape jelly packet. We have Gluten Free Everything Bagel, Sesame Bagel, French Toast Bagel, Bialy, and Poppy Bagel, and more. Do you want one of these or do you want to hear mo...
[FAILED: Item not found: Sorry, we don't have No grape jelly packet. We have Gluten Free Everything Bagel, Sesame Bagel, Fren]
User: With gluten free sesame bagel please
```

### Order Tofu Vegetable Sandwich, The Reuben then modify

**Type:** modifier_flow
**Session:** `12d5cc1e-ec1a-4e20-b672-fd51f75899fb`

**Failure:** Item not found: Got it, Pastrami added. Couldn't find: can, you, and add.. Any more changes? You can add Condiments.

**Conversation:**
```
User: I'd like a Tofu Vegetable Sandwich and also a The Reuben
Bot: Got it, Tofu Vegetable Sandwich and The Reuben. For the tofu vegetable sandwich, what kind of bagel would you like?
User: Can you add rye
Bot: Got it, Rye. For the tofu vegetable sandwich, would you like it toasted?
User: No rye please
Bot: Any more changes? You can add Condiments.
User: Can you add pastrami
Bot: Got it, Pastrami added. Couldn't find: can, you, and add.. Any more changes? You can add Condiments.
[FAILED: Item not found: Got it, Pastrami added. Couldn't find: can, you, and add.. Any more changes? You can add Condiments.]
```
