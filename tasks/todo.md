# Bug Fixes: Bialy Order Issues

## Bug 1: "do you have any bialy" treated as modifier instead of availability question

### Problem
When the user asked "yes do you have any bialy", the system treated "bialy" as a modifier for the existing bagel instead of recognizing it as an availability question.

### Root Cause
1. `AVAILABILITY_PATTERNS` required explicit qualifiers like "in stock", "available", "left"
2. `early_pattern_handler` detected "bialy" as a modifier and added it to existing bagel

### Fix Applied
1. Added simpler availability pattern to `inquiry_patterns.py`:
   ```python
   re.compile(r"do\s+you\s+have\s+(?:any\s+)?(.+?)\s*\??$", re.IGNORECASE)
   ```
2. Added guard in `early_pattern_handler.py` to skip "do you have" inputs

## Bug 2: "can I get a toasted bialy with butter" modifies existing bagel instead of creating new item

### Problem
When the user asked "can I get a toasted bialy with butter and scallion cream cheese?", the system modified the existing Everything Bagel instead of creating a new bialy item.

### Root Cause
In `modifier_input_handler.py`:
1. "can I get" matches `ADD_MODIFIER_PATTERNS` (line 122 in constants.py)
2. When `is_add_modifier_request=True`, the code skipped the `has_other_item` check
3. Modifiers were applied to existing bagel even though "bialy" is a new item

### Fix Applied
1. Moved `has_other_item` check to apply even when `is_add_modifier_request=True`
2. Added early return when `has_other_item=True` to let parser create new item
3. Changed to word-boundary matching for consistency with early_pattern_handler

## Consolidation: Removed Duplicate Handler Logic

The `ModifierInputHandler.handle_add_modifier_to_last_item()` method had ~130 lines of duplicate logic that was already handled by `EarlyPatternHandler.handle_early_modifier_input()`.

### What Was Removed
- Duplicate ADD_MODIFIER_PATTERNS check
- Duplicate has_item_modifier detection
- Duplicate has_other_item check
- Duplicate add_modifiers_from_input() call
- Duplicate category removal logic

### What Was Kept
- Single-select attribute fallback logic (unique functionality)
- This handles edge cases where an ingredient maps to a single_select attribute

### Method Renamed
- `handle_add_modifier_to_last_item()` → `handle_single_select_attribute_fallback()`
- Updated calling code in `taking_items_handler.py`

## Files Modified

1. `orderbot/tasks/parsers/inquiry_patterns.py` - Added simpler availability pattern
2. `orderbot/tasks/early_pattern_handler.py` - Skip "do you have" inputs
3. `orderbot/tasks/modifier_input_handler.py` - Removed duplicate logic, renamed method
4. `orderbot/tasks/taking_items_handler.py` - Updated method calls
5. `tests/test_tasks_parsing.py` - Added TestAvailabilityInquiry test class

## Test Results
- 16 new availability inquiry tests: PASS
- 17 modifier-related tests: PASS
- 331 total tests pass (1 pre-existing failure unrelated to these changes)

---

# Bug Fix: "add an egg" Rejected During Config

## Problem
When a user orders "bagel toasted with scrambled eggs" and then says "add an egg" during configuration, the system incorrectly rejects with "Egg isn't available for the Bagel" instead of asking which egg style they want.

## Root Cause
In `config_modification_handler.py`, the `handle_add_modifiers_during_config()` method validated ingredients at line 426 BEFORE checking if the ingredient matches an attribute with options (lines 437-457).

The flow was:
1. `find_matching_ingredients("egg")` → finds Egg ingredient
2. `is_valid_modifier_for_item_type("egg", "bagel")` → FALSE (reject!)
3. (never reached) Check if "egg" is an attribute with options

The validation assumed "egg" must be a valid ingredient for bagels, but eggs are configured as an **attribute** (not ingredient) for bagels.

## Fix Applied
Reordered the logic in `handle_add_modifiers_during_config()` to check if the ingredient slug matches an attribute BEFORE doing ingredient validation:

