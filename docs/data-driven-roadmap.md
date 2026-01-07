# Data-Driven Architecture Roadmap

This document tracks opportunities to make the codebase more data-driven, reducing hardcoded logic and enabling configuration-based customization.

## Status Legend
- [ ] Not started
- [x] Completed
- [~] In progress

---

## Phase 1: Quick Wins (Low Effort, High Value)

### 1.1 Pagination Configuration
**Status**: [ ] Not started
**Effort**: 1-2 hours
**Impact**: Eliminates magic numbers, enables per-store customization

**Current State**:
- `bagel_config_handler.py:54` - `BAGEL_TYPE_BATCH_SIZE = 4`
- `coffee_config_handler.py:120` - `batch_size = 5`
- `menu_inquiry_handler.py:37` - `MENU_BATCH_SIZE = 10`
- `store_info_handler.py:20` - `MODIFIER_BATCH_SIZE = 6`

**Target State**:
- `pagination_config` table with category and batch_size
- Load into menu_data_cache at startup
- Handlers read from cache instead of constants

**Schema**:
```sql
CREATE TABLE pagination_config (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) UNIQUE NOT NULL,  -- 'bagel_types', 'drinks', 'menu_items', 'modifiers'
    batch_size INT NOT NULL DEFAULT 5,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

---

### 1.2 Question Prompts
**Status**: [ ] Not started
**Effort**: 2-4 hours
**Impact**: Centralizes all user-facing questions, enables A/B testing, i18n-ready

**Current State**:
- Questions scattered across handlers:
  - `bagel_config_handler.py` - "What kind of bagel would you like?"
  - `coffee_config_handler.py` - "What size?"
  - `checkout_handler.py` - "Is this for pickup or delivery?"
- Affirmative/negative responses hardcoded as sets

**Target State**:
- `order_question` table with phase, field, question text
- `response_pattern` table for yes/no/affirmative patterns
- Handlers look up questions by (phase, field) key

**Schema**:
```sql
CREATE TABLE order_question (
    id SERIAL PRIMARY KEY,
    phase VARCHAR(50) NOT NULL,           -- 'configuring_item', 'checkout', etc.
    field VARCHAR(50) NOT NULL,           -- 'bagel_type', 'size', 'toasted', etc.
    question_text TEXT NOT NULL,
    retry_text TEXT,                      -- "Sorry, I didn't get that. {question_text}"
    context VARCHAR(50),                  -- optional context like 'first_ask' vs 'retry'
    UNIQUE(phase, field, context)
);

