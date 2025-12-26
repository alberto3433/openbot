# Slot Orchestrator Migration Plan

## Overview

This document describes the migration from the current hardcoded `FlowState`/`OrderPhase` system to a slot-filling architecture driven by the `OrderTask` model.

## Current State

The state machine (`tasks/state_machine.py`) uses:
- `FlowState` dataclass with `phase: OrderPhase`
- Hardcoded phase transitions like `state.phase = OrderPhase.CHECKOUT_NAME`
- Phase-based routing in `process()` method

The models (`tasks/models.py`) define:
- `OrderTask` with all subtasks (DeliveryMethodTask, ItemsTask, etc.)
- Field completion logic (`get_missing_required_fields`, `get_fields_to_ask`)
- Task status tracking (pending, in_progress, complete, skipped)

**Problem**: The state machine doesn't use the models. Flow logic is duplicated and hardcoded.

## Target State

A `SlotOrchestrator` that:
1. Uses `OrderTask` as the single source of truth
2. Determines "what to ask next" by checking which slots are unfilled
3. Supports conditional slots (e.g., address only if delivery)
4. Makes phases derivable from slot state (no manual tracking)

## Slot Definitions

### Order-Level Slots (in priority order)

| Slot | Field Path | Question | Required | Condition |
|------|------------|----------|----------|-----------|
| Items | `items` | "What can I get for you?" | Yes | Always |
| Delivery Method | `delivery_method.order_type` | "Is this for pickup or delivery?" | Yes | Items exist |
| Delivery Address | `delivery_method.address.street` | "What's the delivery address?" | Yes | order_type == "delivery" |
| Customer Name | `customer_info.name` | "Can I get a name for the order?" | Yes | Always |
| Order Confirm | `checkout.confirmed` | (dynamic summary) | Yes | Always |
| Payment Method | `payment.method` | "How would you like to pay?" | Yes | Always |
| Notification Method | `customer_info.phone` or `customer_info.email` | "Text or email for confirmation?" | Yes | payment.method == "card_link" |

### Item-Level Slots (per item type)

**Bagel:**
| Slot | Required | Default | Condition |
|------|----------|---------|-----------|
| bagel_type | Yes | None | - |
| toasted | Yes | None | - |
| spread | No | None | - |
| extras | No | [] | - |

**Coffee:**
| Slot | Required | Default | Condition |
|------|----------|---------|-----------|
| size | Yes | None | Not a soda |
| iced | Yes | None | Not a soda |
| milk | No | None | - |
| sweetener | No | None | - |

**Speed Menu Bagel:**
| Slot | Required | Default | Condition |
|------|----------|---------|-----------|
| toasted | Yes | None | - |

**Menu Item (Omelette, etc.):**
| Slot | Required | Default | Condition |
|------|----------|---------|-----------|
| side_choice | Yes | None | requires_side_choice == True |
| bagel_choice | Yes | None | side_choice == "bagel" |

## Migration Phases

### Phase 1: Add OrderTask Alongside FlowState

**Goal**: Introduce `OrderTask` and `SlotOrchestrator` without changing existing behavior.

**Changes**:
1. Create `tasks/slot_orchestrator.py` with:
   - `SlotDefinition` dataclass
   - `SlotCategory` enum
   - `SlotOrchestrator` class
   - `ORDER_SLOTS` list

2. Modify `OrderStateMachine.__init__()`:
   - Add `self.order_task: OrderTask = None`
   - Add `self.orchestrator: SlotOrchestrator = None`

3. Add sync method `_sync_db_order_to_task(order: Order)`:
   - Copies DB Order data to OrderTask
   - Called at start of each `process()` call

4. Add logging to compare:
   - What FlowState says the phase is
   - What SlotOrchestrator says the next slot is
   - Log mismatches for debugging

**Testing**:
- Run existing test suite - all tests should pass
- Add new tests for SlotOrchestrator in isolation
- Add logging assertions to verify sync is working

**Files to create/modify**:
- `tasks/slot_orchestrator.py` (new)
- `tasks/state_machine.py` (add OrderTask, sync, logging)
- `tests/test_slot_orchestrator.py` (new)

---

### Phase 2: Use SlotOrchestrator for "What's Next"

**Goal**: Replace hardcoded phase transitions with orchestrator queries.

**Changes**:
1. In handlers that transition phases, replace:
   ```python
   # Before
   state.phase = OrderPhase.CHECKOUT_NAME

   # After
   # (no manual assignment - orchestrator determines next)
   ```

2. Add `_get_next_action()` method:
   ```python
   def _get_next_action(self) -> tuple[SlotCategory, SlotDefinition]:
       return self.orchestrator.get_next_slot()
   ```

3. Update `process()` to route based on slot category instead of phase.

**Testing**:
- Verify all conversation flows still work
- Test edge cases: delivery vs pickup, different payment methods
- Verify no regressions in item configuration

---

### Phase 3: Derive Phase from Slots

**Goal**: Make `OrderPhase` a computed property, not stored state.

**Changes**:
1. Add `SlotOrchestrator.get_current_phase() -> OrderPhase`
2. Change `FlowState.phase` to be computed from orchestrator
3. Remove all `state.phase = ...` assignments

**Testing**:
- Full regression test
- Verify phase is always correct based on order state

---

### Phase 4: Remove FlowState

**Goal**: `OrderTask` becomes the only state object.

**Changes**:
1. Move `pending_item_ids` and `pending_field` to `OrderTask`
2. Remove `FlowState` class
3. Update all method signatures
4. Persist `OrderTask` to session instead of `FlowState`

