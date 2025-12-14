# OpenBot (Sandwich Bot) - Improvement List

This document outlines potential improvements and enhancements for the OpenBot codebase.

---

## High Priority

### 1. Security Improvements

- **CORS Configuration** (`main.py:77-83`): Currently allows all origins (`allow_origins=["*"]`). For production, restrict to specific trusted domains.

- **Session Cache Memory Leak** (`main.py:87`): `SESSION_CACHE` grows unbounded. Add TTL-based expiration or LRU eviction to prevent memory exhaustion.

- ~~**Rate Limiting**~~: **DONE** - Added rate limiting via `slowapi` (default: 30 requests/minute per session/IP). Configurable via `RATE_LIMIT_CHAT` and `RATE_LIMIT_ENABLED` env vars.

- **Input Validation**: Add maximum length validation for user messages to prevent excessively long prompts being sent to the LLM.

### 2. ~~Missing `add_side` Handler~~ **DONE**

- ~~**`order_logic.py`**: The LLM can return `add_side` intent, but there's no handler for it.~~ **DONE** - Added `_add_side()` function.

### ~~2b. Multi-Item Orders Not Supported~~ **DONE**

- ~~**`llm_client.py` / `main.py`**: The LLM schema only supports ONE intent per message.~~ **DONE** - Implemented multi-item order support:
  - Changed LLM response schema from single `intent`/`slots` to `actions` array
  - Each action contains its own `intent` and `slots`
  - Updated system prompt to instruct LLM to return multiple actions for multi-item orders
  - `main.py` now loops through all actions and applies each one sequentially
  - Response includes both `actions` array and backward-compatible `intent`/`slots` from first action
  - Added `remove_item` support by `menu_item_name` to allow removing specific items
  - Added 2 new tests for multi-item orders

### 3. Error Handling Improvements

- ~~**LLM Failures** (`main.py:302-307`)~~: **DONE** - Added try/catch around `call_sandwich_bot()` with graceful error handling.

- ~~**JSON Parse Errors** (`llm_client.py:199`)~~: **DONE** - Added fallback handling for malformed JSON responses from LLM.

### 4. Database Improvements

- ~~**Duplicate Imports** (`models.py:1-12`)~~: **DONE** - Consolidated duplicate imports.

- ~~**Add Database Indexes**~~: **DONE** - Added indexes on frequently queried columns:
  - `Order.status` - for filtering by order status
  - `Order.created_at` - for sorting by date
  - `MenuItem.category` - for filtering menu items
  - `OrderItem.order_id` - for join performance
  - Composite index `ix_orders_status_created_at` for combined status filter + date sort

- ~~**Migration Strategy**~~: **DONE** - Added Alembic for database migrations. Initial migration handles both fresh databases (creates all tables) and existing databases (adds missing indexes). Run `alembic upgrade head` before starting the server.

---

## Medium Priority

### 5. Order Logic Enhancements

- ~~**Update Sandwich** (`order_logic.py`)~~: **DONE** - Implemented `update_sandwich` handler. Supports updating bread, cheese, toppings, sauces, toasted, quantity. Auto-finds last sandwich if no index provided.

- ~~**Remove Item**~~: **DONE** - Implemented `remove_item` handler. Can remove by index, by menu_item_name, or removes last item by default. Sets status to "pending" when cart becomes empty. **BUG FIX**: Added name-based lookup to prevent accidentally removing wrong items when the item to remove doesn't exist (e.g., user tries to remove "Chips" but Chips was never added).

- ~~**Price Modifiers**~~: **DONE** - Implemented price modifier support in `order_logic.py`. Customization choices (extra cheese, premium bread) now apply their `extra_price` from the menu's recipe choice groups. Helper functions added: `_find_menu_item()`, `_get_extra_price_for_choice()`, `_calculate_customization_extras()`. Updated `_add_sandwich`, `_update_sandwich`, and `_confirm` to calculate extras. Added 8 new tests for price modifiers.

### ~~6. LLM Prompt Optimization~~ **DONE**

- ~~**Token Usage** (`llm_client.py:182-186`): Full menu JSON is sent with every message. For large menus, this wastes tokens.~~ **DONE** - Implemented menu caching in system prompt:
  - Menu is now included in the system prompt on first message only
  - Session tracks `menu_version` to detect menu changes
  - If menu changes mid-conversation, the new menu is sent
  - Conversation history is now sent as proper OpenAI message objects (not rendered text)
  - **~60-70% token reduction** on subsequent messages in a conversation
  - New Alembic migration adds `menu_version_sent` column to `chat_sessions` table

- **Conversation History** (`llm_client.py:158`): Only last 6 turns are sent. Consider adaptive history based on token count.

### 7. Frontend Improvements

- **No Loading Indicator** (`index.html`): Add a typing indicator while waiting for bot response.

- **No Order Summary Display**: Show current order state in the UI (items, total, customer info).

- **No Error Recovery**: If session becomes invalid, user must manually refresh. Add automatic session recovery.

- **Accessibility**: Add ARIA labels, keyboard navigation, and screen reader support.

