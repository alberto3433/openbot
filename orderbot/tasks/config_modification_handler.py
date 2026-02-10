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
from .utils.pricing_utils import safe_recalculate_price

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)

# Pattern to detect "add modifier" requests during config
# Matches: "add X", "also add X", "can you add X", "could you add X", "please add X"
ADD_MODIFIER_PREFIXES = [
    r"(?:also\s+)?add\s+",
    r"(?:can|could)\s+you\s+add\s+",
    r"please\s+add\s+",
]
ADD_MODIFIER_PATTERN = re.compile(
    r"^(?:" + "|".join(ADD_MODIFIER_PREFIXES) + r")",
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
        item_type = item.menu_item_type
        if item_type:
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

        # 1b. Try to match weight/priced attribute options via database aliases
        # Aliases like "pound" -> "1 lb" are stored in global_attribute_option_aliases
        if item_type:
            # Get priced attribute, fallback to "weight" for by-weight items
            priced_attr = menu_cache.get_first_priced_attribute(item_type)
            if not priced_attr:
                # Check if this item type has a weight attribute
                attrs = menu_cache.get_item_type_attributes(item_type)
                if "weight" in attrs:
                    priced_attr = "weight"
            if priced_attr:
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

        # Check for add modifier patterns: "add X", "also add X", "can you add X", etc.
        match = ADD_MODIFIER_PATTERN.match(user_lower)
        if not match:
            logger.debug("ADD_DURING_CONFIG: Input doesn't match add pattern, skipping")
            return None

        # Extract the modifier text after the matched prefix
        modifier_text = user_lower[match.end():].strip()
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
        # Pre-fetch modifier→category map once for all terms (avoids repeated lookups in loop)
        modifier_to_category = menu_cache.get_modifier_to_category_map()
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
                ingredient_slug = match["slug"]

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

                # SECOND: Add directly as modifier
                # For explicit "add X" requests, we trust the user's intent.
                # The ingredient exists in our database, so we allow adding it
                # even if it's not pre-configured for this item type.
                item.add_selection(
                    slug=match["slug"],
                    category=match["category"],
                    display_name=match["name"],
                    quantity=quantity,
                    price=match.get("base_price", 0.0),
                    increment_if_exists=True,
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
                # No match found - try category lookup (using pre-fetched map)
                # Use search_term (with quantity stripped) for lookup, not the raw term
                category = modifier_to_category.get(search_term)
                if category:
                    modifier_slug = search_term.replace(" ", "_")
                    item.add_selection(
                        slug=modifier_slug,
                        category=category,
                        display_name=search_term.title(),
                        quantity=quantity,  # Preserve extracted quantity (was hardcoded to 1)
                        increment_if_exists=True,
                    )
                    added_names.append(search_term.title())
                    logger.info(
                        "ADD_DURING_CONFIG: Added '%s' (category=%s, qty=%d) via category lookup",
                        search_term, category, quantity
                    )
                else:
                    logger.warning(
                        "ADD_DURING_CONFIG: Could not find modifier '%s' in database",
                        search_term
                    )

        if not added_names:
            return None

        # Recalculate price
        pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
        safe_recalculate_price(pricing, item, "after adding modifiers")

        # Build acknowledgment message
        from .utils.text import format_english_list
        added_text = format_english_list(added_names)
        message = f"Sure, I've added {added_text}."

        return self._continue_config_with_message(message, item, order)

    def handle_add_item_during_config(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
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

        # Step 1: Check for ordering prefix
        prefix_match = ADD_ITEM_DURING_CONFIG_PREFIX.match(user_input)
        if not prefix_match:
            return None

        # Step 2: Extract item portion and parse with existing parser
        item_text = user_input[prefix_match.end():].strip()
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
