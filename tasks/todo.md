# Plan: Add quantity_per_unit Column for Pack Sizes

## Goal

Allow menu items like "Chocolate Dipped Macaroons" to convey they come in a pack of 3, without using parentheses in the display name (which breaks parsing).

## Current State

- `MenuItem.unit_type` column exists with values: `each`, `by_weight`, `dozen`
- NOT exposed in admin API schemas or UI
- No way to specify "this item comes as a 3 pack"

## Solution

1. Add `quantity_per_unit` column (integer, nullable)
2. Add `pack` as valid `unit_type` value
3. Display "(X pack)" when `unit_type='pack'` and `quantity_per_unit > 1`

## Implementation Plan

### Phase 1: Database Migration
- [ ] Create migration to add `quantity_per_unit` column to `menu_items` table
- [ ] Column: `INTEGER`, nullable, default NULL
- [ ] Update model docstring to document "pack" as valid unit_type

**File:** `alembic/versions/xxx_add_quantity_per_unit.py`

### Phase 2: Update API Schemas
- [ ] Add `unit_type` and `quantity_per_unit` to `MenuItemOut`
- [ ] Add `unit_type` and `quantity_per_unit` to `MenuItemCreate`
- [ ] Add `unit_type` and `quantity_per_unit` to `MenuItemUpdate`

**File:** `orderbot/schemas/menu.py`

### Phase 3: Update Admin API Serialization
- [ ] Include `unit_type` and `quantity_per_unit` in `serialize_menu_item()`
- [ ] Handle these fields in create/update endpoints

**File:** `orderbot/routes/admin_menu.py`

### Phase 4: Update Admin UI
- [ ] Add "Unit Type" dropdown (each, by_weight, dozen, pack)
- [ ] Add "Quantity per Unit" number input (shown when unit_type is 'pack' or 'dozen')
- [ ] Position near the price field (contextually related)

**File:** `static/admin_menu.html`

### Phase 5: Update Display Logic
- [ ] Add helper method to format unit display: `get_unit_display()` → "(3 pack)" or ""
- [ ] Update `get_display_name()` to optionally include unit suffix
- [ ] Update confirmation messages to show pack info

**Files:**
- `orderbot/tasks/models/item_tasks.py` - Add display helper
- `orderbot/cache/menu_queries.py` - Add cache lookup for unit info
- `orderbot/tasks/config_selection_handler.py` - Update "Added X" message

### Phase 6: Update Cache
- [ ] Include `unit_type` and `quantity_per_unit` in menu item cache entries
- [ ] Add lookup method: `get_menu_item_unit_info(item_name) -> (unit_type, quantity)`

**Files:**
- `orderbot/cache/loaders/menu_items.py`
- `orderbot/cache/menu_queries.py`

## Display Logic

```python
def get_unit_display(unit_type: str, quantity_per_unit: int | None) -> str:
    """Return display string like '(3 pack)' or '' for single items."""
    if unit_type == 'pack' and quantity_per_unit and quantity_per_unit > 1:
        return f"({quantity_per_unit} pack)"
    if unit_type == 'dozen':
        return "(dozen)"
    return ""
```

**Example confirmations:**
- "Added Chocolate Dipped Macaroons (3 pack). Anything else?"
- "Added Plain Bagel. Anything else?" (no suffix for unit_type='each')

## Data Migration

After schema is ready, update existing items:
```sql
UPDATE menu_items
SET unit_type = 'pack', quantity_per_unit = 3
WHERE name = 'Chocolate Dipped Macaroons';
```

## Files to Modify

| File | Changes |
|------|---------|
| `alembic/versions/xxx_add_quantity_per_unit.py` | New migration |
| `orderbot/db/models/menu.py` | Add column, update docstring |
| `orderbot/schemas/menu.py` | Add fields to all schemas |
| `orderbot/routes/admin_menu.py` | Serialize and handle fields |
| `static/admin_menu.html` | Add UI controls |
| `orderbot/cache/loaders/menu_items.py` | Include in cache |
| `orderbot/cache/menu_queries.py` | Add lookup method |
| `orderbot/tasks/models/item_tasks.py` | Display helper |
| `orderbot/tasks/config_selection_handler.py` | Update confirmation |