CREATE TABLE response_pattern (
    id SERIAL PRIMARY KEY,
    pattern_type VARCHAR(50) NOT NULL,    -- 'affirmative', 'negative', 'cancel', 'done'
    pattern TEXT NOT NULL,                -- the word/phrase (e.g., 'yes', 'yeah', 'yep')
    is_regex BOOLEAN DEFAULT FALSE,
    UNIQUE(pattern_type, pattern)
);
```

---

### 1.3 Valid Config Answers
**Status**: [ ] Not started
**Effort**: 1 hour
**Impact**: Minor cleanup, removes hardcoded bagel types from VALID_CONFIG_ANSWERS

**Current State**:
- `configuring_item_handler.py:62` - `VALID_CONFIG_ANSWERS` set with hardcoded bagel types

**Target State**:
- Build set dynamically from `get_bagel_types()` + generic answers
- Remove hardcoded bagel type strings

---

## Phase 2: Core Enablers (Medium Effort, High Impact)

### 2.1 Item Type Field Configuration
**Status**: [ ] Not started
**Effort**: 1-2 days
**Impact**: Enables adding new item types without code changes

**Current State**:
- `models.py` - BagelItemTask, CoffeeItemTask, etc. define fields in Python classes
- Required/optional fields hardcoded in class definitions
- Questions for each field hardcoded in handlers

**Target State**:
- `item_type_field` table defines fields per item type
- `field_config.py` or handlers read from database
- New item types can be added via database + minimal code

**Schema**:
```sql
CREATE TABLE item_type_field (
    id SERIAL PRIMARY KEY,
    item_type_id INT REFERENCES item_types(id),
    field_name VARCHAR(100) NOT NULL,
    field_type VARCHAR(50) NOT NULL,      -- 'string', 'boolean', 'enum', 'number'
    required BOOLEAN DEFAULT FALSE,
    ask_if_missing BOOLEAN DEFAULT TRUE,
    default_value TEXT,
    question_key VARCHAR(100),            -- FK to order_question or inline text
    display_order INT DEFAULT 0,
    validation_options TEXT,              -- JSON array of valid values for enums
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(item_type_id, field_name)
);
```

**Example Data**:
```
item_type=bagel, field=bagel_type, required=true, ask_if_missing=true
item_type=bagel, field=toasted, required=true, ask_if_missing=true, default=null
item_type=bagel, field=spread, required=false, ask_if_missing=false
item_type=coffee, field=size, required=true, default='medium'
item_type=coffee, field=iced, required=true, ask_if_missing=true
```

---

### 2.2 Intent/Off-Topic Patterns
**Status**: [ ] Not started
**Effort**: 1 day
**Impact**: Cleaner code, patterns can be tuned without deploys

**Current State**:
- `configuring_item_handler.py:32-59` - OFF_TOPIC_PATTERNS (10+ regexes)
- `parsers/constants.py` - QUALIFIER_PATTERNS, GREETING_PATTERNS, etc.

**Target State**:
- `intent_pattern` table with pattern type, regex, intent name
- Load and compile at startup
- Handlers use pattern registry instead of inline regexes

**Schema**:
```sql
CREATE TABLE intent_pattern (
    id SERIAL PRIMARY KEY,
    pattern_type VARCHAR(50) NOT NULL,    -- 'off_topic', 'qualifier', 'greeting', 'done'
    regex_pattern TEXT NOT NULL,
    intent_name VARCHAR(100),
    capture_group INT,                    -- which group to extract (0 = full match)
    priority INT DEFAULT 0,               -- higher = check first
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

### 2.3 Display Templates
**Status**: [ ] Not started
**Effort**: 1 day
**Impact**: Consistent formatting, enables customization

**Current State**:
- `models.py` - `get_summary()` methods with hardcoded formatting
- `adapter.py` - item display logic with `isinstance` checks

**Target State**:
- `item_display_template` table with format strings per item type
- Template engine renders summaries from data

---

## Phase 3: Architecture Improvements (High Effort, Enables Future)

### 3.1 Handler Registry Pattern
**Status**: [ ] Not started
**Effort**: 3-5 days
**Impact**: Eliminates isinstance checks, enables plugin-style handlers

**Current State**:
- Multiple files with `isinstance(item, BagelItemTask)` checks
- `state_machine.py:199-219` - `_get_pending_item_description()`
- `checkout_utils_handler.py:81-98` - item summary building
- `adapter.py` - item conversion logic

**Target State**:
- Handler classes register for specific item types
- Dispatcher looks up handler by item type string
- No isinstance checks in business logic

---

### 3.2 State Transition Rules
**Status**: [ ] Not started
**Effort**: 3-5 days
**Impact**: Enables custom flows per store, A/B testing of checkout flows

**Current State**:
- `state_machine.py:593-639` - hardcoded if/elif for phase routing
- Phase transitions embedded in handler return values

**Target State**:
- `order_phase_flow` table with phase → handler mapping
- `phase_transition_rule` table for conditional transitions
- State machine reads flow from database

**Schema**:
```sql
CREATE TABLE order_phase_flow (
    id SERIAL PRIMARY KEY,
    phase VARCHAR(50) UNIQUE NOT NULL,
    handler_name VARCHAR(100) NOT NULL,   -- class/method name to invoke
    preserve_on_redirect BOOLEAN DEFAULT FALSE,
    display_order INT DEFAULT 0
);

CREATE TABLE phase_transition_rule (
    id SERIAL PRIMARY KEY,
    from_phase VARCHAR(50) NOT NULL,
    to_phase VARCHAR(50) NOT NULL,
    condition_type VARCHAR(50),           -- 'always', 'if_field_set', 'if_items_complete'
    condition_value TEXT,
    priority INT DEFAULT 0
);
```

---

### 3.3 Per-Store Configuration
**Status**: [ ] Not started
**Effort**: 2-3 days
**Impact**: Multi-tenant support, store-specific behavior

**Current State**:
- Some store-specific data exists (tax rates, delivery zones)
- Most configuration is global

**Target State**:
- Configuration tables have optional `store_id` column
- Null store_id = default, specific store_id = override
- Cache loads store-specific config on request

---

## Completed Items

### Menu Data (Previously Done)
- [x] Bagel types → database (ingredients table)
- [x] Spreads → database (ingredients table)
- [x] Proteins, cheeses, toppings → database (ingredients table)
- [x] Coffee types → database (menu_items + aliases)
- [x] Soda types → database (menu_items + aliases)
- [x] Speed menu bagels → database (menu_items + aliases)
- [x] By-the-pound items → database (menu_items + by_pound_category)
- [x] Modifier normalizations → database (ingredient aliases)
- [x] Menu item recognition → database (menu_items + aliases)
- [x] Category keywords → database (item_types.aliases)
- [x] Coffee typo corrections → database (menu_items aliases) - Jan 2025
- [x] Known menu items → database (menu_items + aliases) - Jan 2025

### Pricing (Previously Done)
- [x] Base prices → database (menu_items.base_price)
- [x] Modifier upcharges → database (attribute_options.price_modifier)
- [x] Bagel type upcharges → database (attribute_options for bagel_type)
- [x] Size upcharges → database (attribute_options for size)
- [x] Iced upcharges → database (iced_price_modifier column)

---

## Notes

- All new tables should include `created_at` and `updated_at` timestamps
- Consider adding `is_active` boolean for soft-delete capability
- Load configuration into `menu_data_cache` at startup for O(1) access
- Add cache invalidation mechanism for runtime updates (future)
