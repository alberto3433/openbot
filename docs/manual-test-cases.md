# Manual Test Cases for Order Chatbot

## Overview
These test cases cover the full ordering flow including edge cases, error handling, and different user paths. Each test case should be run as a fresh conversation.

---

## Basic Ordering Flow

### Test 1: Simple Bagel Pickup Order
**Steps:**
1. "plain bagel toasted"
2. "cream cheese"
3. "that's all"
4. "pickup"
5. "John"
6. "yes"
7. "pay in store"

**Expected:** Order completes successfully with bagel, toasted, cream cheese, pickup.

---

### Test 2: Bagel with No Spread
**Steps:**
1. "everything bagel toasted with nothing on it"
2. "no" (nothing else)
3. "pickup"
4. "Sarah"
5. "yes"
6. "in store"

**Expected:** Order completes with "nothing on it" noted, no spread questions asked.

---

### Test 3: Coffee Order Only
**Steps:**
1. "medium iced coffee"
2. "no milk"
3. "done"
4. "pickup"
5. "Mike"
6. "yes"
7. "pay in store"

**Expected:** Coffee order with size and iced captured.

---

### Test 4: Soda Order (Skip Configuration)
**Steps:**
1. "coke"
2. "that's it"
3. "pickup"
4. "Lisa"
5. "yes"
6. "in store"

**Expected:** Coke added without asking size/hot/iced questions.

---

## Order Type Upfront

### Test 5: Pickup Order Mentioned Upfront
**Steps:**
1. "I'd like to place a pickup order"
2. "plain bagel toasted with butter"
3. "that's all"
4. (Should skip pickup/delivery question)
5. "Tom"
6. "yes"
7. "in store"

**Expected:** Bot acknowledges pickup, skips delivery question at checkout.

---

### Test 6: Delivery Order Mentioned Upfront
**Steps:**
1. "I want to place a delivery order"
2. "sesame bagel not toasted"
3. "no spread"
4. "done"
5. "123 Main Street"
6. "Amy"
7. "yes"
8. "email"
9. "amy@test.com"

**Expected:** Bot acknowledges delivery, asks for address at checkout.

---

### Test 7: Pickup Order with Items in Same Message
**Steps:**
1. "pickup order, I'll have two plain bagels"
2. "both toasted"
3. "cream cheese on both"
4. "that's it"
5. "Dave"
6. "yes"
7. "in store"

**Expected:** Order type and items captured from single message.

---

## Notification Methods

### Test 8: Email Notification Flow
**Steps:**
1. "egg bagel toasted"
2. "no spread"
3. "done"
4. "pickup"
5. "Hank"
6. "yes"
7. "email"
8. "hank@example.com"

**Expected:** Email captured, order completes with confirmation message.

---

### Test 9: Text Notification Flow
**Steps:**
1. "plain bagel not toasted with butter"
2. "nothing else"
3. "pickup"
4. "Jane"
5. "yes"
6. "text"
7. "555-123-4567"

**Expected:** Phone captured, order completes with confirmation message.

---

### Test 10: Contact Info Provided Inline with Choice
**Steps:**
1. "everything bagel toasted"
2. "scallion cream cheese"
3. "that's all"
4. "pickup"
5. "Bob"
6. "yes"
7. "text me at 732-555-0101"

**Expected:** Phone number extracted from message, no follow-up question needed.

---

### Test 11: Email Provided Inline
**Steps:**
1. "cinnamon raisin bagel toasted with butter"
2. "done"
3. "pickup"
4. "Carol"
5. "yes"
6. "email me at carol@gmail.com"

**Expected:** Email extracted from message, no follow-up question needed.

---

## Multi-Item Orders

### Test 12: Multiple Bagels with Different Configurations
**Steps:**
1. "two bagels"
2. "plain and everything"
3. "toast both"
4. "butter on the first, cream cheese on the second"
5. "that's all"
6. "pickup"
7. "Pat"
8. "yes"
9. "in store"

**Expected:** Two distinct bagels with different spreads.

---

### Test 13: Bagel and Coffee Together
**Steps:**
1. "plain bagel toasted with cream cheese and a small hot coffee"
2. "no milk"
3. "done"
4. "pickup"
5. "Sam"
6. "yes"
7. "in store"

**Expected:** Both items captured, coffee configured.

---

### Test 14: Multiple Quantities
**Steps:**
1. "three plain bagels toasted"
2. "butter on all"
3. "and two cokes"
4. "that's it"
5. "pickup"
6. "Group Order"
7. "yes"
8. "in store"

**Expected:** Quantities captured correctly (3 bagels, 2 cokes).

---

## Checkout Modifications

### Test 15: Add Item During Confirmation
**Steps:**
1. "plain bagel toasted"
2. "no spread"
3. "done"
4. "pickup"
5. "Alex"
6. (At confirmation) "actually add a coffee"
7. "medium"
8. "hot"
9. "yes" (confirm updated order)
10. "in store"

**Expected:** Coffee added, returns to confirmation with updated order.

---

