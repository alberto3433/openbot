# Chaos Monkey Test Failures

**Generated:** 2026-02-17T20:31:42.449374
**Session Start:** 2026-02-17T20:21:33.809375
**Total Tests:** 120
**Passed:** 116
**Failed:** 4

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 4 |

## System Error (4 failures, 1 distinct patterns)

### Realistic order: Jalapeno Cream Cheese Sandwich, The Lexington Omelette (+3 similar)

**Count:** 4
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `9a9abf13-3e58-40e5-9d2b-38627237c661`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'll have a Jalapeno Cream Cheese Sandwich and a The Lexington Omelette
Bot: Got it, Jalapeno Cream Cheese Sandwich and The Lexington Omelette. For the Jalapeno Cream Cheese Sandwich, what kind of bread?
User: Plain Sourdough Bagel
Bot: Got it, Plain Sourdough Bagel. For the Jalapeno Cream Cheese Sandwich, toast it?
User: no
Bot: For the Jalapeno Cream Cheese Sandwich, scoop it?
User: no
Bot: Any more changes? Any more condiments?
User: no thanks
Bot: Got it, Jalapeno Cream Cheese Sandwich and The Lexington Omelette. For the The Lexington Omelette, would you like a bagel or fruit salad with it?
User: fruit salad
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Realistic order: The Columbus BEC Omelette, Jalapeno Cream Cheese Sandwich
- Realistic order: The Delancey Omelette with Pastrami
- Realistic order: The Leo Omelette
