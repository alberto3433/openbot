# Fix: "Change item" during config should replace menu item, not just attribute

## Problem

When configuring a Bialy and user says "make it a cinnamon raisin bagel instead", the system:
- **Current**: Changes the `bread` attribute from "bialy" to "cinnamon_raisin_bagel" (via `handle_can_you_make_it`)
- **Expected**: Replaces the Bialy with a Cinnamon Raisin Bagel (new menu item with correct price, type, defaults)

## Root Cause

In `handle_can_you_make_it` (config_modification_handler.py):
1. `parse_can_you_make_it` extracts modifier "cinnamon raisin bagel instead"
2. `find_attr_option_match` fuzzy-matches "cinnamon_raisin_bagel" as a bread attribute option
3. Attribute change is applied → Bialy stays with wrong bread attribute
4. Item replacement steps never reached

Key challenge: "Cinnamon Raisin Bagel" is NOT a menu item — "Bagel" is the menu item and "cinnamon_raisin_bagel" is a bread attribute option. `lookup_menu_items` also fails due to 50% similarity threshold ("bagel" is only 23% of "cinnamon raisin bagel").

## Fix

**File**: `orderbot/tasks/config_modification_handler.py`

Added `_try_cross_type_replacement` as step 0 in `handle_can_you_make_it`, before attribute matching. Uses the deterministic parser (`parse_open_input`) to check if the cleaned modifier text parses as an item of a different type. If so, removes the current item and delegates to `taking_items_handler` for full parsing with attribute extraction.

Guards:
- Requires parser to find a concrete menu item (`item_name` not None) — prevents false positives like "everything" being misinterpreted
- Only triggers for single-item parses of a different item type

### Checklist

- [x] Add cross-type replacement check before attribute change in `handle_can_you_make_it`
- [x] Use `parse_open_input` (not `lookup_menu_items`) to detect item type from compound names
- [x] Guard against false positives (bare attribute values like "everything", "plain")
- [x] Test: "make it a cinnamon raisin bagel" during Bialy config → switches item
- [x] Test: "make it everything" during bagel config → still changes attribute (no false positive)
- [x] Full test suite passes (2049 passed, 1 pre-existing failure unrelated)
