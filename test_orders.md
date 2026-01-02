# Test Orders for Zucker's Bot

Use these scenarios to test the bot via voice (VAPI) or web chat.

---

## Simple Orders

### 1. Basic Sandwich
> "I'll have The Classic BEC"

### 2. Basic Coffee
> "Can I get a small coffee"

### 3. Simple Combo
> "I want The Classic and a large coffee"

---

## Coffee Variations

### 4. Coffee with Free Modifiers
> "Medium coffee, light with Splenda"

### 5. Coffee with Upcharge
> "Small coffee with oat milk and vanilla syrup"

### 6. Complex Coffee
> "Large dark coffee with almond milk, hazelnut syrup, and an extra shot"

### 7. Coffee with Iced Modifier
> "I'll take an iced coffee, large"

---

## Multi-Item Orders

### 8. Family Order
> "I need three Classic BECs, two small coffees, and one large coffee with vanilla"

### 9. Breakfast Spread
> "Give me The Avocado Toast, a lox bagel, and two coffees - one small black, one medium with oat milk"

---

## Challenging Scenarios

### 10. Vague Request
> "I want a bagel"
(Bot should ask what kind or suggest options)

### 11. Item Not on Menu
> "Can I get a hamburger"
(Bot should politely explain it's not available and suggest alternatives)

### 12. Changing Mind
> "I want The Classic... actually no, make that The Avocado Toast"

### 13. Modification Request
> "I'll have The Classic BEC but can you add bacon"

### 14. Unclear Coffee Order
> "Coffee with milk"
(Bot should ask what size and clarify milk type)

### 15. Asking About Ingredients
> "What's on The Classic BEC?"

### 16. Dietary Question
> "Do you have anything gluten-free?"

---

## Order Flow Challenges

### 17. Interrupting Flow
> Order a sandwich, then when asked about drinks say: "Wait, what sandwiches do you have again?"

### 18. Delivery Order
> "I want The Classic for delivery to 123 Main Street, Apartment 4B"

### 19. Email Payment Link
> Complete an order and when asked about payment say: "Email me the link at test@example.com"

### 20. Rapid Fire Order
> "Two Classic BECs, one Avocado Toast, three small coffees - two with vanilla syrup and one black, and one large iced coffee with oat milk. That's for pickup under the name Johnson."

---

## Edge Cases

### 21. Just Browsing
> "I'm just looking at the menu, what do you recommend?"

### 22. Price Check
> "How much is a large coffee with almond milk?"

### 23. Repeat Order (if returning customer)
> "I'll have my usual" or "Same as last time"

### 24. Cancel Mid-Order
> Start ordering, then say: "Actually, never mind. Cancel that."

### 25. Multiple Modifications
> "Small coffee, no wait make it medium, with vanilla, actually hazelnut, and oat milk"

---

## Expected Success Metrics

- [ ] All orders correctly captured in database
- [ ] Coffee modifiers applied with correct pricing
- [ ] Multi-item orders have all items
- [ ] Customer name and contact info saved
- [ ] Delivery orders have address captured
- [ ] Bot handles "not on menu" gracefully
- [ ] Bot asks clarifying questions when needed
- [ ] Bot remembers context within conversation
