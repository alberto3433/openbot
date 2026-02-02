# Orderbot Refactoring Plan

## Overview

This document outlines a comprehensive refactoring plan for the orderbot codebase, organized into 9 phases. Each phase addresses a specific area of technical debt identified in the codebase analysis.

**Estimated Total Effort:** 150-200 hours
**Risk Mitigation:** Run full test suite after each phase

---

## Phase 1: Large Handler Decomposition

### Problem
Multiple handler files exceed 700+ lines, with `MenuItemConfigHandler` at 1,136 lines being the most problematic.

### Files to Refactor
| File | Current Lines | Target |
|------|---------------|--------|
| `orderbot/tasks/config/handler.py` | 1,136 | <400 each |
| `orderbot/tasks/config/select_input.py` | 716 | <350 each |
| `orderbot/tasks/item_adder_handler.py` | 984 | <400 each |
| `orderbot/tasks/configuring_item_handler.py` | 933 | <400 each |
| `orderbot/tasks/config_helper_handler.py` | 813 | <400 each |
| `orderbot/tasks/menu_inquiry_handler.py` | 784 | <400 each |
| `orderbot/tasks/taking_items_handler.py` | 772 | <400 each |
| `orderbot/tasks/modifier_input_handler.py` | 735 | <400 each |

### Implementation Steps

#### Step 1.1: Decompose MenuItemConfigHandler (config/handler.py)
**Create new files:**
- `orderbot/tasks/config/mandatory_attribute_handler.py` - Handle required attributes in sequence
- `orderbot/tasks/config/customization_handler.py` - Offer customization after mandatory attrs
- `orderbot/tasks/config/optional_attribute_handler.py` - Loop through optional attributes

**Extract methods:**
```
get_first_question() → MandatoryAttributeHandler.get_first_question()
handle_attribute_input() → route to appropriate handler
handle_customization_checkpoint() → CustomizationHandler.handle()
_process_optional_attributes() → OptionalAttributeHandler.process()
```

**Keep in handler.py:**
- Orchestration logic (routing between sub-handlers)
- State management coordination
- Public API methods

#### Step 1.2: Decompose select_input.py
**Create new files:**
- `orderbot/tasks/config/option_matching.py` - Option matching logic (consolidate with option_matcher.py)
- `orderbot/tasks/config/selection_pagination.py` - Pagination and "more options" handling

**Extract methods:**
```
_match_selection_to_option() → option_matching.match_selection()
_handle_options_inquiry() → selection_pagination.handle_inquiry()
_paginate_options() → selection_pagination.paginate()
```

#### Step 1.3: Decompose item_adder_handler.py
**Create new files:**
- `orderbot/tasks/item_lookup_service.py` - Menu item lookup (consolidate with menu_lookup.py)
- `orderbot/tasks/item_creation_service.py` - Item creation and initialization

**Extract methods:**
```
_find_menu_item() → item_lookup_service.find()
_create_configurable_item() → item_creation_service.create_configurable()
_create_simple_item() → item_creation_service.create_simple()
```

#### Step 1.4: Decompose configuring_item_handler.py
**Create new files:**
- `orderbot/tasks/config/item_selection_handler.py` - Handle ITEM_SELECTION pending field
- `orderbot/tasks/config/modifier_selection_handler.py` - Handle MODIFIER_SELECTION pending field
- `orderbot/tasks/config/switch_confirmation_handler.py` - Handle item switch confirmations

**Extract methods:**
```
_handle_item_selection() → ItemSelectionHandler.handle()
_handle_modifier_selection() → ModifierSelectionHandler.handle()
_handle_confirm_item_switch() → SwitchConfirmationHandler.handle()
_handle_can_you_make_it() → SwitchConfirmationHandler.handle_can_you_make_it()
```

