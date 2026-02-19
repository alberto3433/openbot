# Chaos Monkey Test Failures

**Generated:** 2026-02-19T16:35:44.493602
**Session Start:** 2026-02-19T16:30:10.650161
**Total Tests:** 60
**Passed:** 44
**Failed:** 16

---

## Summary by Category

| Category | Count |
|----------|-------|
| System Error | 10 |
| Menu Item Not Found | 6 |

## System Error (10 failures, 4 distinct patterns)

### Ask for recommendations (+3 similar)

**Count:** 4
**Pattern:** `menu_inquiry | system_error`
**Type:** menu_inquiry
**Session:** `77b6b713-55f6-46ce-b968-6eb490120b8c`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: What do people usually order?
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Ask about soups
- General menu inquiry
- Ask about beverages

### Corpus [addon_during_config]: Answer bread question with modifier attached (+2 similar)

**Count:** 3
**Pattern:** `corpus_order | system_error`
**Type:** corpus_order
**Session:** `717ac001-61bf-42c9-9a96-75963a96ea65`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: a bagel please
Bot: Got it, for the Bagel. What kind of bagel?
User: Gluten Free Wrap with muenster
Bot: We have Gluten Free Plain Bagel, Gluten Free Sesame Bagel, Gluten Free Cinnamon Raisin Bagel, Gluten Free Everything Bagel, or Gluten Free Bagel. Which would you like?
User: no
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Corpus [context_reference]: Order the same as a previous item
- Corpus [inline_spec]: Order a bagel with bread type and toasted inline

### Realistic order: The Delancey Omelette with Corned Beef, Pastrami Salmon (+1 similar)

**Count:** 2
**Pattern:** `realistic_order | system_error`
**Type:** realistic_order
**Session:** `4961d58e-3ceb-43c0-8d5a-5f8aac3a8785`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: basically I'd like a The Delancey Omelette with Corned Beef and also a Pastrami Salmon
Bot: Got it, for the The Delancey Omelette with Corned Beef with Swiss Cheese, Sauteed Onions, Breakfast Potato Latke, Corned Beef, Egg, Pastrami Salmon, and Corned Beef. Would you like a bagel or fruit sa...
User: bagel
Bot: Got it, for the Bagel. What kind of bagel?
User: everything
Bot: I found a few options matching that. Did you mean Everything Bagel, Whole Wheat Everything Bagel, or Everything Sourdough Bagel?
User: no thanks
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

**Other instances:**
- Realistic order: Snapple Peach Tea, The Lexington Omelette

### Cancel order

**Count:** 1
**Pattern:** `cart_ops | system_error`
**Type:** cart_ops
**Session:** `3f0d6ace-2efd-49a3-bd57-b1dcbc858c84`

**Failure:** System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.

**Conversation:**
```
User: I'll have a Potato Salad
Bot: Got it, Potato Salad. Anything else?
User: Start over
Bot: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.
[FAILED: System error in response: I'm sorry, I'm having trouble processing your request right now. Please try again in a moment.]
```

## Menu Item Not Found (6 failures, 3 distinct patterns)

### Corpus [addon_during_config]: Answer size question with iced preference (+3 similar)

**Count:** 4
**Pattern:** `corpus_order | item_not_recognized`
**Type:** corpus_order
**Session:** `235c6605-96bf-452e-a28b-63ec2dfa307f`

**Failure:** Item not found: Sorry, we don't have Small iced. We have 1/4 lb or 1 lb.

**Conversation:**
```
User: a American Cheese please um
Bot: Got it, for the American Cheese with 1/4 lb. How much? 1/4 lb? 1 lb?
User: Small iced please
Bot: Sorry, we don't have Small iced. We have 1/4 lb or 1 lb.
[FAILED: Item not found: Sorry, we don't have Small iced. We have 1/4 lb or 1 lb.]
```

**Other instances:**
- Corpus [addon_during_config]: Answer bread question with modifier attached
- Corpus [correction]: Switch to a different item entirely
- Corpus [addon_during_config]: Answer yes and add a modifier in the same turn

### Change The Truffled Egg quantity to 5

**Count:** 1
**Pattern:** `cart_ops | item_not_recognized`
**Type:** cart_ops
**Session:** `73947aed-92e9-4488-aa96-f66b20ba34c9`

**Failure:** Item not found: Sorry, we don't have basically Make it five The Truffled Eggs. We have French Toast Bagel, Plain Bag

**Conversation:**
```
User: so I'll have a The Truffled Egg
Bot: Got it, for the The Truffled Egg with Egg, Swiss Cheese, Truffle Cream Cheese, and Sauteed Mushrooms. What kind of bread?
User: basically Make it five The Truffled Eggs
Bot: Sorry, we don't have basically Make it five The Truffled Eggs. We have French Toast Bagel, Plain Bagel, Sesame Bagel, Bialy, and Flagel, and more. Do you want one of these or do you want to hear more ...
[FAILED: Item not found: Sorry, we don't have basically Make it five The Truffled Eggs. We have French Toast Bagel, Plain Bag]
```

### Corpus [addon_during_config]: Answer bread question with modifier attached

**Count:** 1
**Pattern:** `corpus_order | modifier_not_in_order`
**Type:** corpus_order
**Session:** `0d44268b-0320-4588-b7d2-bca030e1231f`

**Failure:** Item not found: I couldn't find bread with skim and in your order. What would you like to do?

**Conversation:**
```
User: a bagel please um
Bot: Got it, for the Bagel. What kind of bagel?
User: No Bread with skim please and thank you
Bot: I couldn't find bread with skim and in your order. What would you like to do?
[FAILED: Item not found: I couldn't find bread with skim and in your order. What would you like to do?]
```
