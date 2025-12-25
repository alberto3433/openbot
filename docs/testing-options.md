# Options for Testing New vs Returning Customer Flow

Since you only have one phone to test with, here are options to reset your customer data and simulate a "new customer" call:

---

## Quick/Manual Approaches

### 1. Direct SQL Delete
Run a query to delete your orders and sessions by phone number. This makes you appear as a new customer on the next call.

```sql
-- Run against Neon PostgreSQL
DELETE FROM orders WHERE phone LIKE '%7328139409';
DELETE FROM chat_sessions WHERE caller_id LIKE '%7328139409';
DELETE FROM session_analytics WHERE customer_phone LIKE '%7328139409';
```

### 2. Admin Endpoint (Recommended)
Add a simple `/admin/reset-customer?phone=XXX` endpoint that clears orders and sessions for a phone number.

Usage:
```
https://8mtpznn4nh.us-east-1.awsapprunner.com/admin/reset-customer?phone=7328139409
```

It would:
- Delete orders matching that phone number
- Delete chat sessions matching that phone number
- Delete session analytics for that phone number
- Return a simple JSON response confirming the reset

Then your next call would be treated as a brand new customer. Call again after placing an order, and you'd be recognized as returning.

### 3. Admin UI Button
Add a "Reset Customer" button in the existing admin pages (admin_orders.html). Enter a phone number, click reset, and it clears all data for that customer.

---

## More Sophisticated Testing Options

### 4. Voice Command
Teach the bot to respond to phrases like:
- "reset my account"
- "pretend I'm a new customer"
- "testing new customer"

This would clear the session's returning_customer data mid-call, allowing you to test both flows in the same call.

### 5. Test Mode Toggle
Add a toggle in the admin UI that puts the system in "test mode" where it ignores returning customer data for all calls. Useful for repeatedly testing the new customer flow.

### 6. Phone Number Suffix Variation
Modify the phone matching logic to be configurable. In test mode, require exact match instead of last-10-digits match. Then you could use *67 or other caller ID tricks to appear as different numbers.

---

## My Recommendation

**Option 2 (Admin Endpoint)** is the cleanest and quickest to implement:

1. Simple to use - just hit a URL in your browser before testing
2. No UI changes needed
3. Protected by existing admin auth
4. Can be called programmatically if needed
5. Quick to implement (15-20 lines of code)

Would you like me to implement the admin endpoint?