#### Step 1.5: Decompose remaining large handlers
Apply similar extraction patterns to:
- `config_helper_handler.py` - Extract side choice handling, cancellation handling
- `menu_inquiry_handler.py` - Extract category listing, item description, pagination
- `taking_items_handler.py` - Already has sub-handlers, verify proper delegation
- `modifier_input_handler.py` - Extract pattern matching, modifier application

### Verification
```bash
python -m pytest --tb=short -q
```
**Expected:** Same test results, no new failures

### Estimated Effort: 40-50 hours

---

## Phase 2: Modifier Code Consolidation

### Problem
Modifier handling code scattered across 5+ files with overlapping responsibilities.

### Files Affected
- `orderbot/tasks/modifier_operations.py` (618 lines)
- `orderbot/tasks/modifier_utils.py` (160 lines)
- `orderbot/tasks/modifier_change_handler.py` (651 lines)
- `orderbot/tasks/modifier_input_handler.py` (735 lines)
- `orderbot/tasks/config/select_input.py` (partial)

### Implementation Steps

#### Step 2.1: Create ModifierService class
**New file:** `orderbot/tasks/services/modifier_service.py`

```python
class ModifierService:
    """Unified service for all modifier operations."""

    def __init__(self, pricing: PricingEngine | None = None):
        self.pricing = pricing

    # Extraction
    def extract_from_text(self, text: str, item_type: str) -> list[ModifierEntry]:
        """Extract modifiers from user text input."""
        pass

    def extract_quantity(self, text: str) -> tuple[int, str]:
        """Extract quantity prefix from text."""
        pass

    # Modification
    def add_to_item(self, item: MenuItemTask, modifier: ModifierEntry) -> bool:
        """Add modifier to item, return success."""
        pass

    def remove_from_item(self, item: MenuItemTask, modifier_slug: str) -> bool:
        """Remove modifier from item by slug."""
        pass

    def update_quantity(self, item: MenuItemTask, modifier_slug: str, qty: int) -> bool:
        """Update modifier quantity on item."""
        pass

    # Lookup
    def find_modifier(self, text: str, item_type: str | None = None) -> ModifierEntry | None:
        """Find matching modifier from cache."""
        pass

    def find_all_matches(self, text: str) -> list[ModifierEntry]:
        """Find all possible modifier matches (for disambiguation)."""
        pass

    # Pricing
    def calculate_price(self, modifier: ModifierEntry) -> float:
        """Calculate price for modifier."""
        pass

    def recalculate_item_modifiers(self, item: MenuItemTask) -> float:
        """Recalculate total modifier price for item."""
        pass
```

#### Step 2.2: Create ModifierEntry dataclass
**Enhance existing in modifier_utils.py:**

```python
@dataclass
class ModifierEntry:
    """Standard format for all modifier entries."""
    slug: str
    category: str
    quantity: int = 1
    price: float = 0.0
    display_name: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "ModifierEntry":
        """Create from dictionary (backward compatibility)."""
        pass

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        pass
```

#### Step 2.3: Migrate modifier_operations.py
- Move extraction functions to `ModifierService.extract_*`
- Move `find_modifier_on_any_item` to `ModifierService.find_on_items`
- Move `remove_modifier_from_item` to `ModifierService.remove_from_item`
- Keep file as facade importing from service (backward compatibility)

#### Step 2.4: Migrate modifier_change_handler.py
- Use `ModifierService` for all operations
- Remove duplicated extraction/normalization code
- Keep handler logic (detect change request, apply change)

#### Step 2.5: Migrate modifier_input_handler.py
- Use `ModifierService` for pattern matching
- Use `ModifierService` for modifier application
- Remove duplicated code

#### Step 2.6: Update select_input.py
- Use `ModifierService.extract_from_text` instead of local extraction
- Use `ModifierService.find_modifier` for matching

### Verification
```bash
python -m pytest --tb=short -q
python -m pytest tests/test_tasks_parsing.py -v  # Modifier-specific tests
```