### Test 16: Remove Item During Confirmation
**Steps:**
1. "plain bagel and a coke"
2. "toasted"
3. "butter"
4. "done"
5. "pickup"
6. "Kim"
7. (At confirmation) "remove the coke"
8. "yes"
9. "in store"

**Expected:** Coke removed, order completes with just bagel.

---

## Delivery Orders

### Test 17: Full Delivery Flow
**Steps:**
1. "everything bagel toasted with veggie cream cheese"
2. "that's all"
3. "delivery"
4. "456 Oak Avenue, Apt 2B"
5. "Chris"
6. "yes"
7. "email"
8. "chris@example.com"

**Expected:** Address captured, delivery noted in confirmation.

---

### Test 18: Delivery with Incomplete Address
**Steps:**
1. "plain bagel"
2. "toasted"
3. "butter"
4. "done"
5. "delivery"
6. "Main Street" (incomplete)

**Expected:** Bot asks for complete address or apartment number.

---

## Edge Cases

### Test 19: Empty Order - Done Without Items
**Steps:**
1. "that's all"

**Expected:** Bot asks what they'd like to order (can't checkout with no items).

---

### Test 20: Unclear Input
**Steps:**
1. "asdfghjkl"

**Expected:** Bot asks for clarification politely.

---

### Test 21: Change Mind on Notification Method
**Steps:**
1. "sesame bagel toasted with butter"
2. "done"
3. "pickup"
4. "Robin"
5. "yes"
6. "text"
7. "actually, email instead"
8. "robin@test.com"

**Expected:** Switches to email flow gracefully.

---

### Test 22: Cancel Order Mid-Flow
**Steps:**
1. "plain bagel"
2. "toasted"
3. "cancel" or "start over"

**Expected:** Order cancelled, fresh start offered.

---

### Test 23: Invalid Email Format
**Steps:**
1. "plain bagel toasted"
2. "no spread"
3. "done"
4. "pickup"
5. "Test"
6. "yes"
7. "email"
8. "notanemail"

**Expected:** Bot asks for valid email address.

---

### Test 24: Invalid Phone Format
**Steps:**
1. "everything bagel"
2. "toasted"
3. "cream cheese"
4. "done"
5. "pickup"
6. "Test"
7. "yes"
8. "text"
9. "123"

**Expected:** Bot asks for valid phone number.

---

## Speed Menu Items

### Test 25: Speed Menu Bagel Order
**Steps:**
1. "The Classic"
2. "toasted"
3. "that's all"
4. "pickup"
5. "Fan"
6. "yes"
7. "in store"

**Expected:** Speed menu item recognized, only asks toasted preference.

---

## Challenging Natural Orders

These test cases simulate realistic phone orders that challenge parsing and order handling.

### Test 26: Split Bagel Order
**Input:**
> "Can I get two everything bagels - one with butter and one with cream cheese, both toasted."

**Expected:**
- Two separate bagel items created
- First bagel: everything, toasted, butter
- Second bagel: everything, toasted, cream cheese
- No follow-up questions about toasting or spread needed

---

### Test 27: Quick Correction (Iced to Hot)
**Input:**
> "I'll have a plain bagel with scallion cream cheese and a medium iced latte. Actually make that a hot latte."

**Expected:**
- Bagel: plain, scallion cream cheese (should ask toasted)
- Latte: medium, hot (not iced) - correction applied
- Single latte in cart, not two

---

### Test 28: Vague Coffee Order
**Input:**
> "Just a coffee with a little bit of milk and a sesame bagel with butter."

**Expected:**
- Coffee added (may need to ask for size and type)
- Milk preference captured as "a little" or similar
- Bagel: sesame, butter (should ask toasted)

---

### Test 29: Add-On Converts to Sandwich
**Input:**
> "I'll take an everything bagel with cream cheese, and can you throw some bacon and egg on there too?"

**Expected:**
- Single bagel item with cream cheese, bacon, and egg
- Price recalculates to sandwich price (not just spread bagel)
- Should ask toasted preference

---

### Test 30: Menu Item with Bagel Swap
**Input:**
> "Let me get The Classic BEC but on a wheat bagel instead of plain, and a small black coffee."

**Expected:**
- The Classic BEC recognized as menu item
- Bagel type changed to wheat
- Coffee: small, black (no milk)
- Should ask toasted preference for BEC

---

## Test Tracking

| Test # | Status | Date | Notes |
|--------|--------|------|-------|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
| 9 | | | |
| 10 | | | |
| 11 | | | |
| 12 | | | |
| 13 | | | |
| 14 | | | |
| 15 | | | |
| 16 | | | |
| 17 | | | |
| 18 | | | |
| 19 | | | |
| 20 | | | |
| 21 | | | |
| 22 | | | |
| 23 | | | |
| 24 | | | |
| 25 | | | |
| 26 | | | |
| 27 | | | |
| 28 | | | |
| 29 | | | |
| 30 | | | |

---

## Notes

- Run each test as a fresh conversation (new session)
- Mark status as: PASS, FAIL, or BLOCKED
- Add notes for any unexpected behavior
- Report bugs with the conversation transcript
