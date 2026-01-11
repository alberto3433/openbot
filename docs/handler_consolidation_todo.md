# Handler Consolidation: Eliminate bagel_config_handler.py and coffee_config_handler.py

## Goal
Consolidate `bagel_config_handler.py` and `coffee_config_handler.py` into `menu_item_config_handler.py` to have a single, generic, DB-driven configuration handler.

## Current State
- `menu_item_config_handler.py` (~1560 lines): Generic DB-driven handler for deli_sandwich, egg_sandwich, fish_sandwich, spread_sandwich, espresso
- `bagel_config_handler.py` (~1370 lines): Specialized handler for bagels with multi-item orchestration
- `coffee_config_handler.py` (~1760 lines): Specialized handler for beverages with multi-item orchestration

## Steps

### Phase 1: Multi-Item Orchestration
- [x] Add `configure_next_incomplete_item(item_type)` method to MenuItemConfigHandler
- [x] Abstract the pattern from `configure_next_incomplete_bagel()` and `configure_next_incomplete_coffee()`
- [x] Handle item-specific incomplete detection (missing required attributes)
- [x] Support returning to TAKING_ITEMS when all items of type are complete
- [x] Update `_advance_to_next_question()` to optionally use multi-item orchestration

### Phase 2: Modifier Extraction During Config
- [x] Add hooks for extracting modifiers from user input during attribute configuration
- [x] Bagels: Extract proteins (bacon, sausage), cheeses (american, swiss), toppings (tomato, onion)
- [x] Coffee: Extract milk types, sweeteners, syrups, flavors
- [ ] Make modifier extraction configurable per item type in DB (optional enhancement)

### Phase 3: Disambiguation Framework
- [x] Generalize spread disambiguation (plain cc vs scallion vs veggie)
- [x] Generalize drink disambiguation (hot chocolate vs iced chocolate)
- [x] Support "remembered modifiers" during disambiguation
- [ ] Store disambiguation options in DB with trigger patterns (optional enhancement)

### Phase 4: Pricing Abstraction
- [x] Abstract `_recalculate_price()` to work with any item type
- [x] Use DB-driven pricing rules instead of hardcoded logic
- [x] Support item-type-specific price calculation hooks

### Phase 5: Field Naming Normalization
- [x] Analyze field naming patterns across handlers
- [x] Fix `toasted` dual-storage issue in `get_summary()`
- [x] Unify field names across item types:
  - bagel: `bagel_type` (property with `bread` fallback), `toasted`, `spread`
  - coffee: `drink_type`, `size`, `iced`, `milk` (all via attribute_values properties)
  - generic: `attribute_values` for DB-driven attributes
- [N/A] Create migration for any schema changes (not needed - compatibility layer handles it)
- [N/A] Update parsers to use normalized field names (already consistent)

### Phase 6: Migration & Cleanup
- [x] Add bagel and sized_beverage to SUPPORTED_ITEM_TYPES
- [x] Add LEGACY_FIELD_TO_ATTR mapping for field name translation
- [x] Add handle_legacy_field_input() method for routing legacy fields
- [x] Add _handle_coffee_style_input() for hot/iced boolean handling
- [x] Update state_machine.py with migration readiness comment
- [ ] Enable routing through MenuItemConfigHandler (blocked on DB config)
- [ ] Update taking_items_handler.py to use unified handler
- [ ] Remove bagel_config_handler.py
- [ ] Remove coffee_config_handler.py
- [ ] Update imports throughout codebase
- [ ] Run full test suite and fix any regressions

## Current Progress
**Completed**: Phase 1 - Multi-Item Orchestration, Phase 2 - Modifier Extraction, Phase 3 - Disambiguation Framework, Phase 4 - Pricing Abstraction, Phase 5 - Field Naming Normalization, Phase 6 - Infrastructure (partial)

### Phase 1 Implementation Details
Added to `menu_item_config_handler.py`:

1. **`configure_next_incomplete_item(order, item_type=None)`** (lines 1074-1190)
   - Finds all incomplete items of supported types (or specific item_type if provided)
   - Groups items by type for ordinal messaging ("the first espresso", "the second espresso")
   - Iterates through IN_PROGRESS items, asking mandatory questions
   - Handles customization checkpoint for each item
   - Returns to TAKING_ITEMS phase when all items are complete
   - Generates summary message with count pluralization

