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

---

## Quick Wins (New - 2026-02-04)

### 6. Remove Deprecated Alias in simple_item_parsing.py
**Status:** [x] Complete
**Effort:** Low
**Files:** `tasks/parsers/deterministic/simple_item_parsing.py`

**Problem:** Line 141 had deprecated `_parse_soda_deterministic` alias.

**Implementation Steps:**
- [x] Find and remove deprecated alias from `simple_item_parsing.py`
- [x] Update tests in `test_soda_aliases.py` to use `_parse_simple_item_deterministic`
- [x] Remove exports from `parsers/__init__.py` and `parsers/deterministic/__init__.py`
- [x] Run tests to verify no regressions (17 tests pass)

**Result:** Removed deprecated alias and updated 4 test methods to use the correct function name.

---

### 7. Merge item_type_queries.py into item_type_core_queries.py
**Status:** [x] Not Needed
**Effort:** N/A
**Files:** `cache/item_type_queries.py`

**Analysis:** `ItemTypeQueryMixin` is a deliberate **facade pattern** that aggregates 4 sub-mixins:
- `ItemTypeCoreQueryMixin`
- `AttributeQueryMixin`
- `OptionQueryMixin`
- `KeywordQueryMixin`

This provides a cleaner inheritance chain in `core.py`. Merging would make `core.py` inherit from 4 more classes directly, making the inheritance chain even longer. Keep as-is.

---

### 8. Address TODO in attribute_queries.py
**Status:** [x] Documented (Requires DB Investigation)
**Effort:** Medium (if fix needed)
**Files:** `cache/attribute_queries.py`

**Problem:** Line 299 has TODO: `# TODO: Remove once DB has proper ingredient_group -> attribute mapping`

**Analysis (2026-02-04):**
The fallback mapping handles cases where ingredient categories don't match attribute slugs:
- `protein` → tries `meat`, `extra_protein`, `protein`
- `condiment` → tries `spread`, `toppings`, `condiments`

This is a real mapping issue. The fix would require one of:
1. Add `ingredient_group` field to `GlobalAttribute` or `ItemTypeGlobalAttribute`
2. Expand `ingredient_categories.code_field_name` to support multiple fallbacks
3. Rename ingredient categories to match attribute slugs (breaking change)

**Next Steps:**
- [ ] When DB is accessible, query to see if `ingredient_categories.code_field_name` covers all cases
- [ ] If not, create migration to add proper mapping
- [ ] Then remove the hardcoded fallback

---

## Medium Impact

### 9. Normalization Consolidation
**Status:** [x] Complete
**Effort:** Medium
**Files:** 5 files with overlapping normalization logic

**Problem:** Duplicate normalization functions scattered across:
| File | Functions |
|------|-----------|
| `tasks/normalization.py` | `normalize_for_option_match()`, `normalize_for_match()`, `normalize_to_slug()` |
| `tasks/utils/input_normalizer.py` | `normalize_input()`, strip/singularize logic |
| `tasks/parsers/constants.py` | `normalize_text()` (removed in dead code pass) |
| `tasks/utils/disambiguation_utils.py` | `normalize_input()` |
| `tasks/utils/option_matcher.py` | Internal normalization |

**Solution Implemented:**
1. Added comprehensive module docstring to `normalization.py` documenting the full API
2. Added `strip_filler_words()` function to `normalization.py`
3. Added `__all__` export list to `normalization.py`
4. Re-exported `singularize` from `normalization.py` for convenience
5. Updated `disambiguation_utils.normalize_input()` to delegate to `strip_filler_words()`
6. Updated `input_normalizer.py` to import `singularize` from `normalization.py`

**Final API in `normalization.py`:**
- `strip_ordering_prefix(text)` - Remove "I want", "can I get", etc.
- `strip_filler_words(text)` - Remove "the", "please", "just", etc.
- `normalize_for_option_match(text)` - Strip quantities, singularize plurals
- `normalize_for_match(text)` - Remove spaces/& for fuzzy matching
- `normalize_to_slug(text)` - Convert to slug format
- `format_slug_for_display(slug)` - Convert slug to display
- `resolve_to_canonical(attr_slug, value)` - Resolve to DB canonical form
- `singularize(word)` - Re-exported from cache.base

**Implementation Steps:**
- [x] Audit all normalization functions across 5 files
- [x] Identify which variations are needed vs duplicates
- [x] Create unified API in `normalization.py`
- [x] Update callers to use unified functions (disambiguation_utils, input_normalizer)
- [x] Remove duplicate implementations (now delegate to normalization.py)
- [x] Run tests to verify no regressions (41 disambiguation tests pass)

---

