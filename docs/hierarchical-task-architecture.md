# Hierarchical Task Architecture for Order Capture

## Overview

This document describes a new architecture for handling food orders using a hierarchical task system. The goals are:

1. **Reliability**: No dropped items, no missed modifiers, no looping questions
2. **Natural conversation flow**: Handle multi-item orders naturally
3. **Low latency**: Response time under 2 seconds
4. **Visual progress tracking**: Support future UI showing order build progress

## Current Problems

1. **Items getting dropped**: When user says "I want a bagel and coffee", sometimes items are lost
2. **Question loops**: Asking about already-answered questions (e.g., "pickup or delivery?" twice)
3. **State confusion**: Hard to track what's been captured vs. what still needs answers

## Architecture

### Task Hierarchy

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
│   ├── items: [ItemTask, ...]
│   │
│   ├── BagelItemTask[0]
│   │   ├── status: pending|in_progress|complete
│   │   ├── bagel_type: string|null (default: from menu or null)
│   │   ├── quantity: int (default: 1)
│   │   ├── toasted: bool|null (default: from menu or null)
│   │   ├── spread: string|null (default: null, optional: true)
│   │   └── extras: [string] (default: [], optional: true)
│   │
│   ├── CoffeeItemTask[0]
│   │   ├── status: pending|in_progress|complete
│   │   ├── drink_type: string|null
│   │   ├── size: string|null (default: "medium")
│   │   ├── iced: bool|null
│   │   ├── milk: string|null (default: null, optional: true)
│   │   └── sweetener: string|null (default: null, optional: true)
│   │
│   └── ... more items
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

### Task States

Each task has a status:
- **pending**: Not started, waiting for prerequisites
- **in_progress**: Currently being worked on, has unfilled required fields
- **complete**: All required fields filled
- **skipped**: Explicitly skipped or cancelled by user

### Field Definitions

Each field in a task has:
```python
class FieldDef:
    name: str
    required: bool  # Must be filled before task is complete
    default: Any | None  # Default value (if set, don't ask)
    question: str | None  # Question to ask if field is empty
    validator: Callable | None  # Validation function
```

### Slot Defaults from Menu

The menu configuration defines defaults per item type:

```python
# menu_config.yaml or in menu_index
item_types:
  bagel:
    fields:
      bagel_type:
        required: true
        default: null  # Must ask - no default
      quantity:
        required: true
        default: 1
      toasted:
        required: true
        default: null  # Must ask - no default (set to false if you don't want to ask)
      spread:
        required: false
        default: null
        question: "Any spread - cream cheese, butter?"
      extras:
        required: false
        default: []
        question: "Anything else on it - lox, bacon, tomato?"

  coffee:
    fields:
      drink_type:
        required: true
        default: null
      size:
        required: true
        default: "medium"  # Don't ask - default to medium
      iced:
        required: true
        default: null  # Must ask
      milk:
        required: false
        default: null
      sweetener:
        required: false
        default: null
```

## Processing Flow

### 1. Input Parsing (LLM with Structured Output)

Every user message is parsed by LLM into a structured format:

```python
class ParsedInput(BaseModel):
    """Structured output from LLM parsing."""

    # New items mentioned
    new_items: list[ParsedItem] = []

    # Modifications to existing items
    modifications: list[Modification] = []

    # Answers to pending questions
    answers: dict[str, Any] = {}

    # Intents
    wants_checkout: bool = False
    wants_cancel: bool = False
    cancel_item_index: int | None = None

    # Delivery/pickup
    order_type: Literal["pickup", "delivery"] | None = None
    address: str | None = None

    # Customer info
    customer_name: str | None = None
    customer_contact: str | None = None


class ParsedItem(BaseModel):
    """A parsed item from user input."""
    item_type: Literal["bagel", "coffee", "sandwich", "drink"]

    # Known fields (extracted from input)
    fields: dict[str, Any] = {}
    # e.g., {"bagel_type": "everything", "toasted": True, "spread": "cream cheese"}


class Modification(BaseModel):
    """A modification to an existing item."""
    item_index: int | None = None  # Which item to modify (None = current/last)
    item_type: str | None = None  # Or identify by type
    field: str  # Which field to change
    new_value: Any  # New value
```

