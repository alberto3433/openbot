# Bagel Store Chatbot Architecture

## Overview

A data-driven conversational ordering system where all order workflows, item configurations, and business logic are driven by database configuration rather than hardcoded paths or constants.

### Goals

1. **Reliability**: No dropped items, no missed modifiers, no looping questions
2. **Natural conversation flow**: Handle multi-item orders naturally
3. **Low latency**: Response time under 500ms (no LLM calls in hot path)
4. **Data-driven**: Add new item types and attributes via database only
5. **Visual progress tracking**: UI shows order build progress in real-time

### Core Principles

**Every aspect of the ordering flow is configurable via database:**

1. **No hardcoded item types** - Item types (bagel, coffee, sandwich, etc.) defined in `item_types` table
2. **No hardcoded attributes** - Item attributes (toasted, size, spread) come from `item_type_attributes` table
3. **No hardcoded options** - Attribute choices (plain, everything, sesame) come from `attribute_options` table
4. **No hardcoded prices** - All pricing from `menu_items.base_price` and `attribute_options.price_modifier`
5. **No hardcoded questions** - Conversation prompts from `item_type_attributes.question_text`
6. **No hardcoded patterns** - Recognition patterns from `ingredient_aliases` and `menu_item_aliases`

**Adding a new menu item or item type requires only database changes, not code changes.**

---

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         STATE MACHINE                               │
│                    (Order Flow Controller)                          │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
        ┌─────────────────────────────────────────────────────────────┐
        │                    SLOT ORCHESTRATOR                         │
        │         (Determines next question from OrderTask)            │
        └─────────────────────────────────────────────────────────────┘
                                  │
        ┌─────────────┬───────────┴───────────┬─────────────┐
        │             │                       │             │
        ▼             ▼                       ▼             ▼
   ┌─────────┐  ┌───────────┐  ┌────────────────────┐  ┌─────────┐
   │ TAKING  │  │CONFIGURING│  │MENU ITEM CONFIG    │  │CHECKOUT │
   │ ITEMS   │  │   ITEM    │  │(DB-driven handler) │  │         │
   └─────────┘  └───────────┘  └────────────────────┘  └─────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │      ORDER TASK         │
                    │   (Pydantic Models)     │
                    └─────────────────────────┘
```

---

## Task Hierarchy

```
OrderTask (root)
├── DeliveryMethodTask
│   ├── status: pending|in_progress|complete
│   ├── order_type: pickup|delivery|null
│   └── AddressTask (only if delivery)
│       ├── street, city, zip
│       └── status: pending|in_progress|complete
│
├── ItemsTask
│   ├── status: pending|in_progress|complete
│   └── items: List[MenuItemTask]  ← Generic, data-driven
│       ├── menu_item_name, menu_item_id
│       ├── item_type: str (from DB - bagel, sized_beverage, etc.)
│       ├── attribute_values: Dict[str, Any] (DB-driven fields)
│       ├── status: pending|in_progress|complete
│       └── unit_price: float (calculated from DB)
│
├── CustomerInfoTask
│   ├── status: pending|in_progress|complete
│   ├── name: string|null
│   └── contact: string|null (email or phone)
│
├── CheckoutTask
│   ├── status: pending|in_progress|complete
│   ├── order_reviewed: bool
│   └── confirmed: bool
│
└── PaymentTask
    ├── status: pending|in_progress|complete
    └── method: in_store|cash_delivery|card_link|null
```

### Generic MenuItemTask

**There are no item-type-specific task classes.** All items use `MenuItemTask` with:

- `item_type`: String loaded from `item_types.slug` (e.g., "bagel", "sized_beverage", "omelette")
- `attribute_values`: Dict storing all configured attributes from `item_type_attributes`

This enables adding new item types via database without code changes.

### Task States

Each task has a status:
- **pending**: Not started, waiting for prerequisites
- **in_progress**: Currently being worked on, has unfilled required fields
- **complete**: All required fields filled
- **skipped**: Explicitly skipped or cancelled by user

### Standard Modifier Entry Format

All modifier entries (sweeteners, syrups, toppings, etc.) must use this canonical dictionary format:

```python
{
    "slug": "vanilla",           # Always "slug" for the identifier (required)
    "category": "syrup",         # Explicit category metadata (required)
    "quantity": 1,               # How many (default: 1)
    "price": 0.75,               # Price if applicable (optional)
    "display_name": "Vanilla Syrup"  # Human-readable name (optional)
}
```

**Rules:**
1. **Always use `slug`** for the identifier key
2. **Always include `category`** - don't infer it from the key name or context
3. **`quantity` defaults to 1** if not specified
4. **`display_name` is optional** - can be derived from slug if not provided

**Why this matters:**
- Single key (`slug`) keeps the code simple - no fallback chains needed
- Explicit `category` makes the data self-describing and generic
- Works for any domain (bagel shop, sushi restaurant, etc.)

---

## Database Schema

### Item Type Configuration

```
item_types
├── id, slug, display_name
├── is_configurable (requires attribute questions)
├── expands_to (virtual types that expand to others)
└── aliases (recognition patterns)

