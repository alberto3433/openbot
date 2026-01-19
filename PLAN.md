# Plan: Remove Legacy `bagel_choice` Code and Dead Side Selection Logic

## Overview

The `handle_bagel_choice_for_side()` function and related `bagel_choice` infrastructure are legacy code from an OLD architecture where bagel type was stored on the parent item (omelette). The NEW architecture creates a child `MenuItemTask` for the bagel side, which uses the standard `bread` attribute.

This plan removes all dead code and cleans up the domain-specific `bagel_choice` references.

## Architecture Context

**OLD (Legacy):** Store everything on parent item
```
OmeletteItem:
  side_choice: "bagel"
  bagel_choice: "plain"  ← Domain-specific attribute
```

**NEW (Current):** Child item model
```
OmeletteItem:
  side_choice: "bagel"

BagelItem (child):
  side_of_item_id: omelette.id
  bread: "plain"  ← Standard bagel attribute
```

---

## Phase 1: Remove Dead Handler and Parser

### 1.1 Delete `handle_bagel_choice_for_side()`
**File:** `orderbot/tasks/config_helper_handler.py`
**Lines:** 698-744

This function is never called - no routing exists for it.

### 1.2 Delete `parse_bagel_choice()` function
**File:** `orderbot/tasks/parsers/llm_parsers.py`
**Lines:** 117-149

Only called by the dead handler above.

### 1.3 Remove `parse_bagel_choice` exports
**File:** `orderbot/tasks/parsers/__init__.py`
- Remove from imports (line ~57)
- Remove from `__all__` list (line ~151)

### 1.4 Remove unused import in state_machine
**File:** `orderbot/tasks/state_machine.py`
- Remove `parse_bagel_choice` from imports (line ~100)

### 1.5 Check and potentially remove `BagelChoiceResponse`
**File:** `orderbot/tasks/schemas/parser_responses.py`
- Check if `BagelChoiceResponse` class is used elsewhere
- If only used by dead `parse_bagel_choice`, delete it

---

## Phase 2: Remove Dead Model Methods

### 2.1 Delete `get_missing_customizations()` method
**File:** `orderbot/tasks/models.py`
**Lines:** 481-495

This method checks `self["requires_side_choice"]` which is always `None` in production because:
- Constructor kwarg `requires_side_choice=` is silently ignored by Pydantic
- The `{side_choice}_choice` pattern (e.g., "bagel_choice") is obsolete with child item model

### 2.2 Delete `is_fully_customized()` method
**File:** `orderbot/tasks/models.py`
**Lines:** 497-499

Only calls the dead `get_missing_customizations()` method.

---

## Phase 3: Remove No-op Constructor Arguments

### 3.1 Remove `requires_side_choice=` kwarg
**File:** `orderbot/tasks/item_adder_handler.py`
**Line:** ~471

```python
# BEFORE
item = MenuItemTask(
    ...
    requires_side_choice=has_side_choice,  # DELETE THIS LINE
    ...
)
```

### 3.2 Remove `requires_side_choice=` kwarg
**File:** `orderbot/tasks/configuring_item_handler.py`
**Line:** ~462

Same change as above.

---

## Phase 4: Clean Up LLM Prompts

### 4.1 Remove `bagel_choice` from prompt examples
**File:** `orderbot/tasks/parsing.py`

Remove/update these references:
- Line ~175: Remove "bagel_choice" from attribute examples
- Lines ~306-329: Remove bagel_choice examples from prompt
- Line ~373: Remove bagel_choice options inquiry example
- Line ~385: Remove "bagel_choice" from omelette attribute list

Replace domain-specific examples with generic ones or remove entirely.

---

## Phase 5: Clean Up Display Logic

### 5.1 Remove `{side_choice}_choice` pattern from display
**File:** `orderbot/services/order.py`
**Lines:** ~356-365

This code builds display names using `{side_choice}_choice` (e.g., "bagel_choice"). With child item model, the side item has its own display name.

Analyze if this code path is still used. If the child item model handles display correctly, this can be simplified or removed.

---

## Phase 6: Clean Up Deterministic Parser

### 6.1 Rename misleading variable
**File:** `orderbot/tasks/parsers/deterministic.py`
**Lines:** ~4120, ~4235

The variable `bagel_choice` is used but actually maps to `bread` attribute. Rename for clarity:
```python
# BEFORE
bagel_choice = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))

# AFTER
bread_type = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))
```

---

## Phase 7: Database Cleanup

### 7.1 Remove `bagel_choice` attribute from omelette item type
Create migration to:
1. Delete `attribute_options` rows linked to `bagel_choice` attribute for omelette
2. Delete `item_type_attributes` row for `bagel_choice` on omelette

The bagel type is now stored on the child bagel item's `bread` attribute.

---

## Phase 8: Update Tests

### 8.1 Fix tests using wrong pattern
Tests that use `attribute_values={"requires_side_choice": True}` are testing a code path that doesn't exist in production.

**Files to check:**
- `tests/test_omelette_cream_cheese.py`
- `tests/test_slot_orchestrator.py`
- `tests/test_tasks_integration.py`
- `tests/test_resiliency_batch1.py`

Update these tests to:
1. Use the child item model (create child MenuItemTask for bagel side)
2. Remove direct `bagel_choice` attribute setting on parent items
3. Remove `requires_side_choice` from `attribute_values`

### 8.2 Remove tests for dead methods
Any tests for `get_missing_customizations()` or `is_fully_customized()` should be removed.

---

## Execution Order

1. **Phase 1** - Remove dead handler/parser (safe, no dependencies)
2. **Phase 2** - Remove dead model methods (safe, never called)
3. **Phase 3** - Remove no-op constructor args (safe, already ignored)
4. **Phase 8** - Update tests (needed before Phase 4-7 to avoid test failures)
5. **Phase 4** - Clean up LLM prompts
6. **Phase 5** - Clean up display logic
7. **Phase 6** - Clean up deterministic parser
8. **Phase 7** - Database migration (last, after code is clean)

---

## Verification

After each phase, run:
```bash
python -m pytest tests/test_tasks_integration.py -v -k "omelette or side"
python -m pytest tests/test_slot_orchestrator.py -v
```

Final verification:
```bash
python -m pytest
```

---

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| 1-3 | Very Low | Code is confirmed dead/no-op |
| 4 | Low | LLM prompts are guidance, not logic |
| 5 | Medium | Display logic may have edge cases - test thoroughly |
| 6 | Low | Variable rename only |
| 7 | Medium | Database migration - test in staging first |
| 8 | Medium | Test updates may reveal hidden dependencies |

---

## Success Criteria

1. No references to `bagel_choice` in `orderbot/` directory (except comments explaining removal)
2. No `parse_bagel_choice` function or imports
3. No `get_missing_customizations` or `is_fully_customized` methods
4. No `requires_side_choice` constructor kwargs
5. All tests pass
6. Side selection flow works correctly with child item model
