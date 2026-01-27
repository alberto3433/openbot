# Fix: "can you make it with 2 vanilla syrups" Fails

## Problem Statement

When user says "can you make it with 2 vanilla syrups" after ordering a latte with 1 vanilla syrup:
- Bot responds: "This item doesn't have a Unknown to change."

## Root Cause

In `modifier_change_handler.py`, the `_analyze_modifier` method:

1. Gets new_value = "2 vanilla syrups"
2. Calls `menu_cache.find_all_categories_for_ingredient("2 vanilla syrups")`
3. This fails because "2 vanilla syrups" isn't recognized as an ingredient (the "2" prefix breaks matching)
4. Falls through to line 216: `return False, ["unknown"]`
5. Then `change_attribute()` tries to change "unknown" attribute, which doesn't exist
6. `_get_attr_display_name("unknown")` returns "Unknown"
7. Error message: "This item doesn't have a Unknown to change."

## Solution

Before returning `["unknown"]`, strip quantity prefixes and re-try the ingredient lookup:

**In `_analyze_modifier` method, before line 215-216:**

```python
# Try stripping quantity prefix and re-analyzing
# e.g., "2 vanilla syrups" -> "vanilla syrups" -> "vanilla syrup"
stripped_value = self._strip_quantity_prefix(new_value_lower)
if stripped_value != new_value_lower:
    # Recurse with stripped value
    is_ambiguous, attrs = self._analyze_modifier(stripped_value, target)
    if attrs and attrs[0] != "unknown":
        return is_ambiguous, attrs

# Unknown modifier
return False, ["unknown"]
```

**Add helper method:**

```python
def _strip_quantity_prefix(self, value: str) -> str:
    """Strip quantity prefixes like '2 ', 'two ', 'double ' from value."""
    import re
    # Strip numeric prefix: "2 vanilla syrups" -> "vanilla syrups"
    value = re.sub(r"^\d+\s+", "", value)
    # Strip word prefix: "two vanilla syrups" -> "vanilla syrups"
    quantity_words = ["one", "two", "three", "four", "five", "six", "double", "triple"]
    for word in quantity_words:
        if value.startswith(word + " "):
            value = value[len(word)+1:]
            break
    # Strip trailing 's' for plural: "vanilla syrups" -> "vanilla syrup"
    if value.endswith("s") and not value.endswith("ss"):
        singular = value[:-1]
        # Verify the singular form is recognized
        try:
            if menu_cache.find_all_categories_for_ingredient(singular):
                return singular
        except:
            pass
    return value
```

## Alternative: Handle in change_attribute

Could also handle this at the `change_attribute` level by:
1. Detecting quantity in new_value
2. Using `add_selection` with quantity instead of single-value attribute change

## File to Modify

| File | Change |
|------|--------|
| `orderbot/tasks/modifier_change_handler.py` | Add quantity stripping before returning "unknown" |

## Verification

1. Order a latte with vanilla syrup
2. Say "can you make it with 2 vanilla syrups"
3. Should update to 2x Vanilla Syrup, not show "Unknown" error