### 10. Deprecate Old Matching Utilities
**Status:** [x] Complete
**Effort:** Medium
**Files:** `tasks/utils/disambiguation_utils.py`, `tasks/utils/option_matcher.py`

**Problem:** `disambiguation_utils.py` had basic matching functions that predated `OptionMatcher`:
- `match_by_ordinal()`
- `match_by_name_exact()`
- `match_by_alias_exact()`
- `match_by_name_in_input()`
- `match_by_word()`

These overlapped with `OptionMatcher`'s multi-phase matching.

**Solution Implemented:**
1. Added `match_from_numbered_list()` method to `OptionMatcher` with:
   - Ordinal matching ("1", "first", "second", etc.)
   - Raw exact match (before normalization)
   - Exact name/slug/alias matching
   - Option name in user input matching
   - Word-boundary alias matching
   - NO partial matching in wrong direction (prevents "ham" matching "Black Forest Ham")

2. Added `ORDINAL_PATTERNS` constant to `option_matcher.py`

3. Migrated callers to use `OptionMatcher.match_from_numbered_list()`:
   - `disambiguation_handler.py` - now uses shared `_option_matcher` instance
   - `config/disambiguation.py` - now uses shared `_option_matcher` instance

4. Removed deprecated functions from `disambiguation_utils.py`:
   - Removed `match_by_ordinal()`, `match_by_name_exact()`, `match_by_alias_exact()`,
     `match_by_name_in_input()`, `match_by_word()`, `ORDINAL_PATTERNS`
   - Kept: `normalize_input()`, `get_aliases()`, `format_options_list()`

**Implementation Steps:**
- [x] Identify all callers of deprecated functions
- [x] Add `match_from_numbered_list()` to `OptionMatcher`
- [x] Migrate callers to use `OptionMatcher`
- [x] Remove deprecated functions from `disambiguation_utils.py`
- [x] Run tests to verify no regressions (41 disambiguation tests pass)

---

### 11. Config Handler Consolidation
**Status:** [ ] Not Started
**Effort:** Medium-High
**Files:** 5 config-related handler files

**Problem:** Over-abstracted config handling split across:
- `tasks/config/handler.py` - MenuItemConfigHandler
- `tasks/config_helper_handler.py` - Config utilities
- `tasks/config_cancellation_handler.py` - Cancellation during config
- `tasks/config_modification_handler.py` - Modification during config
- `tasks/config_selection_handler.py` - Selection during config

**Solution:** Consolidate into single `ConfigurationOrchestrator` with internal methods.

**Implementation Steps:**
- [ ] Map responsibilities of each handler
- [ ] Design unified `ConfigurationOrchestrator` interface
- [ ] Implement consolidated handler
- [ ] Update state machine to use new handler
- [ ] Remove old handler files

---

### 12. Split Large Handlers
**Status:** [ ] Not Started
**Effort:** High
**Files:** `item_adder_handler.py` (1019), `taking_items_handler.py` (755), `modifier_input_handler.py` (741), `checkout_handler.py` (664)

**Problem:** Files over 700 lines are hard to navigate and test.

**12a. item_adder_handler.py (1019 lines)**
- [ ] Extract attribute inference logic (may already be in `attribute_inference.py`)
- [ ] Verify `UnrecognizedItemHandler` is fully utilized
- [ ] Target: ~400 lines

**12b. taking_items_handler.py (755 lines)**
- [ ] Verify `parsed_item_processor.py` is fully utilized
- [ ] Extract quantity extraction if separate
- [ ] Target: ~400 lines

**12c. modifier_input_handler.py (741 lines)**
- [ ] Extract pattern generation to `modifier_patterns.py`
- [ ] Extract validation to `modifier_validator.py`
- [ ] Target: ~400 lines

**12d. checkout_handler.py (664 lines)**
- [ ] Extract payment handling to `payment_handler.py`
- [ ] Target: ~400 lines

---

### 13. Cache Query Consolidation
**Status:** [ ] Not Started
**Effort:** Medium
**Files:** 10 query mixin files