1. `find_matching_ingredients("egg")` → finds Egg ingredient
2. Check if ingredient slug matches an attribute with options for this item type
   - If YES: Skip ingredient validation, proceed to attribute handling (ask which egg style)
   - If NO: Continue with ingredient validation as before
3. Only reject if BOTH checks fail

## Files Modified
1. `orderbot/tasks/config_modification_handler.py` - Reordered attribute check before ingredient validation
2. `tests/scenarios/test_modifications.py` - Added `TestAddEggDuringConfig` test class

## Test Results
- 2 new "add egg during config" tests: PASS
- All existing tests: PASS (same 5 pre-existing failures unrelated to this change)
- Total: 1720 passed, 5 failed (pre-existing)

---

# Bug Fix: "add 2 eggs" Should Add to Existing Quantity

## Problem
When a bagel already had 1 scrambled egg and user said "add 2 eggs", the system would set egg quantity to 2 instead of 3 (1 existing + 2 new).

## Root Cause
The `pending_modifier_quantity` was correctly stored when user said "add 2 eggs", but when applying the selection (user selects "scrambled"), the code replaced the existing quantity instead of adding to it.

## Fix Applied
Added an `is_additive` flag to track when an attribute question came from an "add X" command:

1. **Model**: Added `pending_modifier_is_additive: bool` field to `OrderTask`
2. **Config Modification Handler**: Set flag to `True` when item already has the attribute
3. **Select Input Handler**: When `is_additive=True`, get existing quantity before removing selection and add new quantity to it

### Code Flow
1. User orders "bagel with scrambled eggs" → egg quantity = 1
2. User says "add 2 eggs" → `pending_modifier_quantity=2`, `pending_modifier_is_additive=True`
3. User selects "scrambled" → existing quantity (1) + new quantity (2) = 3

## Files Modified
1. `orderbot/tasks/models/container_tasks.py` - Added `pending_modifier_is_additive` field
2. `orderbot/tasks/adapter.py` - Serialize/deserialize the new field
3. `orderbot/tasks/config_modification_handler.py` - Set flag when item has existing attribute
4. `orderbot/tasks/config/select_input.py` - Add to existing quantity when flag is set
5. `tests/scenarios/test_modifications.py` - Added `test_add_2_eggs_to_existing_egg_gives_3_total`

## Test Results
- 3 new "add egg during config" tests: PASS
- All 1744 tests: PASS

---

# Feature: Inline Attribute Specifications

## Problem
Input "2 bagels 1 everything 1 plain" was creating 1 item with qty=2 and ignoring the "1 everything 1 plain" specification. The user would then have to answer bread question for each bagel separately.

## Solution
Added inline attribute specification parsing that reuses the parsing logic from `PackageInputHandler._parse_package_contents()`.

### How It Works
1. When parsing a configurable item with quantity > 1 (and no specific menu item name):
   - Get the primary configurable attribute (e.g., "bread" for bagels)
   - Extract text after the item trigger
   - Parse for inline specs pattern (e.g., "1 everything 1 plain")
2. If valid specs found:
   - Create separate items for each specification
   - Handle partial specs (e.g., "3 bagels 2 everything" → 2 with bread, 1 generic)
3. Skip inline spec parsing for:
   - Specific menu items (e.g., "2 classic becs on wheat")
   - Over-specified quantities (e.g., "2 bagels 3 everything")

### Supported Patterns
- `"2 bagels 1 everything 1 plain"` → 2 items with correct bread
- `"3 bagels 2 plain 1 sesame"` → 3 items
- `"3 bagels 2 everything"` → 2 with bread, 1 needs config
- `"1 everything and 1 plain"` → Works with "and" separator
- `"1 everything, 1 plain"` → Works with comma separator

## Files Created
1. `orderbot/tasks/parsers/deterministic/inline_spec_parsing.py` - Core parsing logic
2. `tests/test_inline_spec_parsing.py` - Test coverage (20 tests)

## Files Modified
1. `orderbot/tasks/parsers/deterministic/item_parsing.py` - Integration point at step 3b

## Test Results
- 20 new inline spec tests: PASS
- 561 existing parsing tests: PASS
- 31 bagel integration tests: PASS

---

# Feature: Dietary Properties with Fallback

