# Design: Relational Menu Item Configuration Schema

## Goal

Eliminate JSON fields (like `default_config`) and create a proper relational structure where:
1. Item types define what configuration fields are available
2. Menu items store their configuration values in child tables
3. Admin UI can present clean forms instead of JSON editors
4. New menu items automatically inherit configurable fields from their type

---

## Current State Analysis

### Two Parallel Configuration Systems Exist

| Table | Purpose | Item Types Using It |
|-------|---------|---------------------|
| `item_type_field` | Conversational flow questions (what to ask) | bagel (4), sized_beverage (4), espresso (1) |
| `attribute_definitions` | UI configuration options | bagel (5), omelette (5), salad_sandwich (3), sandwich (3), sized_beverage (6), spread_sandwich (3) |

### Problem: Most Item Types Have NO Configuration

| Item Type | is_configurable | attr_defs | item_type_fields | Config Source |
|-----------|-----------------|-----------|------------------|---------------|
| `egg_sandwich` | false | 0 | 0 | `default_config` JSON only |
| `signature_sandwich` | true | 0 | 0 | `default_config` JSON only |
| `deli_classic` | true | 0 | 0 | `default_config` JSON only |
| `fish_sandwich` | false | 0 | 0 | `default_config` JSON only |
| `bagel` | true | 5 | 4 | Both systems + JSON |
| `sized_beverage` | true | 6 | 4 | Both systems |

### Current `default_config` Usage (The Lexington Example)

```json
{
  "bread": "Bagel",
  "protein": "Egg White",
  "cheese": "Swiss",
  "toppings": ["Spinach"]
}
```

This JSON is:
- Stored in `menu_items.default_config` column
- Used by LLM to describe ingredients
- Used to answer "What's on The Lexington?"
- **NOT** used when actually ordering (see `docs/lexington-ingredients-analysis.md`)

---

## Proposed Schema

### Option A: Extend `attribute_definitions` + Add `menu_item_attribute_values`

```
item_types (existing)
    │
    └──> attribute_definitions (existing, extend for all types)
              │
              ├──> attribute_options (existing, for select types)
              │
              └──< menu_item_attribute_values (NEW)
                        │
                        └──< menu_items (existing)
```

**New Table: `menu_item_attribute_values`**
```sql
CREATE TABLE menu_item_attribute_values (
    id SERIAL PRIMARY KEY,
    menu_item_id INTEGER REFERENCES menu_items(id),
    attribute_definition_id INTEGER REFERENCES attribute_definitions(id),

    -- For single_select: store the selected option
    option_id INTEGER REFERENCES attribute_options(id),

    -- For multi_select: use a separate join table OR store as array
    -- For boolean: store true/false
    value_boolean BOOLEAN,

    -- For free text (rarely needed)
    value_text TEXT,

    UNIQUE(menu_item_id, attribute_definition_id)
);

-- For multi-select values
CREATE TABLE menu_item_attribute_multi_values (
    id SERIAL PRIMARY KEY,
    menu_item_id INTEGER REFERENCES menu_items(id),
    attribute_definition_id INTEGER REFERENCES attribute_definitions(id),
    option_id INTEGER REFERENCES attribute_options(id)
);
```

### Option B: Consolidate `item_type_field` + `attribute_definitions`

These two tables serve similar purposes:
- `item_type_field`: What questions to ask during ordering
- `attribute_definitions`: What options are available for configuration

**Proposed Consolidated Table: `item_type_attributes`**
```sql
CREATE TABLE item_type_attributes (
    id SERIAL PRIMARY KEY,
    item_type_id INTEGER REFERENCES item_types(id),

    -- Identity
    slug VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),

    -- Type and validation
    input_type VARCHAR(20), -- 'single_select', 'multi_select', 'boolean', 'text'
    is_required BOOLEAN DEFAULT false,
    allow_none BOOLEAN DEFAULT true,
    min_selections INTEGER,
    max_selections INTEGER,

    -- Ordering/conversational flow
    display_order INTEGER DEFAULT 0,
    ask_in_conversation BOOLEAN DEFAULT true,  -- Renamed from 'ask'
    question_text TEXT,

    UNIQUE(item_type_id, slug)
);
```

