# Plan: Rollback Attribute-Context Type Switch Changes

## Analysis

Comparing the committed version (`HEAD`) against the working copy of `menu_item_matching.py`, there are **4 distinct changes** in the diff (226 lines added, 6 removed):

### Change 1: `_try_attribute_context_type_switch` function + call site — ROLLBACK
- **What**: The entire new function (~160 lines) + 8-line call block in `_resolve_item_type_and_menu_item`
- **Part of the feature**: YES — this IS the attribute-context type switch (Tier 1 + Tier 2)
- **Action**: **ROLLBACK** — delete the function and remove the call

### Change 2: Trigger-outside-span check in `_find_different_type_menu_item` — KEEP
- **What**: Added ~40 lines that check if the detected type's trigger words exist OUTSIDE a matched menu item span. Prevents false positives like "One Applewood Chicken Sausage" triggering `egg_sandwich` because "sausage" trigger only appears inside the menu item name span.
- **Part of the feature?**: NO — this is in `_find_different_type_menu_item` (step 4), independent improvement
- **Action**: **KEEP**

### Change 3: Modifier filtering improvement in `_find_different_type_menu_item` — KEEP
- **What**: Changed modifier check from `any(is_known_modifier(w) for w in split)` to content-word filtering with `all()`. Prevents "Side of Onion" from being blocked because "onion" is a modifier.
- **Part of the feature?**: NO — independent fix in same function
- **Action**: **KEEP**

### Change 4: `_get_default_menu_item_for_type` disambiguation fix — KEEP
- **What**: Changed from returning the first match to only returning when exactly one item name ends with the type display name.
- **Part of the feature?**: NO — independent disambiguation fix
- **Action**: **KEEP**

## Rollback Steps

- [ ] **Step 1**: Remove the call to `_try_attribute_context_type_switch` from `_resolve_item_type_and_menu_item` (delete the 8-line block at step 5, restore the direct return)
- [ ] **Step 2**: Delete the entire `_try_attribute_context_type_switch` function definition
- [ ] **Step 3**: Run parsing tests — verify no regressions
- [ ] **Step 4**: Run full test suite — verify everything passes

## Scope

- **Only file affected**: `orderbot/tasks/parsers/deterministic/menu_item_matching.py`
- **No cache files affected** — the cache methods used by the function (`get_all_attribute_option_words`, `get_item_types_with_attribute`, etc.) are also used elsewhere and will remain
- **No other parser files affected**
