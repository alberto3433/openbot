# TODO - Short Term Wins

Cleanup, rationalization, and simplification opportunities identified 2026-01-11.

## High Priority (Quick Wins)

- [x] **Consolidate `_extract_quantity()` and `WORD_TO_NUM`** into shared location ✓ DONE
  - Merged into `parsers/constants.py` as `extract_quantity()`
  - Removed ~50 lines of duplicated code from handlers

- [x] **Consolidate duplicate callback patterns** across handlers ✓ DONE
  - Removed dead stub from `coffee_config_handler.py`
  - `config_helper_handler.py` now imports from `state_machine.py` (lazy import to avoid circular deps)
  - ~50 lines of duplicate code removed

## Medium Priority (Schema Cleanup)

- [x] **Remove unused `OrderItem.extra` column** ✓ DONE
  - Migration: `d6e7f8g9h0i1_drop_unused_columns.py`
  - Removed column definition from `models.py`

- [x] **Remove unused `MenuItem.classifier` column** ✓ DONE
  - Migration: `d6e7f8g9h0i1_drop_unused_columns.py`
  - Dropped index `ix_menu_items_classifier` and column

- [~] **`MenuItem.extra_metadata` column** - STILL IN USE
  - Used in: `menu_index_builder.py`, seed files, admin routes
  - Keep for now - not actually unused

- [~] **`MenuItem.default_config` column** - STILL IN USE
  - Referenced in multiple places
  - Keep for now - not actually unused

## Medium-High Priority (Architecture)

- [x] **Create BaseHandler class** to consolidate handler initialization ✓ DONE
  - Added `BaseHandler` class to `handler_config.py`
  - Updated 5 handlers: CoffeeConfigHandler, ByPoundHandler, MenuItemConfigHandler,
    BagelConfigHandler, CheckoutHandler
  - ~100 lines of duplicate if/else config extraction removed

- [x] **Extract common attribute loading** into shared `attribute_loader.py` ✓ DONE
  - Created `tasks/attribute_loader.py` with `load_item_type_attributes()` function
  - Updated `coffee_config_handler.py` - reduced 100+ lines to ~15 lines
  - Updated `menu_item_config_handler.py` - uses shared loader for core attributes
  - Module-level cache for efficiency

## Low Priority

- [x] **Clean up unused imports** across handlers ✓ DONE
  - Cleaned: coffee_config_handler.py, config_helper_handler.py, handler_config.py, menu_item_config_handler.py
  - Removed unused: Callable, ItemTask, field, Any imports

- [x] **Consolidate pagination constants** ✓ DONE
  - Removed `OPTIONS_PAGE_SIZE` from `menu_item_config_handler.py`
  - Now uses `DEFAULT_PAGINATION_SIZE` from `parsers/constants.py` everywhere