### 2. State Update (Deterministic)

After parsing, deterministically update the task tree:

```python
def update_state(task_tree: OrderTask, parsed: ParsedInput) -> OrderTask:
    # 1. Apply order type if provided
    if parsed.order_type:
        task_tree.delivery_method.order_type = parsed.order_type
        if parsed.order_type == "pickup":
            task_tree.delivery_method.status = "complete"

    # 2. Apply address if provided
    if parsed.address:
        task_tree.delivery_method.address.street = parsed.address
        # ... parse and validate

    # 3. Add new items
    for item in parsed.new_items:
        item_task = create_item_task(item)
        task_tree.items.items.append(item_task)

    # 4. Apply modifications
    for mod in parsed.modifications:
        target_item = find_item(task_tree, mod)
        if target_item:
            setattr(target_item, mod.field, mod.new_value)

    # 5. Apply answers to pending questions
    active_task = get_active_task(task_tree)
    for field, value in parsed.answers.items():
        if hasattr(active_task, field):
            setattr(active_task, field, value)

    # 6. Handle cancellations
    if parsed.cancel_item_index is not None:
        task_tree.items.items[parsed.cancel_item_index].status = "skipped"

    # 7. Recalculate task statuses
    recalculate_statuses(task_tree)

    return task_tree
```

### 3. Next Action Selection (Deterministic)

After state update, determine what to do next:

```python
def get_next_action(task_tree: OrderTask) -> Action:
    # Priority order for completing tasks

    # 1. If no items yet, prompt for order
    if not task_tree.items.items:
        return AskAction(question="What can I get for you today?")

    # 2. Complete current item before moving to next
    for item in task_tree.items.items:
        if item.status == "in_progress":
            missing = get_missing_required_fields(item)
            if missing:
                field = missing[0]
                return AskAction(question=field.question, target=item)
            else:
                item.status = "complete"

    # 3. Start next pending item
    for item in task_tree.items.items:
        if item.status == "pending":
            item.status = "in_progress"
            missing = get_missing_required_fields(item)
            if missing:
                field = missing[0]
                return AskAction(question=field.question, target=item)

    # 4. All items complete - check delivery method
    if task_tree.delivery_method.status != "complete":
        if task_tree.delivery_method.order_type is None:
            return AskAction(question="Is this for pickup or delivery?")
        # ... address collection for delivery

    # 5. Proceed to checkout
    if task_tree.checkout.status != "complete":
        return CheckoutAction(task_tree)

    # 6. Collect customer info
    if task_tree.customer_info.status != "complete":
        if not task_tree.customer_info.name:
            return AskAction(question="Can I get a name for the order?")
        # ...

    # 7. Payment
    if task_tree.payment.status != "complete":
        return PaymentAction(task_tree)

    # 8. Done!
    return CompleteAction(task_tree)
```

## Example Conversations

### Example 1: Multi-item order

```
User: "Hi, I'd like an everything bagel with lox and a large iced latte"

[LLM Parse]
ParsedInput(
    new_items=[
        ParsedItem(item_type="bagel", fields={"bagel_type": "everything", "extras": ["lox"]}),
        ParsedItem(item_type="coffee", fields={"drink_type": "latte", "size": "large", "iced": True}),
    ]
)

[State Update]
- Create BagelItemTask[0]: bagel_type=everything, extras=[lox], status=in_progress
- Create CoffeeItemTask[0]: drink_type=latte, size=large, iced=True, status=pending

[Next Action]
- BagelItemTask[0] missing: toasted (required, no default)

Bot: "Would you like the everything bagel toasted?"
User: "Yes please"

[LLM Parse]
ParsedInput(answers={"toasted": True})

[State Update]
- BagelItemTask[0].toasted = True
- BagelItemTask[0] now has all required fields → status=complete

[Next Action]
- BagelItemTask[0] complete
- CoffeeItemTask[0] is pending → set to in_progress
- CoffeeItemTask[0] missing: nothing! (drink_type, size, iced all set, milk/sweetener optional)
- CoffeeItemTask[0] → status=complete

[Next Action]
- All items complete
- DeliveryMethodTask missing: order_type

Bot: "Got it - everything bagel toasted with lox, and a large iced latte. Is this for pickup or delivery?"
```

