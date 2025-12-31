"""
Slot Orchestration Handler for Order State Machine.

This module handles slot orchestration operations including
phase derivation from slots, slot transitions, and slot state logging.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask
from .schemas import OrderPhase
from .slot_orchestrator import SlotOrchestrator, SlotCategory

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
slot_logger = logging.getLogger("sandwich_bot.slots")


class SlotOrchestrationHandler:
    """
    Handles slot orchestration operations.

    Manages slot state logging, phase derivation from slots,
    and slot transitions.
    """

    def __init__(self) -> None:
        """Initialize the slot orchestration handler."""
        pass

    def log_slot_comparison(self, order: OrderTask) -> None:
        """
        Log slot orchestrator state for debugging.
        """
        try:
            orchestrator = SlotOrchestrator(order)
            orch_phase = orchestrator.get_current_phase()

            # Get next slot for additional context
            next_slot = orchestrator.get_next_slot()
            next_slot_info = f"{next_slot.category.value}" if next_slot else "none"

            slot_logger.debug(
                "SLOT STATE: phase=%s, orch_phase=%s, next_slot=%s",
                order.phase, orch_phase, next_slot_info
            )

            # Log slot progress for visibility
            progress = orchestrator.get_progress()
            filled_slots = [k for k, v in progress.items() if v]
            empty_slots = [k for k, v in progress.items() if not v]
            slot_logger.debug(
                "SLOT PROGRESS: filled=%s, empty=%s",
                filled_slots, empty_slots
            )

        except Exception as e:
            slot_logger.error("SLOT COMPARISON ERROR: %s", e)

    def derive_next_phase_from_slots(self, order: OrderTask) -> OrderPhase:
        """
        Use SlotOrchestrator to determine the next phase.

        This is Phase 2 of the migration - using the orchestrator to drive
        phase transitions instead of hardcoded assignments.
        """
        orchestrator = SlotOrchestrator(order)

        # Check if any items are being configured
        current_item = order.items.get_current_item()
        if current_item is not None:
            return OrderPhase.CONFIGURING_ITEM

        next_slot = orchestrator.get_next_slot()
        if next_slot is None:
            return OrderPhase.COMPLETE

        # Map slot categories to OrderPhase values
        phase_map = {
            SlotCategory.ITEMS: OrderPhase.TAKING_ITEMS,
            SlotCategory.DELIVERY_METHOD: OrderPhase.CHECKOUT_DELIVERY,
            SlotCategory.DELIVERY_ADDRESS: OrderPhase.CHECKOUT_DELIVERY,  # Address is part of delivery
            SlotCategory.CUSTOMER_NAME: OrderPhase.CHECKOUT_NAME,
            SlotCategory.ORDER_CONFIRM: OrderPhase.CHECKOUT_CONFIRM,
            SlotCategory.PAYMENT_METHOD: OrderPhase.CHECKOUT_PAYMENT_METHOD,
            SlotCategory.NOTIFICATION: OrderPhase.CHECKOUT_PHONE,  # Will be refined later
        }
        return phase_map.get(next_slot.category, OrderPhase.TAKING_ITEMS)

    def transition_to_next_slot(self, order: OrderTask) -> None:
        """
        Update order.phase based on SlotOrchestrator.

        This replaces hardcoded phase transitions with orchestrator-driven
        transitions that look at what's actually filled in the order.
        """
        next_phase = self.derive_next_phase_from_slots(order)
        if order.phase != next_phase.value:
            logger.info("SLOT TRANSITION: %s -> %s", order.phase, next_phase.value)
        order.phase = next_phase.value
