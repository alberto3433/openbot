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
from .parsers.intent_patterns import parse_can_you_make_it, strip_conversational_fillers
from .checkout_messages import got_it_anything_else, modifier_not_available_for_item
from .pending_fields import PendingField
from .modifier_change_handler import ChangeRequest
from .parsers.quantity_utils import extract_leading_quantity
from orderbot.cache import menu_cache
from .utils.pricing_utils import safe_recalculate_price
from .utils.option_matcher import OptionMatcher
from .config.attribute_resolver import get_unanswered_mandatory

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)

# Pattern to detect "add modifier" requests during config
# Matches: "add X", "also add X", "can you add X", "could you add X", "please add X",
#           "with X", "also with X"
ADD_MODIFIER_PREFIXES = [
    r"(?:also\s+)?add\s+",
    r"(?:can|could)\s+you\s+add\s+",
    r"please\s+add\s+",
    r"(?:also\s+)?with\s+",
]
ADD_MODIFIER_PATTERN = re.compile(
    r"^(?:" + "|".join(ADD_MODIFIER_PREFIXES) + r")",
    re.IGNORECASE
)

# Pattern for "I'd like X on that" style phrases where modifier is in the middle
# Captures the modifier term in group 1
ADD_MODIFIER_MIDDLE_PATTERN = re.compile(
    r"^(?:"
    r"i'?d\s+like\s+(.+?)\s+on\s+(?:that|it|this|there)"
    r"|i\s+want\s+(.+?)\s+on\s+(?:that|it|this|there)"
    r"|(?:put|throw)\s+(?:some\s+)?(.+?)\s+on\s+(?:that|it|this|there)"
    r"|(?:can|could)\s+(?:you\s+)?(?:put|throw)\s+(?:some\s+)?(.+?)\s+on\s+(?:that|it|this|there)"
    r")(?:\s+(?:please|thanks|thank\s+you))?$",
    re.IGNORECASE
)


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
        result = self._try_match_attribute_option(modifier_lower, item, order)
        if result:
            return result

        # 1b. Try to match weight/priced attribute options via database aliases
        result = self._try_resolve_priced_attribute(modifier_lower, item, order)
        if result:
            return result

        # 1c. Check for same-type menu items matching this modifier
        # e.g., "make it blueberry" while configuring "Truffle Cream Cheese" (type: spread)
        # should find "Blueberry Cream Cheese" and "Lemon Blueberry Cream Cheese"
        if self.item_adder_handler and self.item_adder_handler.menu_lookup:
            same_type_matches = self._find_same_type_menu_items(
                modifier, item
            )
            if len(same_type_matches) == 1:
                # Single match - remove current item and add the new one
                match_item = same_type_matches[0]
                logger.info(
                    "CAN_YOU_MAKE_IT: Found same-type item '%s', replacing '%s'",
                    match_item.get("name"), item.menu_item_name
                )
                from .handler_utils import remove_item_from_order
                remove_item_from_order(order, item)
                order.clear_pending()
                return self.item_adder_handler.add_menu_item(
                    match_item.get("name", "item"),
                    order=order,
                    quantity=item.quantity,
                )
            elif len(same_type_matches) > 1:
                # Multiple matches - start disambiguation
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

    def _try_match_attribute_option(
        self,
        modifier_lower: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check if the modifier matches an attribute option on the current item.

        Iterates over all item type attributes and their options, checking slug,
        display_name, and aliases. If a match is found, applies the option and
        returns the appropriate result to continue configuration.

        Args:
            modifier_lower: The modifier text, lowercased.
            item: The item being configured.
            order: The current order state.

        Returns:
            StateMachineResult if an attribute option was matched and applied,
            None if no match was found.
        """
        item_type = item.menu_item_type
        if not item_type:
            return None
        try:
            attrs = menu_cache.get_item_type_attributes(item_type)
            for attr_slug, attr_config in attrs.items():
                options = attr_config.get("options", [])
                for opt in options:
                    opt_slug = opt.get("slug", "").lower()
                    opt_display = opt.get("display_name", "").lower()
                    # Also check aliases (e.g., "pound" -> "one_pound")
                    aliases = opt.get("aliases") or []
                    alias_list = [a.strip().lower() for a in aliases] if aliases else []
                    if modifier_lower == opt_slug or modifier_lower == opt_display or modifier_lower in alias_list:
                        # Found matching attribute option - apply it
                        logger.info("CAN_YOU_MAKE_IT: Found matching attr %s=%s", attr_slug, opt_slug)
                        item[attr_slug] = opt.get("slug")
                        # Recalculate price after attribute change
                        pricing = self._taking_items_handler.pricing if self._taking_items_handler else None
                        safe_recalculate_price(pricing, item, "after attribute change")
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

        Args:
            modifier_lower: The modifier text, lowercased.
            item: The item being configured.
            order: The current order state.

        Returns:
            StateMachineResult if a priced attribute was resolved and applied,
            None if not applicable.
        """
        if not item.menu_item_type:
            return None
        item_type = item.menu_item_type
        # Get priced attribute, fallback to "weight" for by-weight items
        priced_attr = menu_cache.get_first_priced_attribute(item_type)
        if not priced_attr:
            # Check if this item type has a weight attribute
            attrs = menu_cache.get_item_type_attributes(item_type)
            if "weight" in attrs:
                priced_attr = "weight"
        if not priced_attr:
            return None
        # Special handling for "half a pound" / "half pound" / "1/2 lb"
        # These map to 2x quarter pound (1/4 lb) - same logic as by_pound_parsing.py
        half_pound_pattern = re.compile(
            r"^(?:a\s+)?half\s+(?:a\s+)?(?:pound|lb)s?$|^1\s*/\s*2\s*(?:pound|lb)s?$",
            re.IGNORECASE
        )
        if half_pound_pattern.match(modifier_lower.strip()):
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
                pricing = self._taking_items_handler.pricing if self._taking_items_handler else None
                safe_recalculate_price(pricing, item, "after half pound")
                # If this answers the current pending question, clear it
                pending = order.pending_field
                if pending and ":" in pending:
                    _, pending_attr = pending.split(":", 1)
                    if pending_attr == priced_attr:
                        order.pending_field = None
                return self._continue_config_with_message(
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
            pricing = self._taking_items_handler.pricing if self._taking_items_handler else None
            safe_recalculate_price(pricing, item, "after weight change")
            opt_name = option.get("display_name") or opt_slug.replace("_", " ").title()
            # If this answers the current pending question, clear it so we move to next
            pending = order.pending_field
            if pending and ":" in pending:
                _, pending_attr = pending.split(":", 1)
                if pending_attr == priced_attr:
                    order.pending_field = None
            return self._continue_config_with_message(
                f"Okay, {opt_name}.", item, order
            )
        return None

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
        modifier_text, target_item, explicit_target = self._extract_add_modifier_text(
            user_input, item, order,
        )
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

        # Apply each modifier to the current item (or redirected target)
        original_config_item = item  # Track original for acknowledgment messages
        added_names: list[str] = []
        modified_items: set[str] = set()
        for term in modifier_terms:
            result = self._process_single_modifier_term(
                term, target_item, original_config_item, order,
                explicit_target, added_names, modified_items,
            )
            if result:
                return result

        if not added_names:
            return None

        # Recalculate price for all items that received modifiers
        pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
        for order_item in order.items.items:
            if isinstance(order_item, MenuItemTask) and order_item.id in modified_items:
                safe_recalculate_price(pricing, order_item, "after adding modifiers")

        # Build acknowledgment message
        from .utils.text import format_english_list
        added_text = format_english_list(added_names)
        message = f"Sure, I've added {added_text}."

        # Always continue config for the original item being configured
        return self._continue_config_with_message(message, original_config_item, order)

    def _extract_add_modifier_text(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> tuple[str | None, MenuItemTask, bool]:
        """Extract modifier text from an 'add X' user input.

        Strips conversational fillers, checks for ADD_MODIFIER_PATTERN and
        ADD_MODIFIER_MIDDLE_PATTERN matches, and handles item-targeting
        suffixes (e.g., "add bacon to the bagel").

        Args:
            user_input: The user's raw input text.
            item: The item currently being configured.
            order: The current order state.

        Returns:
            A tuple of (modifier_text, target_item, explicit_target) where:
                modifier_text: The extracted modifier string, or None if no
                    add pattern matched.
                target_item: The item to add modifiers to (may differ from
                    ``item`` if user specified a target like "to the bagel").
                explicit_target: True if the user explicitly named a target item.
        """
        user_stripped = strip_conversational_fillers(user_input.strip())
        user_lower = user_stripped.lower()

        logger.info("ADD_DURING_CONFIG: Checking input '%s'", user_stripped[:50])

        modifier_text = None
        explicit_target = False

        # Check for add modifier patterns: "add X", "also add X", "can you add X", etc.
        match = ADD_MODIFIER_PATTERN.match(user_lower)
        if match:
            # Extract the modifier text after the matched prefix
            modifier_text = user_lower[match.end():].strip()
            # Remove trailing "please", "thanks"
            modifier_text = re.sub(r"\s*(please|thanks|thank you)$", "", modifier_text).strip()
            # Strip pronoun-targeting suffixes: "to that", "on it", "to this", "on there"
            # During CONFIGURING_ITEM, pronouns refer to the current item (self-referential),
            # so we just strip them. Named targets ("to the bagel") are handled below.
            modifier_text = re.sub(
                r"\s+(?:to|on|for)\s+(?:that|it|this|there)$",
                "",
                modifier_text,
            ).strip()
            # Strip item-targeting suffix: "to the Sausage Egg and Cheese Sandwich"
            # and redirect the modifier to the targeted item
            target_prepositions = (" to the ", " on the ", " for the ",
                                   " to my ", " on my ", " for my ")
            for prep in target_prepositions:
                prep_idx = modifier_text.find(prep)
                if prep_idx != -1:
                    suffix = modifier_text[prep_idx + len(prep):].strip()
                    matched_item = self._find_target_item_by_suffix(suffix, order)
                    if matched_item:
                        modifier_text = modifier_text[:prep_idx].strip()
                        item = matched_item
                        explicit_target = True
                    break
        else:
            # Check for "I'd like X on that" style patterns
            middle_match = ADD_MODIFIER_MIDDLE_PATTERN.match(user_lower)
            if middle_match:
                # Find the first non-None group (different patterns capture in different groups)
                modifier_text = next(
                    (g for g in middle_match.groups() if g is not None), None
                )
                if modifier_text:
                    logger.debug(
                        "ADD_DURING_CONFIG: Matched middle pattern, modifier='%s'",
                        modifier_text
                    )

        if not modifier_text:
            logger.debug("ADD_DURING_CONFIG: Input doesn't match add pattern, skipping")
            return (None, item, False)

        return (modifier_text, item, explicit_target)

    def _process_single_modifier_term(
        self,
        term: str,
        item: MenuItemTask,
        original_config_item: MenuItemTask,
        order: OrderTask,
        explicit_target: bool,
        added_names: list[str],
        modified_items: set[str],
    ) -> StateMachineResult | None:
        """Process a single modifier term during add-modifier-during-config.

        Looks up the term as an ingredient, checks if it is an attribute answer,
        validates it for the target item type, and either adds it as a selection
        or returns a result requiring user interaction (disambiguation, attribute
        option selection).

        Mutates ``added_names`` and ``modified_items`` in place when a modifier
        is successfully added.

        Args:
            term: A single modifier term (e.g., "bacon", "two eggs").
            item: The target item to add modifiers to.
            original_config_item: The item originally being configured (used for
                acknowledgment messages when modifiers are redirected).
            order: The current order state.
            explicit_target: True if the user explicitly named a target item.
            added_names: Accumulator list of added modifier display names.
            modified_items: Accumulator set of item IDs that received modifiers.

        Returns:
            StateMachineResult if processing should stop (disambiguation, attribute
            answer, selection flow), None to continue with the next term.
        """
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
            ingredient_slug = match["slug"]

            # Check if ingredient is actually an answer to the pending attribute question.
            # When the ingredient's category matches the pending attribute slug, the user
            # is answering the config question with "add X" phrasing (e.g., "add whole
            # wheat everything flatz to that" when asked about bread).
            pending_attr = None
            if order.pending_field and ":" in order.pending_field:
                _, pending_attr = order.pending_field.split(":", 1)

            if pending_attr and match.get("category") == pending_attr:
                # Treat as attribute answer: replace the default and advance config
                # (mirrors select_input.py:619-620 pattern)
                # Resolve through OptionMatcher to get the canonical option slug,
                # which may differ from the ingredient slug (e.g. after slug
                # renames).  This ensures pricing lookups find the right option.
                resolved_slug = ingredient_slug
                resolved_display = match.get("name")
                attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
                options = attrs.get(pending_attr, {}).get("options", [])
                if options:
                    matcher = OptionMatcher()
                    matched_opt, _ = matcher.match_single(search_term, options)
                    if not matched_opt:
                        matched_opt, _ = matcher.match_single(
                            match.get("name", ""), options
                        )
                    if matched_opt:
                        resolved_slug = matched_opt["slug"]
                        resolved_display = (
                            matched_opt.get("display_name") or resolved_display
                        )
                item.remove_selection(pending_attr)
                item.add_selection(
                    slug=resolved_slug,
                    category=pending_attr,
                    display_name=resolved_display,
                )
                # Recalculate price
                pricing = (
                    self.modifier_change_handler.pricing
                    if self.modifier_change_handler else None
                )
                safe_recalculate_price(pricing, item, "after setting attribute via add")
                # Advance pending_field to next unanswered mandatory attribute
                unanswered = get_unanswered_mandatory(item, item.menu_item_type)
                if unanswered:
                    order.pending_field = (
                        f"{item.menu_item_type}:{unanswered[0]['slug']}"
                    )
                else:
                    order.pending_field = None
                message = f"Got it, {match.get('name', ingredient_slug)}."
                return self._continue_config_with_message(
                    message, original_config_item, order
                )

            # FIRST: Check if ingredient slug matches an attribute with multiple options
            # This handles generic ingredients like "egg" that map to style choices
            # (scrambled, fried, etc.). We check this BEFORE ingredient validation
            # because "egg" may not be a valid ingredient for bagels, but "egg" IS
            # a valid attribute with options (scrambled, fried, etc.)
            attrs = menu_cache.get_item_type_attributes(item.menu_item_type)
            attr_config = attrs.get(ingredient_slug, {})
            options = attr_config.get("options", [])

            # Only trigger selection if ingredient slug matches attribute slug
            # AND that attribute has multiple options
            if options and len(options) > 1:
                # Check if item already has a value for this attribute
                existing_value = item.attribute_values.get(ingredient_slug)
                is_additive = existing_value is not None
                logger.info(
                    "ADD_DURING_CONFIG: Ingredient '%s' matches attribute '%s' with %d options (qty=%d, additive=%s), starting selection",
                    match["name"], ingredient_slug, len(options), quantity, is_additive
                )
                # Store quantity for when user selects an option
                order.pending_modifier_quantity = quantity
                # Mark as additive if item already has this attribute set
                order.pending_modifier_is_additive = is_additive
                return self._start_attribute_option_selection(
                    ingredient_slug, attr_config, options, item, order
                )

            # SECOND: Validate modifier is allowed for this item type
            target_item = item
            is_valid = menu_cache.is_valid_modifier_for_item_type(
                ingredient_slug, item.menu_item_type
            )

            if not is_valid:
                if explicit_target:
                    # User explicitly named this item — reject
                    msg = modifier_not_available_for_item(
                        match["name"], item.get_display_name()
                    )
                    return self._continue_config_with_message(
                        msg, original_config_item, order
                    )
                # No explicit target — try to auto-redirect
                alt = self._find_item_accepting_modifier(
                    ingredient_slug, item, order
                )
                if alt:
                    target_item = alt
                    logger.info(
                        "ADD_DURING_CONFIG: Redirecting '%s' from %s to %s",
                        match["name"],
                        item.get_display_name(),
                        alt.get_display_name(),
                    )
                else:
                    # No item in order accepts this modifier — reject
                    msg = modifier_not_available_for_item(
                        match["name"], item.get_display_name()
                    )
                    return self._continue_config_with_message(
                        msg, original_config_item, order
                    )

            target_item.add_selection(
                slug=match["slug"],
                category=match["category"],
                display_name=match["name"],
                quantity=quantity,
                price=match.get("base_price", 0.0),
                increment_if_exists=True,
            )
            modified_items.add(target_item.id)
            # Track name + whether it was redirected
            if target_item is not item or item is not original_config_item:
                added_names.append(
                    f"{match['name']} to your {target_item.get_display_name()}"
                )
            else:
                added_names.append(match["name"])
            logger.info(
                "ADD_DURING_CONFIG: Added '%s' (category=%s, qty=%d) to %s",
                match["name"], match["category"], quantity,
                target_item.get_display_name(),
            )
        elif len(matches) > 1:
            # Multiple matches - start disambiguation for this modifier
            logger.info(
                "ADD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation",
                term
            )
            return self._start_modifier_disambiguation(term, matches, item, order)
        else:
            # No match found - don't add fake modifiers
            # Note: modifier_to_category may have an alias entry, but if
            # find_matching_ingredients returned 0, it means must_match filter
            # excluded it (e.g., "plain spread" requires "cream cheese" in input)
            logger.warning(
                "ADD_DURING_CONFIG: Could not find modifier '%s' in database",
                search_term
            )

        return None

    def handle_cross_attribute_match(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Check if user input matches an option from a DIFFERENT attribute than the pending one.

        When asked "What kind of cheese?" and the user says "veggie cream cheese",
        this detects that the input matches a spread option (not a cheese option)
        and applies it to the spread attribute, then re-asks the cheese question.

        Uses exact_only matching to avoid false partial matches on unrelated attributes.
        Aliases (e.g., "veggie cc") are handled by OptionMatcher Phase 0/1.

        Args:
            user_input: The user's input text
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if a cross-attribute match was found and applied,
            None if no match or multiple attributes matched (fall through).
        """
        pending_field = order.pending_field
        if not pending_field or ":" not in pending_field:
            return None

        item_type = item.menu_item_type
        if not item_type:
            return None

        _, pending_attr = pending_field.split(":", 1)

        try:
            all_attrs = menu_cache.get_item_type_attributes(item_type)
        except Exception:
            return None

        matcher = OptionMatcher()
        matched_attr_slug: str | None = None
        matched_option: dict | None = None

        for attr_slug, attr_config in all_attrs.items():
            # Skip the pending attribute (that's handled by the normal flow)
            if attr_slug == pending_attr:
                continue

            options = attr_config.get("options", [])
            if not options:
                continue

            match, _ = matcher.match_single(user_input, options, exact_only=True)
            if match:
                if matched_attr_slug is not None:
                    # Multiple attributes matched — ambiguous, bail out
                    logger.debug(
                        "CROSS_ATTR: Multiple attributes matched for '%s' (%s and %s), skipping",
                        user_input, matched_attr_slug, attr_slug,
                    )
                    return None
                matched_attr_slug = attr_slug
                matched_option = match

        if not matched_attr_slug or not matched_option:
            return None

        # Apply the matched option to the correct attribute
        # Use item[attr] = value (not add_selection) so existing selections are replaced
        display_name = matched_option.get("display_name") or matched_option["slug"].replace("_", " ").title()
        item[matched_attr_slug] = matched_option["slug"]

        # Recalculate price
        pricing = self._taking_items_handler.pricing if self._taking_items_handler else None
        safe_recalculate_price(pricing, item, "after cross-attribute match")

        logger.info(
            "CROSS_ATTR: Matched '%s' to %s=%s (pending was %s)",
            user_input, matched_attr_slug, matched_option["slug"], pending_attr,
        )

        return self._continue_config_with_message(
            f"Got it, {display_name}.", item, order
        )

    def handle_add_item_during_config(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        require_prefix: bool = True,
    ) -> StateMachineResult | None:
        """Handle adding new items during configuration (e.g., 'and a latte').

        When a user says "and a Blueberry Cream Cheese Sandwich" while being asked
        about bread for their Cheesesteak, we should:
        1. Detect the ordering prefix ("and a")
        2. Parse the item portion using existing parse_open_input_deterministic
        3. Add the new item(s) and queue them for later configuration
        4. Restore the original config state and re-ask the current question

        Args:
            user_input: The user's input (e.g., "and a latte", "also two bagels")
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if new items were added, None if not an add-item pattern
        """
        from .parsers.intent_patterns import ADD_ITEM_DURING_CONFIG_PREFIX
        from .parsers import parse_open_input_deterministic
        from .parsed_item_processor import ParsedItemProcessor
        from .models import TaskStatus
        from .utils.text import format_english_list

        # Step 1: Try prefix match on raw input first (preserves "also" before filler stripping)
        # e.g., "Can I also get a Chai Tea" — "also" would be stripped by filler removal
        raw_input = user_input.strip()
        prefix_match = ADD_ITEM_DURING_CONFIG_PREFIX.match(raw_input)
        if prefix_match:
            item_text = raw_input[prefix_match.end():].strip()
        else:
            # Step 2: Fall back to stripped input for cases like "um and a latte"
            cleaned_input = strip_conversational_fillers(raw_input)
            prefix_match = ADD_ITEM_DURING_CONFIG_PREFIX.match(cleaned_input)
            if not prefix_match:
                if require_prefix:
                    return None
                # No prefix — parse full input as item text
                item_text = cleaned_input
            else:
                item_text = cleaned_input[prefix_match.end():].strip()

        # Step 3: Strip conversational fillers from item text after prefix removal
        # e.g., "Also hmm add tofu scallion" -> prefix strips "Also " -> "hmm add tofu scallion"
        # -> strip fillers -> "add tofu scallion"
        item_text = strip_conversational_fillers(item_text)

        # Validate item text is non-empty
        if not item_text:
            return None

        logger.info(
            "ADD_ITEM_DURING_CONFIG: Detected prefix, parsing item text: '%s'",
            item_text[:50]
        )

        parsed = parse_open_input_deterministic(item_text)
        if not parsed or not parsed.parsed_items:
            logger.debug("ADD_ITEM_DURING_CONFIG: No items parsed from '%s'", item_text[:50])
            return None

        logger.info(
            "ADD_ITEM_DURING_CONFIG: Parsed %d item(s): %s",
            len(parsed.parsed_items),
            [p.item_name or p.item_type for p in parsed.parsed_items]
        )

        # Step 3: Save current config state - we need to restore this after adding items
        # because process_items() will change pending_field/pending_item_id to the new item
        original_pending_field = order.pending_field
        original_pending_item_id = order.pending_item_id
        current_item_name = item.get_display_name()

        # Step 4: Use ParsedItemProcessor to add items (reuse existing logic)
        processor = ParsedItemProcessor(
            item_adder_handler=self.item_adder_handler,
            pricing=self._taking_items_handler.pricing if self._taking_items_handler else None,
        )

        # Track items added for the acknowledgment message
        items_before = len(order.items.items)

        # Process items - this handles adding, queuing for config, pricing, etc.
        result = processor.process_items(parsed, order)

        items_after = len(order.items.items)
        items_added = items_after - items_before

        if items_added == 0:
            # No items were added (possibly disambiguation needed)
            # Return the result from process_items if it has a message
            if result and result.message:
                return result
            return None

        # Step 5: Queue ALL new items for later configuration and restore original config state
        # process_items() starts configuring the first new item, but we want to continue
        # configuring the ORIGINAL item (The Cheesesteak), not the new one (Blueberry Sandwich)
        new_items = order.items.items[items_before:]
        for new_item in new_items:
            if new_item.status == TaskStatus.IN_PROGRESS:
                # Queue for later configuration
                order.queue_item_for_config(
                    new_item.id,
                    new_item.menu_item_type,
                    item_name=new_item.get_display_name()
                )
                logger.info(
                    "ADD_ITEM_DURING_CONFIG: Queued %s (%s) for later config",
                    new_item.get_display_name(), new_item.id[:8]
                )

        # Restore original config state so we continue with the original item
        order.pending_field = original_pending_field
        order.pending_item_id = original_pending_item_id

        # Step 6: Build response acknowledging addition + re-ask current question
        added_names = [p.item_name or p.item_type for p in parsed.parsed_items]
        current_question = self.config_helper_handler.get_current_config_question(order, item)

        # Format the added items
        added_text = format_english_list(added_names)

        if current_question:
            message = f"Got it, I've added {added_text}. Now, for your {current_item_name}, {current_question.lower()}"
        else:
            message = f"Got it, I've added {added_text}."

        logger.info(
            "ADD_ITEM_DURING_CONFIG: Added %d item(s), continuing config for %s",
            items_added, current_item_name
        )

        return StateMachineResult(message=message, order=order)

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
        pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
        safe_recalculate_price(pricing, item, "after ingredient match")

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

    def _find_target_item_by_suffix(
        self,
        suffix: str,
        order: OrderTask,
    ) -> MenuItemTask | None:
        """Find an order item matching a target description flexibly.

        Supports exact match, suffix on word boundary, substring, and category
        reference (e.g. "the bagel" when only one bagel in order). Mirrors the
        matching logic in item_modification_handler._find_target_item().

        Args:
            suffix: The target description extracted after "to the …" / "on the …"
            order: The current order state

        Returns:
            The matching MenuItemTask, or None if no match.
        """
        suffix_lower = suffix.lower().strip()
        menu_items = [i for i in order.items.items if isinstance(i, MenuItemTask)]

        # 1. Exact match on menu_item_name
        for it in menu_items:
            if it.menu_item_name and it.menu_item_name.lower() == suffix_lower:
                return it

        # 2. Suffix / substring match on word boundary
        for it in menu_items:
            name_lower = (it.menu_item_name or "").lower()
            if not name_lower:
                continue
            # "latte" matches "Iced Latte" (suffix on word boundary)
            if name_lower.endswith(suffix_lower) and (
                len(name_lower) == len(suffix_lower)
                or name_lower[-(len(suffix_lower) + 1)] == " "
            ):
                return it
            # substring: "latte" in "iced latte"
            if suffix_lower in name_lower:
                return it

        # 3. Category reference: "the bagel" -> only bagel-type item in order
        target_category = menu_cache.is_category_reference(suffix_lower)
        if target_category:
            matching = [i for i in menu_items if i.menu_item_type == target_category]
            if len(matching) == 1:
                return matching[0]

        return None

    def _find_item_accepting_modifier(
        self,
        modifier_slug: str,
        exclude_item: MenuItemTask,
        order: OrderTask,
    ) -> MenuItemTask | None:
        """Find exactly one other item in the order that accepts a modifier.

        Used for auto-redirect when user says "add vanilla syrup" during bagel
        config — vanilla isn't valid for bagel, but the latte in the order accepts it.

        Args:
            modifier_slug: The ingredient slug to check validity for.
            exclude_item: The item to skip (current config item).
            order: The current order state.

        Returns:
            The single matching MenuItemTask, or None if zero or 2+ candidates.
        """
        candidates = []
        for it in order.items.items:
            if not isinstance(it, MenuItemTask):
                continue
            if it.id == exclude_item.id:
                continue
            if it.menu_item_type and menu_cache.is_valid_modifier_for_item_type(
                modifier_slug, it.menu_item_type
            ):
                candidates.append(it)
        return candidates[0] if len(candidates) == 1 else None

    def _find_same_type_menu_items(
        self,
        modifier: str,
        current_item: MenuItemTask,
    ) -> list[dict]:
        """Find menu items matching the modifier that share the same item type.

        Used by handle_can_you_make_it() to detect when "make it blueberry"
        should switch to a different menu item of the same type rather than
        adding an ingredient modifier.

        Args:
            modifier: The modifier text from the user (e.g., "blueberry")
            current_item: The item currently being configured

        Returns:
            List of matching menu item dicts (same type, excluding current item)
        """
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