### Estimated Effort: 18-25 hours

---

## Phase 3: Parser Pipeline Refactoring

### Problem
Parser module has circular dependencies and 300+ private functions with tangled call graphs.

### Files Affected
- `orderbot/tasks/parsers/deterministic/core.py` (413 lines)
- `orderbot/tasks/parsers/deterministic/item_parsing.py` (685 lines)
- `orderbot/tasks/parsers/deterministic/tokenization.py` (664 lines)
- `orderbot/tasks/parsers/deterministic/modification_parsing.py` (631 lines)
- `orderbot/tasks/parsers/deterministic/extraction.py` (621 lines)

### Implementation Steps

#### Step 3.1: Define Pipeline Architecture
**New file:** `orderbot/tasks/parsers/pipeline.py`

```python
@dataclass
class ParseContext:
    """Context passed through pipeline stages."""
    raw_input: str
    tokens: list[str] = field(default_factory=list)
    input_type: InputType | None = None
    items: list[ParsedItem] = field(default_factory=list)
    modifiers: list[ModifierEntry] = field(default_factory=list)
    inquiries: list[Inquiry] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

class ParsingPipeline:
    """Orchestrates parsing through clear stages."""

    def __init__(self):
        self.stages = [
            TokenizationStage(),
            ClassificationStage(),
            ItemExtractionStage(),
            ModifierExtractionStage(),
            InquiryExtractionStage(),
            ValidationStage(),
        ]

    def parse(self, text: str) -> ParseContext:
        ctx = ParseContext(raw_input=text)
        for stage in self.stages:
            ctx = stage.process(ctx)
        return ctx

class PipelineStage(ABC):
    """Base class for pipeline stages."""

    @abstractmethod
    def process(self, ctx: ParseContext) -> ParseContext:
        pass
```

#### Step 3.2: Create TokenizationStage
**New file:** `orderbot/tasks/parsers/stages/tokenization.py`

Move from `tokenization.py`:
- `tokenize_input()` → `TokenizationStage.process()`
- `normalize_text()` → `TokenizationStage._normalize()`
- `split_into_phrases()` → `TokenizationStage._split_phrases()`

#### Step 3.3: Create ClassificationStage
**New file:** `orderbot/tasks/parsers/stages/classification.py`

Move from `core.py`:
- Intent detection (greeting, done_ordering, cancel, inquiry)
- Input type classification
- Create `InputType` enum if not exists

#### Step 3.4: Create ItemExtractionStage
**New file:** `orderbot/tasks/parsers/stages/item_extraction.py`

Move from `item_parsing.py`:
- `parse_configurable_item()` → `ItemExtractionStage._parse_configurable()`
- `parse_menu_item()` → `ItemExtractionStage._parse_menu_item()`
- Item type detection logic

#### Step 3.5: Create ModifierExtractionStage
**New file:** `orderbot/tasks/parsers/stages/modifier_extraction.py`

Move from `modification_parsing.py` and `extraction.py`:
- Modifier pattern matching
- Quantity extraction
- Selection building

#### Step 3.6: Create InquiryExtractionStage
**New file:** `orderbot/tasks/parsers/stages/inquiry_extraction.py`

Move from `inquiry/` subdirectory:
- Menu inquiry detection
- Description inquiry detection
- Ingredient inquiry detection

#### Step 3.7: Update core.py as Facade
Keep `parse_open_input()` as main entry point:
```python
def parse_open_input(text: str, **kwargs) -> OpenInputResponse:
    pipeline = ParsingPipeline()
    ctx = pipeline.parse(text)
    return OpenInputResponse.from_context(ctx)
```