item_type_attributes
├── item_type_id → item_types
├── slug (bread, size, toasted, spread)
├── input_type (single_select, multi_select, boolean)
├── is_required, ask_in_conversation
├── question_text ("Would you like it toasted?")
└── display_order

attribute_options
├── item_type_attribute_id → item_type_attributes
├── slug, display_name
├── price_modifier ($0.90 for large)
└── is_default, is_available
```

### Menu Items

```
menu_items
├── id, name, base_price
├── item_type_id → item_types
├── aliases (recognition patterns)
└── extra_metadata (JSON for special config)

menu_item_attribute_values
├── menu_item_id → menu_items
├── attribute_id → item_type_attributes
├── option_id (for single_select)
└── still_ask (override to ask even with default)

menu_item_attribute_selections
├── menu_item_id, attribute_id
└── option_id (for multi_select values)
```

### Recognition & Parsing

```
ingredients
├── id, name, category
└── price_modifier

ingredient_aliases
├── ingredient_id → ingredients
└── alias (recognition pattern)

response_pattern
├── pattern_type (affirmative, negative, done, cancel)
└── pattern (yes, yeah, yep, etc.)
```

### Example Configurations

**Bagel (from DB):**

| Attribute | Required | Ask | Question |
|-----------|----------|-----|----------|
| bread | Yes | Yes | "What kind of bagel?" |
| toasted | Yes | Yes | "Would you like it toasted?" |
| spread_type | No | Yes | "Any spread on that?" |
| extras | No | Yes | "Anything else on it?" |

**Coffee (from DB):**

| Attribute | Required | Ask | Question |
|-----------|----------|-----|----------|
| size | Yes | Yes | "What size?" |
| iced | Yes | Yes | "Hot or iced?" |
| milk | No | No | - |
| sweetener | No | No | - |

---

## Processing Flow

### 1. Input Parsing (Deterministic)

User input is parsed by the deterministic parser using patterns loaded from:
- `menu_items` + `menu_item_aliases` for item recognition
- `ingredients` + `ingredient_aliases` for modifier recognition
- `response_pattern` for affirmative/negative responses

**No LLM required for parsing** - all patterns are database-driven.

### 2. State Update

After parsing, deterministically update the task tree:

```python
def update_state(order: OrderTask, parsed: ParsedItems):
    # 1. Add new items as MenuItemTask with item_type from DB
    for item in parsed.items:
        task = MenuItemTask(
            item_type=item.item_type,  # From DB lookup
            menu_item_name=item.name,
            attribute_values=item.extracted_attributes,
        )
        order.items.add_item(task)

    # 2. Apply answers to pending questions
    if order.pending_field and parsed.answer:
        item = order.get_pending_item()
        item.attribute_values[order.pending_field] = parsed.answer

    # 3. Recalculate task statuses using DB-defined required fields
    for item in order.items.items:
        item.status = calculate_status(item)  # Checks DB requirements
```

### 3. Next Action Selection (SlotOrchestrator)

The `SlotOrchestrator` determines what to ask next by querying the database:

```python
def get_next_action(order: OrderTask) -> Action:
    # 1. Find first incomplete item
    for item in order.items.get_incomplete_items():
        # 2. Load required attributes from DB
        attrs = db.get_item_type_attributes(item.item_type)

        # 3. Find first missing required attribute that should be asked
        for attr in attrs.order_by('display_order'):
            if attr.ask_in_conversation and attr.slug not in item.attribute_values:
                return AskAction(
                    question=attr.question_text,
                    attribute=attr.slug,
                    item=item,
                )

        # 4. All required attributes filled → complete
        item.mark_complete()

    # 5. Move to checkout slots (delivery, name, payment)
    return get_next_checkout_slot(order)
