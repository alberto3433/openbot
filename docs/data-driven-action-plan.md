# Action Plan: Data-Driven Phase 1 & 2.1

Implementation plan for pagination, item type fields, questions, and admin UI.

---

## Task 1: Pagination Configuration (Simplified)

**Goal**: Standardize pagination to 5 items across all handlers

**Approach**: No database needed - just define a single constant and use it everywhere.

### Step 1.1: Create Constant
**File**: `sandwich_bot/tasks/parsers/constants.py`

```python
# Standard pagination size for all list displays
DEFAULT_PAGINATION_SIZE = 5
```

### Step 1.2: Update Handlers
**Files to modify**:

1. `bagel_config_handler.py:54`
   - Change: `BAGEL_TYPE_BATCH_SIZE = 4` → `from .parsers.constants import DEFAULT_PAGINATION_SIZE`
   - Use: `DEFAULT_PAGINATION_SIZE` (5)

2. `coffee_config_handler.py:120`
   - Change: hardcoded `batch_size = 5` → use constant

3. `menu_inquiry_handler.py:37`
   - Change: `MENU_BATCH_SIZE = 10` → use constant (5)

4. `store_info_handler.py:20`
   - Change: `MODIFIER_BATCH_SIZE = 6` → use constant (5)

### Step 1.3: Test
- Verify pagination works at 5 items in all contexts
- ~15 minutes total

---

## Task 2: Item Type Fields Table (Child of item_types)

**Goal**: Define fields per item type in a normalized child table

### Step 2.1: Create Migration
```bash
alembic revision -m "add_item_type_fields_table"
```

**Table**:
```sql
CREATE TABLE item_type_field (
    id SERIAL PRIMARY KEY,
    item_type_id INT NOT NULL REFERENCES item_types(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,
    display_order INT NOT NULL DEFAULT 0,
    required BOOLEAN NOT NULL DEFAULT FALSE,
    ask BOOLEAN NOT NULL DEFAULT TRUE,
    question_text TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(item_type_id, field_name)
);

CREATE INDEX idx_item_type_field_item_type ON item_type_field(item_type_id);
```

**Notes**:
- `required`: Item cannot be complete without this field having a value
- `ask`: Should we prompt the user for this field (even if not required)
- `question_text`: The question to ask (e.g., "Would you like it toasted?")
- All fields are `string` type for now (as requested)

### Step 2.2: Seed Data

```sql
-- Bagel fields
INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'bagel_type', 1, true, true, 'What kind of bagel would you like?'
FROM item_types WHERE slug = 'bagel';

INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'toasted', 2, true, true, 'Would you like it toasted?'
FROM item_types WHERE slug = 'bagel';

INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'spread', 3, false, true, 'Any spread on that?'
FROM item_types WHERE slug = 'bagel';

INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'extras', 4, false, true, 'Anything else on it?'
FROM item_types WHERE slug = 'bagel';

-- Coffee (sized_beverage) fields
INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'drink_type', 1, true, true, 'What kind of drink would you like?'
FROM item_types WHERE slug = 'sized_beverage';

INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'size', 2, true, true, 'What size?'
FROM item_types WHERE slug = 'sized_beverage';

INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'iced', 3, true, true, 'Hot or iced?'
FROM item_types WHERE slug = 'sized_beverage';

INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'milk', 4, false, false, 'Any milk preference?'
FROM item_types WHERE slug = 'sized_beverage';

-- Espresso fields
INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
SELECT id, 'shots', 1, false, false, 'How many shots?'
FROM item_types WHERE slug = 'espresso';
```

### Step 2.3: Update MenuDataCache
**File**: `sandwich_bot/menu_data_cache.py`

```python
from dataclasses import dataclass

@dataclass
class ItemTypeFieldConfig:
    field_name: str
    display_order: int
    required: bool
    ask: bool
    question_text: str | None

# New attribute
_item_type_fields: dict[str, list[ItemTypeFieldConfig]]  # slug -> fields

# New methods
def _load_item_type_fields(self, db: Session) -> None:
    """Load field configurations for all item types."""

def get_item_type_fields(self, item_type_slug: str) -> list[ItemTypeFieldConfig]:
    """Get all field configs for an item type, ordered by display_order."""

def get_question_for_field(self, item_type_slug: str, field_name: str) -> str | None:
    """Get the question text for a specific field."""
```