---

# COMPLETED: Data-Driven Prefix-Based Menu Inquiries

## Problem (Solved)

When user asked "what iced drinks do you have?", the system returned generic "We have breakfasts, desserts..." instead of listing iced items.

## Solution Implemented

Built a **prefix index** at cache load time that maps first words of item names to items:
- `"iced"` → [Iced Coffee, Iced Latte, Iced Tea, ...]
- `"hot"` → [Hot Coffee, Hot Latte, Hot Tea, ...]

### Files Modified

1. **`orderbot/cache/base.py`** - Added `_menu_items_by_prefix` cache dict
2. **`orderbot/cache/loaders/menu_items.py`** - Added `_build_prefix_index_from_menu_index()` method
3. **`orderbot/cache/loaders/core.py`** - Call prefix index builder after menu index load
4. **`orderbot/cache/menu_queries.py`** - Added `get_menu_items_by_name_prefix()` and `get_known_name_prefixes()`
5. **`orderbot/tasks/menu_inquiry_handler.py`** - Added FALLBACK 2 to use prefix index

### Results

```
User: "what iced drinks do you have?"
Bot: "Our iced drinks include: Iced Coffee, Iced Latte, Iced Cappucino, Iced Americano, Iced Tea, and ...and 1 more. Would you like any of these?"

User: "what hot drinks do you have?"
Bot: "Our hot drinks include: Hot Coffee, Hot Chocolate, Hot Latte, Hot Cappuccino, and Hot Tea. Would you like any of these?"
```

### Data-Driven

- No hardcoded "iced", "hot" checks - works for any prefix derived from menu item names
- Adding new items like "Frozen Lemonade" automatically enables "what frozen drinks do you have?"

---

# COMPLETED: Skip Rules Admin UI

## Summary

Added UI to manage skip rules within the Global Attributes admin page. Skip rules allow an option to skip asking about other attributes when selected (e.g., "Black" coffee skips the "Milk/Sweetener/Syrup" attribute).

### Implementation

1. **Backend API endpoints** (already existed in `admin_global_attributes.py`):
   - `GET /admin/global-attributes/{attr_id}/options/{option_id}/skip-rules` - List skip rules
   - `POST /admin/global-attributes/{attr_id}/options/{option_id}/skip-rules` - Add skip rule
   - `DELETE /admin/global-attributes/{attr_id}/options/{option_id}/skip-rules/{rule_id}` - Delete skip rule

2. **Pydantic schemas** (already existed in `global_attributes.py`):
   - `SkipRuleOut` - Response model for skip rules
   - `SkipRuleCreate` - Request model for creating skip rules
   - `SkipRuleOutBasic` - Embedded in `GlobalAttributeOptionOut.skip_rules`

3. **HTML UI** (`admin_global_attributes.html`):
   - Skip rules section in option edit modal (shown only for existing options)
   - Table displaying current skip rules with delete buttons
   - "Add Skip Rule" modal with attribute dropdown
   - Skip badge in options list showing count of skip rules

4. **JavaScript functions**:
   - `loadOptionSkipRules()` - Fetches skip rules from API
   - `renderSkipRules()` - Renders the table in the modal
   - `addSkipRule()` - Creates new skip rule via API
   - `deleteSkipRule()` - Deletes skip rule via API
   - `loadAvailableAttributesForSkipRule()` - Populates dropdown (excludes already-skipped)
   - `openAddSkipRuleModal()` / `closeAddSkipRuleModal()` - Modal control

### Verification

1. Open Global Attributes admin → Select "Coffee Preparation" → Edit "Black" option
2. Should see "Skip Rules" section showing "Milk/Sweetener/Syrup"
3. Click "+ Add Skip Rule" → dropdown shows available attributes
4. Add a new skip rule → appears in table
5. Click delete → rule removed
6. Changes persist after page refresh

---

# COMPLETED: Consolidate Modifiers and Attributes (Phases 1-2)

## Summary

Implemented Phase 1 and Phase 2 of the pricing consolidation plan:

