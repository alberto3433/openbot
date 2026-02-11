"""
Handler Callbacks - Dataclass for state machine callbacks.

Replaces the pattern of mutating HandlerConfig after initialization.
All callbacks are known upfront, making the dependency graph explicit.
"""

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import OrderTask, ItemTask
    from ..schemas import StateMachineResult


@dataclass
class HandlerCallbacks:
    """
    Callbacks shared across state machine handlers.

    These callbacks are established during state machine initialization
    and remain constant throughout the session. Unlike HandlerConfig,
    these are not dependencies but rather injection points for
    cross-cutting behavior.

    Attributes:
        transition_to_next_slot: Advances order to the next checkout slot.
        configure_next_incomplete_item: Gets config question for incomplete items.
        handle_taking_items_with_parsed: Processes parsed items in TAKING_ITEMS phase.
        get_next_question: Determines the next question to ask.
    """

    transition_to_next_slot: Callable[["OrderTask"], None] | None = None
    configure_next_incomplete_item: Callable[["OrderTask"], "StateMachineResult"] | None = None
    handle_taking_items_with_parsed: Callable[..., "StateMachineResult | None"] | None = None
    get_next_question: Callable[["OrderTask"], "StateMachineResult"] | None = None