- **Mobile Responsiveness**: Test and improve mobile layout.

### ~~8. API Improvements~~ **DONE**

- ~~**No API Versioning**: Add `/api/v1/` prefix for future compatibility.~~ **DONE** - Implemented:
  - All API endpoints now available under `/api/v1/` prefix (e.g., `/api/v1/chat/start`)
  - Backward compatibility maintained - endpoints also available at root level
  - `/health` remains at root (standard practice for health checks)

- ~~**Missing OpenAPI Tags**: Add tags to group endpoints in Swagger docs.~~ **DONE** - Implemented:
  - Added OpenAPI tags: "Health", "Chat", "Admin - Menu", "Admin - Orders"
  - Added docstrings to all endpoints for better API documentation
  - FastAPI auto-generates grouped Swagger UI at `/docs`

- ~~**No Request IDs**: Add request ID tracking for debugging and log correlation.~~ **DONE** - Implemented:
  - Added `RequestIDMiddleware` that generates unique UUID for each request
  - Request ID available in `request.state.request_id` for use in endpoints
  - Request ID returned in `X-Request-ID` response header
  - Clients can provide their own `X-Request-ID` header for tracing
  - 4 new tests added for request ID and API versioning

---

## Low Priority

### 9. Code Quality

- **Type Hints** (`order_logic.py`): Add complete type hints to all functions.

- **Docstrings**: Add docstrings to `_add_sandwich()`, `_add_drink()` functions.

- **Constants**: Extract magic strings ("confirmed", "pending", "collecting_items") to constants or enums.

- **Configuration**: Move hardcoded values to configuration (e.g., history length of 6, page sizes).

### 10. Testing Improvements

- **Integration Tests**: Add end-to-end tests that verify the full order flow.

- **LLM Response Mocking**: Improve test coverage for various LLM response scenarios.

- **Performance Tests**: Add load testing for concurrent sessions.

- **Frontend Tests**: Add JavaScript unit tests and E2E tests (Playwright/Cypress).

### 11. Observability

- **Metrics**: Add Prometheus metrics for:
  - Request latency
  - LLM response times
  - Order completion rates
  - Error rates

- **Structured Logging**: Convert to JSON logging for better log aggregation.

- **Health Check Enhancement**: Add detailed health check that verifies DB and OpenAI connectivity.

### 12. Feature Additions

- **Order Status Updates**: Add endpoints to update order status (preparing, ready, picked up).

- **Order History**: Let customers view their previous orders.

- **Email/SMS Notifications**: Notify customers when order is ready.

- **Payment Integration**: Add payment processing before order confirmation.

- **Specials/Promotions**: Add support for discount codes and daily specials.

- **Multi-language Support**: Internationalize the bot for different languages.

---

## Architecture Considerations

### 13. Scalability

- **Session Storage**: Move from in-memory cache to Redis for horizontal scaling.

- **Database**: Consider PostgreSQL for production instead of SQLite.

- **Background Tasks**: Use Celery/RQ for async tasks (notifications, reports).

### 14. Deployment

- **Docker**: Add Dockerfile and docker-compose.yml for containerization.

- **Environment Separation**: Add configuration profiles for dev/staging/prod.

- **CI/CD**: Add GitHub Actions workflow for automated testing and deployment.

---

## Quick Wins - COMPLETED

All quick wins have been implemented and tested:

1. ~~Fix duplicate imports in `models.py`~~ - **DONE** (consolidated imports)
2. ~~Add `_add_side()` handler in `order_logic.py`~~ - **DONE** (added handler + tests)
3. ~~Add try/catch around LLM call in `main.py`~~ - **DONE** (graceful error handling + test)
4. ~~Add typing indicator in frontend~~ - **DONE** (animated dots while waiting)
5. ~~Add session TTL to prevent memory leaks~~ - **DONE** (TTL + LRU eviction + tests)
6. ~~Restrict CORS origins for production~~ - **DONE** (configurable via `CORS_ORIGINS` env var)
7. ~~Add input length validation~~ - **DONE** (max 2000 chars, configurable via `MAX_MESSAGE_LENGTH`)

### New Environment Variables Added

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed origins |
| `SESSION_TTL_SECONDS` | `3600` | Session cache TTL (1 hour) |
| `SESSION_MAX_CACHE_SIZE` | `1000` | Maximum sessions in cache |
| `MAX_MESSAGE_LENGTH` | `2000` | Maximum user message length |
| `RATE_LIMIT_CHAT` | `30 per minute` | Rate limit for chat endpoints |
| `RATE_LIMIT_ENABLED` | `true` | Enable/disable rate limiting |

---

## Summary

| Category | Count | Status |
|----------|-------|--------|
| High Priority | 4 | Partially addressed |
| Medium Priority | 4 | **2 COMPLETED** (LLM optimization, API improvements) |
| Low Priority | 4 | Pending |
| Architecture | 2 | Pending |
| Quick Wins | 7 | **COMPLETED** |

**Test Coverage**: 82 tests passing

**Next Steps**: Focus on remaining medium priority items (frontend improvements).

---

*Last updated: 2025-12-12*