**Testing**:
- Full regression test
- Session persistence tests
- Multi-turn conversation tests

---

## Testing Strategy

### Unit Tests for SlotOrchestrator

```python
# tests/test_slot_orchestrator.py

def test_empty_order_needs_items():
    """First slot should be items when order is empty."""
    order = OrderTask()
    orch = SlotOrchestrator(order)
    slot = orch.get_next_slot()
    assert slot.category == SlotCategory.ITEMS

def test_with_items_needs_delivery():
    """After items, should ask delivery method."""
    order = OrderTask()
    order.items.add_item(BagelItemTask(bagel_type="plain", toasted=True))
    orch = SlotOrchestrator(order)
    slot = orch.get_next_slot()
    assert slot.category == SlotCategory.DELIVERY_METHOD

def test_pickup_skips_address():
    """Pickup orders should skip address slot."""
    order = OrderTask()
    order.items.add_item(BagelItemTask(bagel_type="plain", toasted=True))
    order.delivery_method.order_type = "pickup"
    orch = SlotOrchestrator(order)
    slot = orch.get_next_slot()
    assert slot.category == SlotCategory.CUSTOMER_NAME  # Skipped address

def test_delivery_needs_address():
    """Delivery orders should ask for address."""
    order = OrderTask()
    order.items.add_item(BagelItemTask(bagel_type="plain", toasted=True))
    order.delivery_method.order_type = "delivery"
    orch = SlotOrchestrator(order)
    slot = orch.get_next_slot()
    assert slot.category == SlotCategory.DELIVERY_ADDRESS

def test_complete_order():
    """Fully filled order should return None for next slot."""
    order = OrderTask()
    order.items.add_item(BagelItemTask(bagel_type="plain", toasted=True))
    order.delivery_method.order_type = "pickup"
    order.customer_info.name = "John"
    order.checkout.confirmed = True
    order.payment.method = "in_store"
    orch = SlotOrchestrator(order)
    assert orch.get_next_slot() is None
    assert orch.is_complete()
```

### Integration Test: Logging Comparison

During Phase 1, add logging to compare FlowState with SlotOrchestrator:

```python
def process(self, user_input: str, state: FlowState, order: Order) -> StateMachineResult:
    # Sync and check
    self._sync_db_order_to_task(order)

    # Compare what FlowState says vs what Orchestrator says
    flow_phase = state.phase
    orch_slot = self.orchestrator.get_next_slot()
    orch_phase = self.orchestrator.get_current_phase()

    if flow_phase != orch_phase:
        logger.warning(
            f"Phase mismatch: FlowState={flow_phase}, Orchestrator={orch_phase}, "
            f"next_slot={orch_slot.category if orch_slot else 'complete'}"
        )

    # Continue with existing logic...
```

### Regression Test Script

```python
# tests/test_slot_migration_regression.py

"""
Run through common order flows and verify:
1. All existing tests pass
2. No phase mismatches logged
3. SlotOrchestrator agrees with FlowState at each step
"""

FLOWS = [
    # Simple pickup
    ["plain bagel toasted", "that's all", "pickup", "John", "yes", "in store"],

    # Delivery order
    ["everything bagel with cream cheese", "done", "delivery",
     "123 Main St", "Jane", "yes", "text", "555-123-4567"],

    # Multiple items
    ["two coffees", "small", "hot", "medium", "iced", "that's it",
     "pickup", "Bob", "yes", "pay in store"],

    # Speed menu item
    ["The Classic", "toasted", "and a coke", "done", "pickup",
     "Alice", "yes", "in store"],
]

def test_all_flows_no_mismatch():
    for flow in FLOWS:
        mismatches = run_flow_and_capture_mismatches(flow)
        assert len(mismatches) == 0, f"Mismatches in flow: {mismatches}"
```

---

## Success Criteria

### Phase 1 Complete When:
- [x] `SlotOrchestrator` class exists and has unit tests
- [x] `OrderTask` is instantiated in state machine
- [x] Sync from DB Order to OrderTask works
- [x] Logging shows orchestrator tracking alongside FlowState
- [x] All existing tests pass
- [x] No phase mismatches in happy path flows

### Phase 2 Complete When:
- [x] Checkout handlers use `_transition_to_next_slot()` instead of explicit phase assignments
- [x] `_derive_next_phase_from_slots()` uses SlotOrchestrator
- [x] ORDER_CONFIRM slot uses `order_reviewed` (user confirmed summary)
- [x] PAYMENT_METHOD sets `payment.method = "card_link"` when text/email selected
- [x] All existing tests pass (489 tests)

### Phase 3 Complete When:
- [x] `FlowState.phase` is computed at start of `process()` via `_transition_to_next_slot()`
- [x] CONFIGURING_ITEM phase handled via `is_configuring_item()` check (takes precedence)
- [x] All existing tests pass (489 tests)

### Phase 4 Complete When:
- [ ] `FlowState` class removed
- [ ] `OrderTask` persisted to session
- [ ] All existing tests pass
- [ ] Code is simpler and more maintainable

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Sync issues between Order (DB) and OrderTask | Extensive logging in Phase 1; fix mismatches before Phase 2 |
| Edge cases not covered by slots | Keep handlers for complex flows; slots handle common cases |
| Item configuration is complex | ItemSlotOrchestrator handles per-item slots separately |
| Breaking existing functionality | Run full test suite at each phase; gradual migration |

---

## Timeline

- Phase 1: Foundation (current focus)
- Phase 2: Use orchestrator
- Phase 3: Derive phases
- Phase 4: Remove FlowState

Each phase should be tested thoroughly before moving to the next.
