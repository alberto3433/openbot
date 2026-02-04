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