**Problem:** Too many small query files:
- `menu_queries.py` (719 lines)
- `ingredient_queries.py` (488 lines)
- `attribute_queries.py` (342 lines)
- `item_type_core_queries.py` (341 lines)
- `option_queries.py` (248 lines)
- `pricing_queries.py` (225 lines)
- `parsing_queries.py` (217 lines)
- `category_queries.py` (145 lines)
- `keyword_queries.py` (126 lines)
- `item_type_queries.py` (42 lines) - keep as facade (see item #7)

**Target state** (5-6 files):
- `item_queries.py` - menu items + item types
- `modifier_queries.py` - ingredients + options
- `attribute_queries.py` - attributes + categories + keywords
- `pricing_queries.py` - keep as is
- `parsing_queries.py` - keep as is

**Implementation Steps:**
- [ ] Map which queries are actually used
- [ ] Group by domain responsibility
- [ ] Merge files with clear module docstrings
- [ ] Update `cache/__init__.py` imports

---

### 14. Adapter/Converter Clarification
**Status:** [ ] Not Started
**Effort:** Medium
**Files:** `adapter.py`, `state_machine_adapter.py`, `item_converters.py`, `order_item_builder.py`

**Problem:** 4 files with unclear responsibility boundaries.

**Implementation Steps:**
- [ ] Document current responsibility of each file
- [ ] Identify overlaps
- [ ] Either merge or clearly separate with docstrings
- [ ] Consider renaming for clarity

---

### 15. Handler Dependency Injection
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

## Backlog (Lower Priority)

- [ ] Extract helper `get_attributes_to_ask_in_conversation()` in cache
- [ ] Centralize response message generation patterns
- [ ] Audit unused imports in large files
- [ ] Review `pass` statements for incomplete implementations
- [ ] Add module-level docstrings to all files

---

## Progress Tracking

| Item | Status | Date Completed |
|------|--------|----------------|
| 1. Cache Decorator | [x] | 2026-02-03 |
| 2. State Machine Dispatch | [x] | 2026-02-03 |
| 3. Dead Code Analysis | [x] | 2026-02-03 |
| 4. Handler Registry Properties | [x] | 2026-02-03 |
| 5. Inquiry Parser Helpers | [x] | 2026-02-03 |
| 6. Remove Deprecated Alias | [x] | 2026-02-04 |
| 7. Merge item_type_queries | N/A (not needed) | 2026-02-04 |
| 8. Address TODO attribute_queries | Documented | 2026-02-04 |
| 9. Normalization Consolidation | [x] | 2026-02-04 |
| 10. Deprecate Old Matching Utils | [x] | 2026-02-04 |
| 11. Config Handler Consolidation | [ ] | |
| 12. Split Large Handlers | [ ] | |
| 13. Cache Query Consolidation | [ ] | |
| 14. Adapter/Converter Clarification | [ ] | |
| 15. Handler DI | [ ] | |

## Review Notes

### 2026-02-04: Quick Wins Session

**Item #6 (Deprecated Alias):**
- Removed `_parse_soda_deterministic` alias from `simple_item_parsing.py`
- Updated 4 tests in `test_soda_aliases.py` to use `_parse_simple_item_deterministic`
- Removed exports from both `__init__.py` files
- All 17 soda alias tests pass

**Item #7 (Merge item_type_queries):**
- Investigation revealed this is a deliberate **facade pattern**, not dead code
- `ItemTypeQueryMixin` aggregates 4 sub-mixins for cleaner inheritance in `core.py`
- Marked as "Not Needed" - keep the current architecture

**Item #8 (TODO in attribute_queries):**
- The fallback mapping (`protein -> meat/extra_protein`, `condiment -> spread/toppings`) is still needed
- Root cause: ingredient categories don't always match attribute slugs
- Requires DB schema investigation when database is accessible
- Documented potential fixes in the item description

### 2026-02-04: Normalization Consolidation

**Item #9 (Normalization Consolidation):**
- Added comprehensive module docstring to `normalization.py` documenting the full public API
- Added `strip_filler_words()` function - extracts the filler word removal logic
- Added `__all__` export list with all public functions
- Re-exported `singularize` from `normalization.py` for convenience
- Updated `disambiguation_utils.normalize_input()` to delegate to `strip_filler_words()`
- Updated `input_normalizer.py` to import `singularize` from `normalization.py`
- All 41 disambiguation tests pass
- `normalization.py` is now the single source of truth for all text normalization

**Item #10 (Deprecate Old Matching Utils):**
- Added `match_from_numbered_list()` method to `OptionMatcher` - handles ordinal + exact + alias + partial matching
- Added `ORDINAL_PATTERNS` constant (18 patterns for "1", "first", "one", etc.)
- Migrated `disambiguation_handler.py` to use `OptionMatcher.match_from_numbered_list()`
- Migrated `config/disambiguation.py` to use `OptionMatcher.match_from_numbered_list()`
- Removed 6 deprecated functions from `disambiguation_utils.py`:
  - `match_by_ordinal()`, `match_by_name_exact()`, `match_by_alias_exact()`
  - `match_by_name_in_input()`, `match_by_word()`, `ORDINAL_PATTERNS`
- Kept only display utilities: `normalize_input()`, `get_aliases()`, `format_options_list()`
- `disambiguation_utils.py` reduced from 248 lines to 83 lines (66% reduction)
- All 41 disambiguation tests pass