## Problem
Menu item dietary columns (is_vegan, contains_eggs, etc.) were removed with intent to compute from ingredients. However, some items (e.g., "Bagel Chips") have no ingredients defined, so dietary properties couldn't be computed.

## Solution
Hybrid approach with fallback:
1. **Restore** dietary columns on `menu_items` table
2. **Compute from ingredients** when a menu item has ingredients defined
3. **Use stored values** as fallback when no ingredients exist
4. **UI shows disabled checkboxes** when values are computed (read-only)

### Data Flow
```
MenuItem with ingredients (e.g., "The Classic BEC"):
├── Has ingredient_links → compute from ingredients
├── UI checkboxes: DISABLED (computed, not editable)
└── Shows "(Computed from X ingredients)" indicator

MenuItem without ingredients (e.g., "Bagel Chips"):
├── No ingredient_links → use stored column values
├── UI checkboxes: ENABLED (can be edited)
└── Shows no indicator (direct edit mode)
```

### Dietary Computation Logic
- **Dietary properties** (is_vegan, is_vegetarian, etc.): Item is True only if ALL ingredients are True
- **Allergen properties** (contains_eggs, contains_fish, etc.): Item is True if ANY ingredient is True

## Files Created
1. `alembic/versions/schema_cleanup_02_restore_dietary_columns.py` - Migration to restore columns

## Files Modified
1. `orderbot/db/models/menu.py` - Added dietary/allergen columns back to MenuItem model
2. `orderbot/cache/loaders/core.py` - Added ingredient_links eager loading for dietary computation
3. `orderbot/cache/loaders/menu_items.py` - Added `_compute_dietary_from_ingredients()` and updated `_load_dietary_data_from_bulk()` to compute with fallback
4. `orderbot/schemas/menu.py` - Restored dietary fields + added `has_ingredients` flag
5. `orderbot/routes/admin_menu.py` - Restored dietary field handling in serialize/create/update
6. `static/admin_menu.html` - Added disabled state and computed indicator for dietary checkboxes

## Test Results
- 563 parsing tests: PASS
- 34 adapter tests: PASS
- 39 modification scenario tests: PASS
- Cache loads successfully with 238 items computing from ingredients, 309 using fallback

---

# Fix: Allow modifier quantity accumulation on repeated "add X" commands

## Problem
When user says "add sausage" multiple times during item configuration:
- Each call logs "Added 'Sausage' (category=meat, qty=1)"
- But quantity never accumulates (stays at 1 sausage, $2.75)
- Response at customization_checkpoint doesn't acknowledge the addition

## Root Cause
`MenuItemTask.add_selection()` in `item_tasks.py` (lines 317-326):
```python
for existing in self.selections:
    if existing.get("slug") == slug and existing.get("category") == category:
        if quantity > 1 and existing.get("quantity", 1) == 1:
            existing["quantity"] = quantity
        return  # <-- EARLY EXIT, no increment
```

When "add sausage" is called with `quantity=1`, it finds existing sausage and returns immediately without incrementing.

## Solution
Add `increment_if_exists` parameter to `add_selection()`:
- Default: `False` (current behavior - for pre-filled defaults)
- Pass `True` when handling user "add X" commands

## Implementation Plan

- [ ] 1. Modify `add_selection()` in `item_tasks.py` to add `increment_if_exists` parameter
- [ ] 2. Update `config_modification_handler.py` to pass `increment_if_exists=True`
- [ ] 3. Update `item_modification_handler.py` to pass `increment_if_exists=True`
- [ ] 4. Update `ingredient_fallback.py` to pass `increment_if_exists=True`
- [ ] 5. Test: Multiple "add sausage" should accumulate quantity
- [ ] 6. Test: Pre-filled defaults from signature items should NOT double-up

## Complexity Assessment
**Low** - Single method change with new parameter. Clear pattern for callers.

## Files to Modify
1. `orderbot/tasks/models/item_tasks.py` - add parameter
2. `orderbot/tasks/config_modification_handler.py` - pass flag
3. `orderbot/tasks/item_modification_handler.py` - pass flag
4. `orderbot/tasks/config/flows/ingredient_fallback.py` - pass flag
