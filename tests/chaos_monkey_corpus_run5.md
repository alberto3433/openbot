# Chaos Monkey Test Failures

**Generated:** 2026-02-19T10:10:58.568455
**Session Start:** 2026-02-19T09:55:03.604090
**Total Tests:** 200
**Passed:** 170
**Failed:** 30

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 15 |
| Other | 7 |
| Menu Item Not Found | 7 |
| Item Recognition | 1 |

## System Error (15 failures, 4 distinct patterns)

### Corpus [addon_during_config]: Answer bread question with toasted in same breath (+7 similar)

**Count:** 8
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `973be9d2-2ef0-4f63-a21c-819da77ecaf9`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'll have a bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: Whole Wheat Bagel toasted
Bot: Got it, toasted. What kind of bagel?
User: sesame
Bot: I found a few options matching that. Did you mean Sesame Bagel or Sesame Sourdough Bagel?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [inline_spec]: Fully specified bagel in one shot
- Corpus [context_reference]: Request toasting via context reference
- Corpus [batch_order]: Two different bagels by bread type
- Corpus [batch_order]: Two different bagels by bread type
- Corpus [shorthand]: Modifier on a bread type
- Corpus [shorthand]: Bread type with modifier, no verb
- Corpus [context_reference]: Order the same as a previous item

### Ask for recommendations (+4 similar)

**Count:** 5
**Pattern:** `menu_inquiry | system_error`
**Type:** menu_inquiry
**Session:** `16f3d443-4d0f-4290-85c6-e26a3a1be5c1`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: What do people usually order?
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Ask about dietary options
- Ask about dietary options
- General menu inquiry
- Ask for recommendations

### Order Peanut Butter Cookie and Apple Cinnamon Muffin

**Count:** 1
**Pattern:** `multi_item | system_error`
**Type:** multi_item
**Session:** `78e7b4de-ce94-4394-8dc9-570792bc5742`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'll have a Peanut Butter Cookie please and thank you
Bot: Got it, Peanut Butter Cookie. Anything else?
User: Also a Apple Cinnamon well Muffin
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

### Realistic order: The Columbus BEC Omelette

**Count:** 1
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `ec837f62-3462-4a84-a0b0-824a9bab04ab`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'd hmm like a The Columbus BEC Omelette
Bot: Got it, for the The Columbus BEC Omelette with Swiss Cheese, Avocado, Turkey Bacon, and Egg White. Would you like a bagel or fruit salad with it?
User: bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: sesame
Bot: I found a few options matching that. Did you mean Sesame Bagel or Sesame Sourdough Bagel?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Other (7 failures, 1 distinct patterns)

### Corpus [quantity]: Multiple bagels of a specific bread (+6 similar)

**Count:** 7
**Pattern:** `corpus_order | failed_to_send_message`
**Type:** corpus_order
**Session:** `4eb4ab97-1179-4aaa-b433-630a749ff2dd`

**Failure:** Failed to send message

**Conversation:**
```
User: three Jalapeno Bagel bagels
[FAILED: Failed to send message]
```

**Other instances:**
- Corpus [quantity]: Multiple bagels of a specific bread
- Corpus [quantity]: Multiple bagels of a specific bread
- Corpus [quantity]: Order a large quantity shorthand
- Corpus [quantity]: Multiple bagels of a specific bread
- Corpus [quantity]: Order a large quantity shorthand
- Corpus [quantity]: Multiple bagels of a specific bread

## Menu Item Not Found (7 failures, 2 distinct patterns)

### Corpus [correction]: Add a modifier after the initial order (+5 similar)

**Count:** 6
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `863dd2ea-805d-4b53-8330-6f4ff7c2cebf`

**Failure:** Item not found: Sorry, we don't have oh and can you add earl gray. We have French Toast Bagel, Plain Bagel, Sesame B

**Conversation:**
```
User: I'd like a Tuna Salad
Bot: Got it, for the Tuna Salad Sandwich with Lettuce, Beefsteak Tomatoes, and Tuna Salad. What kind of bread?
User: oh and can you add earl gray
Bot: Sorry, we don't have oh and can you add earl gray. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more options?
[FAILED: Item not found: Sorry, we don't have oh and can you add earl gray. We have French Toast Bagel, Plain Bagel, Sesame B]
```

**Other instances:**
- Corpus [addon_during_config]: Decline current question but add something else
- Corpus [correction]: Add a modifier after the initial order
- Corpus [addon_during_config]: Decline current question but add something else
- Corpus [addon_during_config]: Answer size question with iced preference
- Corpus [addon_during_config]: Answer yes and add a modifier in the same turn

### Corpus [correction]: Remove a modifier after adding it

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `20e926f5-690c-4a0c-9331-40adb227eca9`

**Failure:** Item not found: I couldn't find hazelnut syrup in your order. What would you like to do?

**Conversation:**
```
User: a Two Deviled Eggs with hazelnut syrup
Bot: Got it, Two Deviled Eggs. Anything else?
User: actually, no hazelnut syrup
Bot: I couldn't find hazelnut syrup in your order. What would you like to do?
[FAILED: Item not found: I couldn't find hazelnut syrup in your order. What would you like to do?]
```

## Item Recognition (1 failures, 1 distinct patterns)

### Order Ham

**Count:** 1
**Pattern:** `single_item | modifier_not_in_order`
**Type:** single_item
**Session:** `1389518c-e312-4c89-9a28-587ab44fcb7e`

**Failure:** Expected item 'Ham' not in cart. Cart contains: []

**Conversation:**
```
User: Just a Ham
Bot: For ham, we have the Side of Ham. Would you like one?
[FAILED: Expected item 'Ham' not in cart. Cart contains: []]
```
