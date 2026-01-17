# CLAUDE.md - Orderbot Project Guide

## ⛔ DATABASE - CRITICAL

**This project uses PostgreSQL ONLY. SQLite is NOT used anywhere.**

### What You MUST NOT Do
- Do NOT create, check, or reference any `.sqlite`, `.sqlite3`, or `.db` files
- Do NOT import `sqlite3` or any SQLite libraries
- Do NOT use SQLite-specific syntax (`sqlite_master`, `batch_alter_table`, etc.)

### What You MUST Do
- All database operations use PostgreSQL via `DATABASE_URL` environment variable
- Connection string format: `postgresql://...` (Neon PostgreSQL)
- Use `psql $DATABASE_URL` to inspect database state

### Schema Changes Require Permission
**ALWAYS ask for permission before** adding columns, tables, or creating migrations that modify the schema.

## Project Overview

This is an AI-powered ordering chatbot for a bagel shop (Zucker's Bagels). The system handles natural language order processing with full customization.

See @README.md for project overview
See @docs/architecture.md for system architecture

## Development Phase

This project is in active testing/development. Backward compatibility is not a concern—feel free to make breaking changes as needed.

## Code Style

- **Python version**: 3.11+
- **Formatting**: PEP 8 compliant, 100 char max line length
- **Type hints**: Required for all function signatures
- **Docstrings**: Google-style for public methods
- **Imports**: Group as stdlib, third-party, local (separated by blank lines)

## Error Handling

- Use specific exception types, never bare `except:`
- Log errors with context before re-raising
- User-facing messages should be friendly; log full details internally
- State machine errors should not crash the conversation

## Common Commands

```bash
# Run all tests
python -m pytest

# Run specific test file / pattern / single test
python -m pytest tests/test_tasks_parsing.py -v
python -m pytest -k "bagel" -v
python -m pytest tests/test_tasks_parsing.py::TestClass::test_name -v -s --tb=long

# Start dev server (with optional verbose logging)
uvicorn orderbot.main:app --reload --port 8000
LOG_LEVEL=DEBUG uvicorn orderbot.main:app --reload

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Query database
psql $DATABASE_URL -c "SELECT session_id, order_state FROM chat_sessions LIMIT 5"
```

## Project Structure

```
orderbot/
├── tasks/                    # Core order processing logic
│   ├── state_machine.py      # Main order flow controller
│   ├── models.py             # Pydantic task models (OrderTask, MenuItemTask)
│   ├── adapter.py            # Converts task objects to database/API formats
│   ├── pricing.py            # Price calculation and modifier pricing
│   ├── parsers/
│   │   ├── deterministic.py  # Rule-based input parsing
│   │   └── validators.py     # Email, phone, address validation
│   └── *_handler.py          # State-specific handlers
├── routes/                   # FastAPI route handlers
├── schemas/                  # Pydantic API schemas
├── services/                 # Order persistence, session management
├── models.py                 # SQLAlchemy database models
└── main.py                   # FastAPI app entry point

tests/
├── test_tasks_parsing.py     # Parser unit tests
├── test_tasks_adapter.py     # Adapter and modifier consistency tests
├── test_resiliency_batch*.py # End-to-end conversation flow tests
└── test_*.py                 # Other test modules
```

## Architecture

### Hierarchical Task System

```
OrderTask (root)
├── phase: OrderPhase (GREETING, TAKING_ITEMS, CHECKOUT, etc.)
├── items: ItemsTask
│   └── items: List[MenuItemTask]  # Generic for all item types
├── customer_info: CustomerInfoTask
├── delivery_info: DeliveryInfoTask
└── checkout: CheckoutTask
```

### State Machine Flow

1. **GREETING**: Initial customer contact
2. **TAKING_ITEMS**: Adding/configuring menu items
3. **CONFIGURING_ITEM**: Collecting missing item details
4. **CHECKOUT**: Collecting customer info, order type, payment method
5. **COMPLETE**: Order finalized

### Frontend/Backend Separation

The frontend should be a pure data renderer with no business logic. All item-type-specific logic, pricing, and display formatting belong in the backend adapter (`tasks/adapter.py`).

### Key Systems

- **Modifier Normalization**: Uses `Ingredient.aliases` in database. Use `menu_cache.normalize_modifier()`.
- **Pricing**: Calculated in `pricing.py` using `menu_items.base_price` and `attribute_options.price_modifier`.

## Data-Driven Architecture

### Core Principle
All food-domain behavior must be **data-driven**, not hardcoded. The codebase should have no knowledge of specific foods—item types are database configurations, not code concepts.

### Rules for New Code
1. No new item-specific files, handlers, or Pydantic models
2. No hardcoded item/modifier lists—query the database
3. No conditionals checking specific item type slugs (`"bagel"`, `"coffee"`, `"sized_beverage"`, etc.)
4. No conditionals checking specific attribute names (`"bread"`, `"size"`, `"toasted"`)
5. Before adding food-domain code, attempt data-driven solution first; ask for approval if not feasible

### Wrong vs Right

**WRONG:**
```python
if item.menu_item_type == "sized_beverage":  # Checking slug
if item.has_attribute("bread"):               # Checking attribute name
if attr_values.get("toasted") is None:        # Assuming specific field
```

**CORRECT:**
```python
item_category = menu_cache.get_item_type_category(item.menu_item_type)
required_attrs = menu_cache.get_required_attributes(item.menu_item_type)
missing = [attr for attr in required_attrs if attr not in item.attribute_values]
```

### Code Validity Test
Before committing order handling code:
1. Could this exact code handle a sushi restaurant?
2. If I delete all `menu_items` rows and add new ones, does the code still work?
3. Are there ZERO string literals matching food items or item type slugs?

### Domain-Specific Helpers: Tests Only

Functions encoding knowledge of specific foods (`is_soda_drink()`, `get_coffee_types()`, etc.) are **ONLY allowed in `tests/` directory**—never in `orderbot/`.

### Legacy Code
Item-specific handlers exist (`bagel_config_handler.py`, `coffee_config_handler.py`). These are technical debt—do not extend them.

## Fail Fast on Missing Data

When querying database for menu configuration, **never silently return empty collections or fall back to hardcoded values**. Raise `MenuDataNotLoadedError` with context.

**WRONG:**
```python
if not self._is_loaded:
    return set()  # Silent failure
```

**CORRECT:**
```python
if not self._is_loaded:
    raise MenuDataNotLoadedError("Menu cache not loaded. Call menu_cache.load_from_db() at startup.")
```

**Exception**: Lookup functions (`find_modifier_match()`, `normalize_modifier()`) may return `None` for "not found"—but must still throw if cache is not loaded.

## Environment Variables

```
DATABASE_URL=postgresql://...  # Neon/Postgres connection string (required)
OPENAI_API_KEY=...             # For LLM parsing fallback
ANTHROPIC_API_KEY=...          # For Claude-based parsing
```

## Security

- **Secrets**: Never hardcode; use environment variables
- **SQL**: Always use parameterized queries via SQLAlchemy
- **Input validation**: Validate all user input before state machine processing
- **Error exposure**: Never expose internal errors in API responses

## Bug Fix Protocol

### 1. Trace First, Fix Second
Find the EXACT line producing buggy output—don't guess.

### 2. Verify Code Path
Prove the function is actually called in this flow.

### 3. End-to-End Verification
Don't claim success based on unit tests alone. Only mark complete after user confirms.

### 4. No Premature Victory
Don't say "fixed" until user verifies. If you can't verify, say "I've made the changes but cannot verify—please test."

### 5. Post-Fix Cleanup
After fixing with failed attempts: identify failed vs. actual fix changes, revert unnecessary changes, verify tests pass.