### Phase 1: Fix slug normalization in priced_slugs tracking ✓
- Added `normalize_to_slug()` import to `attribute_upcharge_calculator.py`
- Modified `_process_string_attribute()` to normalize both `attr_value` and modifier slugs before comparison
- Modified `_process_list_attribute()` to normalize slugs for consistent tracking
- Modified `_apply_modifier_prices()` in `pricing.py` to normalize slugs before checking `priced_slugs`

### Phase 2: Single price source from GlobalAttributeOption ✓
- Modified `add_selection()` in `item_tasks.py` to ignore the `price` parameter (deprecated)
- Prices are now stored as `0.0` at creation time
- `recalculate_item_price()` is the single source of truth for pricing
- Modified `_apply_modifier_prices()` to always look up from DB
- Modified `_process_string_attribute()` to always look up from DB
- Modified `_process_list_attribute()` to always look up from DB
- Updated `selection_extractor.py` to not look up prices upfront
- Updated test helper `item_factories.py` to use `_set_modifier_price()` for test-specific prices

## Files Modified

- `orderbot/tasks/attribute_upcharge_calculator.py` - Single source of truth for pricing
- `orderbot/tasks/pricing.py` - Single source of truth for pricing
- `orderbot/tasks/models/item_tasks.py` - Deprecated price parameter in add_selection()
- `orderbot/tasks/config/selection_extractor.py` - Removed upfront price lookup
- `orderbot/tasks/item_converters.py` - Updated docstring (no recalculate in to_dict)
- `tests/helpers/item_factories.py` - Added _set_modifier_price() helper for tests

## Phase 3: Pending

Single-pass pricing + rename `modifiers` to `selections` is pending. This would:
1. Rename `MenuItemTask.modifiers` → `MenuItemTask.selections`
2. Merge `AttributeUpchargeCalculator` into simpler `_calculate_selection_prices()`
3. Delete `AttributeUpchargeCalculator` class
4. Update all files that reference `item.modifiers` to use `item.selections`

---

# Fix: Skip Rules Not Applied for Boolean Attributes

## Problem

Skip rules aren't being applied when boolean attributes like "decaf" are selected. The logs show:
```
GET_UNANSWERED_MANDATORY: item_type=sized_beverage, attribute_values={'decaf': True}, skipped=set()
```

The `skipped` set is empty when it should contain `"shots"` (because "decaf" has a skip rule to skip "shots").

## Root Cause

In `orderbot/tasks/config/handler.py`, the `_get_skipped_attributes()` function handles boolean attribute values incorrectly:

```python
elif isinstance(value, bool):
    # Boolean - check if "yes" or "no" triggers skip rules
    bool_slug = "yes" if value else "no"
    attr_skips = menu_cache.get_skipped_attributes_for_option(bool_slug)
```

When `decaf=True`, this code looks up skip rules for the generic option `"yes"` instead of the actual option slug. The skip rules are configured for the `"decaf"` option (or similar), not `"yes"`.

## Solution

For boolean attributes with `True` value, use the **attribute slug** as the option slug, since boolean attributes typically have their "yes" option named after the attribute (e.g., attribute "decaf" has option "yes" with slug "yes" or "decaf").

The fix needs to:
1. For boolean `True` values, look up skip rules for the **attribute slug** itself
2. The attribute slug is the key in `attribute_values` dict (e.g., "decaf")
3. This matches how skip rules are configured in the admin UI

## Implementation

**File:** `orderbot/tasks/config/handler.py`

In `_get_skipped_attributes()`, change:
```python
elif isinstance(value, bool) and value:
    # For boolean True, the option slug is the attribute slug itself
    # e.g., decaf=True means "decaf" option was selected, check its skip rules
    attr_skips = menu_cache.get_skipped_attributes_for_option(attr_slug)
    skipped.update(attr_skips)
```

## Verification

1. Restart server
2. Order "decaf coffee"
3. After size and milk, verify shots question is NOT asked
4. Logs should show `skipped={'shots'}` instead of `skipped=set()`

---

# Feature: Suggest Items When User Orders a Modifier

## Problem

When user says "I want caramel syrup", the system responds:
```
"I couldn't find 'caramel syrup' on our menu. We have Drink, Food, or Soda. What would you like?"
```

This is unhelpful. The user clearly wants caramel syrup as an ingredient, not a standalone item.

