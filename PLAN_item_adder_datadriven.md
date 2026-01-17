# Plan: Make item_adder_handler.py Data-Driven

## Decisions
- **Approach**: Incremental (one phase at a time, tested between each)
- **Aliases**: Dropped - callers use canonical attribute names directly
- **Side choice options**: Reference existing attributes (not JSONB array)
- **Unified callbacks**: Yes, tackle as part of this work

---

## Phase 1: Database Schema Extensions

### 1.1 Add columns to `item_types` table

```sql
ALTER TABLE item_types ADD COLUMN display_name_singular VARCHAR(100);
ALTER TABLE item_types ADD COLUMN display_name_plural VARCHAR(100);
ALTER TABLE item_types ADD COLUMN has_side_choice BOOLEAN DEFAULT FALSE;
ALTER TABLE item_types ADD COLUMN side_choice_attribute_id INTEGER REFERENCES item_type_attributes(id);
ALTER TABLE item_types ADD COLUMN requires_configuration BOOLEAN DEFAULT FALSE;
```

### 1.2 Populate data

```sql
-- Display names
UPDATE item_types SET display_name_singular = 'Bagel', display_name_plural = 'Bagels' WHERE slug = 'bagel';
UPDATE item_types SET display_name_singular = 'Coffee', display_name_plural = 'Coffees' WHERE slug = 'sized_beverage';
UPDATE item_types SET display_name_singular = 'Omelette', display_name_plural = 'Omelettes' WHERE slug = 'omelette';

-- Side choice (omelette)
UPDATE item_types SET has_side_choice = TRUE WHERE slug = 'omelette';
-- side_choice_attribute_id will reference the "side_choice" attribute on omelette item type

-- Requires configuration
UPDATE item_types SET requires_configuration = TRUE
WHERE slug IN ('bagel', 'sized_beverage', 'deli_sandwich', 'egg_sandwich', 'fish_sandwich', 'spread_sandwich', 'omelette');
```

### 1.3 Update menu_data_cache.py

Add methods:
- `get_item_type_display_name(slug, plural=False) -> str`
- `item_type_has_side_choice(slug) -> bool`
- `get_side_choice_attribute(slug) -> dict | None`
- `item_type_requires_configuration(slug) -> bool`

### Verification
- Run existing tests - should all pass (no behavior change yet)
- Query new columns to verify data

---

## Phase 2: Replace Display Name Hardcoding

### Target Code (item_adder_handler.py:271-274)
```python
# BEFORE
if is_bread_item:
    canonical_name = "Bagel"
    base_price = self.pricing.lookup_base_price("Bagel")
```

### Change To
```python
# AFTER
if is_bread_item:
    canonical_name = menu_cache.get_item_type_display_name(item_type) or "Bagel"
    base_price = self.pricing.lookup_base_price(canonical_name)
```

### Verification
- Test bagel ordering still works
- Test display name appears correctly in responses

---

## Phase 3: Replace Omelette String Matching

### Target Code (item_adder_handler.py:454-455)
```python
# BEFORE
is_omelette = "omelette" in canonical_name.lower() or "omelet" in canonical_name.lower()
```

### Change To
```python
# AFTER
has_side_choice = menu_cache.item_type_has_side_choice(item_type or category)
```

### Target Code (item_adder_handler.py:508-516)
```python
# BEFORE
if is_omelette:
    order.pending_field = "side_choice"
    return StateMachineResult(
        message=f"Would you like a bagel or fruit salad with your {canonical_name}?",
        order=order,
    )
```

### Change To
```python
# AFTER
if has_side_choice:
    side_attr = menu_cache.get_side_choice_attribute(item_type or category)
    order.pending_field = side_attr.get("slug", "side_choice") if side_attr else "side_choice"
    question = side_attr.get("question_text") if side_attr else f"What side would you like with your {canonical_name}?"
    return StateMachineResult(message=question, order=order)
```

### Verification
- Test omelette ordering asks for side choice
- Test question text comes from DB
- Test non-omelette items don't trigger side choice

---

## Phase 4: Replace Category OR-Chain

### Target Code (item_adder_handler.py:458-473)
```python
# BEFORE
is_spread_sandwich = category == "spread_sandwich"
is_deli_sandwich = category == "deli_sandwich"
is_egg_sandwich = category == "egg_sandwich"
is_fish_sandwich = category == "fish_sandwich"
uses_db_config = is_deli_sandwich or is_egg_sandwich or is_fish_sandwich or is_spread_sandwich
```

### Change To
```python
# AFTER
uses_db_config = menu_cache.item_type_requires_configuration(category)
```

### Verification
- Test deli sandwich configuration flow
- Test egg sandwich configuration flow
- Test spread sandwich configuration flow
- Test non-configurable items skip config

---

## Phase 5: Remove is_soda_drink() Check

### Target Code (item_adder_handler.py:651-653)
```python
# BEFORE
if not skip_config and is_soda_drink(canonical_name):
    skip_config = True
```

### Change To
```python
# AFTER (remove entirely - DB skip_config flag handles this)
# The menu_item dict already has skip_config from DB lookup
```

