"""
Config Modification Handler for Order State Machine.

Handles mid-configuration modifications like "can you make it iced?", "add bacon",
and item switch confirmations during item configuration.
Extracted from configuring_item_handler.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase
from .parsers.intent_patterns import parse_can_you_make_it
from .checkout_messages import got_it_anything_else
from .pending_fields import PendingField
from .modifier_change_handler import ChangeRequest
from .parsers.quantity_utils import extract_leading_quantity
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)


class ConfigModificationHandler:
    """
    Handles modifications to items during configuration.

    When the user wants to change something about the item being configured
    (e.g., "can you make it iced?", "add bacon and cheese", switching to a
    different item), this handler processes those requests.
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
    ) -> None:
        """
        Initialize the config modification handler.

        Args:
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
            item_adder_handler: Handler for adding items.
        """
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler
        # Set via setter after TakingItemsHandler is created (to avoid circular dependency)
        self._taking_items_handler: "TakingItemsHandler | None" = None

    @property
    def taking_items_handler(self) -> "TakingItemsHandler | None":
        """Get the taking items handler."""
        return self._taking_items_handler

    @taking_items_handler.setter
    def taking_items_handler(self, handler: "TakingItemsHandler | None") -> None:
        """Set the taking items handler (called after initialization to avoid circular deps)."""
        self._taking_items_handler = handler

    def handle_can_you_make_it(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle 'can you make it X?' requests during item configuration.

        When user asks "can you make it iced?" while being asked about size:
        1. Check if the current item has an attribute option matching "iced"
        2. If yes, apply it and continue with normal configuration
        3. If not, search for a similar menu item with that modifier
        4. Offer to switch or report "Sorry, we don't have that option"

        Args:
            user_input: The user's input text
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if handled, None if not a "can you make it X?" request
        """
        modifier = parse_can_you_make_it(user_input)
        if not modifier:
            return None

        logger.info("CAN_YOU_MAKE_IT: Detected modifier request '%s' for %s", modifier, item.menu_item_name)
        modifier_lower = modifier.lower()

        # 1. Check if current item has an attribute option matching this modifier
        item_type = item.menu_item_type
        if item_type:
            try:
                attrs = menu_cache.get_item_type_attributes(item_type)
                for attr_slug, attr_config in attrs.items():
                    options = attr_config.get("options", [])
                    for opt in options:
                        opt_slug = opt.get("slug", "").lower()
                        opt_display = opt.get("display_name", "").lower()
                        if modifier_lower == opt_slug or modifier_lower == opt_display:
                            # Found matching attribute option - apply it
                            logger.info("CAN_YOU_MAKE_IT: Found matching attr %s=%s", attr_slug, opt_slug)
                            item[attr_slug] = opt.get("slug")
                            # Recalculate price after attribute change
                            if self._taking_items_handler and self._taking_items_handler.pricing:
                                self._taking_items_handler.pricing.recalculate_item_price(item)
                            # Re-ask current question (the one we were on)
                            current_question = self.config_helper_handler.get_current_config_question(order, item)
                            if current_question:
                                return StateMachineResult(
                                    message=f"Sure! {current_question}",
                                    order=order,
                                )
                            # At customization_checkpoint - return success and continue
                            opt_name = opt.get("display_name") or opt.get("slug", "").replace("_", " ").title()
                            return self._continue_config_with_message(
                                f"Okay, {opt_name}.", item, order
                            )
            except Exception as e:
                logger.debug("Error checking attributes for 'can you make it': %s", e)

        # 2. Check if it's an ingredient/modifier (spread, topping, syrup, etc.)
        matches = menu_cache.find_matching_ingredients(modifier_lower)
        if len(matches) == 1:
            match = matches[0]
            self._replace_or_add_modifier(item, match)
            logger.info("CAN_YOU_MAKE_IT: Applied modifier %s (%s)", match['name'], match['category'])
            return self._continue_config_with_message(
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )
        elif len(matches) > 1:
            # Multiple matches - need disambiguation
            logger.info("CAN_YOU_MAKE_IT: Multiple matches for '%s', starting disambiguation", modifier)
            return self._start_modifier_disambiguation(modifier, matches, item, order)

        # 3. Search for similar menu item with the modifier
        if self.item_adder_handler and self.item_adder_handler.menu_lookup:
            similar_item = self.item_adder_handler.menu_lookup.find_similar_item_with_modifier(
                item.menu_item_name or "",
                modifier,
            )
            if similar_item:
                logger.info(
                    "CAN_YOU_MAKE_IT: Found similar item '%s' for '%s' + '%s'",
                    similar_item.get("name"),
                    item.menu_item_name,
                    modifier,
                )
                # Offer to switch
                order.pending_switch_item = similar_item
                order.pending_field = PendingField.CONFIRM_ITEM_SWITCH
                return StateMachineResult(
                    message=(
                        f"{item.menu_item_name} isn't available {modifier}, "
                        f"but we have {similar_item.get('name')}. Would you like that instead?"
                    ),
                    order=order,
                )

        # 4. Not found - report and re-ask
        logger.info("CAN_YOU_MAKE_IT: No matching attribute, ingredient, or similar item found for '%s'", modifier)
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(
                message=f"Sorry, we don't have that option. {current_question}",
                order=order,
            )
        return StateMachineResult(
            message="Sorry, we don't have that option.",
            order=order,
        )

    def handle_confirm_item_switch(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle user confirmation for item switch (from "can you make it X?").

        Args:
            user_input: The user's response (yes/no)
            order: The current order state

        Returns:
            StateMachineResult with next action
        """
        switch_item = order.pending_switch_item
        if not switch_item:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        from .response_utils import is_affirmative

        if is_affirmative(user_input):
            # Get the current item being configured and remove it
            current_item = order.items.get_item_by_id(order.pending_item_id)
            if current_item:
                order.items.remove_item(current_item)

            # Clear switch state
            order.pending_switch_item = None
            order.clear_pending()

            # Add the new item via item_adder_handler
            if self.item_adder_handler:
                return self.item_adder_handler.add_menu_item(
                    switch_item.get("name", "item"),
                    order,
                    quantity=1,
                )

            # Fallback - just acknowledge
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=got_it_anything_else(switch_item.get('name')),
                order=order,
            )
        else:
            # User declined - continue with original item
            order.pending_switch_item = None
            # Get the original item and continue configuration
            original_item = order.items.get_item_by_id(order.pending_item_id)
            if original_item:
                # Clear the confirm_item_switch field and restore previous config state
                # Get the next question for the original item
                if isinstance(original_item, MenuItemTask):
                    from .config import MenuItemConfigHandler
                    # Get menu_item_handler through item_adder
                    menu_item_handler = None
                    if self.item_adder_handler:
                        menu_item_handler = self.item_adder_handler.menu_item_handler
                    if menu_item_handler:
                        order.pending_field = None  # Clear to let get_first_question set it
                        return menu_item_handler.get_first_question(original_item, order)

            order.clear_pending()
            return StateMachineResult(
                message="No problem. What else can I help you with?",
                order=order,
            )

    def apply_modification_during_config(
        self,
        change_request: ChangeRequest,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Apply a modification to the item being configured, then continue config.

        This handles the case where a user says something like "make it veggie cream cheese"
        during item configuration. Instead of deferring the change, we apply it immediately
        and continue with the remaining configuration questions.

        Args:
            change_request: The detected change request
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if the change was applied, None if we couldn't apply it
        """
        new_value = change_request.new_value
        logger.info("APPLY_MOD_DURING_CONFIG: Attempting to apply '%s' to item being configured", new_value)

        # Case 1: Unambiguous attribute change (bread, size, toasted, temperature)
        if not change_request.is_ambiguous and change_request.possible_attributes:
            attr_slug = change_request.possible_attributes[0]
            if attr_slug != "unknown":
                result = self.modifier_change_handler.apply_change(
                    order, item.id, attr_slug, new_value, target=change_request.target
                )
                if result.success:
                    logger.info("APPLY_MOD_DURING_CONFIG: Applied attribute change %s=%s", attr_slug, new_value)
                    return self._continue_config_with_message(
                        f"Sure, I've changed that to {new_value}.", item, order
                    )

        # Case 2: Try as modifier (spread, topping, syrup, etc.)
        matches = menu_cache.find_matching_ingredients(new_value.lower())

        if len(matches) == 1:
            match = matches[0]
            # Replace or add the modifier
            self._replace_or_add_modifier(item, match)
            logger.info("APPLY_MOD_DURING_CONFIG: Applied modifier change %s (%s)", match['name'], match['category'])
            return self._continue_config_with_message(
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )

        if len(matches) > 1:
            # Multiple matches - need disambiguation
            logger.info("APPLY_MOD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation", new_value)
            return self._start_modifier_disambiguation(new_value, matches, item, order)

        # Couldn't apply - fall through to normal processing
        logger.debug("APPLY_MOD_DURING_CONFIG: Could not apply change for '%s'", new_value)
        return None

    def handle_add_modifiers_during_config(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'add X' patterns during item configuration.

        When a user says "add bacon and cheese" while being asked about toasted,
        we should add the modifiers to the current item and continue with the
        pending configuration question.

        Args:
            user_input: The user's input (e.g., "add bacon and cheese")
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if modifiers were added, None if not an add pattern
        """
        user_lower = user_input.lower().strip()

        logger.info("ADD_DURING_CONFIG: Checking input '%s'", user_input[:50])

        # Quick check: only handle inputs starting with "add "
        if not user_lower.startswith("add "):
            logger.debug("ADD_DURING_CONFIG: Input doesn't start with 'add ', skipping")
            return None

        # Extract the modifier text after "add "
        modifier_text = user_lower[4:].strip()
        # Remove trailing "please", "thanks"
        modifier_text = re.sub(r"\s*(please|thanks|thank you)$", "", modifier_text).strip()

        if not modifier_text:
            return None

        # Split by "and" and commas to get individual modifier terms
        modifier_terms = re.split(r"\s*(?:,\s*|\s+and\s+)\s*", modifier_text)
        modifier_terms = [t.strip() for t in modifier_terms if t.strip()]

        if not modifier_terms:
            return None

        logger.info(
            "ADD_DURING_CONFIG: Detected add pattern '%s' with terms: %s",
            user_input, modifier_terms
        )

        # Apply each modifier to the current item
        added_names = []
        for term in modifier_terms:
            # Extract quantity from the term (e.g., "two eggs" -> qty=2, term="eggs")
            extracted_qty, search_term = extract_leading_quantity(term)
            quantity = extracted_qty or 1
            # If nothing remains after extracting quantity, use the original term
            if not search_term.strip():
                search_term = term

            # Find matching ingredients in database
            matches = menu_cache.find_matching_ingredients(search_term)
            logger.info(
                "ADD_DURING_CONFIG: Looking up term '%s' (qty=%d), found %d matches: %s",
                search_term, quantity, len(matches), [m.get("name") for m in matches[:5]] if matches else []
            )

            if len(matches) == 1:
                match = matches[0]

                # Check if ingredient slug matches an attribute with multiple options
                # This handles generic ingredients like "egg" that map to style choices
                # (scrambled, fried, etc.), but NOT specific ingredients like "bacon"
                # which should be added directly
                ingredient_slug = match["slug"]
                attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
                attr_config = attrs.get(ingredient_slug, {})
                options = attr_config.get("options", [])

                # Only trigger selection if ingredient slug matches attribute slug
                # AND that attribute has multiple options
                if options and len(options) > 1:
                    logger.info(
                        "ADD_DURING_CONFIG: Ingredient '%s' matches attribute '%s' with %d options (qty=%d), starting selection",
                        match["name"], ingredient_slug, len(options), quantity
                    )
                    # Store quantity for when user selects an option
                    order.pending_modifier_quantity = quantity
                    return self._start_attribute_option_selection(
                        ingredient_slug, attr_config, options, item, order
                    )

                # No matching attribute or single option - add directly
                item.add_selection(
                    slug=match["slug"],
                    category=match["category"],
                    display_name=match["name"],
                    quantity=quantity,
                    price=match.get("base_price", 0.0),
                )
                added_names.append(match["name"])
                logger.info(
                    "ADD_DURING_CONFIG: Added '%s' (category=%s, qty=%d) to item",
                    match["name"], match["category"], quantity
                )
            elif len(matches) > 1:
                # Multiple matches - start disambiguation for this modifier
                logger.info(
                    "ADD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation",
                    term
                )
                return self._start_modifier_disambiguation(term, matches, item, order)
            else:
                # No match found - try category lookup
                modifier_to_category = menu_cache.get_modifier_to_category_map()
                category = modifier_to_category.get(term)
                if category:
                    modifier_slug = term.replace(" ", "_")
                    item.add_selection(
                        slug=modifier_slug,
                        category=category,
                        display_name=term.title(),
                        quantity=1,
                    )
                    added_names.append(term.title())
                    logger.info(
                        "ADD_DURING_CONFIG: Added '%s' (category=%s) via category lookup",
                        term, category
                    )
                else:
                    logger.warning(
                        "ADD_DURING_CONFIG: Could not find modifier '%s' in database",
                        term
                    )

        if not added_names:
            return None

        # Recalculate price
        if self.modifier_change_handler and self.modifier_change_handler.pricing:
            self.modifier_change_handler.pricing.recalculate_item_price(item)

        # Build acknowledgment message
        from .utils.text import format_english_list
        added_text = format_english_list(added_names)
        message = f"Sure, I've added {added_text}."

        return self._continue_config_with_message(message, item, order)

    def _replace_or_add_modifier(self, item: MenuItemTask, match: dict) -> None:
        """Replace existing modifier of same category, or add if none exists.

        Args:
            item: The item to modify
            match: Dict with slug, name, category, base_price from find_matching_ingredients()
        """
        category = match["category"]

        # Remove existing modifier of same category (if any)
        item.remove_selection(category)

        # Add new one
        item.add_selection(
            slug=match["slug"],
            category=category,
            display_name=match["name"],
            quantity=1,
            price=match.get("base_price", 0.0),
        )

        # Recalculate price
        if self.modifier_change_handler and self.modifier_change_handler.pricing:
            self.modifier_change_handler.pricing.recalculate_item_price(item)

    def _continue_config_with_message(
        self, message: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Return message + next config question, or proceed if item complete.

        Args:
            message: The feedback message about the change that was applied
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult with the message and next question, or checkout transition
        """
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(message=f"{message} {current_question}", order=order)

        # Item configuration complete - proceed to next question or checkout
        return self.checkout_utils_handler.get_next_question(order)

    def _start_modifier_disambiguation(
        self,
        new_value: str,
        matches: list[dict],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Start disambiguation flow for a modifier with multiple matches.

        Args:
            new_value: The modifier value that has multiple matches
            matches: List of matching ingredient dicts
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult asking user to select which modifier they want
        """
        # Store the modifier options for disambiguation
        order.pending_item_options = matches
        order.pending_field = PendingField.MODIFIER_SELECTION
        order.pending_modifier_target_item_index = order.items.items.index(item)

        # Build disambiguation message
        option_lines = []
        for i, match in enumerate(matches[:6], 1):
            price_str = ""
            if match.get("base_price", 0) > 0:
                price_str = f" (+${match['base_price']:.2f})"
            option_lines.append(f"{i}. {match['name']}{price_str}")

        options_str = "\n".join(option_lines)
        return StateMachineResult(
            message=f"Which {new_value} would you like?\n{options_str}",
            order=order,
        )

    def _start_attribute_option_selection(
        self,
        attr_slug: str,
        attr_config: dict,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Start selection flow for attribute options when modifier maps to an attribute.

        When a user says "add an egg" and the ingredient category maps to an attribute
        with multiple options (scrambled, fried, etc.), this method triggers the
        selection flow to let the user choose their preferred style.

        Args:
            attr_slug: The attribute slug (e.g., "egg")
            attr_config: The attribute configuration dict
            options: List of option dicts with slug, display_name, price_modifier
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult asking user to select which option they want
        """
        # Set pending field to trigger attribute question handling
        order.pending_field = f"{item.menu_item_type}:{attr_slug}"

        # Format options list with "and" before last item
        option_names = [opt.get("display_name") or opt.get("slug", "").replace("_", " ").title() for opt in options[:6]]
        if len(option_names) > 1:
            options_text = ", ".join(option_names[:-1]) + ", and " + option_names[-1]
        else:
            options_text = option_names[0] if option_names else ""

        # Build question - use DB question_text or generate a default
        display_name = attr_config.get("display_name") or attr_slug.replace("_", " ")
        question = f"How would you like your {display_name}?"

        return StateMachineResult(
            message=f"We have {options_text}. {question}",
            order=order,
        )
