# Plan: Fix "That's It" Not Recognized During Item Configuration

## Problem

When asked "Any more changes?" during item configuration, responding "that's it" is not recognized:

```
Bot: Any more changes to that? You can change Style, Shots, or Decaf.
User: that's it
Bot: Sorry, I didn't catch that. You can add: Style, Shots, or Decaf. What would you like?
```

## Root Cause

**File:** `orderbot/tasks/menu_item_config_handler.py`
**Method:** `handle_customization_checkpoint()` (line 1958)

The method only checks for "negative" patterns (no, nope, nothing) at line 1966-1967:
```python
no_patterns = menu_cache.get_response_patterns("negative")
if any(user_lower == p or user_lower.startswith(p) for p in no_patterns):
```

It does **not** check for "done" patterns (that's it, that's all, I'm done).

## Solution

Add `menu_cache.is_done()` check alongside the negative pattern check.

### Change

**File:** `orderbot/tasks/menu_item_config_handler.py`
**Lines:** 1965-1967

**Current:**
```python
# Check for "no" - user doesn't want to customize
no_patterns = menu_cache.get_response_patterns("negative")
if any(user_lower == p or user_lower.startswith(p) for p in no_patterns):
```

**New:**
```python
# Check for "no" or "done" - user doesn't want to customize
if menu_cache.is_negative(user_lower) or menu_cache.is_done(user_lower):
```

This:
1. Uses the cleaner `is_negative()` helper (handles regex patterns)
2. Adds `is_done()` check for "that's it", "that's all", "I'm done", etc.
3. Both methods already exist and work correctly elsewhere in the codebase

## Testing

```bash
python -m pytest tests/ -v -k "config"
```

Manual test: Order coffee, when asked about changes, say "that's it" - should complete the item.
