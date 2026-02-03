"""
Configuration Cancellation Handler for Order State Machine.

Handles cancellation/removal requests during item configuration phase.
Extracted from config_helper_handler.py for better separation of concerns.
"""

import logging
import re
from typing import Optional, Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, TaskStatus
from .schemas import OrderPhase, StateMachineResult
from .parsers import CANCEL_ITEM_PATTERN
from .item_cancellation_handler import extract_ordinal_reference, find_nth_item_of_type
from .modifier_operations import (
    find_modifier_match,
    remove_modifier_from_item,
    find_default_ingredient_match,
    remove_default_ingredient_from_item,
)
from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.cache.base import get_singular_plural_variants, singularize
from .checkout_messages import ok_removed_anything_else, ErrorMessages, item_not_found_in_order

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler

logger = logging.getLogger(__name__)


def _extract_modifier_and_item_reference(cancel_desc: str) -> tuple[str, str] | None:
    """Extract modifier and item reference from phrases like 'onions on the leo'.

    Patterns handled:
    - "X on the Y" / "X on Y"
    - "X from the Y" / "X from Y"
    - "X off the Y" / "X off Y"
    - "X off of the Y" / "X off of Y"

    Returns:
        Tuple of (modifier, item_reference) if pattern matches, None otherwise
    """
    # Pattern: modifier + separator + optional "the"/"my" + item reference
    pattern = r'^(.+?)\s+(?:on|from|off(?:\s+of)?)\s+(?:the\s+|my\s+)?(.+)$'
    match = re.match(pattern, cancel_desc, re.IGNORECASE)
    if match:
        modifier = match.group(1).strip()
        item_ref = match.group(2).strip()
        # Ensure both parts are non-empty
        if modifier and item_ref:
            return (modifier, item_ref)
    return None


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


class ConfigCancellationHandler:
    """
    Handles cancellation/removal requests during item configuration.

    When a user says "remove the coffee" or "cancel this" while being asked
    about coffee size, this handler processes the cancellation request instead
    of forcing the user to answer the configuration question.
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None,
    ) -> None:
        """
        Initialize the config cancellation handler.

        Args:
            config_helper_handler: Parent handler for getting current config question.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
        """
        self.config_helper_handler = config_helper_handler
        self._configure_next_incomplete_item = configure_next_incomplete_item

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

            # Check for remaining incomplete items that need configuration
            if remaining and self._configure_next_incomplete_item:
                for item in remaining:
                    if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                        # Get the next config question and prepend removal confirmation
                        config_result = self._configure_next_incomplete_item(order)
                        return StateMachineResult(
                            message=f"OK, I've removed the {item_name}. {config_result.message}",
                            order=order,
                        )

            if remaining:
                return StateMachineResult(
                    message=ok_removed_anything_else(item_name),
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed the {item_name}. What would you like to order?",
                    order=order,
                )

        # Check if cancel_desc matches an ITEM TYPE (e.g., "bagels", "coffees")
        # If so, skip modifier removal - user wants to remove items, not modifiers
        cancel_variants = get_singular_plural_variants(cancel_desc)
        matches_item_type = False
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping:
                matches_item_type = True
                logger.info(
                    "Cancel during config: '%s' matches item type '%s' - skipping modifier removal",
                    cancel_desc, category_mapping.get("slug")
                )
                break

        # First, try to parse "modifier on/from item" pattern (e.g., "onions on the leo")
        modifier_item_parsed = _extract_modifier_and_item_reference(cancel_desc)
        if modifier_item_parsed:
            modifier_part, item_ref = modifier_item_parsed
            logger.info(
                "Parsed modifier removal: modifier='%s', item_ref='%s'",
                modifier_part, item_ref
            )

            # Find the referenced item in the order
            target_item = None
            active_items = order.items.get_active_items()
            item_ref_lower = item_ref.lower()

            for item in active_items:
                if not isinstance(item, MenuItemTask):
                    continue
                item_name = (item.menu_item_name or "").lower()
                item_summary = item.get_summary().lower()
                # Match if item_ref appears in item name or summary
                if item_ref_lower in item_name or item_ref_lower in item_summary:
                    target_item = item
                    break

            if target_item:
                # Try modifier removal on the target item
                try:
                    modifier_match = find_modifier_match(target_item, modifier_part)
                    if modifier_match:
                        removal_result = remove_modifier_from_item(target_item, modifier_match)
                        if removal_result.success:
                            removed_name = removal_result.removed_value or modifier_part
                            logger.info(
                                "Removed '%s' from '%s' via 'X on Y' pattern",
                                removed_name, target_item.menu_item_name
                            )
                            # Return to config question or acknowledge
                            question = self._get_current_config_question(order, current_item)
                            if question:
                                return StateMachineResult(
                                    message=f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}. {question}",
                                    order=order,
                                )
                            else:
                                return StateMachineResult(
                                    message=f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}. Anything else?",
                                    order=order,
                                )
                except MenuDataNotLoadedError:
                    pass  # Fall through to try default ingredient removal

                # Also try default ingredient removal for the modifier part
                default_match = find_default_ingredient_match(target_item, modifier_part)
                if default_match:
                    removal_result = remove_default_ingredient_from_item(target_item, default_match)
                    if removal_result.success:
                        removed_name = removal_result.removed_value or modifier_part
                        logger.info(
                            "Removed default ingredient '%s' from '%s' via 'X on Y' pattern",
                            removed_name, target_item.menu_item_name
                        )
                        question = self._get_current_config_question(order, current_item)
                        if question:
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}. {question}",
                                order=order,
                            )
                        else:
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}. Anything else?",
                                order=order,
                            )
            # If pattern matched but no item found or no modifier found, fall through to existing logic

        # Check if this is a modifier removal on the current item being configured
        # Use unified modifier_operations for consistent handling
        # But SKIP if cancel_desc matches an item type (user wants to remove items, not modifiers)
        if isinstance(current_item, MenuItemTask) and not matches_item_type:
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
                        question = self._get_current_config_question(order, current_item)
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
                        question = self._get_current_config_question(order, current_item)
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
                message=ErrorMessages.NO_ITEMS_YET,
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

                # Check for remaining incomplete items that need configuration
                if remaining and self._configure_next_incomplete_item:
                    for item in remaining:
                        if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                            config_result = self._configure_next_incomplete_item(order)
                            return StateMachineResult(
                                message=f"OK, I've removed the {removed_name}. {config_result.message}",
                                order=order,
                            )

                if remaining:
                    return StateMachineResult(
                        message=ok_removed_anything_else(removed_name),
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
                message=item_not_found_in_order(cancel_desc),
                order=order,
            )

    def _get_current_config_question(
        self,
        order: OrderTask,
        item: MenuItemTask,
    ) -> str | None:
        """Get the current configuration question being asked.

        Delegates to config_helper_handler if available.
        """
        if self.config_helper_handler:
            return self.config_helper_handler.get_current_config_question(order, item)
        return None
