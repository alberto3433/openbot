"""
Config Modification Handler for Order State Machine.

Handles "can you make it X?" requests and item switch confirmations
during item configuration.
Split from the original monolithic handler; bundle modifications and
modifier additions are now in separate handler modules.
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .models.pending_states import PendingSwitchItem
from .parsers.constants import HALF_POUND_PATTERN
from .schemas import StateMachineResult, OrderPhase
from .parsers.intent_patterns import parse_can_you_make_it
from .checkout_messages import got_it_anything_else
from .pending_fields import PendingField
from .parsers.quantity_utils import extract_leading_quantity
from orderbot.cache import menu_cache
from .utils.pricing_utils import safe_recalculate_price
from .models.utilities import parse_pending_field
from .config_flow_utils import (
    continue_config_with_message as _continue_config,
    start_modifier_disambiguation as _start_disambig,
    replace_or_add_modifier as _replace_or_add,
    apply_attribute_option_to_item as _apply_attr_option,
    get_handler_pricing as _get_handler_pricing,
)

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)


class ConfigModificationHandler:
    """
    Handles "can you make it X?" modifications and item switch confirmations
    during item configuration.
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

    # ─── Group 1: "Can You Make It?" ─────────────────────────────────

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

        # Extract quantity from modifier text (e.g., "two splendas" → qty=2, "splendas")
        quantity, modifier_stripped = extract_leading_quantity(modifier)
        if modifier_stripped:
            modifier = modifier_stripped
        if quantity is None:
            quantity = 1

        logger.info(
            "CAN_YOU_MAKE_IT: Detected modifier request '%s' (qty=%d) for %s",
            modifier, quantity, item.menu_item_name,
        )
        modifier_lower = modifier.lower()

        # 1. Check if current item has an attribute option matching this modifier
        result = self._try_match_attribute_option(modifier_lower, item, order, quantity=quantity)
        if result:
            return result

        # 1b. Try to match weight/priced attribute options via database aliases
        result = self._try_resolve_priced_attribute(modifier_lower, item, order)
        if result:
            return result

        # 1c. Check for same-type menu items matching this modifier
        result = self._try_replace_with_same_type_item(modifier, item, order)
        if result:
            return result

        # 1d. Check for ANY menu item matching (cross-type replacement)
        # Skip when in active attribute config and modifier is a known attribute option
        # (e.g., "black" is a coffee style option — don't search for cookies/drinks)
        if order.pending_field and ":" in order.pending_field:
            is_known, _ = menu_cache.is_known_attribute_option(modifier_lower)
            if is_known:
                logger.info(
                    "CAN_YOU_MAKE_IT: '%s' is a known attribute option during "
                    "attribute config — deferring to attribute handler",
                    modifier_lower,
                )
                return None
        result = self._try_replace_with_any_menu_item(modifier, item, order)
        if result:
            return result

        # 2. Check if it's an ingredient/modifier (spread, topping, syrup, etc.)
        result = self._try_match_ingredient(modifier, modifier_lower, item, order, quantity=quantity)
        if result:
            return result

        # 3. Search for similar menu item with the modifier
        result = self._try_offer_similar_item(modifier, item, order)
        if result:
            return result

        # 4. Not found
        logger.info("CAN_YOU_MAKE_IT: No matching attribute, ingredient, or similar item found for '%s'", modifier)

        # If we're in an attribute config context (pending_field is item_type:attr_slug),
        # return None to let the attribute handler process it. The attribute handler can do
        # more sophisticated matching (normalization, partial matching) and will show
        # available options if no match is found — a better UX than "Sorry, we don't have that option".
        if order.pending_field and ":" in order.pending_field:
            logger.debug(
                "CAN_YOU_MAKE_IT: Deferring to attribute handler for pending_field=%s",
                order.pending_field,
            )
            return None

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

    def _apply_attribute_option_to_item(self, modifier_lower: str, item: MenuItemTask) -> str | None:
        return _apply_attr_option(modifier_lower, item)

    def _try_match_attribute_option(
        self,
        modifier_lower: str,
        item: MenuItemTask,
        order: OrderTask,
        quantity: int = 1,
    ) -> StateMachineResult | None:
        """Check if the modifier matches an attribute option on the current item.

        Iterates over all item type attributes and their options, checking slug,
        display_name, and aliases. If a match is found, applies the option and
        returns the appropriate result to continue configuration.

        Args:
            modifier_lower: The modifier text, lowercased.
            item: The item being configured.
            order: The current order state.
            quantity: How many of this modifier (e.g., 2 for "two splendas").

        Returns:
            StateMachineResult if an attribute option was matched and applied,
            None if no match was found.
        """
        from .handler_utils import find_attr_option_match, get_option_display_name

        item_type = item.menu_item_type
        if not item_type:
            return None
        try:
            attrs = menu_cache.get_item_type_attributes(item_type)
            result = find_attr_option_match(modifier_lower, attrs)
            if result:
                attr_slug, opt = result
                opt_slug = opt.get("slug")
                logger.info("CAN_YOU_MAKE_IT: Matched attr %s=%s (qty=%d)", attr_slug, opt_slug, quantity)

                attr_config = attrs.get(attr_slug, {})
                if attr_config.get("input_type") == "multi_select":
                    # For multi_select, replace existing selection with correct quantity
                    item.remove_selection(attr_slug, slug=opt_slug)
                    item.add_selection(
                        slug=opt_slug,
                        category=attr_slug,
                        quantity=quantity,
                        display_name=opt.get("display_name"),
                    )
                else:
                    item[attr_slug] = opt_slug

                pricing = _get_handler_pricing(self)
                safe_recalculate_price(pricing, item, "after attribute change")
                opt_name = get_option_display_name(opt)
                qty_prefix = f"{quantity} " if quantity > 1 else ""
                return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                    f"Sure, {qty_prefix}{opt_name}.", item, order
                )
        except (KeyError, AttributeError) as e:
            logger.debug("Error checking attributes for 'can you make it': %s", e)
        return None

    def _try_resolve_priced_attribute(
        self,
        modifier_lower: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to match the modifier to a weight/priced attribute option via database aliases.

        Handles the special "half a pound" pattern (mapped to 2x quarter pound) and
        direct alias lookup (e.g., "pound" to "1 lb"). Clears pending_field if the
        answer matches the current pending attribute question.
        """
        if not item.menu_item_type:
            return None
        item_type = item.menu_item_type
        # Get priced attribute; fallback to first attribute with priced options
        priced_attr = menu_cache.get_first_priced_attribute(item_type)
        if not priced_attr:
            attrs = menu_cache.get_item_type_attributes(item_type)
            for attr_slug, attr_info in attrs.items():
                options = attr_info.get("options", [])
                if any(opt.get("price_modifier", 0) for opt in options if isinstance(opt, dict)):
                    priced_attr = attr_slug
                    break
        if not priced_attr:
            return None
        # Special handling for "half a pound" / "half pound" / "1/2 lb"
        # These map to 2x quarter pound (1/4 lb) - same logic as by_pound_parsing.py
        if HALF_POUND_PATTERN.match(modifier_lower.strip()):
            # Look up the quarter pound option
            quarter_option = menu_cache.resolve_option_by_alias(priced_attr, "1/4 lb")
            if quarter_option:
                opt_slug = quarter_option.get("slug")
                logger.info(
                    "CAN_YOU_MAKE_IT: Resolved 'half a pound' to %s=%s with qty=2",
                    priced_attr, opt_slug
                )
                item[priced_attr] = opt_slug
                item.quantity = 2  # Two quarter-pound portions = half pound
                pricing = _get_handler_pricing(self)
                safe_recalculate_price(pricing, item, "after half pound")
                # If this answers the current pending question, clear it
                _, pending_attr = parse_pending_field(order.pending_field)
                if pending_attr == priced_attr:
                    order.pending_field = None
                return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                    "Okay, 1/2 lb.", item, order
                )

        # Direct lookup - aliases in DB handle variations like "pound" -> "1 lb"
        option = menu_cache.resolve_option_by_alias(priced_attr, modifier_lower)
        if option:
            opt_slug = option.get("slug")
            logger.info(
                "CAN_YOU_MAKE_IT: Resolved '%s' to %s=%s via alias",
                modifier_lower, priced_attr, opt_slug
            )
            item[priced_attr] = opt_slug
            pricing = _get_handler_pricing(self)
            safe_recalculate_price(pricing, item, "after weight change")
            from .handler_utils import get_option_display_name
            opt_name = get_option_display_name(option)
            # If this answers the current pending question, clear it so we move to next
            _, pending_attr = parse_pending_field(order.pending_field)
            if pending_attr == priced_attr:
                order.pending_field = None
            return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                f"Okay, {opt_name}.", item, order
            )
        return None

    def _try_replace_with_same_type_item(
        self,
        modifier: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to find and replace with a same-type menu item matching the modifier."""
        if not (self.item_adder_handler and self.item_adder_handler.menu_lookup):
            return None

        same_type_matches = self._find_same_type_menu_items(modifier, item)
        if len(same_type_matches) == 1:
            match_item = same_type_matches[0]
            logger.info(
                "CAN_YOU_MAKE_IT: Found same-type item '%s', replacing '%s'",
                match_item.get("name"), item.menu_item_name
            )
            from .handler_utils import remove_item_from_order
            remove_item_from_order(order, item)
            order.clear_pending()
            # Clear stale multi-item config names from the replaced item's add flow
            order.multi_item_config_names = []
            return self.item_adder_handler.add_menu_item(
                match_item.get("name", "item"),
                order=order,
                quantity=item.quantity,
            )
        elif len(same_type_matches) > 1:
            logger.info(
                "CAN_YOU_MAKE_IT: Found %d same-type items for '%s', starting disambiguation",
                len(same_type_matches), modifier
            )
            order.pending_replace_item_id = item.id
            return self.item_adder_handler.disambiguation_handler.start_disambiguation(
                item_name=modifier,
                matching_items=same_type_matches,
                order=order,
                quantity=item.quantity,
                pending_field=PendingField.ITEM_SELECTION,
            )

        return None

    def _try_match_ingredient(
        self,
        modifier: str,
        modifier_lower: str,
        item: MenuItemTask,
        order: OrderTask,
        quantity: int = 1,
    ) -> StateMachineResult | None:
        """Try to match the modifier as an ingredient (spread, topping, syrup, etc.)."""
        matches = menu_cache.find_matching_ingredients(modifier_lower)
        if len(matches) == 1:
            match = matches[0]
            self._replace_or_add_modifier(item, match, quantity=quantity)
            logger.info("CAN_YOU_MAKE_IT: Applied modifier %s (%s) qty=%d", match['name'], match['category'], quantity)
            return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )
        elif len(matches) > 1:
            logger.info("CAN_YOU_MAKE_IT: Multiple matches for '%s', starting disambiguation", modifier)
            return _start_disambig(modifier, matches, item, order)

        return None

    def _try_offer_similar_item(
        self,
        modifier: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Search for a similar menu item with the modifier and offer to switch."""
        if not (self.item_adder_handler and self.item_adder_handler.menu_lookup):
            return None

        similar_item = self.item_adder_handler.menu_lookup.find_similar_item_with_modifier(
            item.menu_item_name or "",
            modifier,
        )
        if not similar_item:
            return None

        logger.info(
            "CAN_YOU_MAKE_IT: Found similar item '%s' for '%s' + '%s'",
            similar_item.get("name"),
            item.menu_item_name,
            modifier,
        )
        order.pending_switch_item = PendingSwitchItem(**similar_item)
        order.pending_field = PendingField.CONFIRM_ITEM_SWITCH
        return StateMachineResult(
            message=(
                f"{item.menu_item_name} isn't available {modifier}, "
                f"but we have {similar_item.get('name')}. Would you like that instead?"
            ),
            order=order,
        )

    def _find_same_type_menu_items(
        self,
        modifier: str,
        current_item: MenuItemTask,
    ) -> list[dict]:
        """Find menu items matching the modifier that share the same item type."""
        lookup = self.item_adder_handler.menu_lookup
        all_matches = lookup.lookup_menu_items(modifier)
        if not all_matches:
            return []

        current_type = current_item.menu_item_type
        current_name = (current_item.menu_item_name or "").lower()

        same_type = [
            m for m in all_matches
            if m.get("item_type") == current_type
            and m.get("name", "").lower() != current_name
        ]
        if same_type:
            logger.debug(
                "CAN_YOU_MAKE_IT: Same-type matches for '%s' (type=%s): %s",
                modifier, current_type,
                [m.get("name") for m in same_type]
            )
        return same_type

    def _try_replace_with_any_menu_item(
        self,
        modifier: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to replace the current item with ANY menu item matching the modifier.

        Unlike _try_replace_with_same_type_item which only considers items of the
        same type, this searches all menu items. Used for cross-type replacement
        (e.g., switching from a turkey sandwich to a Classic BEC during config).

        Args:
            modifier: The user's text describing the replacement item.
            item: The current item being configured.
            order: The current order state.

        Returns:
            StateMachineResult if a replacement was made or disambiguation started,
            None if no matching menu item was found.
        """
        if not (self.item_adder_handler and self.item_adder_handler.menu_lookup):
            return None

        lookup = self.item_adder_handler.menu_lookup

        # Strip leading articles ("a", "an", "the") from the modifier text
        cleaned = re.sub(r'^(?:a|an|the)\s+', '', modifier.strip(), flags=re.IGNORECASE).strip()
        if not cleaned:
            return None

        all_matches = lookup.lookup_menu_items(cleaned)
        if not all_matches:
            return None

        # Exclude the current item from results
        current_name = (item.menu_item_name or "").lower()
        matches = [
            m for m in all_matches
            if m.get("name", "").lower() != current_name
        ]
        if not matches:
            return None

        if len(matches) == 1:
            match_item = matches[0]
            logger.info(
                "CROSS_TYPE_REPLACE: Replacing '%s' with '%s'",
                item.menu_item_name, match_item.get("name"),
            )
            from .handler_utils import remove_item_from_order
            remove_item_from_order(order, item)
            order.clear_pending()
            # Clear stale multi-item config names from the replaced item's add flow
            order.multi_item_config_names = []
            return self.item_adder_handler.add_menu_item(
                match_item.get("name", "item"),
                order=order,
                quantity=item.quantity,
            )
        else:
            logger.info(
                "CROSS_TYPE_REPLACE: Found %d items for '%s', starting disambiguation",
                len(matches), cleaned,
            )
            order.pending_replace_item_id = item.id
            return self.item_adder_handler.disambiguation_handler.start_disambiguation(
                item_name=cleaned,
                matching_items=matches,
                order=order,
                quantity=item.quantity,
                pending_field=PendingField.ITEM_SELECTION,
            )

    # ─── Group 2: Confirm Item Switch ────────────────────────────────

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
            current_item = order.items.get_item_by_id(order.first_pending_item_id)
            if current_item:
                order.items.remove_item(current_item)

            # Clear switch state
            order.pending_switch_item = None
            order.clear_pending()

            # Add the new item via item_adder_handler
            if self.item_adder_handler:
                return self.item_adder_handler.add_menu_item(
                    switch_item.name,
                    order,
                    quantity=1,
                )

            # Fallback - just acknowledge
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=got_it_anything_else(switch_item.name),
                order=order,
            )
        else:
            # User declined - continue with original item
            order.pending_switch_item = None
            # Get the original item and continue configuration
            original_item = order.items.get_item_by_id(order.first_pending_item_id)
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

    # ─── Shared Utilities (delegated to config_flow_utils) ───────────

    def _replace_or_add_modifier(self, item: MenuItemTask, match: dict, quantity: int = 1) -> None:
        pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
        _replace_or_add(item, match, pricing, quantity)