### Step 2.4: Create Field Config Helper
**New file**: `sandwich_bot/tasks/field_config.py`

```python
from sandwich_bot.menu_data_cache import menu_cache

def get_fields_for_item_type(item_type: str) -> list:
    """Get field configuration for an item type."""
    return menu_cache.get_item_type_fields(item_type)

def get_next_question_field(item_type: str, current_values: dict):
    """Get the next field that needs a question asked."""
    fields = get_fields_for_item_type(item_type)
    for field in fields:  # already sorted by display_order
        if field.ask and current_values.get(field.field_name) is None:
            return field
    return None

def is_item_complete(item_type: str, current_values: dict) -> bool:
    """Check if all required fields are filled."""
    fields = get_fields_for_item_type(item_type)
    for field in fields:
        if field.required and current_values.get(field.field_name) is None:
            return False
    return True

def get_question(item_type: str, field_name: str) -> str | None:
    """Get question text for a field."""
    return menu_cache.get_question_for_field(item_type, field_name)
```

---

## Task 3: Response Patterns Table (Global/Shared)

**Goal**: Centralize affirmative/negative/cancel/done response patterns

### Step 3.1: Create Migration
```bash
alembic revision -m "add_response_patterns_table"
```

**Table**:
```sql
CREATE TABLE response_pattern (
    id SERIAL PRIMARY KEY,
    pattern_type VARCHAR(50) NOT NULL,    -- 'affirmative', 'negative', 'cancel', 'done'
    pattern VARCHAR(100) NOT NULL,         -- the word/phrase
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(pattern_type, pattern)
);

CREATE INDEX idx_response_pattern_type ON response_pattern(pattern_type);
```

### Step 3.2: Seed Data
```sql
-- Affirmative responses
INSERT INTO response_pattern (pattern_type, pattern) VALUES
('affirmative', 'yes'),
('affirmative', 'yeah'),
('affirmative', 'yep'),
('affirmative', 'yup'),
('affirmative', 'sure'),
('affirmative', 'ok'),
('affirmative', 'okay'),
('affirmative', 'correct'),
('affirmative', 'right'),
('affirmative', 'that''s right'),
('affirmative', 'that''s correct'),
('affirmative', 'looks good'),
('affirmative', 'perfect'),
('affirmative', 'sounds good'),
('affirmative', 'please'),
('affirmative', 'definitely'),
('affirmative', 'absolutely');

-- Negative responses
INSERT INTO response_pattern (pattern_type, pattern) VALUES
('negative', 'no'),
('negative', 'nope'),
('negative', 'nah'),
('negative', 'no thanks'),
('negative', 'no thank you'),
('negative', 'not really'),
('negative', 'i''m good'),
('negative', 'none'),
('negative', 'nothing');

-- Cancel responses
INSERT INTO response_pattern (pattern_type, pattern) VALUES
('cancel', 'cancel'),
('cancel', 'cancel that'),
('cancel', 'cancel order'),
('cancel', 'never mind'),
('cancel', 'nevermind'),
('cancel', 'forget it'),
('cancel', 'forget that'),
('cancel', 'scratch that');

-- Done responses
INSERT INTO response_pattern (pattern_type, pattern) VALUES
('done', 'that''s all'),
('done', 'that''s it'),
('done', 'nothing else'),
('done', 'i''m done'),
('done', 'all set'),
('done', 'that''s everything'),
('done', 'done');
```

### Step 3.3: Update MenuDataCache
**File**: `sandwich_bot/menu_data_cache.py`

```python
# New attribute
_response_patterns: dict[str, set[str]]  # type -> set of patterns

# New methods
def _load_response_patterns(self, db: Session) -> None:
    """Load response patterns grouped by type."""

def is_response_type(self, text: str, pattern_type: str) -> bool:
    """Check if text matches any pattern of the given type."""
    patterns = self._response_patterns.get(pattern_type, set())
    return text.lower().strip() in patterns
```

### Step 3.4: Create Response Helper
**New file**: `sandwich_bot/tasks/response_helper.py`