### Example 2: Correction mid-flow

```
User: "I want a sesame bagel toasted with cream cheese"

[State]
- BagelItemTask[0]: sesame, toasted=True, spread=cream cheese, status=in_progress

Bot: "Anything else on it - lox, bacon, tomato?"
User: "Actually, make that not toasted. And add a coffee."

[LLM Parse]
ParsedInput(
    modifications=[Modification(item_index=0, field="toasted", new_value=False)],
    new_items=[ParsedItem(item_type="coffee", fields={})]
)

[State Update]
- BagelItemTask[0].toasted = False
- Create CoffeeItemTask[0]: status=pending

[Next Action]
- Still on BagelItemTask[0], asked about extras, user didn't answer
- Treat "not toasted" + "add coffee" as response to extras question: no extras

Bot: "No problem, sesame bagel not toasted with cream cheese. Now for your coffee - what kind would you like?"
```

### Example 3: Cancel an item

```
User: "I want a plain bagel and a latte"

[State]
- BagelItemTask[0]: plain, status=in_progress
- CoffeeItemTask[0]: latte, status=pending

Bot: "Would you like the plain bagel toasted?"
User: "Actually, forget the bagel. Just the latte."

[LLM Parse]
ParsedInput(cancel_item_index=0)

[State Update]
- BagelItemTask[0].status = "skipped"
- CoffeeItemTask[0].status = "in_progress"

[Next Action]
- CoffeeItemTask[0] missing: size, iced

Bot: "No problem, just the latte. What size - small, medium, or large?"
```

## Implementation Plan

### Phase 1: Task Tree Foundation
1. Define Pydantic models for task hierarchy
2. Implement task status management
3. Implement field definitions with defaults
4. Create menu configuration for field defaults

### Phase 2: LLM Parsing
1. Set up `instructor` library for structured outputs
2. Define ParsedInput schema
3. Create parsing prompt
4. Implement parsing function with retry logic

### Phase 3: State Management
1. Implement state update logic
2. Implement next action selection
3. Handle modifications and cancellations
4. Integrate with existing session persistence

### Phase 4: Integration
1. Create new endpoint or update existing
2. Bridge with existing chains (gradual migration)
3. Update adapter for compatibility
4. Add logging and debugging

### Phase 5: Testing & Refinement
1. Unit tests for task tree logic
2. Integration tests for conversation flows
3. Load testing for latency
4. Edge case handling

## Visual Progress (Future)

The task tree structure naturally supports visual progress display:

```
Order Progress
├── ✅ Everything Bagel - toasted, cream cheese, lox ($8.50)
├── 🔄 Large Iced Latte
│   ├── ✅ Size: Large
│   ├── ✅ Style: Iced
│   ├── ❓ Milk: ?
│   └── ❓ Sweetener: ?
├── ⏳ Delivery Method
├── ⏳ Customer Info
└── ⏳ Payment
```

Each task exposes:
- `get_progress()` → percentage complete
- `get_display_summary()` → human-readable summary
- `get_missing_fields()` → what still needs answers

## Technology Stack

- **State Management**: Custom task tree with Pydantic models
- **LLM Parsing**: `instructor` library with OpenAI/Anthropic
- **Flow Control**: Deterministic Python logic (no LangGraph dependency)
- **Persistence**: Same session storage (Redis/DB)

## Latency Budget

| Step | Target | Notes |
|------|--------|-------|
| LLM Parsing | 500-800ms | Single call with structured output |
| State Update | <10ms | Pure Python logic |
| Next Action | <10ms | Pure Python logic |
| Response Generation | <10ms | Template-based |
| **Total** | **<1 second** | Well under 2s target |

If latency becomes an issue:
1. Use faster models (GPT-4o-mini, Claude Haiku)
2. Cache common parsing patterns
3. Parallelize parsing with response prep