### Directory Structure After Refactoring
```
orderbot/tasks/parsers/
├── __init__.py
├── pipeline.py              # Pipeline orchestrator
├── stages/
│   ├── __init__.py
│   ├── base.py              # PipelineStage ABC
│   ├── tokenization.py      # TokenizationStage
│   ├── classification.py    # ClassificationStage
│   ├── item_extraction.py   # ItemExtractionStage
│   ├── modifier_extraction.py # ModifierExtractionStage
│   └── inquiry_extraction.py  # InquiryExtractionStage
├── deterministic/           # Keep for backward compat, delegate to stages
│   ├── core.py              # Facade
│   └── ...
└── llm_parsers.py           # LLM fallback (unchanged)
```

### Verification
```bash
python -m pytest tests/test_tasks_parsing.py -v
python -m pytest --tb=short -q
```

### Estimated Effort: 30-40 hours

---

## Phase 4: Cache Architecture Reorganization

### Problem
Cache fragmented into 16 mixin files with unclear organization and duplicate item type queries.

### Files Affected
- `orderbot/cache/core.py`
- `orderbot/cache/menu_queries.py`
- `orderbot/cache/item_type_queries.py`
- `orderbot/cache/item_type_core_queries.py` (duplicate!)
- All other query/loader mixins

### Implementation Steps

#### Step 4.1: Audit and Document Current Methods
Create inventory of all cache methods and their locations:
```
get_menu_item() - menu_queries.py
get_item_type() - item_type_queries.py AND item_type_core_queries.py (!)
get_ingredient() - ingredient_queries.py
...
```

#### Step 4.2: Consolidate Item Type Queries
Merge `item_type_queries.py` and `item_type_core_queries.py`:
- Identify overlapping methods
- Keep one canonical implementation
- Add deprecation warnings for removed methods

#### Step 4.3: Reorganize by Domain
**New structure:**
```
orderbot/cache/
├── __init__.py
├── core.py                  # MenuDataCache main class
├── queries/
│   ├── __init__.py
│   ├── menu.py              # Menu item queries
│   ├── item_types.py        # Item type queries (consolidated)
│   ├── ingredients.py       # Ingredient queries
│   ├── categories.py        # Category queries
│   ├── pricing.py           # Pricing queries
│   └── parsing.py           # Parsing-related queries
├── loaders/
│   ├── __init__.py
│   ├── menu_items.py
│   ├── item_types.py
│   ├── ingredients.py
│   └── patterns.py
└── base.py                  # Shared utilities
```

#### Step 4.4: Create Query Classes (Optional Improvement)
Instead of mixins, use composition:
```python
class MenuDataCache:
    def __init__(self):
        self._data = CacheData()
        self.menu = MenuQueries(self._data)
        self.item_types = ItemTypeQueries(self._data)
        self.ingredients = IngredientQueries(self._data)
        # ...

    # Delegate common methods for backward compatibility
    def get_menu_item(self, *args, **kwargs):
        return self.menu.get_item(*args, **kwargs)
```

#### Step 4.5: Update Imports
- Add `__all__` to each module
- Update `cache/__init__.py` exports
- Add backward compatibility imports

### Verification
```bash
python -m pytest --tb=short -q
# Verify no import errors
python -c "from orderbot.cache import menu_cache; print(menu_cache)"
```

### Estimated Effort: 20-30 hours

---

## Phase 5: Attribute/Question Consolidation

### Problem
Question generation and attribute tracking scattered across 4+ modules.

### Files Affected
- `orderbot/tasks/attribute_inference.py`
- `orderbot/tasks/config/question_builder.py`
- `orderbot/tasks/field_config.py`
- `orderbot/tasks/pending_fields.py`
- `orderbot/tasks/slot_orchestrator.py`

### Implementation Steps

#### Step 5.1: Create Question Domain Model
**New file:** `orderbot/tasks/models/question.py`

```python
@dataclass
class Question:
    """Represents a question to ask the user."""
    attribute_slug: str
    text: str
    options: list[str] | None = None
    is_required: bool = True
    item_id: str | None = None
    item_type: str | None = None
    display_order: int = 0

    @classmethod
    def from_attribute(cls, attr: dict, item: MenuItemTask) -> "Question":
        """Create question from attribute definition."""
        pass
```

