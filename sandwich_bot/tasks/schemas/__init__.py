"""
State Machine Schemas.

This package contains all Pydantic models and data structures used by the
state machine for parsing user input and representing order phases.
"""

from .phases import OrderPhase
from .parser_responses import (
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

__all__ = [
    # Phases
    "OrderPhase",
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
]