### Prerequisites
- Verify all soda/bottled items have `skip_config=True` in database
- Or verify their item_type has appropriate flag

### Verification
- Test ordering soda doesn't ask configuration questions
- Test ordering coffee still asks for size

---

## Phase 6: Unify Item Configuration Callbacks

### Current State
```python
# item_adder_handler.py constructor
configure_next_incomplete_bagel: Callable[[OrderTask], StateMachineResult] | None = None,
configure_next_incomplete_coffee: Callable[[OrderTask], StateMachineResult] | None = None,
```

Used in 5+ files:
- item_adder_handler.py
- checkout_utils_handler.py
- handler_config.py
- state_machine.py
- taking_items_handler.py

### Target State
```python
# Single unified callback
configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None,
```

### Implementation Steps

#### 6.1 Create unified method in state_machine.py
```python
def _configure_next_incomplete_item(self, order: OrderTask) -> StateMachineResult:
    """Configure the next incomplete item of any type."""
    for item in order.items.get_incomplete_items():
        item_type = item.menu_item_type
        if menu_cache.item_type_requires_configuration(item_type):
            # Route to MenuItemConfigHandler for all types
            return self.menu_item_handler.get_first_question(item, order)
    return self._get_next_question(order)
```

#### 6.2 Update handler_config.py
- Replace two callbacks with one
- Update HandlerConfig dataclass

#### 6.3 Update item_adder_handler.py
- Remove bagel/coffee specific callbacks
- Use single `_configure_next_incomplete_item`

#### 6.4 Update checkout_utils_handler.py
- Replace type-specific callback checks with unified check:
```python
# BEFORE
if item.has_attribute('bread'):
    if self._configure_next_incomplete_bagel:
        return self._configure_next_incomplete_bagel(order)
elif item.has_attribute('size'):
    if self._configure_next_incomplete_coffee:
        return self._configure_next_incomplete_coffee(order)

# AFTER
if self._configure_next_incomplete_item:
    return self._configure_next_incomplete_item(order)
```

#### 6.5 Update taking_items_handler.py
- Similar changes to checkout_utils_handler.py

#### 6.6 Update state_machine.py wiring
- Wire single callback instead of two

### Verification
- Test bagel configuration flow end-to-end
- Test coffee configuration flow end-to-end
- Test sandwich configuration flow end-to-end
- Test mixed orders (bagel + coffee + sandwich)

---

## Phase 7: Clean Up Beverage-Specific Code in add_item()

### Target Code (item_adder_handler.py:118-188)
Large block of beverage-specific handling with hardcoded modifier keys.

### Strategy
This is lower priority. The code works and is somewhat data-driven already (uses menu_cache checks). Consider:
1. Move modifier key list to DB (beverage_modifier_attributes on item_type)
2. Or leave as-is since it's functional

### Decision
Defer to future cleanup. The callbacks unification (Phase 6) has higher impact.

---

## Phase 8: Clean Up _extract_pre_filled_attributes()

### Target Code (item_adder_handler.py:311-349)
Hardcoded mapping of kwargs to attribute names.

### Strategy
Since we dropped aliases, callers should pass canonical attribute names. This method can be simplified to just pass through kwargs that match known attributes:

```python
def _extract_pre_filled_attributes(self, item_type: str, kwargs: dict) -> dict:
    """Extract pre-filled attributes from kwargs."""
    known_attrs = menu_cache.get_item_type_attributes(item_type)
    return {k: v for k, v in kwargs.items() if k in known_attrs and v is not None}
```

### Prerequisites
- Update all callers to use canonical attribute names
- Search for usages of `bagel_type=`, `coffee_type=`, etc.

### Verification
- Test all item creation flows still work

---

## Execution Order

| Phase | Description | Risk | Dependencies |
|-------|-------------|------|--------------|
| 1 | DB schema + cache methods | Low | None |
| 2 | Display name from DB | Low | Phase 1 |
| 3 | Side choice from DB | Medium | Phase 1 |
| 4 | Configuration flag from DB | Low | Phase 1 |
| 5 | Remove is_soda_drink | Low | Phase 4 |
| 6 | Unify callbacks | High | Phases 1-4 |
| 7 | Beverage code cleanup | Low | Phase 6 |
| 8 | Pre-filled attrs cleanup | Medium | Phase 6 |

---

## Files Modified (Summary)

| File | Phases |
|------|--------|
| alembic migration (new) | 1 |
| orderbot/menu_data_cache.py | 1 |
| orderbot/tasks/item_adder_handler.py | 2, 3, 4, 5, 6, 7, 8 |
| orderbot/tasks/handler_config.py | 6 |
| orderbot/tasks/state_machine.py | 6 |
| orderbot/tasks/checkout_utils_handler.py | 6 |
| orderbot/tasks/taking_items_handler.py | 6 |

---

## Success Criteria

After all phases:
1. No hardcoded item type names in item_adder_handler.py (except logging)
2. No string matching on item names to determine behavior
3. Single unified callback for item configuration
4. Adding a new configurable item type requires only DB changes
5. All existing tests pass
6. Manual testing of bagel, coffee, sandwich, omelette flows works
