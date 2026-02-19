"""
Configuration Cancellation Handler for Order State Machine.

Handles cancellation/removal requests during item configuration phase.
Extracted from config_helper_handler.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, TaskStatus
from .schemas import OrderPhase, StateMachineResult
from .parsers import CANCEL_ITEM_PATTERN, strip_conversational_fillers
from .pending_fields import PendingField
from .parsers.quantity_utils import extract_leading_quantity
from .item_cancellation_handler import extract_ordinal_reference, find_nth_item_of_type
from .handler_utils import check_has_active_items, remove_item_from_order, build_removal_response
from .modifier_operations import (
    find_modifier_match,
    remove_modifier_from_item,
    find_default_ingredient_match,
    remove_default_ingredient_from_item,
)
from .modifier_resolver import TRAILING_FILLERS
from .normalization import format_slug_for_display
from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.cache.base import get_singular_plural_variants, singularize
from .models.utilities import parse_pending_field
from .checkout_messages import ok_removed_anything_else, ErrorMessages, item_not_found_in_order
from .utils.pricing_utils import safe_recalculate_price

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)

# Pattern for "start over" / "start fresh" - clears entire order
START_OVER_PATTERN = re.compile(
    r"^(?:"
    r"start\s*over"
    r"|start\s*fresh"
    r"|let(?:'?s)?\s+start\s*over"
    r"|(?:can\s+)?(?:i|we)\s+start\s*over"
    r"|begin\s*again"
    r"|from\s+the\s+(?:beginning|start)"
    r")[\s!.,?]*$",
    re.IGNORECASE
)

# Pattern for standalone cancellation phrases (no target specified)
# During CONFIGURING_ITEM phase, these mean "cancel the current item being configured"
STANDALONE_CANCEL_PATTERN = re.compile(
    r"^(?:"
    r"cancel"
    r"|never\s*mind"
    r"|nevermind"
    r"|forget\s*it"
    r"|skip\s*(?:this|it)?"
    r"|(?:i\s+)?changed?\s*my\s*mind(?:,?\s*cancel)?"
    r"|(?:i\s+)?don'?t\s+want\s+(?:it|this)(?:\s+anymore)?"
    r")[\s!.,?]*$",
    re.IGNORECASE
)

# Pattern for abandoning the entire order during TAKING_ITEMS phase.
# These phrases express whole-order cancellation intent (not single-item removal).
# Matches: "I changed my mind", "never mind", "forget it", "cancel", etc.
CANCEL_ORDER_PATTERN = re.compile(
    r"^(?:"
    r"(?:i\s+)?changed?\s*my\s*mind(?:,?\s*(?:cancel|never\s*mind|nevermind))?"
    r"|never\s*mind(?:,?\s*cancel)?"
    r"|nevermind(?:,?\s*cancel)?"
    r"|forget\s*(?:it|about\s+it)"
    r"|cancel"
    r"|(?:i\s+)?don'?t\s+want\s+(?:anything|to\s+order)(?:\s+(?:anymore|any\s*more))?"
    r")[\s!.,?]*$",
    re.IGNORECASE
)


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


def _item_matches(
    item: "MenuItemTask",
    cancel_variants: list[str],
    cancel_desc: str,
    mapped_item_type: str | None,
) -> bool:
    """Check if an item matches the cancellation description."""
    item_summary = item.get_summary().lower()
    item_name = item.menu_item_name or ''
    item_name_lower = item_name.lower()
    item_type = item.item_type or ''
    menu_item_type = item.menu_item_type or ''

    if any(v in item_summary for v in cancel_variants):
        return True
    if item_name_lower and any(v in item_name_lower for v in cancel_variants):
        return True
    if item_name_lower and item_name_lower in cancel_desc:
        return True
    if item_type and any(v == item_type for v in cancel_variants):
        return True
    if menu_item_type and any(v == menu_item_type for v in cancel_variants):
        return True
    if mapped_item_type and menu_item_type == mapped_item_type:
        return True
    return False


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
        pricing: "PricingEngine | None" = None,
    ) -> None:
        """
        Initialize the config cancellation handler.

        Args:
            config_helper_handler: Parent handler for getting current config question.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
            pricing: PricingEngine for recalculating prices after modifier removal.
        """
        self.config_helper_handler = config_helper_handler
        self._configure_next_incomplete_item = configure_next_incomplete_item
        self.pricing = pricing

    def _handle_start_over(self, order: OrderTask) -> StateMachineResult:
        """Clear all items and return to TAKING_ITEMS phase."""
        active_items = order.items.get_active_items()
        if active_items:
            num_items = len(active_items)
            for item in active_items:
                remove_item_from_order(order, item)
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            logger.info("Start over: cleared ALL %d items from cart", num_items)
            return StateMachineResult(
                message="OK, let's start over. What would you like to order?",
                order=order,
            )
        return StateMachineResult(
            message="Your order is already empty. What would you like to order?",
            order=order,
        )

    @staticmethod
    def _extract_cancel_description(user_input_stripped: str) -> str | None:
        """Extract the cancel target from user input.

        Matches STANDALONE_CANCEL_PATTERN (→ "this") or CANCEL_ITEM_PATTERN
        (→ extracted description). Returns None if no cancel intent detected.
        """
        if STANDALONE_CANCEL_PATTERN.match(user_input_stripped):
            logger.info("Standalone cancel during config: '%s'", user_input_stripped)
            return "this"

        cancel_match = CANCEL_ITEM_PATTERN.match(user_input_stripped)
        if not cancel_match:
            return None

        cancel_desc = None
        for group in cancel_match.groups():
            if group:
                cancel_desc = group.strip().lower()
                break
        if not cancel_desc:
            return None

        # Strip trailing pleasantries ("thank you", "thanks", "please")
        for filler in TRAILING_FILLERS:
            if cancel_desc.endswith(filler.strip()):
                cancel_desc = cancel_desc[:-len(filler.strip())].strip()
                break

        return cancel_desc

    @staticmethod
    def _should_defer_to_attribute_handler(cancel_desc: str, order: OrderTask) -> bool:
        """Check if cancel_desc matches the pending attribute slug.

        If so, this is a decline/skip ("no cheese" during cheese config means
        "I don't want cheese"), not an item removal. Returns True to defer.
        """
        _, pending_attr_slug = parse_pending_field(order.pending_field)
        if not pending_attr_slug:
            return False

        cancel_variants = get_singular_plural_variants(cancel_desc)
        # Check if cancel_desc words overlap with the slug's word components
        # (e.g., "shots" matches "espresso_shots" via the "shots" component)
        attr_slug_parts = set(pending_attr_slug.split("_"))
        if (pending_attr_slug in cancel_variants
                or cancel_desc == pending_attr_slug
                or set(cancel_variants) & attr_slug_parts):
            logger.info(
                "Cancel during config: '%s' matches pending attribute '%s' - "
                "deferring to attribute handler",
                cancel_desc, pending_attr_slug,
            )
            return True
        return False

    @staticmethod
    def _cancel_matches_item_or_type(
        cancel_desc: str, order: OrderTask,
    ) -> tuple[bool, bool]:
        """Check if cancel_desc matches an item type name or an item's base name.

        Returns (matches_item_type, matches_item_in_order). When either is True,
        modifier removal should be skipped — the user wants to remove items.
        """
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

        # Check against item BASE NAMES only (not full summary which includes modifiers)
        matches_item_in_order = False
        cancel_desc_lower = cancel_desc.lower()
        for item in order.items.get_active_items():
            if not isinstance(item, MenuItemTask):
                continue
            item_name = (item.menu_item_name or "").lower()
            if item_name and (cancel_desc_lower in item_name or item_name in cancel_desc_lower):
                matches_item_in_order = True
                logger.info(
                    "Cancel during config: '%s' matches item name '%s' - skipping modifier removal",
                    cancel_desc, item_name
                )
                break

        return matches_item_type, matches_item_in_order

    def check_cancellation_during_config(
        self,
        user_input: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check if user wants to cancel/remove items while in configuration phase.

        Returns StateMachineResult if cancellation handled, None otherwise.
        """
        user_input_stripped = strip_conversational_fillers(user_input.strip())

        # Check for "start over" - clears entire order
        if START_OVER_PATTERN.match(user_input_stripped):
            logger.info("Start over during config: '%s'", user_input_stripped)
            return self._handle_start_over(order)

        # Extract cancel target description
        cancel_desc = self._extract_cancel_description(user_input_stripped)
        if not cancel_desc:
            return None
        logger.info("Cancel request during config: '%s'", cancel_desc)

        # Defer to attribute handler if cancel matches pending attribute
        if self._should_defer_to_attribute_handler(cancel_desc, order):
            return None

        # Try removing an already-set attribute by name
        if isinstance(current_item, MenuItemTask):
            result = self._try_remove_attribute_by_name(cancel_desc, current_item, order)
            if result:
                return result

        # At customization checkpoint, defer unset attribute declines
        if order.pending_field in (
            PendingField.CUSTOMIZATION_CHECKPOINT,
            PendingField.CUSTOMIZATION_SELECTION,
        ) and isinstance(current_item, MenuItemTask):
            result = self._try_remove_attribute_by_name(
                cancel_desc, current_item, order, defer_if_unset=True
            )
            if result:
                return result

        # Cancel current item ("this", "it") or all items ("everything", "all")
        result = self._try_cancel_current_item(cancel_desc, current_item, order)
        if result:
            return result
        result = self._try_cancel_all_items(cancel_desc, order)
        if result:
            return result

        # Determine if cancel_desc refers to an item type or cart item name
        matches_item_type, matches_item_in_order = self._cancel_matches_item_or_type(
            cancel_desc, order
        )

        # Try modifier removal (skipped when cancel_desc matches an item)
        result = self._try_remove_modifier_by_reference(cancel_desc, current_item, order)
        if result:
            return result
        result = self._try_remove_modifier_on_current_item(
            cancel_desc, current_item, order, matches_item_type, matches_item_in_order,
        )
        if result:
            return result

        # Fall through: find and remove matching items
        return self._find_and_remove_matching_items(cancel_desc, current_item, order)

    def _try_remove_attribute_by_name(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
        *,
        defer_if_unset: bool = False,
    ) -> StateMachineResult | None:
        """Try to match cancel_desc to an attribute name and remove its value.

        Args:
            cancel_desc: Normalized cancellation description.
            current_item: The item currently being configured.
            order: The current order task.
            defer_if_unset: If True and attribute matches but has no value,
                return None (defer to another handler). Used at customization checkpoint.

        Returns:
            StateMachineResult if attribute was removed, None to continue.
        """
        item_type_attrs = menu_cache.get_item_type_attributes(current_item.menu_item_type)
        cancel_variants = get_singular_plural_variants(cancel_desc)
        for attr_slug, attr_data in item_type_attrs.items():
            attr_display_lower = (attr_data.get("display_name") or "").lower()
            if attr_slug in cancel_variants or attr_display_lower in cancel_variants:
                current_value = current_item.attribute_values.get(attr_slug)
                if current_value is not None:
                    current_item[attr_slug] = None
                    safe_recalculate_price(
                        self.pricing, current_item, "after attribute removal via cancel"
                    )
                    display_name = (
                        attr_data.get("display_name") or format_slug_for_display(attr_slug)
                    )
                    logger.info(
                        "Removed attribute '%s' from %s during config",
                        attr_slug, current_item.menu_item_name,
                    )
                    return self._config_removal_response(
                        f"OK, I've removed the {display_name}.",
                        order, current_item,
                        ok_removed_anything_else(display_name),
                    )
                if defer_if_unset:
                    logger.info(
                        "Cancel during config: '%s' matches attribute '%s' at customization "
                        "checkpoint - deferring to checkpoint handler",
                        cancel_desc, attr_slug,
                    )
                    return None
        return None

    def _try_cancel_current_item(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'cancel this/it/that' — remove the current item."""
        if cancel_desc not in ("this", "it", "that", "this one", "that one"):
            return None

        item_name = current_item.get_summary()
        current_item.mark_skipped()
        order.clear_pending()
        order.set_phase(OrderPhase.TAKING_ITEMS)
        return build_removal_response(
            order, item_name, self._configure_next_incomplete_item
        )

    def _try_cancel_all_items(
        self,
        cancel_desc: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'cancel everything/all' — clear entire order."""
        all_items_phrases = {
            "all", "everything", "all of it", "the order", "my order",
            "the whole order", "my whole order", "all items", "all the items",
            "the whole thing", "it all", "them all",
            "order", "whole order", "whole thing"
        }
        if cancel_desc.lower() not in all_items_phrases:
            return None

        active_items = order.items.get_active_items()
        if active_items:
            num_items = len(active_items)
            for item in active_items:
                remove_item_from_order(order, item)
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            logger.info("Cancel during config: cleared ALL %d items from cart", num_items)
            return StateMachineResult(
                message="OK, I've cleared your order. What would you like to order?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="Your order is already empty. What would you like to order?",
                order=order,
            )

    def _try_remove_modifier_by_reference(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to remove a modifier using "X on/from Y" pattern.

        Handles phrases like "remove onions from the leo" by parsing the modifier
        and item reference, finding the target item, and attempting modifier removal
        followed by default ingredient removal.

        Args:
            cancel_desc: Normalized cancellation description from user input.
            current_item: The item currently being configured.
            order: The current order task.

        Returns:
            StateMachineResult if modifier was removed, None to continue with
            other checks.
        """
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
                            # Recalculate price after modifier removal
                            safe_recalculate_price(
                                self.pricing, target_item, "after modifier removal via X on Y pattern"
                            )
                            removed_name = format_slug_for_display(removal_result.removed_value or modifier_part)
                            logger.info(
                                "Removed '%s' from '%s' via 'X on Y' pattern",
                                removed_name, target_item.menu_item_name
                            )
                            return self._config_removal_response(
                                f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}.",
                                order, current_item,
                                f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}. Anything else?",
                            )
                except MenuDataNotLoadedError:
                    pass  # Fall through to try default ingredient removal

                # Also try default ingredient removal for the modifier part
                default_match = find_default_ingredient_match(target_item, modifier_part)
                if default_match:
                    removal_result = remove_default_ingredient_from_item(target_item, default_match)
                    if removal_result.success:
                        # Note: Default ingredient removal doesn't affect price (already included)
                        removed_name = format_slug_for_display(removal_result.removed_value or modifier_part)
                        logger.info(
                            "Removed default ingredient '%s' from '%s' via 'X on Y' pattern",
                            removed_name, target_item.menu_item_name
                        )
                        return self._config_removal_response(
                            f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}.",
                            order, current_item,
                            f"OK, I've removed the {removed_name} from your {target_item.menu_item_name}. Anything else?",
                        )
            # If pattern matched but no item found or no modifier found, fall through to existing logic

        return None

    def _try_remove_modifier_on_current_item(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
        matches_item_type: bool,
        matches_item_in_order: bool,
    ) -> StateMachineResult | None:
        """Try to remove a modifier from the current item being configured.

        Uses unified modifier_operations for consistent handling, with a legacy
        fallback using the removable_modifiers set. Supports quantity-aware
        removal (e.g., "remove 1 shot" decrements by 1).

        Skipped entirely if cancel_desc matches an item type or item name in the
        order, since the user likely wants to remove the item itself, not a modifier.

        Args:
            cancel_desc: Normalized cancellation description from user input.
            current_item: The item currently being configured.
            order: The current order task.
            matches_item_type: Whether cancel_desc matches a known item type.
            matches_item_in_order: Whether cancel_desc matches an item name in order.

        Returns:
            StateMachineResult if modifier was removed, None to continue with
            other checks.
        """
        # Check if this is a modifier removal on the current item being configured
        # Use unified modifier_operations for consistent handling
        # But SKIP if cancel_desc matches an item type or item in order (user wants to remove items, not modifiers)
        if isinstance(current_item, MenuItemTask) and not matches_item_type and not matches_item_in_order:
            # Extract leading quantity from cancel_desc (e.g., "1 shot" -> (1, "shot"))
            # This enables quantity-aware removal: "remove 1 shot" decrements by 1
            removal_qty, modifier_term = extract_leading_quantity(cancel_desc)
            # If no quantity found, use the full cancel_desc for matching
            if removal_qty is None:
                modifier_term = cancel_desc

            try:
                modifier_match = find_modifier_match(current_item, modifier_term)
                # If direct match fails, resolve via ingredient DB lookup
                # (e.g., "jalapeno spread" → "Jalapeno Cream Cheese" → match on item)
                if not modifier_match:
                    ingredient_matches = menu_cache.find_matching_ingredients(modifier_term)
                    if len(ingredient_matches) == 1:
                        resolved_name = ingredient_matches[0].get("slug", "").replace("_", " ")
                        if resolved_name:
                            modifier_match = find_modifier_match(current_item, resolved_name)
                if modifier_match:
                    removal_result = remove_modifier_from_item(
                        current_item, modifier_match, quantity=removal_qty
                    )
                    if removal_result.success:
                        # Recalculate price after modifier removal/decrement
                        safe_recalculate_price(
                            self.pricing, current_item, "after modifier removal during config"
                        )

                        removed_modifier_name = format_slug_for_display(removal_result.removed_value or modifier_term)
                        logger.info(
                            "Modifier removal during config: removed '%s' (qty=%s) from %s",
                            removed_modifier_name, removal_qty, current_item.menu_item_name
                        )

                        updated_summary = current_item.get_summary()
                        return self._config_removal_response(
                            removal_result.message, order, current_item,
                            f"{removal_result.message} Your {current_item.menu_item_name} is now {updated_summary}. Anything else?",
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

                    for sel in current_item.selections:
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
                        # Recalculate price after modifier removal
                        safe_recalculate_price(
                            self.pricing, current_item, "after modifier removal during config (fallback)"
                        )
                        logger.info(
                            "Modifier removal during config (fallback): removed '%s' from %s",
                            removed_modifier_name, current_item.menu_item_name
                        )
                        updated_summary = current_item.get_summary()
                        return self._config_removal_response(
                            f"OK, I've removed the {removed_modifier_name}.",
                            order, current_item,
                            f"OK, I've removed the {removed_modifier_name}. Your {current_item.menu_item_name} is now {updated_summary}. Anything else?",
                        )

        return None

    def _find_and_remove_matching_items(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Search for and remove matching items from the order.

        Handles ordinal references ("second bagel"), plural removal ("coffees"),
        category mapping, and item name/type/summary matching. This is the final
        fallback -- it always returns a StateMachineResult.

        Args:
            cancel_desc: Normalized cancellation description from user input.
            current_item: The item currently being configured.
            order: The current order task.

        Returns:
            StateMachineResult indicating items were removed or not found.
        """
        # Get all active items to search through
        active_items, error = check_has_active_items(order)
        if error:
            order.clear_pending()
            return error

        # First, check for ordinal reference (e.g., "second bagel", "3rd coffee")
        ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_desc)

        if ordinal_index is not None and item_type_keyword:
            # User wants to remove a specific Nth item
            result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
            if result:
                item_to_remove, _ = result
                removed_name = item_to_remove.get_summary()
                remove_item_from_order(order, item_to_remove)

                # Clear pending state since we're leaving config phase
                order.clear_pending()
                order.set_phase(OrderPhase.TAKING_ITEMS)

                logger.info(
                    "Removed %s #%d during config: %s",
                    item_type_keyword, ordinal_index, removed_name
                )

                return build_removal_response(
                    order, removed_name, self._configure_next_incomplete_item
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

        # For singular removal during config, prioritize the item being configured.
        # When user says "remove the bagel" while configuring an Onion Bagel, they
        # most likely mean the one they're actively configuring, not a different bagel.
        if not is_plural and current_item and _item_matches(
            current_item, cancel_variants, cancel_desc, mapped_item_type
        ):
            items_to_remove.append(current_item)
        else:
            for item in active_items:
                if _item_matches(item, cancel_variants, cancel_desc, mapped_item_type):
                    items_to_remove.append(item)
                    if not is_plural:
                        break

        if items_to_remove:
            # Remove the items
            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                remove_item_from_order(order, item)

            # Clear pending state since we're leaving config phase
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            logger.info("Removed %d item(s) during config: %s", len(removed_names), removed_names)

            if len(removed_names) == 1:
                return build_removal_response(
                    order, removed_names[0], self._configure_next_incomplete_item
                )

            # Multiple items removed - custom message format
            removed_str = f"the {len(removed_names)} {singular_desc}s"
            remaining = order.items.get_active_items()
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

    def _config_removal_response(
        self,
        removal_msg: str,
        order: OrderTask,
        config_item: MenuItemTask,
        fallback_msg: str,
    ) -> StateMachineResult:
        """Build a response after removing an attribute/modifier during configuration.

        If there's a pending config question, appends it to the removal message.
        Otherwise falls back to the provided fallback message.

        Args:
            removal_msg: The removal acknowledgment (e.g., "OK, I've removed the lox.").
            order: The current order task.
            config_item: The item being configured (used to find the next question).
            fallback_msg: Message to use if no config question is pending.
        """
        question = self._get_current_config_question(order, config_item)
        if question:
            return StateMachineResult(message=f"{removal_msg} {question}", order=order)
        return StateMachineResult(message=fallback_msg, order=order)
