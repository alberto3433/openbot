"""
State Machine Result.

Defines the result structure returned by state machine processing.
"""

from dataclasses import dataclass
from ..models import OrderTask


@dataclass
class StateMachineResult:
    """Result from state machine processing."""
    message: str
    order: OrderTask
    is_complete: bool = False