#### Step 5.2: Create QuestionOrchestrator
**New file:** `orderbot/tasks/question_orchestrator.py`

```python
class QuestionOrchestrator:
    """Unified orchestrator for all question-related logic."""

    def __init__(self, menu_cache: MenuDataCache):
        self.cache = menu_cache

    def get_next_question(self, item: MenuItemTask) -> Question | None:
        """Get next question for an item."""
        # Unified logic: get required attrs, find first missing, build question
        pass

    def get_all_pending_questions(self, order: OrderTask) -> list[Question]:
        """Get all pending questions across all items."""
        pass

    def infer_attributes(self, item_name: str, item_type: str) -> dict[str, Any]:
        """Infer attributes from item name."""
        # Moved from attribute_inference.py
        pass

    def get_field_config(self, item_type: str) -> FieldConfig:
        """Get field configuration for item type."""
        # Moved from field_config.py
        pass

    def build_question_text(self, attr: dict, item: MenuItemTask) -> str:
        """Build question text for attribute."""
        # Moved from question_builder.py
        pass
```

#### Step 5.3: Migrate attribute_inference.py
- Move `infer_attributes_from_name()` to `QuestionOrchestrator.infer_attributes()`
- Keep file as facade for backward compatibility

#### Step 5.4: Migrate question_builder.py
- Move question building logic to `QuestionOrchestrator.build_question_text()`
- Move option formatting to `QuestionOrchestrator._format_options()`

#### Step 5.5: Migrate field_config.py
- Move field configuration lookup to `QuestionOrchestrator.get_field_config()`
- Consider moving FieldConfig to models/

#### Step 5.6: Enhance pending_fields.py
- Convert to proper Enum if not already
- Add helper methods for pending field manipulation

#### Step 5.7: Update slot_orchestrator.py
- Use `QuestionOrchestrator` for question-related logic
- Keep slot ordering logic

### Verification
```bash
python -m pytest tests/test_tasks_integration.py -v
python -m pytest --tb=short -q
```

### Estimated Effort: 15-20 hours

---

## Phase 6: Test Suite Reorganization

### Problem
Tests split across 18 batch files with no clear organization.

### Files Affected
- `tests/test_resiliency_batch1.py` through `tests/test_resiliency_batch18.py`
- All other test files

### Implementation Steps

#### Step 6.1: Audit Current Test Coverage
```bash
# Generate coverage report
python -m pytest --cov=orderbot --cov-report=html
```

Document what each batch file tests.

#### Step 6.2: Define New Test Structure
```
tests/
├── unit/                    # Unit tests for individual functions/classes
│   ├── test_parsers.py
│   ├── test_cache.py
│   ├── test_models.py
│   └── test_pricing.py
├── integration/             # Integration tests for handler flows
│   ├── test_item_adding.py
│   ├── test_item_modification.py
│   ├── test_checkout_flow.py
│   └── test_state_transitions.py
├── e2e/                     # End-to-end conversation tests
│   ├── test_complete_orders.py
│   ├── test_edge_cases.py
│   └── test_error_recovery.py
├── features/                # Feature-specific tests
│   ├── test_modifiers.py
│   ├── test_pricing.py
│   ├── test_disambiguation.py
│   └── test_inquiries.py
├── helpers/                 # Test utilities (existing)
└── conftest.py              # Shared fixtures
```

#### Step 6.3: Add Pytest Markers
**Update `pytest.ini` or `pyproject.toml`:**
```ini
[pytest]
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    bagel: Bagel-related tests
    beverage: Beverage-related tests
    modifier: Modifier handling tests
    pricing: Pricing tests
    slow: Slow tests (skip in quick runs)
```

