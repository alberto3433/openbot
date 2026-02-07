# Plan: Validate Modifiers Against Item Type in Add Handler

## Problem

When user says "add green peppers" to a bagel, the system accepts it even though green peppers are NOT a valid topping for bagels (only for omelettes).

**Root cause:** `config_modification_handler.py:handle_add_modifiers_during_config()` finds matching ingredients globally via `find_matching_ingredients()` but never validates if they're valid for the current item type via `is_valid_modifier_for_item_type()`.

## Current Flow (Buggy)

```
1. User: "add green peppers"
2. find_matching_ingredients("green peppers") → [{"name": "Green Pepper", "category": "topping"}]
3. len(matches) == 1 → add_selection() directly  ← NO VALIDATION!
```

## Fix

Add validation after finding a single match:

```python
if len(matches) == 1:
    match = matches[0]

    # NEW: Validate modifier is allowed for this item type
    if not menu_cache.is_valid_modifier_for_item_type(match["slug"], item.menu_item_type):
        # Return rejection message
        from .checkout_messages import modifier_not_available_for_item
        return StateMachineResult(
            message=modifier_not_available_for_item(match["name"], item.display_name),
            phase=order.phase,
            pending_field=order.pending_field,
        )

    # ... rest of existing code
```

## Files to Modify

1. `orderbot/tasks/config_modification_handler.py` - Add validation in `handle_add_modifiers_during_config()`

## Test Cases

- "add green peppers" to bagel → Rejected: "Sorry, green peppers isn't available for the bagel"
- "add green peppers" to omelette → Accepted (green peppers IS valid for omelettes)
- "add bacon" to bagel → Accepted (bacon IS valid for bagels via Meat attribute)
