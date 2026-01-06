# CLAUDE.md - Sandwich Bot Project Guide

## Project Overview

This is an AI-powered ordering chatbot for a bagel shop (Zucker's Bagels). The system handles natural language order processing, supporting bagels, coffees, sandwiches, and other menu items with full customization.

See @README.md for project overview
See @docs/hierarchical-task-architecture.md for task system details
See @docs/bagel_bot_architecture.md for architecture diagrams

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

See migration `m7n8o9p0q1r2_populate_modifier_prices.py` for initial price data.

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

### Adding New Menu Items

1. Add to `parsers/constants.py` if it needs recognition
2. Update `pricing.py` for modifier prices
3. Create handler in `tasks/*_handler.py` if special flow needed
4. Add tests in `tests/test_tasks_parsing.py`

### Test Organization

- **Parsing tests**: `test_tasks_parsing.py` - validates input recognition
- **Adapter tests**: `test_tasks_adapter.py` - validates data conversion
- **Resiliency tests**: `test_resiliency_batch*.py` - end-to-end conversation flows

## Database Environment

**IMPORTANT**: This project uses a single Neon PostgreSQL database as the source of truth. There is no local development database.

- Do NOT query or inspect local SQLite files (e.g., `app.db`) - they are stale/incomplete
- Do NOT use `sqlite3` commands to check schema or data
- All database access should use the configured `DATABASE_URL` environment variable
- To inspect database state, use the running application or connect to Neon directly
- Alembic for migrations in `alembic/versions/`

Key tables:
- `orders`: Customer orders with totals and status
- `order_items`: Individual items with `item_config` JSON
- `chat_sessions`: Conversation state and history
- `menu_items`: Available menu items per store
- `stores`: Store locations with tax rates and delivery zones

## Daily Database Checks

**Check for duplicate menu items daily** - Duplicates can cause incorrect matching and pricing issues.

```sql
-- Find duplicate menu items (run against Neon database)
SELECT LOWER(name) as name, category, COUNT(*) as count
FROM menu_items
GROUP BY LOWER(name), category
HAVING COUNT(*) > 1
ORDER BY count DESC;

-- Delete duplicates, keeping the oldest entry (lowest ID)
DELETE FROM menu_items
WHERE id NOT IN (
    SELECT MIN(id)
    FROM menu_items
    GROUP BY LOWER(name), category
);
```

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

## Git Workflow

- **Branch naming**: `feature/*`, `bugfix/*`, `hotfix/*` prefixes
- **Commit messages**: Imperative mood ("Add feature" not "Added feature")
- **PR requirements**: All tests must pass, code should be reviewed
- **Main branch**: Protected; merge only via PR

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

## Known Issues

- 9 resiliency tests in batches 9, 10, 11, 14, 17 fail due to using non-existent `current_item_id` field
- These are pre-existing test issues, not code bugs

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