#### Step 6.4: Create Migration Script
```python
# scripts/migrate_tests.py
# Analyze each batch file and suggest target location
# Don't auto-migrate - manual review needed
```

#### Step 6.5: Migrate Tests Incrementally
1. Start with batch1 - identify themes, move to appropriate locations
2. Add markers to each migrated test
3. Verify passing: `python -m pytest tests/features/test_modifiers.py -v`
4. Repeat for each batch

#### Step 6.6: Create Shared Fixtures
**Update `conftest.py`:**
```python
@pytest.fixture
def order_task():
    """Fresh OrderTask for testing."""
    return OrderTask()

@pytest.fixture
def state_machine(db_session):
    """Configured state machine."""
    return StateMachine(db_session=db_session)

@pytest.fixture
def menu_data():
    """Standard test menu data."""
    return MenuDataBuilder()...
```

#### Step 6.7: Deprecate Batch Files
- Add deprecation comment to batch files
- Keep for 1-2 releases
- Remove once all tests migrated

### Verification
```bash
# Run by marker
python -m pytest -m "modifier" -v
python -m pytest -m "not slow" -v

# Full suite
python -m pytest --tb=short -q
```

### Estimated Effort: 25-35 hours

---

## Phase 7: Quick Wins Bundle

### 7.1: Clean Unused Imports/Dead Code

**Tool:**
```bash
pip install vulture autoflake
vulture orderbot/ --min-confidence 80
autoflake --in-place --remove-all-unused-imports orderbot/**/*.py
```

**Manual review required for:**
- Functions only used via `getattr()` or dynamic dispatch
- Test-only imports

**Estimated Effort:** 4-6 hours

### 7.2: Consolidate Messaging

**Files:**
- `orderbot/tasks/message_builder.py`
- `orderbot/tasks/checkout_messages.py`

**Create:** `orderbot/tasks/messaging/`
```
messaging/
├── __init__.py
├── builder.py           # MessageBuilder class
├── templates.py         # Message templates/constants
└── formatters.py        # Formatting utilities
```

**Estimated Effort:** 6-8 hours

### 7.3: Fix Circular Import Risks

**Create:** `orderbot/tasks/handler_factory.py`
```python
class HandlerFactory:
    _handlers: dict[str, type] = {}

    @classmethod
    def register(cls, name: str, handler_class: type) -> None:
        cls._handlers[name] = handler_class

    @classmethod
    def create(cls, name: str, config: HandlerConfig) -> Any:
        if name not in cls._handlers:
            raise ValueError(f"Unknown handler: {name}")
        return cls._handlers[name](config)

# Usage in state_machine.py
item_adder = HandlerFactory.create("item_adder", config)
```

**Estimated Effort:** 4-6 hours

### Total Phase 7 Effort: 14-20 hours

---

## Phase 8: Error Handling Standardization

### Problem
Inconsistent error handling patterns across the codebase.

### Implementation Steps

#### Step 8.1: Define Error Hierarchy
**New file:** `orderbot/exceptions.py` (enhance existing)

```python
class OrderbotError(Exception):
    """Base exception for orderbot."""
    pass

class ParsingError(OrderbotError):
    """Error during input parsing."""
    def __init__(self, message: str, input_text: str = None):
        self.input_text = input_text
        super().__init__(message)

class MenuDataError(OrderbotError):
    """Error accessing menu data."""
    pass

class MenuDataNotLoadedError(MenuDataError):
    """Menu cache not loaded."""
    pass

class ItemNotFoundError(MenuDataError):
    """Requested item not found."""
    def __init__(self, item_name: str):
        self.item_name = item_name
        super().__init__(f"Item not found: {item_name}")

class ValidationError(OrderbotError):
    """Input validation error."""
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"{field}: {message}")
```