2. **Updated `_advance_to_next_question()`** (lines 1510-1544)
   - Added `use_multi_item_orchestration` parameter (default: False)
   - When True, calls `configure_next_incomplete_item()` instead of single-item flow
   - Enables backwards compatibility with existing single-item flows

### Phase 2 Implementation Details
Added modifier extraction system to `menu_item_config_handler.py`:

1. **`MODIFIER_EXTRACTION_TYPE`** class constant (lines 45-58)
   - Maps item types to extraction type: "food" or "beverage"
   - Food items (bagel, sandwich types) → ExtractedModifiers (proteins, cheeses, toppings, spreads)
   - Beverage items (espresso, sized_beverage) → ExtractedCoffeeModifiers (milk, sweetener, syrup)

2. **`_extract_modifiers_from_input(user_input, item_type)`** (lines 917-948)
   - Calls appropriate extraction function based on item type
   - Returns ExtractedModifiers or ExtractedCoffeeModifiers

3. **`_apply_extracted_modifiers(item, modifiers)`** (lines 950-1040)
   - Applies food modifiers: proteins → sandwich_protein/extras, cheeses/toppings → extras, spreads → item.spread
   - Applies beverage modifiers: milk/sweetener/syrup → attribute_values
   - Returns acknowledgment string for added modifiers

4. **`_extract_and_apply_modifiers(user_input, item)`** (lines 1042-1068)
   - Convenience method combining extraction and application
   - Called in `_handle_boolean_input` and `_handle_select_input` after attribute capture

5. **Integration points**:
   - `_handle_boolean_input()`: Extracts modifiers after capturing boolean (e.g., "yes with bacon")
   - `_handle_select_input()`: Extracts modifiers after capturing single/multi-select options

### Phase 3 Implementation Details
Added generic disambiguation framework to `menu_item_config_handler.py`:

1. **`pending_attr_disambiguation` field in OrderTask** (`models.py` lines 909-917)
   - New field to store disambiguation state between turns
   - Contains: options (list[dict]), attr_slug, modifiers (stored during disambiguation), item_id

2. **`_resolve_disambiguation(user_input, options)`** (lines 1214-1279)
   - Resolves user's selection from disambiguation options
   - Matching strategies (in order):
     - Exact match on display_name
     - Exact match on slug
     - First word match (e.g., "honey" → "honey walnut")
     - Substring match (e.g., "maple" → "maple raisin walnut")
     - Ordinal selection ("first one", "second", "1", "2")
   - Returns matched option dict or None

3. **`_handle_disambiguation_response(user_input, order)`** (lines 1281-1375)
   - Entry point for disambiguation resolution
   - Checks for pending disambiguation state
   - Calls `_resolve_disambiguation()` to match selection
   - Applies stored modifiers after resolution
   - Returns next question or re-asks if no match

4. **`_apply_stored_modifiers(item, modifiers)`** (lines 1377-1419)
   - Applies modifiers stored during disambiguation
   - Handles beverage modifiers: milk, sweetener, syrup, size, iced, decaf
   - Handles food modifiers: spread

5. **Updated `handle_attribute_input()`** (lines 1425-1432)
   - Added disambiguation check at start of method
   - If disambiguation pending, calls `_handle_disambiguation_response()`

6. **Updated `_handle_select_input()` partial matches** (lines 1642-1678)
   - When multiple partial matches found, stores disambiguation state
   - Extracts and stores modifiers from input before disambiguation
   - Sets `order.pending_attr_disambiguation` with options, attr_slug, modifiers, item_id

7. **Updated `is_configuring_item()` and `clear_pending()`** in OrderTask
   - `is_configuring_item()` returns True when `pending_attr_disambiguation` is set
   - `clear_pending()` clears `pending_attr_disambiguation`

### Phase 4 Implementation Details
Added pricing abstraction to `menu_item_config_handler.py`:

1. **`_recalculate_item_price(item)`** (lines 1074-1098)
   - Generic entry point for price recalculation
   - Delegates to specialized methods for bagels and beverages:
     - `item_type == "bagel"` → `self.pricing.recalculate_bagel_price(item)`
     - `item_type in ("sized_beverage", "espresso")` → `self.pricing.recalculate_coffee_price(item)`
   - For other item types, calls `_calculate_generic_item_price()`

