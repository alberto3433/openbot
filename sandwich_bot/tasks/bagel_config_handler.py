"""
Bagel Configuration Handler for Order State Machine.

This module handles all bagel configuration flow including:
- Bagel type selection
- Spread selection
- Toasted preference
- Cheese type clarification
- Multi-bagel configuration orchestration

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable, Union

from .models import (
    OrderTask,
    BagelItemTask,
    MenuItemTask,
    CoffeeItemTask,
    ItemTask,
    TaskStatus,
)
from .schemas import OrderPhase, StateMachineResult, ExtractedModifiers
from .parsers import (
    BAGEL_TYPES,
    parse_toasted_deterministic,
)
from .parsers.llm_parsers import (
    parse_bagel_choice,
    parse_spread_choice,
    parse_toasted_choice,
)
from .parsers.deterministic import extract_modifiers_from_input

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


def apply_modifiers_to_bagel(
    item: BagelItemTask,
    modifiers: ExtractedModifiers,
    skip_cheeses: bool = False,
) -> None:
    """
    Apply extracted modifiers to a bagel item.

    This consolidates the repeated modifier application logic used in
    multiple handlers (handle_bagel_choice, handle_toasted_choice, etc.).

    Args:
        item: The BagelItemTask to modify
        modifiers: Extracted modifiers from user input
        skip_cheeses: If True, don't add cheeses to extras (used when
                      cheese was already handled, e.g., in cheese choice handler)
    """
    # Proteins: first one goes to sandwich_protein if not set, rest to extras
    if modifiers.proteins:
        if not item.sandwich_protein:
            item.sandwich_protein = modifiers.proteins[0]
            item.extras.extend(modifiers.proteins[1:])
        else:
            item.extras.extend(modifiers.proteins)

    # Cheeses go to extras (unless we're skipping them)
    if not skip_cheeses and modifiers.cheeses:
        item.extras.extend(modifiers.cheeses)

    # Toppings go to extras
    if modifiers.toppings:
        item.extras.extend(modifiers.toppings)

    # Spreads: set if not already set
    if modifiers.spreads and not item.spread:
        item.spread = modifiers.spreads[0]

    # Append notes
    if modifiers.has_notes():
        existing_notes = item.notes or ""
        new_notes = modifiers.get_notes_string()
        item.notes = f"{existing_notes}, {new_notes}".strip(", ") if existing_notes else new_notes

    # Check if user said generic "cheese" without specifying type
    if modifiers.needs_cheese_clarification:
        item.needs_cheese_clarification = True


class BagelConfigHandler:
    """
    Handles bagel configuration flow for orders.

    Manages bagel type selection, spread choice, toasted preference,
    cheese clarification, and multi-bagel configuration orchestration.
    """

    # Ordinal number mappings
    ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        pricing: "PricingEngine | None" = None,
        get_next_question: Callable[[OrderTask], StateMachineResult] | None = None,
        get_item_by_id: Callable[[OrderTask, str], ItemTask | None] | None = None,
        configure_coffee: Callable[[OrderTask], StateMachineResult] | None = None,
        check_redirect: Callable[[str, ItemTask, OrderTask, str], StateMachineResult | None] | None = None,
    ):
        """
        Initialize the bagel configuration handler.

        Args:
            model: LLM model to use for parsing.
            pricing: PricingEngine instance for price calculations.
            get_next_question: Callback to get the next question for the order.
            get_item_by_id: Callback to find an item by ID.
            configure_coffee: Callback to configure next incomplete coffee.
            check_redirect: Callback to check for redirect to pending item.
        """
        self.model = model
        self.pricing = pricing
        self._get_next_question = get_next_question
        self._get_item_by_id = get_item_by_id
        self._configure_coffee = configure_coffee
        self._check_redirect = check_redirect

    def _get_ordinal(self, n: int) -> str:
        """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
        return self.ORDINALS.get(n, f"#{n}")

    def handle_bagel_choice(
        self,
        user_input: str,
        item: ItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle bagel type selection for the CURRENT pending item only.

        This handles one item at a time. After configuring this item,
        configure_next_incomplete_bagel will move to the next item.
        """
        # Try deterministic parsing first - check if input matches a known bagel type
        # Do this BEFORE redirect check so "do you have everything bagel" works
        input_lower = user_input.lower().strip()
        bagel_type = None

        # Check for exact match or "[type] bagel" pattern
        for bt in BAGEL_TYPES:
            if input_lower == bt or input_lower == f"{bt} bagel":
                bagel_type = bt
                break
            # Also check if type is contained in the input
            if bt in input_lower:
                bagel_type = bt
                break

        # If no bagel type found, check if user is trying to order a new item
        if not bagel_type and self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "What kind of bagel would you like?"
            )
            if redirect:
                return redirect

        # Fall back to LLM parser only if deterministic parsing failed
        if not bagel_type:
            parsed = parse_bagel_choice(user_input, num_pending_bagels=1, model=self.model)
            if not parsed.unclear and parsed.bagel_type:
                bagel_type = parsed.bagel_type

        if not bagel_type:
            return StateMachineResult(
                message="What kind of bagel? We have plain, everything, sesame, and more.",
                order=order,
            )

        logger.info("Parsed bagel type '%s' for item %s", bagel_type, type(item).__name__)

        # Extract any additional modifiers from the input (e.g., "plain with salt pepper and ketchup")
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers() or extracted_modifiers.has_notes():
            logger.info("Extracted additional modifiers from bagel choice: %s", extracted_modifiers)

        # Apply to the current pending item
        if isinstance(item, MenuItemTask):
            item.bagel_choice = bagel_type

            # For spread/salad sandwiches, use unified config flow for toasted question
            if item.menu_item_type in ("spread_sandwich", "salad_sandwich"):
                order.clear_pending()
                return self.configure_next_incomplete_bagel(order)

            # For omelettes with bagel side, use unified config flow for toasted/spread questions
            if item.side_choice == "bagel":
                order.clear_pending()
                return self.configure_next_incomplete_bagel(order)

            # For other menu items, mark complete
            item.mark_complete()
            order.clear_pending()
            return self._get_next_question(order)

        elif isinstance(item, BagelItemTask):
            item.bagel_type = bagel_type

            # Apply any additional modifiers from the input
            apply_modifiers_to_bagel(item, extracted_modifiers)

            if self.pricing:
                self.pricing.recalculate_bagel_price(item)

            # Clear pending and configure next incomplete item
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        return self._get_next_question(order)

    def handle_spread_choice(
        self,
        user_input: str,
        item: Union[BagelItemTask, MenuItemTask],
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle spread selection for bagel or omelette side bagel."""
        # For MenuItemTask (omelette side bagels), use simpler handling
        if isinstance(item, MenuItemTask):
            parsed = parse_spread_choice(user_input, model=self.model)

            if parsed.no_spread:
                item.spread = "none"
            elif parsed.spread:
                # Build spread description (e.g., "scallion cream cheese")
                if parsed.spread_type and parsed.spread_type != "plain":
                    item.spread = f"{parsed.spread_type} {parsed.spread}"
                else:
                    item.spread = parsed.spread

                # Add spread price to omelette (same as standalone bagel)
                if self.pricing:
                    spread_price = self.pricing.lookup_spread_price(parsed.spread, parsed.spread_type)
                    if spread_price > 0 and item.unit_price is not None:
                        item.spread_price = spread_price  # Store for itemized display
                        item.unit_price += spread_price
                        logger.info(
                            "Added spread price to omelette: %s ($%.2f) -> new total $%.2f",
                            item.spread, spread_price, item.unit_price
                        )
            else:
                return StateMachineResult(
                    message="Would you like butter or cream cheese on the bagel?",
                    order=order,
                )

            # Omelette side bagel is complete
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        # For BagelItemTask - full handling with modifiers
        # First check if the user is requesting modifiers instead of a spread
        # e.g., "make it bacon egg and cheese" when asked about spread
        modifiers = extract_modifiers_from_input(user_input)
        has_modifiers = (
            modifiers.proteins or modifiers.cheeses or modifiers.toppings
        )

        if has_modifiers:
            # User wants modifiers instead of spread - apply them
            logger.info(f"Spread question answered with modifiers: {modifiers}")

            apply_modifiers_to_bagel(item, modifiers)

            # If no spread was specified with the modifiers, mark as none
            if not modifiers.spreads:
                item.spread = "none"
        else:
            # Standard spread choice parsing
            parsed = parse_spread_choice(user_input, model=self.model)

            if parsed.no_spread:
                item.spread = "none"  # Mark as explicitly no spread
            elif parsed.spread:
                item.spread = parsed.spread
                item.spread_type = parsed.spread_type
                # Capture special instructions like "a little", "extra", etc.
                if parsed.notes:
                    # Build full spread description for notes
                    spread_desc = parsed.spread
                    if parsed.spread_type and parsed.spread_type != "plain":
                        spread_desc = f"{parsed.spread_type} {parsed.spread}"
                    # Combine modifier with spread (e.g., "a little cream cheese")
                    item.notes = f"{parsed.notes} {spread_desc}"
            else:
                return StateMachineResult(
                    message="Would you like cream cheese, butter, or nothing on that?",
                    order=order,
                )

        # Recalculate price to include spread modifier
        if self.pricing:
            self.pricing.recalculate_bagel_price(item)

        # This bagel is complete
        item.mark_complete()
        order.clear_pending()

        # Check for more incomplete bagels
        return self.configure_next_incomplete_bagel(order)

    def handle_toasted_choice(
        self,
        user_input: str,
        item: Union[BagelItemTask, MenuItemTask],
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for bagel or sandwich."""
        if self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "Would you like it toasted?"
            )
            if redirect:
                return redirect

        # Try deterministic parsing first, fall back to LLM
        toasted = parse_toasted_deterministic(user_input)
        if toasted is None:
            parsed = parse_toasted_choice(user_input, model=self.model)
            toasted = parsed.toasted

        if toasted is None:
            return StateMachineResult(
                message="Would you like that toasted? Yes or no?",
                order=order,
            )

        item.toasted = toasted

        # Extract any additional modifiers from the input (e.g., "yes with extra cheese")
        if isinstance(item, BagelItemTask):
            extracted_modifiers = extract_modifiers_from_input(user_input)
            if extracted_modifiers.has_modifiers() or extracted_modifiers.has_notes():
                logger.info("Extracted additional modifiers from toasted choice: %s", extracted_modifiers)
                apply_modifiers_to_bagel(item, extracted_modifiers)

        # For MenuItemTask, handle based on type
        if isinstance(item, MenuItemTask):
            # For omelette side bagels, continue to spread question
            if item.side_choice == "bagel":
                order.clear_pending()
                return self.configure_next_incomplete_bagel(order)
            # For spread/salad sandwiches, mark complete after toasted
            item.mark_complete()
            order.clear_pending()
            return self._get_next_question(order)

        # For BagelItemTask, check if spread is already set or has sandwich toppings
        if item.spread is not None:
            # Spread already specified, bagel is complete
            if self.pricing:
                self.pricing.recalculate_bagel_price(item)
            item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        # Skip spread question if bagel already has sandwich toppings (ham, egg, cheese, etc.)
        # But continue to cheese clarification if needed
        if item.extras or item.sandwich_protein:
            logger.info("Skipping spread question - bagel has toppings: extras=%s, protein=%s", item.extras, item.sandwich_protein)
            # If cheese clarification still needed, don't mark complete yet
            if not item.needs_cheese_clarification:
                if self.pricing:
                    self.pricing.recalculate_bagel_price(item)
                item.mark_complete()
            order.clear_pending()
            return self.configure_next_incomplete_bagel(order)

        # Move to spread question
        order.pending_field = "spread"
        return StateMachineResult(
            message="Would you like cream cheese or butter on that?",
            order=order,
        )

    def handle_cheese_choice(
        self,
        user_input: str,
        item: BagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle cheese type selection when user said generic 'cheese'."""
        if self._check_redirect:
            redirect = self._check_redirect(
                user_input, item, order, "What kind of cheese would you like?"
            )
            if redirect:
                return redirect

        input_lower = user_input.lower().strip()

        # Try to extract cheese type from input
        cheese_types = {
            "american": ["american", "america"],
            "cheddar": ["cheddar", "ched"],
            "swiss": ["swiss"],
            "muenster": ["muenster", "munster"],
            "provolone": ["provolone", "prov"],
        }

        selected_cheese = None
        for cheese, patterns in cheese_types.items():
            for pattern in patterns:
                if pattern in input_lower:
                    selected_cheese = cheese
                    break
            if selected_cheese:
                break

        if not selected_cheese:
            return StateMachineResult(
                message="What kind of cheese? We have American, cheddar, Swiss, and muenster.",
                order=order,
            )

        # Add the cheese to extras
        item.extras.append(selected_cheese)
        item.needs_cheese_clarification = False

        # Extract any additional modifiers from the input (e.g., "cheddar with extra bacon")
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers() or extracted_modifiers.has_notes():
            logger.info("Extracted additional modifiers from cheese choice: %s", extracted_modifiers)
            # Apply modifiers (skip cheeses since we already handled cheese above)
            apply_modifiers_to_bagel(item, extracted_modifiers, skip_cheeses=True)

        # Recalculate price with the new cheese
        if self.pricing:
            self.pricing.recalculate_bagel_price(item)

        logger.info("Cheese choice '%s' applied to bagel", selected_cheese)

        # Clear pending and continue configuration
        order.clear_pending()
        return self.configure_next_incomplete_bagel(order)

    def get_bagel_descriptions(self, order: OrderTask, bagel_ids: list[str]) -> list[str]:
        """Get descriptions for a list of bagel IDs (e.g., ['plain bagel', 'everything bagel'])."""
        descriptions = []
        for bagel_id in bagel_ids:
            bagel = self._get_item_by_id(order, bagel_id) if self._get_item_by_id else None
            if bagel and isinstance(bagel, BagelItemTask):
                if bagel.bagel_type:
                    descriptions.append(f"{bagel.bagel_type} bagel")
                else:
                    descriptions.append("bagel")
        return descriptions

    def configure_next_incomplete_bagel(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Find the next incomplete bagel item and configure it fully before moving on.

        This handles:
        - BagelItemTask (bagels with spreads/toppings)
        - MenuItemTask for spread_sandwich/salad_sandwich (Butter Sandwich, etc.)
        - MenuItemTask for omelettes with side_choice == "bagel"

        Each item is fully configured (type -> toasted -> spread) before
        moving to the next item.
        """
        # Collect all items that need bagel configuration (both types)
        all_bagel_items = []
        for item in order.items.items:
            if isinstance(item, BagelItemTask):
                all_bagel_items.append(item)
            elif isinstance(item, MenuItemTask) and item.menu_item_type in ("spread_sandwich", "salad_sandwich"):
                all_bagel_items.append(item)
            elif isinstance(item, MenuItemTask) and item.side_choice == "bagel":
                # Omelettes with bagel side need bagel configuration
                all_bagel_items.append(item)

        total_items = len(all_bagel_items)

        # Find the first incomplete item and ask about its next missing field
        for idx, item in enumerate(all_bagel_items):
            if item.status != TaskStatus.IN_PROGRESS:
                continue

            item_num = idx + 1

            # Build ordinal descriptor if multiple items
            if total_items > 1:
                ordinal = self._get_ordinal(item_num)
                bagel_desc = f"the {ordinal} bagel"
                your_bagel_desc = f"your {ordinal} bagel"
            else:
                bagel_desc = "your bagel"
                your_bagel_desc = "your bagel"

            # Handle MenuItemTask (spread_sandwich, salad_sandwich, omelette with bagel side)
            if isinstance(item, MenuItemTask):
                is_omelette_side = item.side_choice == "bagel"

                # Ask about bagel type first
                if not item.bagel_choice:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "bagel_choice"
                    if total_items > 1:
                        return StateMachineResult(
                            message=f"For {bagel_desc}, what kind of bagel would you like that on?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message="What kind of bagel would you like that on?",
                            order=order,
                        )

                # Then ask about toasted (with bagel type confirmation)
                if item.toasted is None:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "toasted"
                    bagel_type_desc = f"{item.bagel_choice} bagel" if item.bagel_choice else "bagel"
                    if is_omelette_side:
                        return StateMachineResult(
                            message=f"Ok, {bagel_type_desc}. Would you like that toasted?",
                            order=order,
                        )
                    elif total_items > 1:
                        return StateMachineResult(
                            message=f"Ok, {bagel_type_desc}. For {bagel_desc}, would you like that toasted?",
                            order=order,
                        )
                    else:
                        return StateMachineResult(
                            message=f"Ok, {bagel_type_desc}. Would you like that toasted?",
                            order=order,
                        )

                # For omelette side bagels, ask about spread (butter/cream cheese)
                if is_omelette_side and item.spread is None:
                    order.phase = OrderPhase.CONFIGURING_ITEM
                    order.pending_item_id = item.id
                    order.pending_field = "spread"
                    return StateMachineResult(
                        message="Would you like butter or cream cheese on the bagel?",
                        order=order,
                    )

                # MenuItemTask is complete
                item.mark_complete()
                continue

            # Handle BagelItemTask
            bagel = item

            # Ask about type first
            if not bagel.bagel_type:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "bagel_choice"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, what kind of bagel would you like that on?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="What kind of bagel would you like that on?",
                        order=order,
                    )

            # Then ask about toasted (with bagel type confirmation)
            if bagel.toasted is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "toasted"
                bagel_type_desc = f"{bagel.bagel_type} bagel" if bagel.bagel_type else "bagel"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"Ok, {bagel_type_desc}. For {bagel_desc}, would you like that toasted?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=f"Ok, {bagel_type_desc}. Would you like that toasted?",
                        order=order,
                    )

            # Then ask about cheese type if user said generic "cheese"
            if bagel.needs_cheese_clarification:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "cheese_choice"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, what kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="What kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                        order=order,
                    )

            # Then ask about spread (skip if bagel already has toppings)
            if bagel.spread is None and not bagel.extras and not bagel.sandwich_protein:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = bagel.id
                order.pending_field = "spread"
                if total_items > 1:
                    return StateMachineResult(
                        message=f"For {bagel_desc}, would you like cream cheese or butter?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message="Would you like cream cheese or butter on that?",
                        order=order,
                    )

            # This bagel is complete, mark it and continue to next
            bagel.mark_complete()

        # No incomplete bagels - generate confirmation message for the bagels
        # Get all completed bagels to summarize
        completed_bagels = [item for item in order.items.items
                          if isinstance(item, BagelItemTask) and item.status == TaskStatus.COMPLETE]

        if completed_bagels:
            # Get the most recently completed bagel(s) summary
            last_bagel = completed_bagels[-1]
            bagel_summary = last_bagel.get_summary()

            # Count identical bagels at the end
            count = 0
            for bagel in reversed(completed_bagels):
                if bagel.get_summary() == bagel_summary:
                    count += 1
                else:
                    break

            if count > 1:
                summary = f"{count} {bagel_summary}s" if not bagel_summary.endswith("s") else f"{count} {bagel_summary}"
            else:
                summary = bagel_summary

            order.clear_pending()

            # Check if there are items queued for configuration (e.g., coffee after bagel)
            if order.has_queued_config_items():
                next_config = order.pop_next_config_item()
                if next_config:
                    item_id = next_config.get("item_id")
                    item_type = next_config.get("item_type")
                    logger.info("Bagel complete, processing queued config item: id=%s, type=%s", item_id[:8] if item_id else None, item_type)

                    # Find the item by ID and start its configuration
                    for item in order.items.items:
                        if item.id == item_id:
                            if item_type == "coffee" and isinstance(item, CoffeeItemTask):
                                if self._configure_coffee:
                                    return self._configure_coffee(order)

            # Explicitly set to TAKING_ITEMS - we're asking for more items
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                order=order,
            )

        # Fallback to generic next question
        return self._get_next_question(order)