## Desired Behavior

```
User: "I want caramel syrup"
Bot: "We could make you a Latte, Cappuccino, or Americano with caramel syrup. Would you like one of those?"
```

## Data Available

The cache already has `_ingredient_price_contexts` which maps ingredient names to their usage contexts:

```python
_ingredient_price_contexts["caramel syrup"] = [
    {
        "context_type": "modifier",
        "item_type_slug": "espresso_based",
        "label": "Espresso Based topping",
        "price": 0.75,
    },
    {
        "context_type": "modifier",
        "item_type_slug": "sized_beverage",
        "label": "Sized Beverage topping",
        "price": 0.75,
    },
    # ... etc
]
```

This tells us which item_types can have "caramel syrup" as a modifier.

## Implementation Plan

### Part 1: Add Cache Method to Get Item Types for Ingredient

**File:** `orderbot/cache/ingredient_queries.py`

```python
def get_item_types_for_ingredient(self, ingredient_name: str) -> list[dict]:
    """Get item types that can have this ingredient as a modifier.

    Returns list of dicts with item_type_slug and display_name.
    """
    contexts = self._ingredient_price_contexts.get(ingredient_name.lower(), [])
    item_types = []
    seen = set()
    for ctx in contexts:
        if ctx["context_type"] == "modifier":
            slug = ctx["item_type_slug"]
            if slug not in seen:
                seen.add(slug)
                item_types.append({
                    "slug": slug,
                    "display_name": ctx.get("label", slug),
                })
    return item_types
```

### Part 2: Add Parser Response Type

**File:** `orderbot/tasks/schemas/parser_responses.py`

Add new fields to `OpenInputResponse`:
```python
# Ingredient without item context
found_ingredient_without_item: bool = Field(
    default=False,
    description="User ordered an ingredient/modifier without specifying an item"
)
found_ingredient_name: str | None = Field(
    default=None,
    description="The ingredient name that was found"
)
```

### Part 3: Update Parser to Detect Standalone Ingredients

**File:** `orderbot/tasks/parsers/deterministic/core.py` or a new handler

When menu item matching fails, before returning "not found":
1. Check if the input matches a known ingredient via `normalize_modifier()`
2. If yes, check if it has modifier contexts via `get_item_types_for_ingredient()`
3. If yes, return `OpenInputResponse(found_ingredient_without_item=True, found_ingredient_name=...)`

### Part 4: Add Handler for Ingredient Suggestions

**File:** `orderbot/tasks/taking_items_handler.py` or new handler

When `found_ingredient_without_item=True`:
1. Get item_types for the ingredient
2. Get sample menu items for those item_types
3. Format response: "We could make you a [items] with [ingredient]. Would you like one of those?"
4. Store context for follow-up (pending_suggested_ingredient, pending_item_types)

### Part 5: Handle User Confirmation

When user says "yes" after ingredient suggestion:
- Show disambiguation of items from those item_types
- OR ask "What drink would you like with [ingredient]?"

## Data-Driven Requirements

- Ingredient names/aliases from `Ingredient` table and `ingredient_aliases`
- Item type mappings from `ItemTypeIngredient` junction table
- Menu items from `menu_items` table

No hardcoded food-domain terms needed.

## Edge Cases

1. **Multiple item types** - Show items from most common type, mention others
2. **Standalone items** - "cream cheese" can be modifier OR by-the-pound item - handle both
3. **Ambiguous input** - "bacon" could be ordering bacon (by-the-pound) or wanting bacon on something

## Files to Modify

1. `orderbot/cache/ingredient_queries.py` - Add `get_item_types_for_ingredient()`
2. `orderbot/tasks/schemas/parser_responses.py` - Add new response fields
3. `orderbot/tasks/parsers/deterministic/core.py` - Add ingredient detection fallback
4. `orderbot/tasks/taking_items_handler.py` - Handle ingredient suggestion response
5. `tests/test_resiliency_batch8.py` - Add test for "I want caramel syrup"

## Questions

1. Should we prioritize "modifier" context over "standalone" context, or mention both?
2. How many sample items to show? (3-4 seems reasonable)
3. Should confirmation ("yes") add the item with the modifier, or ask which item?
