"""
Espresso Configuration Handler for Order State Machine.

This module handles espresso ordering - a simpler flow than regular coffee
since espresso drinks don't need size or temperature configuration.

The main variable is the number of shots:
- Single (1 shot) - default
- Double (2 shots) - upcharge
- Triple (3 shots) - upcharge
"""

import logging
from typing import TYPE_CHECKING

from .models import EspressoItemTask, OrderTask
from .schemas import StateMachineResult
from .handler_config import HandlerConfig

if TYPE_CHECKING:
    from .pricing import PricingEngine
    from .menu_lookup import MenuLookup

logger = logging.getLogger(__name__)

# Note: DEFAULT_DOUBLE_SHOT_PRICE and DEFAULT_TRIPLE_SHOT_PRICE were removed.
# All pricing should come from the database. If not found, we return 0 (fail gracefully).


class EspressoConfigHandler:
    """
    Handles espresso ordering flow.

    Espresso is simpler than regular coffee:
    - No size options (fixed size)
    - Always hot (no iced option)
    - Main config is number of shots (single, double, triple)
    """

    def __init__(self, config: HandlerConfig | None = None, **kwargs):
        """
        Initialize the espresso config handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support (pricing, menu_lookup, get_next_question).
        """
        if config:
            self.pricing = config.pricing
            self.menu_lookup = config.menu_lookup
            self._get_next_question = config.get_next_question
        else:
            # Legacy support for direct parameters
            self.pricing = kwargs.get("pricing")
            self.menu_lookup = kwargs.get("menu_lookup")
            self._get_next_question = kwargs.get("get_next_question")

    def add_espresso(
        self,
        shots: int,
        quantity: int,
        order: OrderTask,
        decaf: bool | None = None,
        special_instructions: str | None = None,
    ) -> StateMachineResult:
        """
        Add espresso drink(s) to the order.

        Args:
            shots: Number of shots (1=single, 2=double, 3=triple)
            quantity: Number of espresso drinks to add
            order: The current order task
            decaf: Whether decaf (True=decaf, None=regular)
            special_instructions: Any special instructions

        Returns:
            StateMachineResult with confirmation message and updated order
        """
        # Ensure valid values
        shots = max(1, min(3, shots))  # Clamp to 1-3
        quantity = max(1, quantity)

        # Look up base price from menu
        base_price = self._get_espresso_base_price()

        # Calculate extra shots upcharge
        extra_shots_upcharge = 0.0
        if shots == 2:
            extra_shots_upcharge = self._get_double_shot_upcharge()
        elif shots >= 3:
            extra_shots_upcharge = self._get_triple_shot_upcharge()

        logger.info(
            "ADD ESPRESSO: shots=%d, quantity=%d, decaf=%s, base_price=%.2f, upcharge=%.2f",
            shots, quantity, decaf, base_price, extra_shots_upcharge
        )

        # Create the espresso item(s)
        for _ in range(quantity):
            espresso = EspressoItemTask(
                shots=shots,
                decaf=decaf,
                unit_price=base_price + extra_shots_upcharge,
                extra_shots_upcharge=extra_shots_upcharge,
                special_instructions=special_instructions,
            )
            logger.info(
                "ESPRESSO CREATED: shots=%d, extra_shots_upcharge=%.2f, unit_price=%.2f",
                espresso.shots, espresso.extra_shots_upcharge, espresso.unit_price
            )
            espresso.mark_complete()  # No configuration needed
            order.items.add_item(espresso)

        # Clear any pending state
        order.clear_pending()

        # Build confirmation message
        shot_name = self._get_shot_name(shots)
        if decaf:
            item_desc = f"decaf {shot_name} espresso"
        else:
            item_desc = f"{shot_name} espresso" if shots > 1 else "espresso"

        if quantity > 1:
            item_desc = f"{quantity} {item_desc}s"

        # Return to taking items flow
        if self._get_next_question:
            result = self._get_next_question(order)
            # Prepend our confirmation to the message
            result.message = f"Got it, {item_desc}. {result.message}"
            return result

        return StateMachineResult(
            message=f"Got it, {item_desc}. Anything else?",
            order=order,
        )

    def _get_espresso_base_price(self) -> float:
        """Look up base espresso price from menu."""
        if self.menu_lookup:
            items = self.menu_lookup.lookup_menu_items("espresso")
            for item in items:
                if item.get("name", "").lower() == "espresso":
                    return item.get("base_price", 0)
        return 0  # Fail gracefully - no fallback

    def _get_double_shot_upcharge(self) -> float:
        """Get upcharge for double shot."""
        if self.pricing:
            upcharge = self.pricing.lookup_coffee_modifier_price("double_shot", "extras")
            if upcharge > 0:
                return upcharge
        return 0  # Fail gracefully - no fallback

    def _get_triple_shot_upcharge(self) -> float:
        """Get upcharge for triple shot."""
        if self.pricing:
            upcharge = self.pricing.lookup_coffee_modifier_price("triple_shot", "extras")
            if upcharge > 0:
                return upcharge
        return 0  # Fail gracefully - no fallback

    def _get_shot_name(self, shots: int) -> str:
        """Get the name for the shot count."""
        if shots == 1:
            return "single"
        elif shots == 2:
            return "double"
        else:
            return "triple"