---

## Design Questions for You

### Q1: Consolidation Strategy

Should we:
- **A) Consolidate** `item_type_field` and `attribute_definitions` into one table?
- **B) Keep separate** but ensure both are populated for all configurable types?

The current situation has:
- `bagel` with 4 fields in `item_type_field` AND 5 in `attribute_definitions` (different!)
- `omelette` with 5 in `attribute_definitions` but 0 in `item_type_field`

### Q2: Multi-Select Storage

For fields like `toppings: ["Spinach", "Tomato"]`:
- **A) Join table** (`menu_item_attribute_multi_values`)
- **B) Array column** (PostgreSQL array type)
- **C) JSON array** (keep some JSON, just structured)

### Q3: Menu Item Creation Workflow

When creating a new `egg_sandwich` in the admin:

**Current flow:**
1. Create menu item
2. Manually fill `default_config` JSON

**Proposed flow:**
1. Select item type: "Egg Sandwich"
2. System loads attribute definitions for egg_sandwich
3. Present form: Bread [select], Protein [select], Cheese [select], Toppings [multi-select]
4. Save creates menu item + child records

Should the system:
- **A) Pre-create** all attribute value records (empty) when menu item is created?
- **B) Only create** records when values are entered?

### Q4: Default Values in Type vs Instance

Where should defaults live?
- **Type level**: "Egg sandwiches default to bagel bread"
- **Instance level**: "The Lexington is egg whites, swiss, spinach"

Current `attribute_options.is_default` suggests type-level defaults.
But menu items can override (The Lexington has specific ingredients).

Proposal:
- Type-level defaults in `attribute_options.is_default`
- Instance overrides in `menu_item_attribute_values`
- If no instance value, use type default

### Q5: What About Kitchen Tickets?

Currently, kitchen sees "The Lexington" and knows what to make.
With this change, should kitchen tickets show:
- **A) Just the name**: "The Lexington"
- **B) Name + ingredients**: "The Lexington (Egg White, Swiss, Spinach)"
- **C) Full breakdown**: "Bagel, Egg White, Swiss, Spinach"

---

## Migration Path (Detailed)

### User Decisions
- **Consolidate**: Merge `item_type_field` + `attribute_definitions` into one table
- **Multi-select**: Use join table
- **Pre-create**: Create empty records when menu item created
- **Defaults**: Set at menu item level (not type level)
- **Kitchen tickets**: No changes to current display logic

---

### Phase 1: Schema Creation

**1.1 Create consolidated attribute definition table**
```sql
-- Alembic migration: consolidate_item_type_attributes

CREATE TABLE item_type_attributes (
    id SERIAL PRIMARY KEY,
    item_type_id INTEGER NOT NULL REFERENCES item_types(id) ON DELETE CASCADE,

    -- Identity
    slug VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),

    -- Type and validation
    input_type VARCHAR(20) NOT NULL DEFAULT 'single_select',
        -- 'single_select', 'multi_select', 'boolean', 'text'
    is_required BOOLEAN DEFAULT false,
    allow_none BOOLEAN DEFAULT true,
    min_selections INTEGER,
    max_selections INTEGER,

    -- Conversational flow
    display_order INTEGER DEFAULT 0,
    ask_in_conversation BOOLEAN DEFAULT true,
    question_text TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(item_type_id, slug)
);

CREATE INDEX idx_item_type_attributes_type ON item_type_attributes(item_type_id);
```

**1.2 Create attribute options table (reuse existing or recreate)**
```sql
-- Keep existing attribute_options structure but reference new table
-- OR migrate data to new foreign key

CREATE TABLE item_type_attribute_options (
    id SERIAL PRIMARY KEY,
    attribute_id INTEGER NOT NULL REFERENCES item_type_attributes(id) ON DELETE CASCADE,

    slug VARCHAR(50) NOT NULL,
    display_name VARCHAR(100),
    price_modifier DECIMAL(10,2) DEFAULT 0,
    is_available BOOLEAN DEFAULT true,
    display_order INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(attribute_id, slug)
);

CREATE INDEX idx_attr_options_attr ON item_type_attribute_options(attribute_id);
```

