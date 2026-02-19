# Chaos Monkey Test Failures

**Generated:** 2026-02-17T20:21:07.964796
**Session Start:** 2026-02-17T20:10:42.994521
**Total Tests:** 120
**Passed:** 117
**Failed:** 3

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 2 |
| Other | 1 |

## System Error (2 failures, 1 distinct patterns)

### Realistic order: Hot Coffee, The Delancey Omelette with Corned Beef (+1 similar)

**Count:** 2
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `dc554dee-b35c-407d-bd1d-78de91b6dc31`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: Can I get a Hot Coffee and a The Delancey Omelette with Corned Beef
Bot: Got it, Hot Coffee and The Delancey Omelette with Corned Beef. For the Hot Coffee, what size?
User: Small
Bot: Got it, Small. For the Hot Coffee, any milk, sweetener, or syrup?
User: I'm good
Bot: For the Hot Coffee, would you like an espresso shot?
User: no
Bot: Got it, Hot Coffee and The Delancey Omelette with Corned Beef. For the The Delancey Omelette with Corned Beef, would you like a bagel or fruit salad with it?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Realistic order: The Delancey Omelette with Pastrami, Macchiato

## Other (1 failures, 1 distinct patterns)

### Realistic order: Ham

**Count:** 1
**Pattern:** `realistic_order | failed_to_send_message`
**Type:** realistic_order
**Session:** `6c8e327d-2148-4d98-ade7-321c57f4f5c3`

**Failure:** Failed to send message

**Conversation:**
```
User: Can I get a Ham
Bot: Got it, for the Egg Sandwich. What kind of bread?
User: plain
[FAILED: Failed to send message]
```
