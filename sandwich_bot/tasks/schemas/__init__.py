"""
State Machine Schemas.

This package contains all Pydantic models and data structures used by the
state machine for parsing user input and representing order phases.
"""

from .phases import OrderPhase
from .parser_responses import (
    # Helper types for modifiers with quantity
    QuantifiedModifier,
    SweetenerItem,  # Alias for QuantifiedModifier
    SyrupItem,  # Alias for QuantifiedModifier
    # Qualifier conflict model
    QualifierConflict,
    # ParsedItem types for multi-item handling
    ParsedItemEntry,  # New unified type (replaces ParsedBagelEntry/ParsedCoffeeEntry)
    ParsedMenuItemEntry,
    ParsedBagelEntry,  # Deprecated - use ParsedItemEntry
    ParsedCoffeeEntry,  # Deprecated - use ParsedItemEntry
    ParsedSignatureItemEntry,
    ParsedSpeedMenuBagelEntry,
    ParsedSideItemEntry,
    ParsedByPoundEntry,
    ParsedItem,
    # Parser response schemas
    SideChoiceResponse,
    BagelChoiceResponse,
    MultiBagelChoiceResponse,
    MultiToastedResponse,
    MultiSpreadResponse,
    SpreadChoiceResponse,
    ToastedChoiceResponse,
    CoffeeSizeResponse,
    CoffeeStyleResponse,
    BagelOrderDetails,
    CoffeeOrderDetails,
    MenuItemOrderDetails,
    ByPoundOrderItem,
    OpenInputResponse,
    ByPoundCategoryResponse,
    DeliveryChoiceResponse,
    NameResponse,
    ConfirmationResponse,
    PaymentMethodResponse,
    EmailResponse,
    PhoneResponse,
)
from .modifiers import (
    ExtractedModifiers,
    ExtractedCoffeeModifiers,
)
from .result import StateMachineResult

__all__ = [
    # Phases
    "OrderPhase",
    # Helper types for modifiers with quantity
    "QuantifiedModifier",
    "SweetenerItem",  # Alias for QuantifiedModifier
    "SyrupItem",  # Alias for QuantifiedModifier
    # Qualifier conflict model
    "QualifierConflict",
    # ParsedItem types for multi-item handling
    "ParsedItemEntry",  # New unified type
    "ParsedMenuItemEntry",
    "ParsedBagelEntry",  # Deprecated
    "ParsedCoffeeEntry",  # Deprecated
    "ParsedSignatureItemEntry",
    "ParsedSpeedMenuBagelEntry",
    "ParsedSideItemEntry",
    "ParsedByPoundEntry",
    "ParsedItem",
    # Parser responses
    "SideChoiceResponse",
    "BagelChoiceResponse",
    "MultiBagelChoiceResponse",
    "MultiToastedResponse",
    "MultiSpreadResponse",
    "SpreadChoiceResponse",
    "ToastedChoiceResponse",
    "CoffeeSizeResponse",
    "CoffeeStyleResponse",
    "BagelOrderDetails",
    "CoffeeOrderDetails",
    "MenuItemOrderDetails",
    "ByPoundOrderItem",
    "OpenInputResponse",
    "ByPoundCategoryResponse",
    "DeliveryChoiceResponse",
    "NameResponse",
    "ConfirmationResponse",
    "PaymentMethodResponse",
    "EmailResponse",
    "PhoneResponse",
    # Modifiers
    "ExtractedModifiers",
    "ExtractedCoffeeModifiers",
    # Result
    "StateMachineResult",
]