**1.3 Create menu item attribute values table**
```sql
CREATE TABLE menu_item_attribute_values (
    id SERIAL PRIMARY KEY,
    menu_item_id INTEGER NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    attribute_id INTEGER NOT NULL REFERENCES item_type_attributes(id) ON DELETE CASCADE,

    -- For single_select and boolean
    option_id INTEGER REFERENCES item_type_attribute_options(id),
    value_boolean BOOLEAN,
    value_text TEXT,

    -- Whether to still ask user even if there's a default value
    still_ask BOOLEAN DEFAULT false,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(menu_item_id, attribute_id)
);

CREATE INDEX idx_menu_item_attr_values_item ON menu_item_attribute_values(menu_item_id);
```

**1.4 Create multi-select values join table**
```sql
CREATE TABLE menu_item_attribute_multi_values (
    id SERIAL PRIMARY KEY,
    menu_item_id INTEGER NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
    attribute_id INTEGER NOT NULL REFERENCES item_type_attributes(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES item_type_attribute_options(id) ON DELETE CASCADE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(menu_item_id, attribute_id, option_id)
);

CREATE INDEX idx_menu_item_multi_values_item ON menu_item_attribute_multi_values(menu_item_id);
```

---

### Phase 2: Data Migration

**2.1 Migrate `item_type_field` data**
```python
# migration script pseudocode
for field in db.query(ItemTypeField).all():
    attr = ItemTypeAttribute(
        item_type_id=field.item_type_id,
        slug=field.field_name,
        display_name=field.field_name.replace('_', ' ').title(),
        input_type=infer_input_type(field.field_name),  # bagel_type->single_select, extras->multi_select
        is_required=field.required,
        display_order=field.display_order,
        ask_in_conversation=field.ask,
        question_text=field.question_text,
    )
    db.add(attr)
```

**2.2 Migrate `attribute_definitions` data**
```python
for attr_def in db.query(AttributeDefinition).all():
    # Check if already migrated from item_type_field
    existing = db.query(ItemTypeAttribute).filter_by(
        item_type_id=attr_def.item_type_id,
        slug=attr_def.slug
    ).first()

    if existing:
        # Merge: update with attribute_definition fields
        existing.input_type = attr_def.input_type
        existing.allow_none = attr_def.allow_none
        existing.min_selections = attr_def.min_selections
        existing.max_selections = attr_def.max_selections
    else:
        # Create new
        attr = ItemTypeAttribute(
            item_type_id=attr_def.item_type_id,
            slug=attr_def.slug,
            display_name=attr_def.display_name,
            input_type=attr_def.input_type,
            is_required=attr_def.is_required,
            allow_none=attr_def.allow_none,
            min_selections=attr_def.min_selections,
            max_selections=attr_def.max_selections,
            ask_in_conversation=True,  # default
        )
        db.add(attr)
```

**2.3 Migrate `attribute_options` to new table**
```python
for opt in db.query(AttributeOption).all():
    # Find new attribute ID
    old_attr = db.query(AttributeDefinition).get(opt.attribute_definition_id)
    new_attr = db.query(ItemTypeAttribute).filter_by(
        item_type_id=old_attr.item_type_id,
        slug=old_attr.slug
    ).first()

    new_opt = ItemTypeAttributeOption(
        attribute_id=new_attr.id,
        slug=opt.slug,
        display_name=opt.display_name,
        price_modifier=opt.price_modifier,
        is_available=opt.is_available,
    )
    db.add(new_opt)
```