#### Step 8.2: Document Error Handling Rules
**Add to CLAUDE.md:**
```markdown
## Error Handling Patterns

1. **Cache queries that fail** → raise `MenuDataNotLoadedError` or `ItemNotFoundError`
2. **Parsing that finds nothing** → return `None` (use `Optional` type hint)
3. **Handler flows with issues** → return `StateMachineResult` with user-friendly message
4. **Validation failures** → raise `ValidationError` with field name
5. **Unexpected errors** → log with context, re-raise or return error result
```

#### Step 8.3: Audit and Update Handlers
For each handler:
1. Identify current error patterns
2. Update to match standard
3. Add appropriate logging

### Estimated Effort: 15-20 hours

---

## Phase 9: Service Layer Cleanup

### Problem
Unclear boundaries between services and task handlers.

### Implementation Steps

#### Step 9.1: Define Layer Responsibilities
```
orderbot/
├── services/          # External concerns: DB, APIs, caching
│   ├── order.py       # Order persistence
│   ├── session.py     # Session management
│   └── menu.py        # Menu data service (wraps cache)
├── tasks/             # Business logic: workflows, state, interaction
│   ├── handlers/      # User interaction handlers
│   ├── models/        # Domain models
│   └── services/      # Domain services (ModifierService, etc.)
└── routes/            # HTTP layer
```

#### Step 9.2: Move Helpers to Appropriate Layer
- `services/helpers.py` → merge into relevant service or utils
- `services/item_type_helpers.py` → move to `tasks/services/` if domain logic

#### Step 9.3: Create Menu Service Facade
**New file:** `orderbot/services/menu.py`
```python
class MenuService:
    """Service facade for menu operations."""

    def __init__(self, cache: MenuDataCache):
        self.cache = cache

    def get_item(self, name: str) -> MenuItem | None:
        return self.cache.get_menu_item(name)

    def search_items(self, query: str) -> list[MenuItem]:
        return self.cache.search_menu_items(query)

    # ... other delegated methods
```

### Estimated Effort: 12-18 hours

---

## Execution Timeline

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| 7 | Quick Wins | 14-20h | None |
| 2 | Modifier Consolidation | 18-25h | None |
| 5 | Attribute/Question | 15-20h | None |
| 8 | Error Handling | 15-20h | None |
| 4 | Cache Reorganization | 20-30h | Phase 2 |
| 1 | Handler Decomposition | 40-50h | Phases 2, 5 |
| 3 | Parser Pipeline | 30-40h | Phase 2 |
| 9 | Service Layer | 12-18h | Phases 1, 4 |
| 6 | Test Reorganization | 25-35h | All others |

**Recommended Order:**
1. Phase 7 (Quick Wins) - Low risk, immediate cleanup
2. Phase 2 (Modifiers) - Address major duplication
3. Phase 5 (Questions) - Simplify question logic
4. Phase 8 (Errors) - Standardize patterns
5. Phase 4 (Cache) - Better organization
6. Phase 1 (Handlers) - Major decomposition
7. Phase 3 (Parsers) - Complex refactoring
8. Phase 9 (Services) - Architecture cleanup
9. Phase 6 (Tests) - Final reorganization

---

## Risk Mitigation

### Before Each Phase
1. Create git branch: `refactor/phase-N-description`
2. Run full test suite, document baseline
3. Review affected files

### During Each Phase
1. Make incremental commits
2. Run tests after each significant change
3. Document any behavioral changes

### After Each Phase
1. Run full test suite
2. Compare with baseline
3. Code review
4. Merge to main

### Rollback Plan
Each phase is independent - if issues arise:
1. Revert to pre-phase commit
2. Analyze what went wrong
3. Adjust approach
4. Re-attempt

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Max file size | 1,136 lines | <400 lines |
| Duplicate code blocks | ~15 | <5 |
| Circular import risks | 3-4 | 0 |
| Test organization | 18 batch files | Feature-based |
| Cache method discoverability | Poor | Good (organized by domain) |
| Error handling consistency | Mixed | Standardized |
