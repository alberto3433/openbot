# Make Modifier Extraction Data-Driven

## Problem

In `orderbot/tasks/parsers/deterministic/extraction.py` lines 651-663, the `_extract_modifiers_for_item` function has hardcoded checks for "food" and "beverage" modifier types:

```python
if modifier_type == "food":
    # Food modifiers: extracted in database-defined order
    for category in menu_cache.get_ordered_ingredient_categories("food"):
        ingredients = menu_cache.get_ingredients(category)
        for ingredient in ingredients:
            if ingredient.lower() in text_lower:
                found_modifiers.append(ingredient.lower())

elif modifier_type == "beverage":
    # Beverage modifiers are handled differently
    pass
```

**Issues:**
1. Assumes exactly two modifier categories ("food" and "beverage")
2. Hardcodes "food" string instead of using the dynamic `modifier_type` variable
3. The "beverage" branch does nothing (`pass`) - the generic path can handle both

## Solution

Remove the conditional checks and use `modifier_type` directly with `get_ordered_ingredient_categories()`. This makes it fully data-driven:

```python
# Get modifier category for this item type
modifier_type = menu_cache.get_modifier_category(item_type)

# Extract modifiers in database-defined category order
for category in menu_cache.get_ordered_ingredient_categories(modifier_type):
    ingredients = menu_cache.get_ingredients(category)
    for ingredient in ingredients:
        if ingredient.lower() in text_lower:
            found_modifiers.append(ingredient.lower())
```

## Why This Works

1. **Already data-driven**: `get_ordered_ingredient_categories(modifier_type)` returns the appropriate categories for ANY modifier type defined in the database
2. **No special cases needed**: The same loop works for food, beverage, or any future modifier type
3. **Database controls behavior**: Adding a new modifier type only requires database changes

## Implementation

**File:** `orderbot/tasks/parsers/deterministic/extraction.py`

Replace lines 648-663:
```python
# Get modifier category for this item type (food or beverage)
modifier_type = menu_cache.get_modifier_category(item_type)

if modifier_type == "food":
    # Food modifiers: extracted in database-defined order (proteins, cheeses, toppings, spreads)
    for category in menu_cache.get_ordered_ingredient_categories("food"):
        # Get ingredients for this category
        ingredients = menu_cache.get_ingredients(category)
        for ingredient in ingredients:
            if ingredient.lower() in text_lower:
                found_modifiers.append(ingredient.lower())

elif modifier_type == "beverage":
    # Beverage modifiers are handled differently (syrups, sweeteners, milk)
    # These have quantities so they're extracted separately
    pass
```

With:
```python
# Get modifier category for this item type and extract modifiers in category order
modifier_type = menu_cache.get_modifier_category(item_type)

for category in menu_cache.get_ordered_ingredient_categories(modifier_type):
    ingredients = menu_cache.get_ingredients(category)
    for ingredient in ingredients:
        if ingredient.lower() in text_lower:
            found_modifiers.append(ingredient.lower())
```

## Verification

Run parsing tests to ensure no regressions:
```bash
python -m pytest tests/test_tasks_parsing.py -v --tb=short
```