**2.4 Add missing attribute definitions for unconfigured types**
```python
# Define what attributes each type should have
TYPE_ATTRIBUTES = {
    'egg_sandwich': [
        {'slug': 'bread', 'display_name': 'Bread', 'input_type': 'single_select', 'is_required': True},
        {'slug': 'bagel_type', 'display_name': 'Bagel Type', 'input_type': 'single_select', 'is_required': True},
        {'slug': 'protein', 'display_name': 'Protein', 'input_type': 'single_select', 'is_required': True},
        {'slug': 'cheese', 'display_name': 'Cheese', 'input_type': 'single_select', 'is_required': False},
        {'slug': 'toppings', 'display_name': 'Toppings', 'input_type': 'multi_select', 'is_required': False},
        {'slug': 'toasted', 'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': True},
    ],
    'deli_classic': [...],
    'fish_sandwich': [...],
    'signature_sandwich': [...],
}

for type_slug, attributes in TYPE_ATTRIBUTES.items():
    item_type = db.query(ItemType).filter_by(slug=type_slug).first()
    for attr_data in attributes:
        attr = ItemTypeAttribute(item_type_id=item_type.id, **attr_data)
        db.add(attr)
```

**2.5 Migrate `default_config` JSON to relational**
```python
for menu_item in db.query(MenuItem).filter(MenuItem.default_config.isnot(None)).all():
    config = menu_item.default_config  # dict
    item_type = menu_item.item_type

    for attr in db.query(ItemTypeAttribute).filter_by(item_type_id=item_type.id).all():
        if attr.slug in config:
            value = config[attr.slug]

            if attr.input_type == 'multi_select':
                # Create multiple rows in join table
                for v in value:
                    option = find_option(attr.id, v)
                    db.add(MenuItemAttributeMultiValue(
                        menu_item_id=menu_item.id,
                        attribute_id=attr.id,
                        option_id=option.id
                    ))
            elif attr.input_type == 'boolean':
                db.add(MenuItemAttributeValue(
                    menu_item_id=menu_item.id,
                    attribute_id=attr.id,
                    value_boolean=value,
                    still_ask=False
                ))
            else:  # single_select
                option = find_option(attr.id, value)
                db.add(MenuItemAttributeValue(
                    menu_item_id=menu_item.id,
                    attribute_id=attr.id,
                    option_id=option.id,
                    still_ask=should_still_ask(attr.slug)  # e.g., bagel_type=True
                ))
        else:
            # Pre-create empty record
            db.add(MenuItemAttributeValue(
                menu_item_id=menu_item.id,
                attribute_id=attr.id,
                still_ask=attr.is_required
            ))
```

---

### Phase 3: Code Updates

**3.1 Add SQLAlchemy models**
File: `sandwich_bot/models.py`
- Add `ItemTypeAttribute` model
- Add `ItemTypeAttributeOption` model
- Add `MenuItemAttributeValue` model
- Add `MenuItemAttributeMultiValue` model

**3.2 Update menu index builder**
File: `sandwich_bot/menu_index_builder.py`
- Replace `default_config` JSON reading with relational queries
- Build same structure from relational data for backward compatibility

**3.3 Update admin routes**
Files: `sandwich_bot/routes/admin_*.py`
- Menu item create: auto-create attribute value records
- Menu item edit: form-based editing of attribute values

**3.4 Update population script**
File: `populate_zuckers_menu.py`
- Create attribute values instead of JSON

---

### Phase 4: Cleanup

**4.1 Remove old tables**
```sql
DROP TABLE item_type_field;
DROP TABLE attribute_options;
DROP TABLE attribute_definitions;
```

**4.2 Remove JSON column**
```sql
ALTER TABLE menu_items DROP COLUMN default_config;
```

**4.3 Remove old models from code**
- Remove `ItemTypeField` model
- Remove `AttributeDefinition` model
- Remove `AttributeOption` model

---

### Phase 5: Verification

1. Run existing tests - should pass with no changes to order flow
2. Verify admin UI shows correct forms
3. Verify menu index builds correctly
4. Verify "What's on The Lexington?" still works
5. Verify signature sandwich ordering still works

---

## Files That Would Need Updates

| File | Current Role | Changes Needed |
|------|--------------|----------------|
| `sandwich_bot/models.py` | SQLAlchemy models | Add `MenuItemAttributeValue` model |
| `sandwich_bot/menu_index_builder.py` | Builds menu JSON | Read from relational tables instead of JSON |
| `populate_zuckers_menu.py` | Populates menu | Create attribute values instead of JSON |
| `sandwich_bot/tasks/item_adder_handler.py` | Creates order items | Use relational config for signature items |
| `sandwich_bot/tasks/item_converters.py` | Converts tasks | May not need changes (order capture separate from menu config) |
| Admin UI routes | Menu editing | Form-based editing instead of JSON |

