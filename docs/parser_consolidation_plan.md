# Parser Consolidation Plan: Unified Item Parsing

## Executive Summary

**Goal:** Eliminate the two-path architecture (single-item vs multi-item parsing) by making ALL parsing flow through a unified `parsed_items` list.

**Current State:**
- Multi-item orders use `parsed_items: list[ParsedItem]`
- Single-item orders set boolean flags (`new_coffee=True`, `new_bagel=True`)
- A model validator auto-converts boolean flags to `parsed_items` for backwards compatibility

**Target State:**
- ALL parsers populate `parsed_items` directly
- Handlers ONLY read from `parsed_items`
- Boolean flags deprecated (kept for LLM fallback compatibility)

---

## Current Architecture

```
User Input: "large iced latte"
                ↓
parse_open_input_deterministic()
                ↓
_parse_multi_item_order() → returns None (only 1 item detected)
                ↓
_parse_coffee_deterministic() → sets new_coffee=True, new_coffee_size="large", etc.
                ↓
model_validator auto-converts → parsed_items=[ParsedCoffeeEntry(...)]
                ↓
Handler reads parsed_items


User Input: "bagel and coffee"
                ↓
parse_open_input_deterministic()
                ↓
_parse_multi_item_order() → detects 2 items, dual-writes to parsed_items
                ↓
Returns: parsed_items=[ParsedBagelEntry(...), ParsedCoffeeEntry(...)]
                ↓
Handler reads parsed_items
```

**Problem:** Single-item path relies on model_validator conversion, adding latency and complexity.

---

## Target Architecture

```
User Input: "large iced latte" OR "bagel and coffee"
                ↓
parse_open_input_deterministic()
                ↓
_parse_items() → ALWAYS returns parsed_items=[...]
                ↓
Handler reads parsed_items (same code path for 1 or N items)
```

---

## Phase 1: Parser Dual-Write (Low Risk)

**Goal:** Make single-item parsers populate `parsed_items` directly while keeping boolean flags for compatibility.

### 1.1 Update `_parse_coffee_deterministic()`

**File:** `orderbot/tasks/parsers/deterministic.py`

```python
# BEFORE (line ~2500)
def _parse_coffee_deterministic(user_input: str) -> OpenInputResponse | None:
    # ... parsing logic ...
    return OpenInputResponse(
        new_coffee=True,
        new_coffee_type=drink_type,
        new_coffee_size=size,
        # ... more fields
    )

# AFTER
def _parse_coffee_deterministic(user_input: str) -> OpenInputResponse | None:
    # ... parsing logic ...

    # Build the ParsedCoffeeEntry
    coffee_entry = ParsedCoffeeEntry(
        drink_type=drink_type,
        size=size,
        temperature="iced" if is_iced else "hot" if is_iced is False else None,
        milk=milk,
        sweeteners=sweeteners,
        syrups=syrups,
        quantity=quantity,
        decaf=is_decaf,
        special_instructions=special_instructions,
        original_text=user_input,
    )

    return OpenInputResponse(
        # Keep boolean flags for LLM compatibility
        new_coffee=True,
        new_coffee_type=drink_type,
        new_coffee_size=size,
        # ... more fields

        # NEW: Also populate parsed_items directly
        parsed_items=[coffee_entry],
    )
```

### 1.2 Update bagel parsing in `parse_open_input_deterministic()`

Similar pattern - when bagel is detected, create `ParsedBagelEntry` and add to `parsed_items`.

### 1.3 ~~Update `_parse_signature_item_deterministic()`~~ (REMOVED)

**Status: COMPLETED** - Function has been removed. Signature items are now handled by the generic
menu item parser (`_extract_menu_item_from_text()`), which uses database aliases to match items.

### 1.4 Update `_parse_soda_deterministic()`

Create appropriate entry and add to `parsed_items`.

**Verification:**
```bash
# All existing tests should pass (boolean flags still set)
python -m pytest tests/test_tasks_parsing.py -v

# Verify parsed_items is populated
python -c "
from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
result = parse_open_input_deterministic('large iced latte')
assert result.parsed_items, 'parsed_items should be populated'
print(f'Success: {len(result.parsed_items)} items')
"
```

---

## Phase 2: Handler Simplification (Medium Risk)

**Goal:** Update handlers to ONLY read from `parsed_items`, removing boolean flag checks.

### 2.1 Update `TakingItemsHandler._handle_taking_items_with_parsed()`

**File:** `orderbot/tasks/taking_items_handler.py`

```python
# BEFORE (multiple branches)
def _handle_taking_items_with_parsed(self, parsed, order):
    if parsed.parsed_items:
        return self._process_multi_item_order(parsed, order)
    elif parsed.new_coffee:
        # Handle single coffee...
    elif parsed.new_bagel:
        # Handle single bagel...
    # ... more branches

# AFTER (single path)
def _handle_taking_items_with_parsed(self, parsed, order):
    if not parsed.parsed_items:
        return self._no_items_detected(order)

    # Same code path for 1 or N items
    return self._process_items(parsed, order)
```

### 2.2 Rename `_process_multi_item_order()` → `_process_items()`

The function already handles any number of items. Rename to reflect this.

### 2.3 Remove dead code branches

Search for and remove:
- `if parsed.new_coffee:` branches
- `if parsed.new_bagel:` branches
- `if parsed.new_menu_item:` branches

**Verification:**
```bash
# Run integration tests
python -m pytest tests/test_tasks_integration.py -v
python -m pytest tests/test_critical_order_scenarios.py -v
```

---

## Phase 3: Unify ParsedItem Types (Medium Risk)

