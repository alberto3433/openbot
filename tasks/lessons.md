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

---

## Menu Item Name Words Should Be Excluded from Attribute Extraction

**Date**: 2026-02-07

**Issue**: User says "cinnamon butter sandwich" and the item "Cinnamon Sugar Butter Sandwich" is correctly matched, but "butter" is also incorrectly extracted as a spread attribute.

**Root Cause**: When extracting attributes from user input, the code tried to find and exclude the span of the menu item name. However, it searched for the **canonical** name ("Cinnamon Sugar Butter Sandwich") instead of the **alias** that the user typed ("cinnamon butter sandwich"). Since the canonical name wasn't in the input text, the exclusion span was None and "butter" was matched as a spread.

**The Rule**: When calculating exclusion spans for attribute extraction, always use the ACTUAL TEXT that matched (the alias), not the canonical name that it resolved to.

**Fix Location**:
- `orderbot/tasks/parsers/deterministic/modification_parsing.py` - Modified `_extract_menu_item_from_text()` to return the matched alias as a third return value
- `orderbot/tasks/parsers/deterministic/core.py` - Updated caller to use the matched alias for exclusion span calculation

**Pattern to Remember**:
1. User types an alias (e.g., "cinnamon butter sandwich")
2. Parser matches it to canonical name (e.g., "Cinnamon Sugar Butter Sandwich")
3. When excluding the matched text from attribute extraction, use the ALIAS, not the canonical name
4. The alias is what's actually in the user's input text

**Key Code Changes**:
```python
# modification_parsing.py - return matched alias
def _extract_menu_item_from_text(text: str) -> tuple[str | None, int, str | None]:
    ...
    return canonical, quantity, item  # item is the matched alias

# core.py - use alias for exclusion
menu_item, qty, matched_alias = _extract_menu_item_from_text(text)
search_terms = [matched_alias, menu_item.lower()] if matched_alias else [menu_item.lower()]
for search_term in search_terms:
    pos = text_lower.find(search_term.lower())
    if pos != -1:
        menu_item_span = (pos, pos + len(search_term))
        break
```
