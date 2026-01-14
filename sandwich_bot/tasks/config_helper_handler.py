"""
Configuration Helper Handler for Order State Machine.

This module handles configuration-related helper operations including
cancellation during config, change clarifications, modifier changes,
and side choice handling.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Optional, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, ItemTask
from .schemas import OrderPhase, StateMachineResult
from .parsers import parse_side_choice
from .handler_config import HandlerConfig
from .taking_items_handler import extract_ordinal_reference, find_nth_item_of_type
from sandwich_bot.menu_data_cache import menu_cache
from sandwich_bot.exceptions import MenuDataNotLoadedError

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
    from sandwich_bot.menu_data_cache import menu_cache

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

# Pattern to detect cancel/remove requests during configuration
CANCEL_ITEM_PATTERN = re.compile(
    r"^(?:(?:can\s+you\s+)?(?:please\s+)?)?(?:remove|cancel|delete|take\s+off|get\s+rid\s+of|forget|nevermind|never\s+mind)"
    r"(?:\s+(?:the|my|that|this))?\s*(.+?)(?:\s+please)?$",
    re.IGNORECASE
)


class ConfigHelperHandler:
    """
    Handles configuration helper operations.

    Manages cancellation during config, change clarifications,
    modifier changes, and side choice handling.
    """

    def __init__(
        self,
        config: HandlerConfig | None = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        **kwargs,
    ):
        """
        Initialize the config helper handler.

        Args:
            config: HandlerConfig with shared dependencies.
            modifier_change_handler: Handler for modifier changes.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.model = config.model
            self._get_next_question = config.get_next_question
            self.pricing = config.pricing
        else:
            # Legacy support for direct parameters
            self.model = kwargs.get("model", "gpt-4o-mini")
            self._get_next_question = kwargs.get("get_next_question")
            self.pricing = kwargs.get("pricing")

        # Handler-specific dependency
        self.modifier_change_handler = modifier_change_handler or kwargs.get("modifier_change_handler")

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
            order.phase = OrderPhase.TAKING_ITEMS.value
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
        # Get removable modifiers from database
        removable_modifiers = _get_removable_modifiers()

        if cancel_desc in removable_modifiers and isinstance(current_item, MenuItemTask) and current_item.has_attribute("bread"):
            modifier_removed = False
            removed_modifier_name = cancel_desc

            # Check extra_protein
            if current_item.extra_protein and cancel_desc in current_item.extra_protein.lower():
                current_item.extra_protein = None
                modifier_removed = True
                logger.info("Modifier removal during config: removed protein '%s' from bagel", cancel_desc)

            # Check toppings list
            if current_item.toppings:
                new_toppings = []
                for topping in current_item.toppings:
                    if cancel_desc not in topping.lower():
                        new_toppings.append(topping)
                    else:
                        modifier_removed = True
                        logger.info("Modifier removal during config: removed topping '%s' from bagel", topping)
                current_item.toppings = new_toppings

            # Check spread
            if current_item.spread and cancel_desc in current_item.spread.lower():
                current_item.spread = None
                current_item.spread_type = None
                modifier_removed = True
                logger.info("Modifier removal during config: removed spread '%s' from bagel", cancel_desc)

            if modifier_removed:
                # Recalculate price if pricing handler is available
                if self.pricing:
                    try:
                        self.pricing.recalculate_item_price(current_item)
                    except (ValueError, KeyError):
                        # Price recalculation failed (missing menu data), skip
                        logger.debug("Could not recalculate bagel price after modifier removal")

                updated_summary = current_item.get_summary()

                # Return to config question or continue with configuration
                question = self.get_current_config_question(order, current_item)
                if question:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_modifier_name}. {question}",
                        order=order,
                    )
                else:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_modifier_name}. Your bagel is now {updated_summary}. Anything else?",
                        order=order,
                    )

        # Handle modifier removal for MenuItemTask (deli sandwiches, etc.)
        # Modifiers are stored in attribute_values with _selections format
        if cancel_desc in removable_modifiers and isinstance(current_item, MenuItemTask):
            modifier_removed = False
            removed_modifier_name = cancel_desc

            # Normalize cancel_desc for matching - handle singular/plural
            # "eggs" -> also check "egg", "cheeses" -> also check "cheese"
            cancel_desc_singular = cancel_desc.rstrip('s') if cancel_desc.endswith('s') and len(cancel_desc) > 2 else cancel_desc
            # Also handle the reverse: "egg" -> also check "eggs"
            cancel_desc_plural = cancel_desc + 's' if not cancel_desc.endswith('s') else cancel_desc

            # Check all attribute_values for selections that match the cancel description
            attrs_to_clear = []
            for attr_slug, attr_value in list(current_item.attribute_values.items()):
                # Skip metadata fields
                if attr_slug.endswith("_price") or attr_slug.endswith("_selections"):
                    continue

                # Check _selections data for this attribute
                selections_key = f"{attr_slug}_selections"
                selections = current_item.attribute_values.get(selections_key, [])
                if selections and isinstance(selections, list):
                    new_selections = []
                    for sel in selections:
                        sel_display = sel.get("display_name", "").lower()
                        sel_slug = sel.get("slug", "").lower()
                        # Check if this selection matches the cancel description (singular or plural)
                        if (cancel_desc in sel_display or cancel_desc_singular in sel_display or
                            cancel_desc in sel_slug or cancel_desc_singular in sel_slug):
                            modifier_removed = True
                            removed_modifier_name = sel.get("display_name", cancel_desc)
                            logger.info("Modifier removal during config: removed '%s' from menu item", removed_modifier_name)
                        else:
                            new_selections.append(sel)

                    if len(new_selections) != len(selections):
                        # Some selections were removed
                        if new_selections:
                            current_item.attribute_values[selections_key] = new_selections
                            # Update the main attribute value too
                            current_item.attribute_values[attr_slug] = [s["slug"] for s in new_selections]
                        else:
                            # All selections removed - clear the attribute
                            attrs_to_clear.append(attr_slug)
                            attrs_to_clear.append(selections_key)

            # Clear any attributes that had all selections removed
            for attr_key in attrs_to_clear:
                if attr_key in current_item.attribute_values:
                    del current_item.attribute_values[attr_key]

            if modifier_removed:
                updated_summary = current_item.get_summary()

                # Return to customization checkpoint or continue
                question = self.get_current_config_question(order, current_item)
                if question:
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_modifier_name}. {question}",
                        order=order,
                    )
                else:
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
                order.phase = OrderPhase.TAKING_ITEMS.value

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
        is_plural = cancel_desc.endswith('s') and len(cancel_desc) > 2
        singular_desc = cancel_desc[:-1] if is_plural else cancel_desc

        # Find matching items (fallback for non-ordinal cancellations)
        items_to_remove = []

        # Map user category terms to item_type via database (e.g., "coffee" -> "sized_beverage")
        # Uses category keywords from item_types.aliases in the database
        from sandwich_bot.menu_data_cache import menu_cache
        mapped_item_type = None
        category_mapping = menu_cache.get_category_keyword_mapping(cancel_desc)
        if not category_mapping:
            category_mapping = menu_cache.get_category_keyword_mapping(singular_desc)
        if category_mapping:
            mapped_item_type = category_mapping.get("slug")

        for item in active_items:
            item_summary = item.get_summary().lower()
            item_name = getattr(item, 'menu_item_name', '') or ''
            item_name_lower = item_name.lower()
            item_type = getattr(item, 'item_type', '') or ''
            menu_item_type = getattr(item, 'menu_item_type', '') or ''

            # Check for matches - be careful with empty strings
            matches = False
            if cancel_desc in item_summary:
                matches = True
            elif singular_desc in item_summary:
                matches = True
            elif item_name_lower and cancel_desc in item_name_lower:
                matches = True
            elif item_name_lower and singular_desc in item_name_lower:
                matches = True
            elif item_name_lower and item_name_lower in cancel_desc:
                matches = True
            # Check item_type for things like "coffee" -> matches item_type="coffee"
            elif item_type and (cancel_desc == item_type or singular_desc == item_type):
                matches = True
            # Check menu_item_type (e.g., "sized_beverage", "bagel")
            elif menu_item_type and (cancel_desc == menu_item_type or singular_desc == menu_item_type):
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
            order.phase = OrderPhase.TAKING_ITEMS.value

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
        from sandwich_bot.menu_data_cache import menu_cache

        field = order.pending_field
        if not field:
            return None

        # Special case: side_choice is flow control, not a DB attribute
        # TODO: Future enhancement - support menu items as components of other items
        if field == "side_choice":
            return "Would you like a bagel or fruit salad with it?"

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
        except Exception:
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
            return StateMachineResult(
                message=error or "I didn't catch that. Would you like to change the bagel type or the cream cheese?",
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
        """Handle side choice for omelette - uses constrained parser."""
        # Import here to avoid circular dependency
        from .state_machine import _check_redirect_to_pending_item

        # "bagel" and "fruit salad" are valid answers, not new order attempts
        redirect = _check_redirect_to_pending_item(
            user_input, item, order, "Would you like a bagel or fruit salad with it?",
            valid_answers={"bagel", "fruit", "fruit salad"}
        )
        if redirect:
            return redirect

        # This parser can ONLY return side choice - no new items possible!
        parsed = parse_side_choice(user_input, item.menu_item_name, model=self.model)

        if parsed.wants_cancel:
            item.mark_skipped()
            order.clear_pending()
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message="No problem, I've removed that. Anything else?",
                order=order,
            )

        if parsed.choice == "unclear":
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {item.menu_item_name}?",
                order=order,
            )

        # Apply the choice
        item.side_choice = parsed.choice

        # Data-driven: check if choice is a bread-based side (has bread attribute)
        choice_attrs = menu_cache.get_item_type_attributes(parsed.choice) if parsed.choice else {}
        is_bread_side = "bread" in choice_attrs

        if is_bread_side:
            if parsed.bread:
                # User specified bagel type upfront (e.g., "plain bagel")
                # Set bagel_choice but don't mark complete - still need toasted/spread questions
                item.bagel_choice = parsed.bread

                # Also apply toasted if specified (e.g., "plain bagel toasted")
                if parsed.toasted is not None:
                    item.toasted = parsed.toasted

                # Also apply spread if specified (e.g., "with cream cheese")
                # Note: spread price will be calculated by bagel_config_handler when spread is set
                if parsed.spread:
                    item.spread = parsed.spread

                order.clear_pending()
                # Continue to ask remaining questions via configure_next_incomplete_bagel
                # This will handle toasted, spread, and pricing
                if self._get_next_question:
                    return self._get_next_question(order)
                # Fallback: ask about toasted if not specified, otherwise spread
                if item.toasted is None:
                    order.pending_field = "bagel:toasted"
                    return StateMachineResult(
                        message=f"Ok, {parsed.bread} bagel. Would you like that toasted?",
                        order=order,
                    )
                elif item.spread is None:
                    order.pending_field = "bagel:spread_type"
                    toasted_desc = " toasted" if item.toasted else ""
                    return StateMachineResult(
                        message=f"Ok, {parsed.bread} bagel{toasted_desc}. Would you like butter or cream cheese on that?",
                        order=order,
                    )
                else:
                    # All fields filled - mark complete
                    item.mark_complete()
                    return StateMachineResult(
                        message="Got it. Anything else?",
                        order=order,
                    )
            else:
                # Need to ask for bagel type
                order.pending_field = "bagel:bread"
                return StateMachineResult(
                    message="What kind of bagel would you like?",
                    order=order,
                )
        else:
            # Fruit salad - omelette is complete
            order.clear_pending()
            item.mark_complete()
            if self._get_next_question:
                return self._get_next_question(order)
            return StateMachineResult(
                message="Got it. Anything else?",
                order=order,
            )

    def handle_bagel_choice_for_side(
        self,
        user_input: str,
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> "StateMachineResult":
        """Handle bagel type selection for menu items with bagel sides.

        This handles the bagel_choice question for items like omelettes and salads
        that have a bagel as a side option. It parses the user's bagel choice and
        updates the item's bagel_choice field.

        Args:
            user_input: The user's input (e.g., "plain", "everything bagel")
            item: The menu item with a bagel side
            order: The current order

        Returns:
            StateMachineResult with next question or completion message
        """
        from .state_machine import BagelChoiceResponse
        from .parsers.llm_parsers import parse_bagel_choice

        # Parse the bagel choice
        parsed = parse_bagel_choice(user_input, num_pending_bagels=1)

        if parsed.bread:
            # Set the bagel choice on the menu item
            item.bagel_choice = parsed.bread
            logger.info(
                "Set bagel_choice='%s' on menu item '%s'",
                parsed.bread, item.menu_item_name
            )

            # Clear pending and continue to next question
            order.clear_pending()
            if self._get_next_question:
                return self._get_next_question(order)
            return StateMachineResult(
                message="Got it. Anything else?",
                order=order,
            )
        else:
            # Couldn't parse - ask again
            return StateMachineResult(
                message="What kind of bagel would you like for your side?",
                order=order,
            )
