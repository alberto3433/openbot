# Refactoring Plan

## Quick Wins (Low Effort, Immediate Benefit)

### 1. Cache Decorator - Eliminate `_ensure_loaded()` Boilerplate
**Status:** [x] Complete
**Effort:** Low
**Files:** `cache/base.py`, `cache/*_queries.py`

**Problem:** `self._ensure_loaded()` is called at the start of 50+ cache methods.

**Solution:** Create an `@ensure_cache_loaded` decorator that wraps methods automatically.

```python
# Before (repeated 50+ times)
def get_item_type(self, slug: str) -> ItemType | None:
    self._ensure_loaded()
    return self._item_types_by_slug.get(slug)

# After
@ensure_cache_loaded
def get_item_type(self, slug: str) -> ItemType | None:
    return self._item_types_by_slug.get(slug)
```

**Implementation Steps:**
- [x] Add `ensure_cache_loaded` decorator to `cache/base.py`
- [x] Apply decorator to methods in `cache/item_type_core_queries.py`
- [x] Apply decorator to methods in `cache/ingredient_queries.py`
- [x] Apply decorator to methods in `cache/menu_queries.py`
- [x] Apply decorator to methods in `cache/attribute_queries.py`
- [x] Run tests to verify no regressions

---

### 2. State Machine Dispatch Dictionary
**Status:** [x] Complete
**Effort:** Low
**Files:** `tasks/state_machine.py`

**Problem:** Long if-elif chain for phase routing (lines ~405-450).

**Solution:** Replace with a dispatch dictionary mapping phases to handler methods.

```python
# Before
if order.is_configuring_item():
    result = self._handle_configuring_item(user_input, order)
elif order.phase == OrderPhase.GREETING.value:
    result = self._handle_greeting(user_input, order)
# ... 6 more elif blocks

# After
self._phase_handlers = {
    OrderPhase.GREETING.value: self._handle_greeting,
    OrderPhase.TAKING_ITEMS.value: self._handle_taking_items,
    # ...
}
handler = self._phase_handlers.get(order.phase)
if handler:
    result = handler(user_input, order)
```

**Implementation Steps:**
- [x] Create `_phase_handlers` dispatch dict in `__init__`
- [x] Handle special case for `is_configuring_item()` check
- [x] Replace if-elif chain with dict lookup
- [x] Run tests to verify no regressions

---

### 3. Dead Code Analysis with Vulture
**Status:** [x] Complete
**Effort:** Low
**Files:** Entire codebase

**Problem:** Potentially unused imports, functions, or classes accumulating.

**Solution:** Run static analysis to identify and remove dead code.

**Implementation Steps:**
- [x] Install vulture: `pip install vulture`
- [x] Run: `vulture orderbot/ --min-confidence 80`
- [x] Review results and remove confirmed dead code
- [x] Run tests to verify no regressions

**Removed dead code:**
- `cache/category_queries.py`: `get_category_needing_clarification()`
- `cache/menu_queries.py`: `resolve_side_alias()`, `find_menu_item_matches()`
- `tasks/parsers/constants.py`: `normalize_text()`
- `tasks/utils/constants.py`: `is_attr_metadata_key()`
- `tasks/pricing.py`: `lookup_size_upcharge()`
- `tasks/utils/disambiguation_utils.py`: `match_by_input_in_name()`
- `db/models/menu.py`: Renamed unused SQLAlchemy event params to `_mapper`, `_connection`

**False positives ignored:**
- `rapidfuzz` import in `unrecognized_item_handler.py` (try/except availability check)

---

### 4. Handler Registry Property Simplification
**Status:** [x] Complete
**Effort:** Low
**Files:** `tasks/handler_registry.py`

**Problem:** Lines 180-227 define repetitive property accessors for handlers.

**Solution:** Use `__getattr__` for dynamic property access.

**Implementation Steps:**
- [x] Add `__getattr__` method to HandlerRegistry
- [x] Remove 12 individual property definitions (48 lines → 12 lines)
- [x] Run tests to verify no regressions

**Result:** Replaced 12 repetitive `@property` methods with a single `__getattr__` method.

---

### 5. Inquiry Parser Helper Utilities
**Status:** [x] Complete
**Effort:** Low-Medium
**Files:** `parsers/deterministic/inquiry/*.py`

**Problem:** ~700+ LOC of repeated pattern-matching boilerplate across inquiry parsers.

**Solution:** Created shared helper utilities instead of a rigid base class (parsers have different logic flows).

**Implementation Steps:**
- [x] Create `helpers.py` with shared utilities: `first_match()`, `any_pattern_matches()`, `extract_group()`, `log_inquiry()`, `simple_inquiry_check()`
- [x] Refactor `store_info.py` to use helpers
- [x] Refactor `description.py` to use helpers
- [x] Refactor `price.py` to use helpers
- [x] Run tests to verify no regressions (61 inquiry tests pass)

**Result:** Lighter-touch approach reduces boilerplate without forcing parsers into rigid structure.

---

## Medium Impact

### 6. Split Large Handlers
**Status:** [ ] Not Started
**Effort:** High
**Files:** `configuring_item_handler.py`, `item_adder_handler.py`, `config_helper_handler.py`

**Problem:** 1000+ LOC files with multiple responsibilities.

**Solution:** Extract focused sub-handlers with single responsibilities.

**Implementation Steps:**
- [ ] Analyze `configuring_item_handler.py` responsibilities
- [ ] Extract disambiguation logic to separate module
- [ ] Extract pending item processing to separate module
- [ ] Repeat for `item_adder_handler.py` and `config_helper_handler.py`
- [ ] Run tests to verify no regressions

---

### 7. Handler Dependency Injection
**Status:** [ ] Not Started
**Effort:** High
**Files:** `handler_registry.py`, all handler files

**Problem:** Complex manual callback wiring, fragile initialization order.

**Solution:** Implement structured dependency injection or service locator.

**Implementation Steps:**
- [ ] Design DI container or service locator pattern
- [ ] Refactor handlers to declare dependencies explicitly
- [ ] Remove manual callback wiring from registry
- [ ] Run tests to verify no regressions

---

## Progress Tracking

| Item | Status | Date Completed |
|------|--------|----------------|
| 1. Cache Decorator | [x] | 2026-02-03 |
| 2. State Machine Dispatch | [x] | 2026-02-03 |
| 3. Dead Code Analysis | [x] | 2026-02-03 |
| 4. Handler Registry Properties | [x] | 2026-02-03 |
| 5. Inquiry Parser Helpers | [x] | 2026-02-03 |
| 6. Split Large Handlers | [ ] | |
| 7. Handler DI | [ ] | |

## Review Notes

_Add observations and lessons learned here after each refactoring._
