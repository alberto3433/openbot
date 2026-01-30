"""
Configuration Helper Handler for Order State Machine.

This module handles configuration-related helper operations including
cancellation during config, change clarifications, modifier changes,
and side choice handling.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Optional, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, ItemTask
from .pending_fields import PendingField
from .schemas import OrderPhase, StateMachineResult
from .parsers import parse_side_choice, CANCEL_ITEM_PATTERN
from .handler_config import HandlerConfig
from .item_cancellation_handler import extract_ordinal_reference, find_nth_item_of_type
from .modifier_operations import find_modifier_match, remove_modifier_from_item
from orderbot.menu_data_cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.cache.base import get_singular_plural_variants

if TYPE_CHECKING:
    from .modifier_change_handler import ModifierChangeHandler

logger = logging.getLogger(__name__)


def _get_removable_modifiers() -> set[str]:
    """Get the set of removable modifier names from the database.

    Uses the ingredient_categories table to determine which ingredient categories
    are "food" modifiers, then combines all ingredients from those categories.
    This is fully data-driven - no hardcoded category names.

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded or no food categories
            are configured in ingredient_categories table.
    """
    modifiers: set[str] = set()

    # Get all food modifier ingredient categories from database
    # This is data-driven: ingredient_categories table defines which categories
    # are "food" modifiers (protein, topping, sauce, cheese, spread, etc.)
    food_categories = menu_cache.get_ingredient_categories_by_modifier_type("food")

    if not food_categories:
        raise MenuDataNotLoadedError(
            "No food modifier categories found in database. "
            "Check that ingredient_categories table has entries with modifier_type='food'."
        )

    # Combine all ingredients from food modifier categories
    for category in food_categories:
        modifiers.update(menu_cache.get_ingredients(category))

    # Also include all modifier aliases from the database
    # This covers variations like "egg" vs "eggs", "mayo" vs "mayonnaise", etc.
    modifiers.update(menu_cache.get_all_modifier_words())

    return modifiers

class ConfigHelperHandler:
    """
    Handles configuration helper operations.

    Manages cancellation during config, change clarifications,
    modifier changes, and side choice handling.
    """

    def __init__(
        self,
        config: HandlerConfig,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
    ):
        """
        Initialize the config helper handler.

        Args:
            config: HandlerConfig with shared dependencies.
            modifier_change_handler: Handler for modifier changes.
        """
        self.model = config.model
        self._get_next_question = config.get_next_question
        self.pricing = config.pricing

        # Handler-specific dependency
        self.modifier_change_handler = modifier_change_handler

    def check_cancellation_during_config(
        self,
        user_input: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> Optional[StateMachineResult]:
        """
        Check if user wants to cancel/remove items while in configuration phase.

        This allows users to say things like "remove the coffee" or "cancel this"
        while they're being asked for coffee size, instead of being forced to answer.

        Returns StateMachineResult if cancellation handled, None otherwise.
        """
        cancel_match = CANCEL_ITEM_PATTERN.match(user_input.strip())
        if not cancel_match:
            return None

        # Extract what they want to cancel from any of the capture groups
        cancel_desc = None
        for group in cancel_match.groups():
            if group:
                cancel_desc = group.strip().lower()
                break

        if not cancel_desc:
            return None

        logger.info("Cancel request during config: '%s'", cancel_desc)

        # Handle "this" or "it" - cancel the current item being configured
        if cancel_desc in ("this", "it", "that", "this one", "that one"):
            item_name = current_item.get_summary()
            current_item.mark_skipped()
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            remaining = order.items.get_active_items()
            if remaining:
                return StateMachineResult(
                    message=f"OK, I've removed the {item_name}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed the {item_name}. What would you like to order?",
                    order=order,
                )

        # Check if this is a modifier removal on the current item being configured
        # Use unified modifier_operations for consistent handling
        if isinstance(current_item, MenuItemTask):
            try:
                modifier_match = find_modifier_match(current_item, cancel_desc)
                if modifier_match:
                    removal_result = remove_modifier_from_item(current_item, modifier_match)
                    if removal_result.success:
                        removed_modifier_name = removal_result.removed_value or cancel_desc
                        logger.info(
                            "Modifier removal during config: removed '%s' from %s",
                            removed_modifier_name, current_item.menu_item_name
                        )

                        # Return to customization checkpoint or continue
                        question = self.get_current_config_question(order, current_item)
                        if question:
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_modifier_name}. {question}",
                                order=order,
                            )
                        else:
                            updated_summary = current_item.get_summary()
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_modifier_name}. Your {current_item.menu_item_name} is now {updated_summary}. Anything else?",
                                order=order,
                            )
            except MenuDataNotLoadedError:
                # Menu cache not loaded - fall back to checking removable modifiers set
                logger.debug("Menu cache not loaded for modifier match - using removable modifiers set")

                # Legacy fallback using removable modifiers set
                removable_modifiers = _get_removable_modifiers()
                if cancel_desc in removable_modifiers:
                    cancel_variants = get_singular_plural_variants(cancel_desc)
                    selections_to_remove = []
                    removed_modifier_name = cancel_desc

                    for sel in current_item.modifiers:
                        sel_display = sel.get("display_name", "").lower()
                        sel_slug = sel.get("slug", "").lower()
                        sel_category = sel.get("category", "")
                        if (any(v in sel_display for v in cancel_variants) or
                            any(v in sel_slug for v in cancel_variants)):
                            selections_to_remove.append((sel_category, sel_slug))
                            removed_modifier_name = sel.get("display_name", cancel_desc)

                    for category, slug in selections_to_remove:
                        current_item.remove_selection(category, slug)

                    if selections_to_remove:
                        logger.info(
                            "Modifier removal during config (fallback): removed '%s' from %s",
                            removed_modifier_name, current_item.menu_item_name
                        )
                        question = self.get_current_config_question(order, current_item)
                        if question:
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_modifier_name}. {question}",
                                order=order,
                            )
                        else:
                            updated_summary = current_item.get_summary()
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_modifier_name}. Your {current_item.menu_item_name} is now {updated_summary}. Anything else?",
                                order=order,
                            )

        # Get all active items to search through
        active_items = order.items.get_active_items()
        if not active_items:
            order.clear_pending()
            return StateMachineResult(
                message="There's nothing in your order yet. What can I get for you?",
                order=order,
            )

        # First, check for ordinal reference (e.g., "second bagel", "3rd coffee")
        ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_desc)

        if ordinal_index is not None and item_type_keyword:
            # User wants to remove a specific Nth item
            result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
            if result:
                item_to_remove, _ = result
                removed_name = item_to_remove.get_summary()
                idx = order.items.items.index(item_to_remove)
                order.items.remove_item(idx)

                # Clear pending state since we're leaving config phase
                order.clear_pending()
                order.set_phase(OrderPhase.TAKING_ITEMS)

                logger.info(
                    "Removed %s #%d during config: %s",
                    item_type_keyword, ordinal_index, removed_name
                )

                remaining = order.items.get_active_items()
                if remaining:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_name}. Anything else?",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_name}. What would you like to order?",
                        order=order,
                    )
            else:
                # Ordinal item not found
                return StateMachineResult(
                    message=f"I couldn't find a {item_type_keyword} #{ordinal_index} in your order. What would you like to do?",
                    order=order,
                )

        # Check if this is a plural removal (e.g., "coffees", "bagels")
        # If plural, we remove ALL matching items
        # Use singularize to properly detect plural forms
        from orderbot.cache.base import singularize
        singular_desc = singularize(cancel_desc)
        is_plural = singular_desc != cancel_desc.lower()

        # Get all variants for matching
        cancel_variants = get_singular_plural_variants(cancel_desc)

        # Find matching items (fallback for non-ordinal cancellations)
        items_to_remove = []

        # Map user category terms to item_type via database (e.g., "coffee" -> "sized_beverage")
        # Uses category keywords from item_types.aliases in the database
        mapped_item_type = None
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping:
                mapped_item_type = category_mapping.get("slug")
                break

        for item in active_items:
            item_summary = item.get_summary().lower()
            item_name = getattr(item, 'menu_item_name', '') or ''
            item_name_lower = item_name.lower()
            item_type = getattr(item, 'item_type', '') or ''
            menu_item_type = getattr(item, 'menu_item_type', '') or ''

            # Check for matches using all variants
            matches = False
            if any(v in item_summary for v in cancel_variants):
                matches = True
            elif item_name_lower and any(v in item_name_lower for v in cancel_variants):
                matches = True
            elif item_name_lower and item_name_lower in cancel_desc:
                matches = True
            # Check item_type for things like "coffee" -> matches item_type="coffee"
            elif item_type and any(v == item_type for v in cancel_variants):
                matches = True
            # Check menu_item_type (e.g., "sized_beverage", "bagel")
            elif menu_item_type and any(v == menu_item_type for v in cancel_variants):
                matches = True
            # Check if user's category term maps to this item's type (e.g., "coffee" -> "sized_beverage")
            elif mapped_item_type and menu_item_type == mapped_item_type:
                matches = True
            elif any(word in item_summary for word in cancel_desc.split() if word):
                matches = True

            if matches:
                items_to_remove.append(item)
                # If not plural, only remove one item
                if not is_plural:
                    break

        if items_to_remove:
            # Remove the items
            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                idx = order.items.items.index(item)
                order.items.remove_item(idx)

            # Clear pending state since we're leaving config phase
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            # Build response message
            remaining = order.items.get_active_items()
            if len(removed_names) == 1:
                removed_str = f"the {removed_names[0]}"
            else:
                removed_str = f"the {len(removed_names)} {singular_desc}s"

            logger.info("Removed %d item(s) during config: %s", len(removed_names), removed_names)

            if remaining:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. What would you like to order?",
                    order=order,
                )
        else:
            # Couldn't find a matching item
            return StateMachineResult(
                message=f"I couldn't find {cancel_desc} in your order. What would you like to do?",
                order=order,
            )

    def get_current_config_question(
        self,
        order: OrderTask,
        item: ItemTask,
    ) -> str | None:
        """Get the current configuration question being asked.

        Uses database-driven question lookup for attribute-based fields.
        The pending_field format is "item_type:attr_slug" (e.g., "bagel:toasted").
        """
        field = order.pending_field
        if not field:
            return None

        # Handle side_choice - query database for the question text
        if field == PendingField.SIDE_CHOICE:
            if isinstance(item, MenuItemTask) and item.menu_item_type:
                side_attr = menu_cache.get_side_choice_attribute(item.menu_item_type)
                if side_attr and side_attr.get("question_text"):
                    return side_attr["question_text"]
            # Fallback to generic question if DB lookup fails
            return "Would you like a side with it?"

        # Parse pending_field to get item_type and attr_slug
        # Format: "item_type:attr_slug" (e.g., "bagel:toasted", "sized_beverage:size")
        if ":" in field:
            item_type, attr_slug = field.split(":", 1)
        else:
            # Legacy format without colon - try to infer from item
            if isinstance(item, MenuItemTask) and item.menu_item_type:
                item_type = item.menu_item_type
                attr_slug = field
            else:
                return None

        # Look up attribute from database
        try:
            attrs = menu_cache.get_item_type_attributes(item_type)
        except MenuDataNotLoadedError:
            logger.warning("Menu cache not loaded when getting question for %s:%s", item_type, attr_slug)
            return None

        attr = attrs.get(attr_slug)
        if not attr:
            return None

        # Use question_text from DB if available, otherwise generate
        db_question = attr.get("question_text")
        if db_question:
            return db_question

        # Generate question based on input_type and display_name
        input_type = attr.get("input_type", "single_select")
        attr_name = attr.get("display_name", attr_slug).lower()

        if input_type == "boolean":
            return f"Would you like it {attr_name}?"
        else:
            return f"What kind of {attr_name} would you like?"

    def handle_change_clarification_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle user response to a change clarification question.

        Returns StateMachineResult if handled, None if response wasn't understood.
        """
        clarification = order.pending_change_clarification
        if not clarification:
            return None

        if not self.modifier_change_handler:
            return None

        # Try to resolve the clarification
        attr_slug, error = self.modifier_change_handler.resolve_clarification(
            clarification, user_input
        )

        if attr_slug is None:
            # Couldn't understand the response
            logger.info("CHANGE CLARIFICATION: Couldn't understand response '%s'", user_input)
            # Build a generic clarification message from the possible attributes
            possible_attrs = clarification.get("possible_attributes", [])
            if possible_attrs and len(possible_attrs) >= 2:
                # Format: "Would you like to change the X or the Y?"
                attr_names = [a.replace("_", " ") for a in possible_attrs]
                fallback_msg = f"I didn't catch that. Would you like to change the {attr_names[0]} or the {attr_names[1]}?"
            else:
                fallback_msg = "I didn't catch that. Which part would you like to change?"
            return StateMachineResult(
                message=error or fallback_msg,
                order=order,
            )

        # Clear the pending clarification
        order.pending_change_clarification = None

        # Apply the change
        item_id = clarification.get("item_id")
        new_value = clarification.get("new_value", "")

        result = self.modifier_change_handler.apply_change(
            order=order,
            item_id=item_id,
            attr_slug=attr_slug,
            new_value=new_value,
        )

        if result.success:
            msg = f"{result.message} Anything else?"
            return StateMachineResult(message=msg, order=order)
        else:
            return StateMachineResult(message=result.message, order=order)

    def handle_modifier_change_request(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle a modifier change request when not mid-configuration.

        Returns StateMachineResult if handled, None otherwise.
        """
        if not self.modifier_change_handler:
            return None

        change_request = self.modifier_change_handler.detect_change_request(user_input)
        if not change_request:
            return None

        logger.info(
            "CHANGE REQUEST: Detected: target=%s, new_value=%s, ambiguous=%s",
            change_request.target,
            change_request.new_value,
            change_request.is_ambiguous,
        )

        # If ambiguous, ask for clarification
        if change_request.is_ambiguous:
            # Find the target item
            active_items = order.items.get_active_items()
            item_id = active_items[-1].id if active_items else None

            # Store clarification state
            order.pending_change_clarification = {
                "new_value": change_request.new_value,
                "possible_attributes": list(change_request.possible_attributes),
                "item_id": item_id,
            }

            msg = self.modifier_change_handler.generate_clarification_message(change_request)
            return StateMachineResult(message=msg, order=order)

        # Unambiguous - apply the change directly
        if change_request.possible_attributes:
            attr_slug = change_request.possible_attributes[0]

            # If "unknown" modifier, check if it's actually a menu item replacement
            if attr_slug == "unknown":
                from orderbot.tasks.parsers.deterministic import parse_open_input_deterministic
                parsed = parse_open_input_deterministic(change_request.new_value)
                if parsed and parsed.parsed_items:
                    # This is a menu item, not a modifier - defer to normal parsing
                    logger.info(
                        "CHANGE REQUEST: '%s' is a menu item, deferring to item replacement flow",
                        change_request.new_value
                    )
                    return None

            # Find target item
            active_items = order.items.get_active_items()
            if not active_items:
                return StateMachineResult(
                    message="I don't see any items to change. What would you like to order?",
                    order=order,
                )

            result = self.modifier_change_handler.apply_change(
                order=order,
                item_id=None,  # Last item
                attr_slug=attr_slug,
                new_value=change_request.new_value,
            )

            if result.success:
                msg = f"{result.message} Anything else?"
                return StateMachineResult(message=msg, order=order)
            else:
                return StateMachineResult(message=result.message, order=order)

        return None

    def handle_side_choice(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle side choice - creates child MenuItemTask for the chosen side.

        This is a data-driven handler that works with any side choice options
        from the database. The chosen side becomes a separate MenuItemTask that
        is configured using standard item configuration handlers.

        Flow:
        1. Parse user's choice using generic parser with DB options
        2. Create child MenuItemTask for the chosen side
        3. Mark parent item complete
        4. Let slot orchestrator pick up the new incomplete child item
        """
        # Import here to avoid circular dependency
        from .state_machine import _check_redirect_to_pending_item

        # Load side choice options from database (data-driven)
        parent_item_type = item.menu_item_type
        side_attr = menu_cache.get_side_choice_attribute(parent_item_type) if parent_item_type else None
        question_text = f"Would you like a side with your {item.menu_item_name}?"

        # Build valid_answers and options list from database
        valid_answers: set[str] = set()
        valid_options: list[dict] = []
        if side_attr:
            attr_slug = side_attr.get("slug")
            question_text = side_attr.get("question_text") or question_text
            # Load options for the side_choice attribute
            try:
                options = menu_cache.get_global_attribute_options(attr_slug)
                valid_options = options  # Pass to parser
                for opt in options:
                    # Add option slug and display_name as valid answers
                    valid_answers.add(opt.get("slug", "").lower())
                    valid_answers.add(opt.get("display_name", "").lower())
                    # Add any aliases
                    for alias in opt.get("aliases", []):
                        valid_answers.add(alias.lower())
            except MenuDataNotLoadedError:
                # If cache not loaded, fall back to empty set (won't filter anything)
                logger.debug("Menu cache not loaded when getting side choice options for %s", attr_slug)

        redirect = _check_redirect_to_pending_item(
            user_input, item, order, question_text,
            valid_answers=valid_answers if valid_answers else None
        )
        if redirect:
            return redirect

        # Parse the side choice using generic data-driven parser
        parsed = parse_side_choice(
            user_input,
            item.menu_item_name,
            valid_options=valid_options,
            question_text=question_text,
            model=self.model,
        )

        if parsed.wants_cancel:
            item.mark_skipped()
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message="No problem, I've removed that. Anything else?",
                order=order,
            )

        if parsed.choice == "unclear":
            return StateMachineResult(
                message=f"{question_text.replace(' with it?', '')} with your {item.menu_item_name}?",
                order=order,
            )

        # Record the side choice on parent for reference
        item["side_choice"] = parsed.choice

        # Create a child MenuItemTask for the chosen side
        # The side item type slug is the parsed choice (e.g., "bagel", "fruit_salad")
        side_item_type = parsed.choice
        side_display_name = menu_cache.get_item_type_display_name(side_item_type)

        # Create the child task with side_of_item_id linking to parent
        child_item = MenuItemTask(
            menu_item_name=side_display_name,
            menu_item_type=side_item_type,
            unit_price=0.0,  # Side items are free (base price = 0)
            side_of_item_id=item.id,  # Link to parent item
        )

        # Check if the side requires configuration (has required attributes)
        side_attrs = menu_cache.get_item_type_attributes(side_item_type) if side_item_type else {}
        has_required_attrs = any(
            attr_config.get("is_required", False) and attr_config.get("ask_in_conversation", False)
            for attr_config in side_attrs.values()
        )

        if has_required_attrs:
            child_item.mark_in_progress()  # Needs configuration
        else:
            child_item.mark_complete()  # No configuration needed (e.g., fruit_salad)

        # Add the child item to the order
        order.items.add_item(child_item)

        # Mark parent item complete - its configuration is done
        item.mark_complete()

        # Clear pending state
        order.clear_pending()

        # Let slot orchestrator pick up the next incomplete item (the child if it needs config)
        if self._get_next_question:
            return self._get_next_question(order)

        # Fallback: return simple acknowledgment
        return StateMachineResult(
            message="Got it. Anything else?",
            order=order,
        )

