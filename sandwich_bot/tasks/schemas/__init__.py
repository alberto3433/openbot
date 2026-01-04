"""
State Machine Schemas.

This package contains all Pydantic models and data structures used by the
state machine for parsing user input and representing order phases.
"""

from .phases import OrderPhase
from .parser_responses import (
    # Helper types for coffee modifiers
    SweetenerItem,
    SyrupItem,
    # ParsedItem types for multi-item handling
    ParsedMenuItemEntry,
    ParsedBagelEntry,
    ParsedCoffeeEntry,
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
    # Helper types for coffee modifiers
    "SweetenerItem",
    "SyrupItem",
    # ParsedItem types for multi-item handling
    "ParsedMenuItemEntry",
    "ParsedBagelEntry",
    "ParsedCoffeeEntry",
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
