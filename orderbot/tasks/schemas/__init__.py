"""
State Machine Schemas.

This package contains all Pydantic models and data structures used by the
state machine for parsing user input and representing order phases.
"""

from .phases import OrderPhase
from .parser_responses import (
    # Selection model for unified customizations
    Selection,
    # Backward compatibility alias
    QuantifiedModifier,
    # Qualifier conflict model
    QualifierConflict,
    # ParsedItem types for multi-item handling
    ParsedItemEntry,
    ParsedItem,
    # Parser response schemas
    AttributeChoiceResponse,
    MultiAttributeChoiceResponse,
    OpenInputResponse,
    DeliveryChoiceResponse,
    NameResponse,
    ConfirmationResponse,
    PaymentMethodResponse,
    EmailResponse,
    PhoneResponse,
)
from .result import StateMachineResult

__all__ = [
    # Phases
    "OrderPhase",
    # Selection model for unified customizations
    "Selection",
    # Backward compatibility alias
    "QuantifiedModifier",
    # Qualifier conflict model
    "QualifierConflict",
    # ParsedItem types for multi-item handling
    "ParsedItemEntry",
    "ParsedItem",
    # Parser responses
    "AttributeChoiceResponse",
    "MultiAttributeChoiceResponse",
    "OpenInputResponse",
    "DeliveryChoiceResponse",
    "NameResponse",
    "ConfirmationResponse",
    "PaymentMethodResponse",
    "EmailResponse",
    "PhoneResponse",
    # Result
    "StateMachineResult",
]