```python
from sandwich_bot.menu_data_cache import menu_cache

def is_affirmative(text: str) -> bool:
    """Check if text is an affirmative response (yes, yeah, etc.)"""
    return menu_cache.is_response_type(text, "affirmative")

def is_negative(text: str) -> bool:
    """Check if text is a negative response (no, nope, etc.)"""
    return menu_cache.is_response_type(text, "negative")

def is_cancel(text: str) -> bool:
    """Check if text is a cancel request."""
    return menu_cache.is_response_type(text, "cancel")

def is_done(text: str) -> bool:
    """Check if text indicates user is done ordering."""
    return menu_cache.is_response_type(text, "done")
```

---

## Task 4: Admin UI for Item Type Fields

**Goal**: Add admin interface to manage item type fields

### Step 4.1: Create Backend Routes
**New file**: `sandwich_bot/routes/admin_item_type_fields.py`

```python
# CRUD endpoints:
# GET    /admin/item-types/{id}/fields     - List fields for item type
# POST   /admin/item-types/{id}/fields     - Create field
# PUT    /admin/item-types/{id}/fields/{field_id} - Update field
# DELETE /admin/item-types/{id}/fields/{field_id} - Delete field
# PUT    /admin/item-types/{id}/fields/reorder    - Reorder fields
```

### Step 4.2: Extend Item Types Admin UI
**File**: `static/admin_item_types.html`

Add "Manage Fields" button to each item type row that opens a modal/section showing:
- List of fields for that item type
- Add/Edit/Delete field buttons
- Drag-to-reorder functionality (optional, can use up/down buttons)

**Field edit form**:
- Field Name (text input)
- Display Order (number)
- Required (checkbox)
- Ask (checkbox) - "Prompt user for this field"
- Question Text (textarea)

### Step 4.3: Add Navigation Link
Add "Item Type Fields" or integrate into existing "Item Types" page in the admin nav.

---

## Task 5: Admin UI for Response Patterns

**Goal**: Add admin interface to manage response patterns

### Step 5.1: Create Backend Routes
**New file**: `sandwich_bot/routes/admin_response_patterns.py`

```python
# CRUD endpoints:
# GET    /admin/response-patterns           - List all patterns (grouped by type)
# POST   /admin/response-patterns           - Create pattern
# PUT    /admin/response-patterns/{id}      - Update pattern
# DELETE /admin/response-patterns/{id}      - Delete pattern
```

### Step 5.2: Create Admin UI Page
**New file**: `static/admin_response_patterns.html`

Simple list interface showing:
- Grouped by pattern_type (Affirmative, Negative, Cancel, Done)
- Add/Edit/Delete buttons
- Follows existing admin UI style

### Step 5.3: Add Navigation Link
Add "Response Patterns" link to admin header nav.

---

## Implementation Order

### Week 1: Pagination + Questions Foundation
1. **Day 1-2**: Task 1 (Pagination) - Migration, cache, handler updates
2. **Day 3-4**: Task 2 Steps 2.1-2.3 (Questions) - Migration, cache, helper
3. **Day 5**: Task 2 Step 2.4 Phase A - Checkout handler integration

### Week 2: Questions Completion + Field Config Start
4. **Day 1-2**: Task 2 Step 2.4 Phase B-C - Remaining handler migrations
5. **Day 3-4**: Task 3 Steps 3.1-3.3 - Migration, cache, field config helper
6. **Day 5**: Task 3 Step 3.4 - Configuring item handler refactor

### Week 3: Field Config Completion + Testing
7. **Day 1-2**: Task 3 Step 3.5 - Model enhancements
8. **Day 3-5**: Integration testing, bug fixes, documentation

---

## Success Criteria

### Task 1: Pagination
- [ ] No hardcoded batch size constants in handler files
- [ ] Changing database value changes pagination behavior
- [ ] All existing tests pass

### Task 2: Questions
- [ ] Checkout flow uses database questions
- [ ] `is_affirmative()` handles all yes variations
- [ ] Questions can be modified in database without code deploy
- [ ] All existing tests pass

### Task 3: Field Config
- [ ] Field requirements defined in database
- [ ] New item type can be added with just database + minimal code
- [ ] Configuring item handler uses database config
- [ ] All existing tests pass

---

## Rollback Plan

Each task is independent. If issues arise:
1. Database tables can remain (no harm)
2. Revert code changes to use hardcoded fallbacks
3. Cache methods include fallback defaults

The `get_*` functions all have fallback logic, so partial migration is safe.
