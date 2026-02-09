"""
Item Adder Handler for Order State Machine.

This module handles adding new items to orders, including menu items,
side items, and bagels with their configurations.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import (
    OrderTask,
    MenuItemTask,
    TaskStatus,
)
from .pending_fields import PendingField
from .schemas import OrderPhase, StateMachineResult, Selection
from .handler_config import HandlerConfig
from .disambiguation_handler import DisambiguationHandler
from .item_lookup_handler import ItemLookupHandler
from .mixins import MenuDataMixin
from .checkout_messages import got_it_anything_else
from .attribute_inference import (
    infer_attributes_from_item_name,
    extract_pre_filled_attributes,
)
from .unrecognized_item_handler import UnrecognizedItemHandler
from .order_item_builder import OrderItemBuilder
from orderbot.cache import menu_cache
from orderbot.cache.base import singularize
from orderbot.constants import MULTI_CONFIG_THRESHOLD
from .default_ingredients import (
    populate_default_ingredients,
    filter_redundant_default_selections,
)
from .builders import ItemBuilder, ItemBuildContext

if TYPE_CHECKING:
    from .context import OrderContext

logger = logging.getLogger(__name__)


class ItemAdderHandler(MenuDataMixin):
    """
    Handles adding items to orders.

    Manages menu item lookup, price calculation, and item creation
    for menu items, side items, and bagels.
    """

    def __init__(
        self,
        config: HandlerConfig,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
        item_lookup_handler: ItemLookupHandler | None = None,
        db_session=None,
    ):
        """
        Initialize the item adder handler.

        Args:
            config: HandlerConfig with shared dependencies.
            menu_item_handler: Unified handler for all item configuration.
            item_lookup_handler: Handler for menu item lookup with disambiguation.
            db_session: Optional SQLAlchemy session for database operations.
        """
        self.menu_lookup = config.menu_lookup
        self.pricing = config.pricing
        self._get_next_question = config.get_next_question
        self._db_session = db_session

        # Unified configuration handler for all item types
        self.menu_item_handler = menu_item_handler
        self._menu_data: dict = {}

        # Generic disambiguation handler
        self.disambiguation_handler = DisambiguationHandler()

        # Item lookup handler (with disambiguation)
        self.item_lookup_handler = item_lookup_handler or ItemLookupHandler(
            menu_lookup=self.menu_lookup,
            disambiguation_handler=self.disambiguation_handler,
        )

        # Order item builder for creating menu item dicts
        self._item_builder = OrderItemBuilder(
            menu_lookup_func=self.menu_lookup.lookup_menu_item if self.menu_lookup else None,
            pricing=self.pricing,
        )

        # Unrecognized item handler with fallback chain
        self._unrecognized_handler = UnrecognizedItemHandler(
            menu_lookup=self.menu_lookup,
            db_session=db_session,
        )

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context including db_session.

        Args:
            ctx: OrderContext with db_session and other request-scoped data.
        """
        logger.debug(
            "ItemAdderHandler.set_context: ctx.db_session=%s",
            "set" if ctx.db_session else "None"
        )
        if ctx.db_session is not None:
            self._db_session = ctx.db_session
            # Update the unrecognized handler's db_session
            if self._unrecognized_handler:
                self._unrecognized_handler._db_session = ctx.db_session
                logger.debug("Updated _unrecognized_handler._db_session")

    def _infer_attributes_from_item_name(self, item: MenuItemTask) -> None:
        """Infer attribute values from the menu item name.

        Delegates to attribute_inference.infer_attributes_from_item_name().
        See that function for full documentation.
        """
        infer_attributes_from_item_name(item)

    def add_item(
        self,
        item_type: str,
        order: OrderTask,
        quantity: int = 1,
        skip_first_question: bool = False,
        **kwargs,
    ) -> StateMachineResult:
        """
        Unified item adder using data-driven configuration.

        All item types flow through _create_configurable_item() which handles
        DB-driven configuration. Items that need disambiguation (matching multiple
        menu items) use _lookup_menu_item_with_disambiguation().

        Args:
            item_type: The item type slug (e.g., "bagel", "sized_beverage", "deli_sandwich")
            order: The current order
            skip_first_question: If True, don't ask the first config question immediately.
                Used when adding multiple items - questions are asked after all items are added.
            quantity: Number of items to add (default 1)
            **kwargs: Item-specific parameters:
                - item_name: Menu item name (e.g., "Iced Latte", "Turkey Club")
                - Any attribute values to pre-fill (bread, toasted, size, milk, etc.)
                - modifications, bagel_choice (for menu items with bagel choice)
                - extracted_selections (list of Selection objects for any item)

        Returns:
            StateMachineResult with next question or confirmation
        """
        quantity = max(1, quantity)

        # Get item name from kwargs - use standardized "item_name" parameter
        item_name = kwargs.get("item_name") or item_type

        # Check if this needs disambiguation (any item type, not just beverages)
        # Disambiguation is needed when:
        # 1. Item name is a category reference (e.g., "coffee" matches multiple items)
        # 2. Item name is empty but we have an item_type (generic request)
        # 3. Item name matches multiple items by word boundary (e.g., "tea" matches Hot Tea, Iced Tea)
        item_name_lower = (item_name or "").lower().strip()
        category_ref = menu_cache.is_category_reference(item_name_lower) if item_name_lower else None
        is_category_reference = category_ref is not None
        is_empty_name = not item_name_lower

        # Skip word-match disambiguation for configurable item types requested generically
        # e.g., "plain bagel" has item_type="bagel" and item_name="bagel" (or item_name=None)
        # User wants a configurable bagel, not disambiguation among "6 Bagel Package", "Pizza Bagel", etc.
        # EXCEPTION: If the item type has NO generic item (only signature items like omelettes),
        # we should show disambiguation to let user pick which specific item they want.
        configurable_types = menu_cache.get_configurable_item_types()
        is_configurable_generic_request = (
            item_type in configurable_types and
            (item_name_lower == item_type.lower() or is_empty_name)
        )

        # Override: If item type has component slots (like omelette with side choice),
        # it's a signature-item-only type that requires user to pick a specific item.
        # Trigger disambiguation instead of treating as a generic configurable request.
        if is_configurable_generic_request and item_type:
            has_component_slots = menu_cache.item_type_has_component_slots(item_type)
            if has_component_slots:
                items_of_type = menu_cache.get_items_by_item_type(item_type)
                if len(items_of_type) > 1:
                    # Item type with component slots (e.g., omelette) - need disambiguation
                    is_configurable_generic_request = False

        # Check for multiple word-boundary matches (e.g., "tea" matches Hot Tea, Iced Tea, etc.)
        # This triggers disambiguation even when the term isn't a registered category reference
        # Skip this check for configurable item types requested generically
        word_matches = []
        has_multiple_word_matches = False
        if not is_configurable_generic_request:
            word_matches = menu_cache.find_items_by_word_match(item_name_lower) if item_name_lower else []
            has_multiple_word_matches = len(word_matches) > 1

        # Generic modifier storage for disambiguation (stores ALL non-None kwargs)
        # This preserves modifiers like size, milk, sweetener during disambiguation
        item_modifiers = {k: v for k, v in kwargs.items() if v is not None}
        item_modifiers["quantity"] = quantity

        # Convert Selection objects to dicts for JSON serialization
        # (extracted_selections may contain Pydantic Selection objects)
        if "extracted_selections" in item_modifiers:
            selections = item_modifiers["extracted_selections"]
            if selections and hasattr(selections[0], "model_dump"):
                item_modifiers["extracted_selections"] = [s.model_dump() for s in selections]

        # Trigger disambiguation for category references, empty names, or multiple word matches
        # BUT skip if it's a configurable item type requested generically (like "bagel")
        needs_disambiguation = (is_category_reference or is_empty_name or has_multiple_word_matches) and not is_configurable_generic_request
        if needs_disambiguation:
            # Determine item_type_filter:
            # - Category reference: use the category slug
            # - Word matches: None (let all matching items through)
            # - Empty name: use original item_type
            if is_category_reference:
                filter_type = category_ref
            elif has_multiple_word_matches:
                filter_type = None  # Don't filter - show all word matches
            else:
                filter_type = item_type

            menu_item, disambiguation_result = self.item_lookup_handler.lookup_menu_item_with_disambiguation(
                item_name=item_name_lower or "item",
                quantity=quantity,
                order=order,
                modifiers=item_modifiers,
                pending_field=PendingField.ITEM_SELECTION,
                item_type_filter=filter_type,
            )

            if disambiguation_result:
                return disambiguation_result

            if menu_item:
                canonical_name = menu_item.get("name", item_name)
                item_name = canonical_name
                item_type = menu_item.get("item_type") or item_type
                kwargs["item_name"] = canonical_name
            elif item_name_lower and not is_category_reference:
                # Unknown item - mark for error handling
                order.pending_field = PendingField.ITEM_SELECTION
                order.unknown_item_request = item_name
                order.set_phase(OrderPhase.CONFIGURING_ITEM)
                return StateMachineResult(message="", order=order)

        # Build menu_item dict (unified lookup for all item types)
        menu_item = self._build_menu_item_dict(item_type, item_name, kwargs)

        # Build pre_filled_attributes from kwargs (data-driven, queries DB for item type attributes)
        pre_filled_attributes = self._extract_pre_filled_attributes(item_type, kwargs)

        # Get extracted_selections from kwargs if provided
        extracted_selections = kwargs.get("extracted_selections")

        # Get unavailable_selections from kwargs (for "We don't have X" messaging)
        unavailable_selections = kwargs.get("unavailable_selections")

        # Get unmatched_selections from kwargs (for unrecognized tokens messaging)
        unmatched_selections = kwargs.get("unmatched_selections")

        # Get special_instructions from kwargs (e.g., "room for cream", "extra hot")
        special_instructions = kwargs.get("special_instructions")

        logger.info(
            "ADD ITEM: type=%s, name=%s, qty=%d, pre_filled=%s",
            item_type, item_name, quantity,
            {k: v for k, v in pre_filled_attributes.items() if v is not None}
        )

        # Create item through generic flow
        result = self._create_configurable_item(
            menu_item=menu_item,
            order=order,
            quantity=quantity,
            user_input=kwargs.get("original_input"),
            pre_filled_attributes=pre_filled_attributes if pre_filled_attributes else None,
            extracted_selections=extracted_selections,
            unavailable_selections=unavailable_selections,
            unmatched_selections=unmatched_selections,
            special_instructions=special_instructions,
            skip_first_question=skip_first_question,
        )

        return result

    def _build_menu_item_dict(
        self,
        item_type: str,
        item_name: str,
        kwargs: dict,
    ) -> dict:
        """Build menu_item dict for _create_configurable_item().

        Delegates to OrderItemBuilder.

        Args:
            item_type: The item type slug
            item_name: The item name (e.g., "Bagel", "Latte", "Turkey Club")
            kwargs: Original kwargs with item details

        Returns:
            Dict with name, item_type, base_price, id, is_signature
        """
        return self._item_builder.build_menu_item_dict(item_type, item_name, kwargs)

    def _extract_pre_filled_attributes(self, item_type: str, kwargs: dict) -> dict:
        """Extract pre-filled attributes from kwargs based on item type.

        Delegates to attribute_inference.extract_pre_filled_attributes().
        """
        return extract_pre_filled_attributes(item_type, kwargs)

    def add_menu_item(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        attributes: dict | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Add a menu item and determine next question.

        Uses DisambiguationHandler for unified disambiguation logic.

        Args:
            item_name: Name of the menu item
            quantity: Number of items to add
            order: Current order task
            attributes: Optional dict of attribute values to pre-fill
            modifications: Optional list of modification strings
        """
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Step 1: Look up menu item with disambiguation handling
        menu_item, disambiguation_result = self.item_lookup_handler.lookup_menu_item_with_disambiguation(
            item_name, quantity, order
        )

        # If disambiguation is needed, return the question
        if disambiguation_result:
            return disambiguation_result

        # If item not found, provide helpful suggestions using hybrid handler
        if not menu_item:
            session_id = getattr(order, 'session_id', None)
            message, category_for_followup = self._unrecognized_handler.get_not_found_response(
                item_name, order=order, session_id=session_id
            )
            if category_for_followup:
                # Track state so "yes" response can list items in this category
                order.pending_field = PendingField.CATEGORY_INQUIRY
                order.pending_config_queue = [category_for_followup]
            return StateMachineResult(
                message=message,
                order=order,
            )

        # Step 2: Create the item using existing logic
        return self._create_menu_item_from_lookup(
            menu_item=menu_item,
            item_name=item_name,
            quantity=quantity,
            order=order,
            attributes=attributes,
            modifications=modifications,
        )


    def _create_menu_item_from_lookup(
        self,
        menu_item: dict,
        item_name: str,
        quantity: int,
        order: OrderTask,
        attributes: dict | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Create a menu item from lookup result.

        Args:
            menu_item: Menu item dict from lookup
            item_name: Original item name from user
            quantity: Number of items to create
            order: Current order task
            attributes: Optional dict of attribute values to pre-fill
            modifications: Optional list of modification strings
        """
        # Use the canonical name from menu if found
        canonical_name = menu_item.get("name", item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        category = menu_item.get("item_type", "")  # item_type slug like "spread_sandwich"
        is_signature = menu_item.get("is_signature", False)  # Signature item like "The Classic BEC"

        # Check if item type has component slots (data-driven, e.g., omelette includes a side)
        has_component_slots = menu_cache.item_type_has_component_slots(category) if category else False

        # Check if it uses DB-driven configuration (item types with configurable attributes)
        # Note: has_component_slots items are handled separately and return early
        uses_db_config = category and category in menu_cache.get_configurable_item_types()

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', has_component_slots=%s, uses_db_config=%s, quantity=%d",
            canonical_name,
            category,
            has_component_slots,
            uses_db_config,
            quantity,
        )

        # Determine the menu item type for tracking
        if has_component_slots:
            item_type = category  # Use the actual category slug (e.g., "omelette")
        elif uses_db_config:
            item_type = category  # "deli_sandwich", "egg_sandwich", "fish_sandwich", or "spread_sandwich"
        else:
            item_type = None

        # Create the requested quantity of items
        first_item = None
        for i in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type=item_type,
                modifications=modifications or [],  # User modifications like "with mayo and mustard"
                is_signature=is_signature,  # Signature item flag from menu data
            )
            # Populate default ingredients for items that have them defined
            # This must happen before applying user selections so user selections
            # can replace defaults (e.g., "BEC with swiss" replaces cheddar)
            # Check if item has default ingredients (more reliable than is_signature flag)
            if menu_item_id:
                populate_default_ingredients(item)
            # Apply pre-filled attributes
            if attributes:
                for attr_name, attr_value in attributes.items():
                    if attr_value is not None:
                        item[attr_name] = attr_value

            # Apply pending ingredient from ingredient suggestion flow
            # (e.g., "I want caramel syrup" -> "yes" -> "iced coffee" -> apply caramel)
            # Only apply to the first item (first_item is None means this is the first)
            if first_item is None:
                self._apply_pending_ingredient(item, order, item_type, canonical_name)

            # Infer attributes from item name (data-driven, e.g., "Hot Coffee" -> temperature=hot)
            self._infer_attributes_from_item_name(item)
            item.mark_in_progress()
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        logger.info("Added %d menu item(s): %s (price: $%.2f each, id: %s, attrs=%s, mods=%s)", quantity, canonical_name, price, menu_item_id, attributes, modifications)

        if has_component_slots:
            # Set state to wait for component slot selection (applies to first item, others will be configured after)
            order.phase = OrderPhase.CONFIGURING_ITEM
            order.pending_item_id = first_item.id
            # Get component slot configuration from DB (e.g., "side" slot)
            side_slot = menu_cache.get_component_slot(category, "side")
            order.pending_field = PendingField.SIDE_CHOICE
            # Use prompt text from DB or fallback
            question = (
                side_slot.get("prompt_text")
                if side_slot
                else f"What side would you like with your {canonical_name}?"
            )
            return StateMachineResult(
                message=question,
                order=order,
            )
        elif uses_db_config and self.menu_item_handler:
            # For deli/egg sandwiches, use DB-driven configuration with customization checkpoint
            # Capture any attributes mentioned in the initial order
            # Note: item_name contains the item + any modifiers the user mentioned
            self.menu_item_handler.capture_attributes_from_input(item_name, first_item)
            # Start the configuration flow
            return self.menu_item_handler.get_first_question(first_item, order)
        else:
            # Mark all items complete (non-omelettes don't need configuration)
            for item in order.items.items:
                # Use getattr to safely access menu_item_name on any item type
                if getattr(item, 'menu_item_name', None) == canonical_name and item.status == TaskStatus.IN_PROGRESS:
                    item.mark_complete()
            return self._get_next_question(order)

    def add_side_item(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> tuple[str | None, str | None]:
        """Add a side item to the order without returning a response.

        Used when a side item is ordered alongside another item (e.g., "bagel with a side of sausage").

        Returns:
            Tuple of (canonical_name, error_message).
            If successful: (canonical_name, None)
            If item not found: (None, error_message)
        """
        quantity = max(1, quantity)

        # Look up the side item in the menu
        menu_item = self.menu_lookup.lookup_menu_item(side_item_name)

        # If item not found, return error message using hybrid handler
        if not menu_item:
            logger.warning("Side item not found: '%s' - rejecting", side_item_name)
            message, _ = self._unrecognized_handler.get_not_found_response(
                side_item_name, order=order
            )
            return (None, message)

        # Use canonical name and price from menu
        canonical_name = menu_item.get("name", side_item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")

        # Get item type from DB lookup
        item_type = menu_item.get("item_type")

        # Create the side item(s)
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type=item_type,
            )
            item.mark_complete()  # Side items don't need configuration
            order.items.add_item(item)

        logger.info("Added %d side item(s): %s (price: $%.2f each)", quantity, canonical_name, price)
        return (canonical_name, None)

    def _apply_pending_ingredient(
        self,
        item: MenuItemTask,
        order: OrderTask,
        item_type: str | None,
        canonical_name: str,
    ) -> None:
        """Apply pending ingredient from ingredient suggestion flow.

        When a user orders a modifier without an item (e.g., "I want caramel syrup"),
        then confirms they want to add it to a drink (e.g., "yes"), then orders the item
        (e.g., "iced coffee"), this method applies the pending ingredient to the new item.

        The pending ingredient is stored in order.pending_ingredient_to_apply and is
        cleared after being applied to prevent it from being applied to subsequent items.

        Args:
            item: The MenuItemTask to apply the ingredient to.
            order: The OrderTask containing the pending ingredient.
            item_type: The item type slug for attribute lookup.
            canonical_name: The menu item name for logging.
        """
        if not order.pending_ingredient_to_apply or not self.menu_item_handler:
            return

        pending_ingredient = order.pending_ingredient_to_apply
        # Clear it now so it's not applied to subsequent items
        order.pending_ingredient_to_apply = None

        # Find the attribute and option that match this ingredient
        # Search through item type's attributes for an option matching the ingredient
        attrs = menu_cache.get_item_type_attributes(item_type) if item_type else {}
        pending_lower = pending_ingredient.lower().strip()
        pending_slug = pending_lower.replace(' ', '_')
        found_attr_slug = None
        found_option = None

        for attr_slug_iter, attr_config in attrs.items():
            options = attr_config.get('options', [])
            for opt in options:
                opt_slug = opt.get('slug', '').lower()
                opt_display = opt.get('display_name', '').lower()
                opt_aliases = [a.lower() for a in (opt.get('aliases') or [])]
                # Match by slug, display name, or alias
                if (opt_slug == pending_slug or
                    opt_display == pending_lower or
                    pending_lower in opt_aliases):
                    found_attr_slug = attr_slug_iter
                    found_option = opt
                    break
            if found_option:
                break

        if found_attr_slug and found_option:
            # Get the correct slug and price from the matched option
            option_slug = found_option.get('slug', pending_ingredient)
            option_price = found_option.get('price_modifier', 0.0)
            # Create and apply the selection
            pending_selection = Selection(
                slug=option_slug,
                category=found_attr_slug,
                quantity=1,
                price=option_price,
                display_name=found_option.get('display_name'),
            )
            self.menu_item_handler._apply_selections(item, [pending_selection])
            logger.info(
                "Applied pending ingredient '%s' to %s (attr=%s, price=$%.2f)",
                pending_ingredient, canonical_name, found_attr_slug, option_price
            )
        else:
            logger.warning(
                "Could not find attribute for pending ingredient '%s' on item type '%s'",
                pending_ingredient, item_type
            )

    # =========================================================================
    # Generic Item Creation (Data-Driven)
    # =========================================================================

    def _check_config_complete(
        self,
        item_type: str | None,
        pre_filled_attributes: dict | None,
    ) -> bool:
        """Check if all mandatory attributes for item_type are already filled.

        Returns True if configuration would be complete (no questions needed).
        Used to decide whether to create a single item with quantity=N vs
        N separate items for individual configuration.

        Args:
            item_type: Item type slug (e.g., "cold_cut", "cheese")
            pre_filled_attributes: Dict of attribute values already filled

        Returns:
            True if all mandatory attributes are filled, False otherwise
        """
        if not item_type:
            return False

        from .config.attribute_resolver import get_mandatory_attributes
        mandatory = get_mandatory_attributes(item_type)

        if not mandatory:
            return True  # No mandatory attributes = config complete

        if not pre_filled_attributes:
            return False  # Has mandatory attrs but nothing pre-filled

        # Check if all mandatory attrs have values in pre_filled_attributes
        for attr in mandatory:
            attr_slug = attr.get("slug")
            if attr_slug and attr_slug not in pre_filled_attributes:
                return False

        return True

    def _create_configurable_item(
        self,
        menu_item: dict,
        order: OrderTask,
        quantity: int = 1,
        user_input: str | None = None,
        pre_filled_attributes: dict | None = None,
        extracted_selections: list[Selection] | None = None,
        unavailable_selections: dict | None = None,
        unmatched_selections: dict | None = None,
        special_instructions: list[str] | None = None,
        skip_first_question: bool = False,
    ) -> StateMachineResult:
        """
        Create an item and start its configuration flow if needed.

        This is the generic, data-driven item creation method. It handles all item types
        by checking the database for configuration requirements.

        Args:
            menu_item: Menu item dict from lookup (must have 'name', 'item_type', 'base_price')
            order: Current order task
            quantity: Number of items to create (default: 1)
            user_input: Original user input for attribute extraction (optional)
            pre_filled_attributes: Dict of attribute values to pre-fill (optional)
            extracted_selections: List of Selection objects to apply (optional)
            unavailable_selections: Dict of attr_slug -> {attempted_slug, attempted_display}
                for options user tried that aren't available (e.g., "medium" size)
            unmatched_selections: Dict of attr_slug -> {tokens: list[str]}
                for tokens user mentioned that don't match any option (e.g., "honey" for coffee)
            special_instructions: List of special instruction strings (e.g., "room for cream")

        Returns:
            StateMachineResult with next question or confirmation
        """
        # Create build context with all parameters
        ctx = ItemBuildContext(
            menu_item=menu_item,
            order=order,
            quantity=quantity,
            user_input=user_input,
            pre_filled_attributes=pre_filled_attributes,
            extracted_selections=extracted_selections,
            unavailable_selections=unavailable_selections,
            unmatched_selections=unmatched_selections,
            special_instructions=special_instructions,
            skip_first_question=skip_first_question,
        )

        # Create builder with callbacks
        builder = ItemBuilder(
            pricing=self.pricing,
            config_handler=self.menu_item_handler,
            infer_attributes_callback=self._infer_attributes_from_item_name,
            apply_pending_ingredient_callback=self._apply_pending_ingredient,
        )

        # Prepare context (determine configuration requirements)
        builder.prepare_context(ctx)

        # Calculate how many items to create and with what quantity
        item_count, item_quantity = builder.calculate_item_count(
            ctx, self._check_config_complete
        )

        # Build the items
        first_item = None
        for i in range(item_count):
            is_first = (first_item is None)
            item = builder.build_single_item(ctx, item_quantity, is_first)

            # Check for pricing failure
            if item.unit_price == 0.0 and ctx.price > 0.0:
                logger.warning("Price lookup failed for '%s'", item.menu_item_name)
                return StateMachineResult(
                    message="What can I get for you?",
                    order=order
                )

            order.items.add_item(item)
            if first_item is None:
                first_item = item

        # If item needs configuration, start the configuration flow
        needs_configuration = ctx.needs_configuration
        if needs_configuration and self.menu_item_handler:
            # Capture any attributes from original user input
            # Skip if extracted_selections provided - parser already extracted attributes
            if ctx.user_input and not ctx.extracted_selections:
                self.menu_item_handler.capture_attributes_from_input(ctx.user_input, first_item)

            # If skip_first_question=True, return without asking config question.
            # This is used when adding multiple items - all items are added first,
            # then process_items() calls get_first_question after all are added.
            if skip_first_question:
                logger.info(
                    "skip_first_question=True: added %s (%s), deferring config question",
                    ctx.canonical_name, first_item.id[:8]
                )
                # Return a result without a message - just the updated order
                # The caller (process_items) will handle asking questions
                return StateMachineResult(message="", order=order)

            # Check if there are pending parsed items that haven't been added yet
            # If so, process them first (they were stored during disambiguation)
            if self.menu_item_handler._process_pending_parsed_items_callback:
                pending_result = self.menu_item_handler._process_pending_parsed_items_callback(order)
                if pending_result:
                    # Queue this item for later and return the pending result
                    order.queue_item_for_config(first_item.id, ctx.item_type, item_name=ctx.canonical_name)
                    logger.info(
                        "Queued newly selected item %s (%s) - processing pending parsed items first",
                        ctx.canonical_name, first_item.id[:8]
                    )
                    return pending_result

            # Check if there are other items queued for configuration
            # If so, configure them first (they were ordered earlier in the conversation)
            if order.has_queued_config_items():
                from .handler_utils import process_next_queued_item
                # Queue this item for later
                order.queue_item_for_config(first_item.id, ctx.item_type, item_name=ctx.canonical_name)
                logger.info(
                    "Queued newly selected item %s (%s) - processing queued item first",
                    ctx.canonical_name, first_item.id[:8]
                )
                # Start config for the first queued item
                queued_result = process_next_queued_item(
                    order, self.menu_item_handler, "before new item"
                )
                if queued_result:
                    return queued_result

            # Start configuration flow for this item
            return self.menu_item_handler.get_first_question(first_item, order)
        else:
            # Not configurable - item is complete
            order.clear_pending()

            # If skip_first_question=True, return without confirmation message.
            # This is used when adding multiple items - confirmation comes after all added.
            if skip_first_question:
                logger.info(
                    "skip_first_question=True: added non-configurable %s (%s)",
                    ctx.canonical_name, first_item.id[:8]
                )
                return StateMachineResult(message="", order=order)

            # Check if there are other items queued for configuration
            # This handles the case where disambiguation was triggered after other items
            # were already added (e.g., "an everything bagel and a latte")
            from .handler_utils import process_next_queued_item
            queued_result = process_next_queued_item(
                order, self.menu_item_handler, "after non-configurable"
            )
            if queued_result:
                return queued_result

            # No queued items - return confirmation
            # Use get_display_name() to include unit suffix (e.g., "(3 pack)")
            display_name = first_item.get_display_name()
            if ctx.quantity > 1:
                return StateMachineResult(
                    message=got_it_anything_else(f"{ctx.quantity} {display_name}"),
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=got_it_anything_else(display_name),
                    order=order,
                )

    def _lookup_menu_item_with_disambiguation(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        modifiers: dict | None = None,
        pending_field: str = PendingField.ITEM_SELECTION,
        item_type_filter: str | None = None,
    ) -> tuple[dict | None, StateMachineResult | None]:
        """Delegate to item_lookup_handler for menu item lookup with disambiguation.

        This method is kept for backward compatibility.
        """
        return self.item_lookup_handler.lookup_menu_item_with_disambiguation(
            item_name=item_name,
            quantity=quantity,
            order=order,
            modifiers=modifiers,
            pending_field=pending_field,
            item_type_filter=item_type_filter,
        )
