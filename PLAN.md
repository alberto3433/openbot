# Fix: "salt and pepper" Matching Wrong Attribute

## Problem

User says `"salt and pepper"` in response to "Any more changes?"

**Expected:** Salt + Black Pepper added (from Condiments)
**Actual:** Onion, Pepper & Caper Relish added (from Toppings)

## Root Cause

Two different code paths exist:

| Path | Used When | Result for "salt and pepper" |
|------|-----------|------------------------------|
| `extract_attribute_values()` | Initial order parsing | ✅ Correct: `{condiments: [salt, black_pepper]}` |
| `_match_multiple_options_from_input()` | Checkpoint responses | ❌ Wrong: matches relish in Toppings |

The checkpoint handler uses `_try_direct_option_match()` which iterates attributes and returns on FIRST match. "pepper" matches "Onion, Pepper & Caper Relish" via reverse matching before Condiments is checked.

## Solution

**Use `extract_attribute_values()` in the checkpoint handler** instead of the per-attribute matching loop.

This is the cleanest fix because:
1. Already works correctly for "salt and pepper"
2. Consistent behavior between initial parsing and checkpoint responses
3. Has proper longest-match-first logic and must_match handling

## Implementation

**File:** `menu_item_config_handler.py`
**Method:** `_try_direct_option_match()` (line ~2347)

Replace the per-attribute loop with:
1. Call `extract_attribute_values(user_input, item_type)`
2. Apply any matched attributes to the item
3. Return result if matches found

## Testing

```
User: plain bagel toasted not scooped no spread
Bot: Any more changes to that? You can add Egg, Cheese, Meat, Toppings, or Condiments.
User: salt and pepper
Bot: Okay, Salt and Black Pepper added. Any more changes to that?
```
