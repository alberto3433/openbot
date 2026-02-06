# Lessons Learned

## Parsing Priority: Specific Items Before Generic Triggers

**Date**: 2026-02-06

**Issue**: User says "Snapple Iced Tea" but parser creates generic "Hot Tea" instead of matching the specific menu item.

**Root Cause**: In `_parse_configurable_item()`, the parser detected the "tea" trigger word and created a generic configurable item BEFORE checking if a specific menu item (like "Snapple Iced Tea") matches the input.

**The Rule**: When parsing user input, always check for specific menu item matches BEFORE falling back to generic item type trigger detection. Longer/more specific matches should win over shorter trigger words.

**Fix Location**: `orderbot/tasks/parsers/deterministic/item_parsing.py` - Added check for simple (non-configurable) menu items before item type trigger detection.

**Pattern to Remember**:
1. Check for items with default ingredients (signature items) - most specific
2. Check for simple (non-configurable) menu items - specific named products
3. Only then do generic item type trigger detection - fallback for configurable items

**Key Code Added**:
```python
# 1c. Check if text contains a specific simple (non-configurable) menu item.
# This prevents "Snapple Iced Tea" from matching generic "tea" type.
if not matched_item_name:
    simple_item_types = menu_cache.get_simple_item_types()
    for item_type_slug in simple_item_types:
        item_names = menu_cache.get_item_names(item_type_slug)
        for item_name in sorted(item_names, key=len, reverse=True):
            if re.search(rf'\b{item_normalized}\b', text_normalized):
                return None  # Let simple item parser handle it
```
