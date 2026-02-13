# Fix: "remove the cheese" at customization checkpoint

## Root Cause

In `config_cancellation_handler.py:244-258`, when at `customization_checkpoint`, the handler defers ALL cancel patterns that match an attribute name (returns `None`). This was designed for **declining** optional attributes not yet set (e.g., "no condiments" when the bot offers "You can add Condiments"). But it also catches **removal** of already-set attributes (e.g., "remove the cheese" after the user chose American Cheese).

After deferring, the input cascades through handlers that can't handle removal:
1. `detect_change_request` → no removal patterns → `None`
2. `handle_add_modifiers_during_config` → no "remove" prefix → `None`
3. Falls through to customization checkpoint → `ingredient_fallback` → treats "cheese" as an addition → **adds cheese with qty=1 instead of removing it**

## Fix: Single block in `config_cancellation_handler.py`

**File:** `orderbot/tasks/config_cancellation_handler.py`, lines 244-258

In the checkpoint deferral loop (line 250-258), when `cancel_desc` matches an attribute slug:

- **If the attribute IS already set** on the item (`current_item.has_selection(attr_slug)`): this is a removal request. Handle it directly:
  1. Get display name from the existing selection for the confirmation message
  2. Call `current_item.remove_selection(category=attr_slug)` to clear the selection
  3. Call `safe_recalculate_price()` to fix the price ($13.00 → $11.50)
  4. Get the current config question to re-prompt
  5. Return confirmation like "OK, I've removed the American Cheese. Any more changes? ..."

- **If the attribute is NOT set**: defer as before (return `None`) — it's a decline of an unselected option

No other files need changes. The `remove_selection` method already handles price subtraction, and `safe_recalculate_price` recalculates from scratch. The `cheese_price` key in `attribute_values` is auto-derived and will disappear when the selection is removed.

## Checklist

- [ ] Modify `config_cancellation_handler.py` deferral block (lines 244-258)
- [ ] Verify with test or manual check