```

**No hardcoded field checks** - requirements come from `item_type_attributes.is_required`.

---

## Key Components

### State Machine (`tasks/state_machine.py`)
- Routes user input to appropriate handlers
- Manages phase transitions
- Coordinates with SlotOrchestrator for next action

### Slot Orchestrator (`tasks/slot_orchestrator.py`)
- Determines next question based on OrderTask state
- Checks item completeness using DB attribute definitions
- Returns appropriate slot/question

### Menu Item Config Handler (`tasks/menu_item_config_handler.py`)
- **Generic, DB-driven handler for ALL item types**
- Loads attribute definitions from database
- Asks questions in `display_order`
- Applies prices from `attribute_options.price_modifier`

### Pricing Engine (`tasks/pricing.py`)
- Calculates prices from `menu_items.base_price`
- Adds attribute upcharges from `attribute_options`
- Handles modifier pricing from `ingredients`

### Deterministic Parser (`tasks/parsers/deterministic.py`)
- Recognizes items using `menu_item_aliases`
- Recognizes modifiers using `ingredient_aliases`
- All patterns loaded from database at startup

---

## Order Flow

### Phase Progression

```
GREETING → TAKING_ITEMS → CONFIGURING_ITEM → CHECKOUT → COMPLETE
              ↑                    │
              └────────────────────┘
              (loop for each item)
```

### Slot-Based Configuration

The `SlotOrchestrator` determines what to ask next by:

1. Checking `OrderTask` for incomplete items
2. Looking up required attributes from `item_type_attributes`
3. Finding first attribute where `ask_in_conversation=True` and value is missing
4. Returning the `question_text` for that attribute

---

## Example Conversation

```
User: "I'd like an everything bagel with lox and a large iced latte"

[Deterministic Parse]
- Recognized: "everything bagel" → bagel item, bread=everything
- Recognized: "lox" → modifier (nova scotia salmon)
- Recognized: "large iced latte" → sized_beverage, size=large, iced=true

[State Update]
- Create MenuItemTask(item_type="bagel", attribute_values={bread: "everything", extras: ["lox"]})
- Create MenuItemTask(item_type="sized_beverage", attribute_values={size: "large", iced: true})

[SlotOrchestrator Query]
- Bagel item: check item_type_attributes for "bagel"
- Required: bread ✓, toasted ✗
- Next question: "Would you like the everything bagel toasted?"

Bot: "Would you like the everything bagel toasted?"
User: "Yes please"

[Parse] → affirmative response
[State Update] → bagel.attribute_values.toasted = true
[SlotOrchestrator] → bagel complete, coffee complete, ask delivery

Bot: "Got it! Everything bagel toasted with lox, and a large iced latte. Is this for pickup or delivery?"
```

---

## Visual Progress

The task tree structure supports real-time progress display:

```
Order Progress
├── ✅ Everything Bagel - toasted, lox ($8.50)
├── ✅ Large Iced Latte ($4.75)
├── 🔄 Delivery Method
│   └── ❓ Pickup or delivery?
├── ⏳ Customer Info
└── ⏳ Payment
```

Each task exposes:
- `get_progress()` → percentage complete
- `get_display_summary()` → human-readable summary
- `get_missing_fields()` → what still needs answers (from DB)

---

## Technology Stack

| Component | Implementation |
|-----------|---------------|
| Backend | FastAPI + SQLAlchemy |
| Database | PostgreSQL (prod), SQLite (dev) |
| State Management | Pydantic models (`OrderTask`, `MenuItemTask`) |
| Parsing | Deterministic parser with DB-loaded patterns |
| Flow Control | `SlotOrchestrator` with DB-driven slot definitions |
| Persistence | PostgreSQL via SQLAlchemy + session storage |
| Configuration | Database tables (no config files) |
| LLM | Optional fallback for ambiguous inputs |

---

## Performance

| Operation | Target | Actual |
|-----------|--------|--------|
| Deterministic Parse | <50ms | ~20ms |
| State Update | <10ms | ~5ms |
| DB Attribute Lookup | <5ms | ~2ms (cached) |
| Response Generation | <50ms | ~30ms |
| **Total** | **<200ms** | **~60ms** |

All menu data and attribute definitions are cached at startup in `MenuDataCache` for O(1) access.

---

## Adding New Capabilities

### Adding a New Item Type

1. Insert into `item_types` (slug, display_name)
2. Add attributes to `item_type_attributes` (what to ask)
3. Add options to `attribute_options` (valid choices)
4. Add recognition patterns to `menu_item_aliases`
5. **No code changes required**

### Adding a New Attribute

1. Insert into `item_type_attributes` with question_text
2. Add options to `attribute_options`
3. **No code changes required**

### Adding a New Menu Item

1. Insert into `menu_items` with item_type_id
2. Add aliases for recognition
3. Optionally set defaults in `menu_item_attribute_values`
4. **No code changes required**
