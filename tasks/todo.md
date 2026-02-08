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