**Goal:** Replace `ParsedBagelEntry`, `ParsedCoffeeEntry` with unified `ParsedItemEntry`.

### Current State

```python
# Three separate types with different fields
class ParsedBagelEntry:
    type: Literal["bagel"]
    bagel_type: str
    toasted: bool
    spread: str
    # bagel-specific fields

class ParsedCoffeeEntry:
    type: Literal["coffee"]
    drink_type: str
    size: str
    temperature: str
    # coffee-specific fields

class ParsedItemEntry:  # NEW unified type
    type: Literal["item"]
    item_type: str  # "bagel", "sized_beverage", etc.
    attribute_values: dict  # {"bagel_type": "plain", "toasted": True}
```

### Target State

```python
# Single unified type
class ParsedItemEntry:
    type: Literal["item"] = "item"
    item_type: str  # "bagel", "sized_beverage", "deli_sandwich", etc.
    item_name: str | None  # Menu item name if applicable
    quantity: int = 1

    # ALL configuration via attribute_values (data-driven)
    attribute_values: dict = {}
    # Examples:
    # Bagel: {"bagel_type": "plain", "toasted": True, "spread": "cream cheese"}
    # Coffee: {"size": "large", "temperature": "iced", "milk": "oat"}

    # Modifiers that aren't attributes
    modifiers: list[str] = []  # ["extra bacon", "light cream cheese"]
    sweeteners: list[SweetenerItem] = []
    syrups: list[SyrupItem] = []

    special_instructions: str | None = None
    original_text: str | None = None

    # Backwards-compatible property accessors
    @property
    def bagel_type(self) -> str | None:
        return self.attribute_values.get("bagel_type")

    @property
    def toasted(self) -> bool | None:
        return self.attribute_values.get("toasted")

    @property
    def size(self) -> str | None:
        return self.attribute_values.get("size")

    # ... etc
```

### Migration Steps

1. **Update parsers** to create `ParsedItemEntry` instead of type-specific entries
2. **Update handler isinstance checks** from `isinstance(item, ParsedCoffeeEntry)` to `item.item_type == "sized_beverage"`
3. **Keep deprecated classes** with deprecation warnings for compatibility

---

## Phase 4: Remove Deprecated Fields (Breaking Change - Optional)

**Goal:** Clean up `OpenInputResponse` by removing boolean flag fields.

### Fields to Deprecate

```python
class OpenInputResponse:
    # REMOVE all of these:
    new_coffee: bool = False
    new_coffee_type: str | None = None
    new_coffee_size: str | None = None
    # ... 30+ more coffee fields

    new_bagel: bool = False
    new_bagel_type: str | None = None
    # ... 15+ more bagel fields

    new_signature_item: bool = False
    # ... more fields

    # KEEP only:
    parsed_items: list[ParsedItem] = []

    # Intent/action fields (not item-specific)
    wants_checkout: bool = False
    cancel_item: bool = False
    # etc.
```

### Risk Mitigation

1. **Mark fields as deprecated first** (add deprecation warnings)
2. **Run full test suite** to find any code still using them
3. **Update LLM parsers** to use `parsed_items` format
4. **Remove fields** only after all code migrated

---

## Implementation Order

| Phase | Risk | Effort | Benefit |
|-------|------|--------|---------|
| 1. Parser Dual-Write | Low | 2-3 hours | Enables Phase 2 |
| 2. Handler Simplification | Medium | 3-4 hours | Removes branching logic |
| 3. Unify ParsedItem Types | Medium | 4-6 hours | True data-driven parsing |
| 4. Remove Deprecated Fields | High | 2 hours + testing | Clean schema |

**Recommended approach:** Complete Phases 1-2 first. They provide immediate simplification with low risk. Phase 3 is optional but enables full data-driven architecture. Phase 4 is optional cleanup.

---

## Key Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| `parsers/deterministic.py` | 1 | Add `parsed_items` population to single-item parsers |
| `taking_items_handler.py` | 2 | Simplify to single code path |
| `schemas/parser_responses.py` | 3, 4 | Unify types, deprecate fields |
| `tests/test_tasks_parsing.py` | All | Update test assertions |

---

## Verification Checklist

After each phase:

```bash
# Unit tests
python -m pytest tests/test_tasks_parsing.py -v

# Integration tests
python -m pytest tests/test_tasks_integration.py -v

# Critical scenarios
python -m pytest tests/test_critical_order_scenarios.py -v

# Full suite
python -m pytest
```

---

## Example: Before and After

### Before (Current)

```python
# Parser returns different structures
result = parse_open_input_deterministic("large iced latte")
# result.new_coffee = True
# result.new_coffee_size = "large"
# result.parsed_items = [] (empty, populated by validator)

# Handler has multiple branches
if parsed.parsed_items:
    self._process_multi_item_order(parsed, order)
elif parsed.new_coffee:
    self._add_single_coffee(parsed, order)
elif parsed.new_bagel:
    self._add_single_bagel(parsed, order)
```

### After (Target)

```python
# Parser always returns parsed_items
result = parse_open_input_deterministic("large iced latte")
# result.parsed_items = [ParsedItemEntry(item_type="sized_beverage", ...)]

# Handler has single path
for item in parsed.parsed_items:
    self._add_item(item, order)
```

---

## Summary

The consolidation is **straightforward** because:

1. **Infrastructure already exists** - `parsed_items` field, `ParsedItemEntry` class
2. **Handlers already use `parsed_items`** - for multi-item orders
3. **Model validator provides safety net** - auto-converts boolean flags
4. **Incremental migration possible** - each phase is independent

The main work is updating parsers to dual-write and then simplifying handlers to use the single code path.
