# CLAUDE.md - Sandwich Bot Project Guide

## ⛔ DATABASE - CRITICAL

**This project uses PostgreSQL ONLY. SQLite is NOT used anywhere.**

### What You MUST NOT Do
- Do NOT create, check, or reference any `.sqlite`, `.sqlite3`, or `.db` files
- Do NOT import `sqlite3` or any SQLite libraries
- Do NOT run commands like `sqlite3 app.db` or `DATABASE_URL=sqlite:///app.db`
- Do NOT use SQLite-specific syntax (`sqlite_master`, `batch_alter_table` for SQLite compatibility, etc.)

### What You MUST Do
- All database operations use PostgreSQL via `DATABASE_URL` environment variable
- Connection string format: `postgresql://...` (Neon PostgreSQL)
- Use `psql $DATABASE_URL` to inspect database state
- Use PostgreSQL syntax in all migrations and queries

### Why This Matters
Any `.db` files in the project are stale artifacts. The Neon PostgreSQL database is the single source of truth for all data.

## Project Overview

This is an AI-powered ordering chatbot for a bagel shop (Zucker's Bagels). The system handles natural language order processing, supporting bagels, coffees, sandwiches, and other menu items with full customization.

See @README.md for project overview
See @docs/architecture.md for system architecture

## Development Phase

This project is in active testing/development. Backward compatibility is not a concern—feel free to make breaking changes to APIs, database schemas, or data formats as needed.

## Code Style

- **Python version**: 3.11+
- **Formatting**: PEP 8 compliant
- **Type hints**: Required for all function signatures
- **Line length**: 100 characters max
- **Docstrings**: Google-style for public methods
- **Imports**: Group as stdlib, third-party, local (separated by blank lines)

## Error Handling

- Use specific exception types, never bare `except:`
- Log errors with context before re-raising
- User-facing messages should be friendly; log full details internally
- Database operations should use try/finally to ensure session cleanup
- State machine errors should not crash the conversation; return graceful error messages

## Common Commands

```bash
# Run all tests
python -m pytest

# Run specific test file
python -m pytest tests/test_tasks_parsing.py -v

# Run tests matching a pattern
python -m pytest -k "bagel" -v

# Start the development server
uvicorn sandwich_bot.main:app --reload --port 8000

# Run database migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"
```

## Project Structure

```
sandwich_bot/
├── tasks/                    # Core order processing logic
│   ├── state_machine.py      # Main order flow controller
│   ├── models.py             # Pydantic task models (OrderTask, BagelItemTask, etc.)
│   ├── adapter.py            # Converts task objects to database/API formats
│   ├── pricing.py            # Price calculation and modifier pricing
│   ├── parsers/
│   │   ├── deterministic.py  # Rule-based input parsing
│   │   ├── constants.py      # Bagel types, spreads, modifiers, normalizations
│   │   └── validators.py     # Email, phone, address validation
│   └── *_handler.py          # State-specific handlers (bagel, coffee, checkout, etc.)
├── routes/                   # FastAPI route handlers
│   ├── chat.py               # Chat/messaging endpoints
│   ├── admin_*.py            # Admin panel endpoints
│   └── public.py             # Public-facing endpoints
├── schemas/                  # Pydantic API schemas
│   └── orders.py             # Order response schemas with modifier extraction
├── services/
│   ├── order.py              # Order persistence and retrieval
│   └── session.py            # Chat session management
├── models.py                 # SQLAlchemy database models
└── main.py                   # FastAPI app entry point

tests/
├── test_tasks_parsing.py     # Parser unit tests (300+ tests)
├── test_tasks_adapter.py     # Adapter and modifier consistency tests
├── test_resiliency_batch*.py # End-to-end conversation flow tests
└── test_*.py                 # Other test modules
```

## Architecture

### Hierarchical Task System

The order capture uses a hierarchical task model:

```
OrderTask (root)
├── phase: OrderPhase (GREETING, TAKING_ITEMS, CHECKOUT, etc.)
├── items: ItemsTask
│   └── items: List[ItemTask]  # BagelItemTask, CoffeeItemTask, MenuItemTask, etc.
├── customer_info: CustomerInfoTask
├── delivery_info: DeliveryInfoTask
└── checkout: CheckoutTask
```

### State Machine Flow

1. **GREETING**: Initial customer contact
2. **TAKING_ITEMS**: Adding/configuring menu items
3. **CONFIGURING_ITEM**: Collecting missing item details (bagel type, toasted, etc.)
4. **CHECKOUT**: Collecting customer info, order type, payment method
5. **COMPLETE**: Order finalized

### Frontend/Backend Separation

The frontend (`static/index.html`) should be a pure data renderer with no business logic. All item-type-specific logic, pricing calculations, and display formatting decisions belong in the backend adapter (`tasks/adapter.py`). The frontend renders whatever data structure the API returns without checking `item_type` or other schema-specific fields.

### Modifier Normalization

Input variations are normalized to canonical forms:
- "lox" → "nova scotia salmon"
- "cc" → "cream cheese"
- "bec" → bacon, egg, cheese

Modifier normalization uses `Ingredient.aliases` in the database. Use `menu_cache.normalize_modifier()` to normalize modifier names.

### Pricing System

Prices are calculated in `pricing.py` using database lookups:
- Base item prices from `menu_items` table
- Modifier upcharges from `attribute_options` table (`price_modifier` column)
- Bagel type upcharges (e.g., gluten free) from `bagel_type` attribute options
- Coffee modifiers (size, milk, syrup) from `sized_beverage` attribute options
- Iced upcharges from `iced_price_modifier` column on size options
- Modifiers stored in `item_config` for database persistence

## Data-Driven Architecture

### Principle
All food-domain behavior must be **data-driven**, not hardcoded. The codebase should have no knowledge of specific foods - item types are database configurations, not code concepts.

### Current State → Target State

| Legacy (Avoid) | Generic (Preferred) |
|----------------|---------------------|
| `bagel_handler.py` | `menu_item_handler.py` |
| `BagelItemTask` | `MenuItemTask` |
| `BAGEL_TYPES` constant | `AttributeOption` query |
| `if item == "coffee":` | `if item.requires("temperature"):` |

### Rules for New Code
1. No new item-specific files or handlers
2. No new item-specific Pydantic models
3. No hardcoded item/modifier lists - query the database
4. No conditionals that check for specific item type names
5. No cross-type fallback mechanisms (see below)

### No Fallback Mechanisms

**Do NOT create "fallback" patterns** where one item type falls back to another for pricing, attributes, or behavior. Examples of what to avoid:

```python
# WRONG: Fallback chain for pricing
if item_type == "bagel":
    types_to_check.append("sandwich")  # "fall back to sandwich prices"

# WRONG: Database column for fallback relationships
ALTER TABLE item_types ADD COLUMN modifier_fallback_types JSONB;
UPDATE item_types SET modifier_fallback_types = '["sandwich"]' WHERE slug = 'bagel';
```

**Why fallbacks are harmful:**
1. **Hidden coupling** - Creates implicit dependencies between item types that aren't visible in the schema
2. **Unpredictable behavior** - When bagel pricing changes, sandwich pricing silently affects bagels
3. **Not truly data-driven** - Fallbacks encode business logic ("bagels are like sandwiches") in config, not data
4. **Debugging nightmares** - "Why did this bagel price change?" requires tracing through fallback chains
5. **Migration hazards** - Removing or renaming an item type can break unrelated item types

**The correct approach:** Each item type should be fully self-contained. If a bagel needs the same modifier prices as a sandwich, configure those prices explicitly on the bagel item type. Explicit duplication is better than implicit coupling.

### Legacy Code
Item-specific handlers exist (`bagel_config_handler.py`, `coffee_config_handler.py`). These are technical debt. Do not extend them - work toward consolidating into generic handlers.

### Code Validity Test
Before committing any order handling code, verify:
1. Could this exact code handle a sushi restaurant?
2. If I delete all rows from `menu_items` and add new ones, does the code still work?
3. Are there ZERO string literals that match food items?

If any answer is "no", refactor to be data-driven.

## Database Queries: Fail Fast on Missing Data

### Principle
When querying the database for menu configuration data (ingredients, modifiers, item types, attributes, etc.), **never silently return empty collections or fall back to hardcoded values**. Instead, raise a descriptive `MenuDataNotLoadedError` exception with full context.

### Why This Matters
Silent fallbacks mask configuration problems:
- An order that "works" with stale hardcoded data is worse than a visible failure
- Debugging "why isn't X recognized?" is impossible when fallbacks are silent
- Stale fallback data diverges from the database over time
- Problems surface in production instead of at startup

### The Pattern

**WRONG - Silent empty return:**
```python
def get_proteins(self) -> set[str]:
    if not self._is_loaded:
        return set()  # Caller has no idea data is missing
    return self._proteins.copy()
```

**WRONG - Silent fallback to hardcoded values:**
```python
def get_modifier_fields(item):
    db_fields = load_from_db(item_type)
    if not db_fields:
        return HARDCODED_FIELDS  # Masks DB configuration problem
    return db_fields
```

**CORRECT - Fail fast with context:**
```python
def get_proteins(self) -> set[str]:
    if not self._is_loaded:
        raise MenuDataNotLoadedError(
            "Menu cache not loaded. Ensure menu_cache.load_from_db() is called at startup."
        )
    if not self._proteins:
        raise MenuDataNotLoadedError(
            "No proteins found in database. "
            "Check that ingredients table has records with category='protein'."
        )
    return self._proteins.copy()
```

### Exception Class
Use `MenuDataNotLoadedError` (defined in `sandwich_bot/exceptions.py`) for all menu data loading failures. The error message must include:
1. What data was expected
2. Where to look to fix it (which table, which column)
3. Any relevant context (item type slug, attribute name, etc.)

### Exceptions to This Rule
The following **lookup/search functions** may return `None` or the original input when no match is found (this is semantic "not found", not a data error):
- `find_modifier_match()` - returns `None` if modifier not found on item
- `resolve_coffee_alias()` - returns original name if no alias exists
- `find_by_pound_item()` - returns `None` if item not in by-pound catalog
- `normalize_modifier()` - returns original if no normalization needed

These functions **MUST still throw** `MenuDataNotLoadedError` if the cache is not loaded.

## Key Patterns

### Item Configuration Storage

Items store all details in `item_config` JSON column:
```python
{
    "item_type": "bagel",
    "bagel_type": "plain",
    "toasted": True,
    "modifiers": [{"name": "nova scotia salmon", "price": 6.00}],
    "base_price": 2.75,
    "free_details": ["toasted"]
}
```

### Test Organization

- **Parsing tests**: `test_tasks_parsing.py` - validates input recognition
- **Adapter tests**: `test_tasks_adapter.py` - validates data conversion
- **Resiliency tests**: `test_resiliency_batch*.py` - end-to-end conversation flows

## Database Environment

**PostgreSQL ONLY** - See "DATABASE - CRITICAL" section at top.

- `DATABASE_URL` environment variable contains the Neon PostgreSQL connection string
- Run migrations: `alembic upgrade head` (uses DATABASE_URL automatically)
- Alembic migrations are in `alembic/versions/`
- All migrations must use PostgreSQL syntax only (no SQLite fallbacks)

Key tables:
- `orders`: Customer orders with totals and status
- `order_items`: Individual items with `item_config` JSON
- `chat_sessions`: Conversation state and history
- `menu_items`: Available menu items per store
- `stores`: Store locations with tax rates and delivery zones

## Environment Variables

```
DATABASE_URL=postgresql://...  # Neon/Postgres connection string (required)
OPENAI_API_KEY=...             # For LLM parsing fallback
ANTHROPIC_API_KEY=...          # For Claude-based parsing
```

## Testing Tips

```bash
# Run only fast unit tests (skip integration)
python -m pytest tests/test_tasks_parsing.py tests/test_tasks_models.py -v

# Run with coverage
python -m pytest --cov=sandwich_bot --cov-report=html

# Debug a specific test
python -m pytest tests/test_tasks_parsing.py::TestBagelParsing::test_plain_bagel -v -s
```

## Security

- **Secrets**: Never hardcode; use environment variables (DATABASE_URL, API keys)
- **SQL**: Always use parameterized queries via SQLAlchemy; never string concatenation
- **Input validation**: Validate all user input before state machine processing
- **Error exposure**: Never expose internal errors or stack traces in API responses
- **Sessions**: Use secure session tokens; expire inactive sessions

## Debugging

```bash
# Enable verbose logging
LOG_LEVEL=DEBUG uvicorn sandwich_bot.main:app --reload

# Test state machine in isolation with output
python -m pytest tests/test_tasks_parsing.py -v -s

# Run single test with debugging
python -m pytest tests/test_tasks_parsing.py::TestBagelParsing::test_plain_bagel -v -s --tb=long

# Query database (use psql or a Postgres client with DATABASE_URL)
# Example: Check session state
psql $DATABASE_URL -c "SELECT session_id, order_state FROM chat_sessions LIMIT 5"
```

## Bug Fix Protocol

Before claiming any bug is fixed, you MUST:

### 1. Trace First, Fix Second
- Find the EXACT line of code that produces the observed buggy output
- Do NOT guess which functions are involved - trace and prove it

### 2. Verify Code Path
- Prove the function you want to modify is actually called in this flow
- If unsure, add temporary logging or search for call sites
- Ask: "How do I know this code runs when [X happens]?"

### 3. End-to-End Verification
- After making changes, tell me how to restart/reload the server
- Do NOT claim success based on unit tests alone
- Only mark complete after I confirm the actual behavior changed

### 4. No Premature Victory
- Do NOT say "fixed" or "done" until I verify the change works
- If you can't verify it yourself, explicitly say "I've made the changes but cannot verify - please test"

### 5. Post-Fix Cleanup
After successfully fixing a bug that required one or more failed attempts:
1. Review all changes made during debugging
2. Identify which changes were failed attempts vs. part of the actual solution
3. Flag any changes from failed attempts that may need to be reverted
4. Revert unnecessary changes after confirmation
5. Verify tests still pass after cleanup