2. **`_calculate_generic_item_price(item)`** (lines 1100-1135)
   - Calculates price from base price + attribute selections
   - Sums prices from all `*_selections` entries in `attribute_values`
   - Each selection has: `{slug, display_name, price, quantity}`
   - Updates `item.unit_price` with rounded total

3. **`_get_item_base_price(item)`** (lines 1137-1181)
   - Looks up base price from menu data:
     - First tries by `menu_item_id` in menu index
     - Then tries by `menu_item_name` lookup
   - Fallback: calculates from `unit_price - selections_total`

4. **Integration points** - added `_recalculate_item_price(item)` call before `mark_complete()`:
   - `get_first_question()`: For unsupported item types
   - `_ask_customization_checkpoint()`: When no optional attributes
   - `configure_next_incomplete_item()`: When item config complete
   - `_ask_more_customizations()`: When no more optional attributes
   - `handle_customization_checkpoint()`: When user says "no" to customization

### Phase 5 Implementation Details
Analysis of field naming patterns across item types:

1. **`bagel_type` / `bread`** - Already Normalized
   - Parser output uses `bagel_type`
   - Database attribute uses `bread` (shared with sandwiches)
   - `MenuItemTask.bagel_type` property already has compatibility layer:
     ```python
     return self.attribute_values.get("bagel_type") or self.attribute_values.get("bread")
     ```

2. **`toasted` Dual-Storage Issue** - Fixed
   - `bagel_config_handler` stores directly: `item.toasted = True`
   - `menu_item_config_handler` stores in: `attribute_values["toasted"] = True`
   - `get_summary()` only checked `attribute_values`, missing direct property
   - **Fix** (`models.py` lines 545-553): Now checks both locations:
     ```python
     toasted_from_attr = self.attribute_values.get("toasted")
     toasted_value = toasted_from_attr if toasted_from_attr is not None else self.toasted
     ```

3. **Coffee Fields** - Already Normalized
   - All beverage properties (`size`, `iced`, `milk`, etc.) backed by `attribute_values`
   - Property accessors provide clean interface
   - Parser `temperature` ("iced"/"hot") mapped to `iced` (bool) during item creation

4. **`spread`** - Consistent Storage
   - Stored as direct property `item.spread`
   - `spread_type` stored in `attribute_values["spread_type"]`
   - No normalization needed

### Phase 6 Implementation Details (In Progress)
Added infrastructure to `menu_item_config_handler.py`:

1. **Expanded `SUPPORTED_ITEM_TYPES`** (lines 43-46)
   - Added "bagel" and "sized_beverage" to supported types
   - Handler now recognizes these types for DB-driven configuration

2. **`LEGACY_FIELD_TO_ATTR` mapping** (lines 50-63)
   - Maps legacy `pending_field` names to DB attribute slugs:
     - Bagel: `bagel_choice` → `bread`, `spread` → `spread_type`, `toasted` → `toasted`
     - Coffee: `coffee_size` → `size`, `coffee_style` → `iced`, `syrup_flavor` → `syrup`
   - Enables routing legacy field handlers through generic handler

3. **`handle_legacy_field_input()`** (lines 1561-1597)
   - Entry point for legacy field routing
   - Translates field name via `LEGACY_FIELD_TO_ATTR`
   - Delegates to `handle_attribute_input()` with translated attribute

4. **`_handle_coffee_style_input()`** (lines 1599-1628)
   - Specialized handler for hot/iced boolean conversion
   - Maps "hot"/"iced" strings to boolean `iced` attribute

5. **State machine readiness comment** (`state_machine.py` lines 380-383)
   - Documents that infrastructure is ready
   - Explains routing will switch once DB is properly configured

**Blocker**: Full migration requires DB attribute configuration:
- Bagels need `spread_type` configured as mandatory (or optional with prompt)
- Beverages need "medium" size option added to DB
- Currently, specialized handlers have hardcoded flow logic that DB lacks

**Pre-existing test failures** (not caused by Phase 6):
- `test_bagel_toasted_should_ask_about_spread` - bagel handler doesn't ask spread
- `test_bagel_not_toasted_should_ask_about_spread` - same issue
- `test_change_spread_on_bagel_with_existing_spread` - spread modification issue

## Notes
- Preserve all existing functionality during consolidation
- Each phase should be independently testable
- Keep backwards compatibility with existing order data
