# Plan: Add Disambiguation for Multi-Select Modifier Matching

## Problem

When user says "bacon" at the customization checkpoint, all three bacon options (Bacon, Turkey Bacon, Applewood Smoked Bacon) are added instead of asking which one they want.

**Conversation flow showing the bug:**
```
Bot: Any more changes to that? You can add Egg, Cheese, Meat, Toppings, or Condiments.
User: bacon
Bot: Okay, Bacon, Turkey Bacon, Applewood Smoked Bacon added.  ← BUG: should ask which one
```

## Root Cause

The `match_multiple` method in `orderbot/tasks/utils/option_matcher.py` is designed to find ALL matching options for multi-select attributes. This works correctly for inputs like "bacon and eggs" but fails when a single ambiguous term like "bacon" partial-matches multiple options.

**Code path:**
1. `menu_item_config_handler.py:1949` - "bacon" matches "meat" attribute
2. `menu_item_config_handler.py:2006` - Since meat is `multi_select`, calls `_match_multiple_options_from_input`
3. `option_matcher.py:167-181` - "bacon" word-matches all three options containing "bacon"
4. `menu_item_config_handler.py:2008-2026` - All three options are added without disambiguation

## Solution

Detect when user input is a **single term** that **partial-matches multiple options** (without an exact match). In this case, trigger disambiguation instead of adding all matches.

### Changes Required

**File: `orderbot/tasks/utils/option_matcher.py`**

Add a new method `match_multiple_with_disambiguation`:

```python
def match_multiple_with_disambiguation(
    self, user_input: str, options: list[dict]
) -> tuple[list[dict], list[dict]]:
    """
    Match options with disambiguation detection for multi-select attributes.

    Returns:
        (matched_options, disambiguation_candidates) tuple:
        - ([opt1, opt2], []) = multiple distinct matches from explicit input, add all
        - ([opt1], []) = single match, add it
        - ([], [opt1, opt2, opt3]) = single ambiguous term matches multiple, need disambiguation
    """
```

**Logic:**
1. Check if input is a single term (no separators: "and", ",", "&")
2. Check if there's an exact match on any option → return as single match
3. If single term + no exact match + multiple partial matches → return as disambiguation candidates
4. Otherwise return as matched options to add

**File: `orderbot/tasks/menu_item_config_handler.py`**

Update the multi-select handling around line 2005-2026:

```python
if input_type == "multi_select":
    matched_opts, disambiguation = self._option_matcher.match_multiple_with_disambiguation(user_clean, options)

    if disambiguation:
        # Single ambiguous term - ask user to clarify
        return self._ask_disambiguation_for_options(
            item, order, attr_slug, disambiguation, user_input
        )

    if matched_opts:
        # Clear matches - add them all
        # ... existing add logic ...
```

Add disambiguation question method:
```python
def _ask_disambiguation_for_options(
    self, item: MenuItemTask, order: OrderTask, attr_slug: str,
    candidates: list[dict], original_input: str
) -> StateMachineResult:
    """Ask user to clarify which option they meant."""
    options_list = ", ".join(c["display_name"] for c in candidates)
    order.pending_field = f"{item.menu_item_type}:{attr_slug}"
    order.pending_item_options = [c["display_name"] for c in candidates]
    return StateMachineResult(
        message=f"Which {attr_slug} would you like? {options_list}",
        order=order,
    )
```

## Test Cases

1. **Single ambiguous term → disambiguation**
   - Input: "bacon" with options [Bacon, Turkey Bacon, Applewood Smoked Bacon]
   - Expected: "Which meat would you like? Bacon, Turkey Bacon, Applewood Smoked Bacon"

2. **Explicit multiple items → add all**
   - Input: "bacon and turkey bacon"
   - Expected: Both added without disambiguation

3. **Exact match → add directly**
   - Input: "Bacon" (exact match on display_name)
   - Expected: Only "Bacon" added, no disambiguation

4. **Single unambiguous term → add directly**
   - Input: "turkey bacon" (only matches one option)
   - Expected: "Turkey Bacon" added directly

## Files to Modify

1. `orderbot/tasks/utils/option_matcher.py` - Add `match_multiple_with_disambiguation` method
2. `orderbot/tasks/menu_item_config_handler.py` - Handle disambiguation in multi-select flow, add `_ask_disambiguation_for_options` method