---

## Benefits

1. **Admin UI**: Clean forms instead of JSON editing
2. **Validation**: Database enforces valid options
3. **Consistency**: Same attribute options across menu items
4. **Pricing**: `attribute_options.price_modifier` automatically applies
5. **Inventory**: Could link options to inventory (future)
6. **Reporting**: Easy to query "all items with swiss cheese"

## Risks

1. **Migration complexity**: Need to parse existing JSON correctly
2. **Performance**: More joins to load menu items (mitigated by caching)
3. **Flexibility loss**: JSON is freeform; relational requires predefined options

---

## Implementation Status

### Phase 1: Schema Creation ✅ COMPLETE

**Migration**: `5f7a8b9c0d1e_consolidate_item_type_attributes.py`

Created tables:
- `item_type_attributes` - Consolidated attribute definitions (merges `item_type_field` + `attribute_definitions`)
- `menu_item_attribute_values` - Per-menu-item configuration values
- `menu_item_attribute_selections` - Join table for multi-select values

Added FK column to existing `attribute_options` table:
- `item_type_attribute_id` - Links options to consolidated attributes

**SQLAlchemy Models** added to `sandwich_bot/models.py`:
- `ItemTypeAttribute` (lines 355-393)
- `MenuItemAttributeValue` (lines 395-425)
- `MenuItemAttributeSelection` (lines 427-455)

### Phase 2: Data Migration ✅ COMPLETE

**Script**: `scripts/migrate_default_config_to_relational.py`

Migration results:
- 70 menu items with `default_config` migrated
- 172 attribute values created
- 108 multi-select selections created

**Item types with attribute definitions added**:
- `egg_sandwich`: bread, protein, cheese, toppings, extras, toasted
- `signature_sandwich`: bread, protein, cheese, toppings, extras, sauce, toasted
- `fish_sandwich`: fish, bread, toasted
- `salad_sandwich`: salad, bread, toasted
- `spread_sandwich`: spread
- `omelette`: protein, cheese, extras, includes_side_choice, side_options

**Verified data integrity**:
```
The Lexington (egg_sandwich):
  bread: Bagel (still_ask=True)     -- Ask for bagel type
  protein: Egg White (still_ask=False)  -- Locked
  cheese: Swiss Cheese (still_ask=True) -- Default but changeable
  toppings: [Spinach] (multi-select)

Plain Cream Cheese Sandwich (spread_sandwich):
  spread: Plain Cream Cheese (still_ask=False)

The Delancey Omelette (omelette):
  protein: Corned Beef (still_ask=False)
  cheese: Swiss Cheese (still_ask=False)
  extras: [Potato Latke, Sautéed Onions] (multi-select)
  side_options: [Bagel, Small Fruit Salad] (multi-select)
```

### Phase 3: Code Updates 🔄 IN PROGRESS

Completed:
1. ✅ Update `menu_index_builder.py` to read from relational tables instead of `default_config` JSON
   - Added `_build_default_config_from_relational()` helper function
   - Updated `build_menu_index()` to use relational tables with JSON fallback
   - Updated `_build_item_types_data()` to use `item_type_attributes` with `attribute_definitions` fallback
   - All 120 menu-related tests passing

Remaining work:
2. Update admin routes for form-based menu item editing
3. Update population scripts to use relational structure

### Phase 4: Cleanup ⏳ PENDING

After Phase 3 is complete and verified:
1. Remove old `item_type_field` table
2. Remove old `attribute_definitions` table
3. Remove `default_config` column from `menu_items`
4. Remove old model classes

### Phase 5: Verification ⏳ PENDING

Testing to complete after Phase 3:
1. Run existing tests - should pass with no changes to order flow
2. Verify admin UI shows correct forms
3. Verify menu index builds correctly
4. Verify "What's on The Lexington?" still works
5. Verify signature sandwich ordering still works
