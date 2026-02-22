"""
Item Creation Handler.

Handles the configurable item creation pipeline, including building items
for orders, starting configuration flows, and completing non-configurable items.

Extracted from item_adder_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable

from .models import MenuItemTask
from .schemas import StateMachineResult
from .checkout_messages import got_it_anything_else, build_inapplicable_note
from .builders import ItemBuilder, ItemBuildContext

if TYPE_CHECKING:
    from .item_adder_handler import ItemAdderHandler

logger = logging.getLogger(__name__)


class ItemCreationHandler:
    """Handles the configurable item creation pipeline.

    Manages building items for orders, starting configuration flows,
    and completing non-configurable items.
    """

    def __init__(self, parent: "ItemAdderHandler"):
        """Initialize the item creation handler.

        Args:
            parent: The parent ItemAdderHandler providing shared dependencies.
        """
        self._parent = parent

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
        order: "OrderTask",
        quantity: int = 1,
        user_input: str | None = None,
        pre_filled_attributes: dict | None = None,
        extracted_selections: "list[Selection] | None" = None,
        unavailable_selections: dict | None = None,
        unmatched_selections: dict | None = None,
        ambiguous_selections: "list[dict] | None" = None,
        special_instructions: "list[str] | None" = None,
        inapplicable_attributes: "list[dict] | None" = None,
        skip_first_question: bool = False,
    ) -> StateMachineResult:
        """
        Create an item and start its configuration flow if needed.

        This is the generic, data-driven item creation method. It handles all item types
        by checking the database for configuration requirements.

        Delegates item building to _build_items_for_order(), then routes to either
        _start_configuration_flow() or _complete_non_configurable_item().

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
            ambiguous_selections=ambiguous_selections,
            special_instructions=special_instructions,
            inapplicable_attributes=inapplicable_attributes,
            skip_first_question=skip_first_question,
        )

        # Create builder with callbacks
        builder = ItemBuilder(
            pricing=self._parent.pricing,
            config_handler=self._parent.menu_item_handler,
            infer_attributes_callback=self._parent._infer_attributes_from_item_name,
            apply_pending_ingredient_callback=self._parent._apply_pending_ingredient,
        )

        # Prepare context (determine configuration requirements)
        builder.prepare_context(ctx)

        # Build items and add to order
        first_item = self._build_items_for_order(ctx, builder)
        if first_item is None:
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        # Route to configuration or completion flow
        if ctx.needs_configuration and self._parent.menu_item_handler:
            return self._start_configuration_flow(ctx, first_item)
        else:
            return self._complete_non_configurable_item(ctx, first_item)

    def _build_items_for_order(
        self,
        ctx: ItemBuildContext,
        builder: ItemBuilder,
    ) -> MenuItemTask | None:
        """Build menu items and add them to the order.

        Args:
            ctx: The build context with item parameters.
            builder: The ItemBuilder for constructing items.

        Returns:
            The first item created, or None if pricing failed.
        """
        item_count, item_quantity = builder.calculate_item_count(
            ctx, self._check_config_complete
        )

        first_item = None
        for i in range(item_count):
            is_first = (first_item is None)
            item = builder.build_single_item(ctx, item_quantity, is_first)

            # Check for pricing failure
            if item.unit_price == 0.0 and ctx.price > 0.0:
                logger.warning("Price lookup failed for '%s'", item.menu_item_name)
                return None

            ctx.order.items.add_item(item)
            if first_item is None:
                first_item = item

        # Check if user's input had a trailing "done" signal (e.g., "nothing else")
        # If so, mark all items in this batch so optional customization is skipped
        if first_item and ctx.user_input:
            from .response_utils import has_trailing_done_signal
            if has_trailing_done_signal(ctx.user_input):
                for item_in_order in ctx.order.items.items:
                    if item_in_order.id == first_item.id or (
                        item_count > 1 and item_in_order.menu_item_name == first_item.menu_item_name
                        and not item_in_order.is_complete()
                    ):
                        item_in_order.customization_declined = True

        return first_item

    def _start_configuration_flow(
        self,
        ctx: ItemBuildContext,
        first_item: MenuItemTask,
    ) -> StateMachineResult:
        """Start the configuration flow for a configurable item.

        Handles attribute capture from user input, skip-first-question deferral,
        pending parsed items, and queued config items before starting the
        configuration question flow.

        Args:
            ctx: The build context.
            first_item: The first item created (used for configuration).

        Returns:
            StateMachineResult with the next configuration question or deferred result.
        """
        order = ctx.order
        menu_item_handler = self._parent.menu_item_handler

        # Capture any attributes from original user input
        # Skip if extracted_selections provided - parser already extracted attributes
        if ctx.user_input and ctx.extracted_selections is None:
            # Strip the menu item name to prevent words in the name from
            # falsely matching attribute options (e.g., "Nova" in "Tofu Nova Sandwich")
            capture_input = ctx.user_input
            if ctx.canonical_name:
                idx = ctx.user_input.lower().find(ctx.canonical_name.lower())
                if idx >= 0:
                    capture_input = (ctx.user_input[:idx] + ctx.user_input[idx + len(ctx.canonical_name):]).strip()
            menu_item_handler.capture_attributes_from_input(capture_input, first_item)

        # If skip_first_question=True, return without asking config question.
        # This is used when adding multiple items - all items are added first,
        # then process_items() calls get_first_question after all are added.
        if ctx.skip_first_question:
            logger.info(
                "skip_first_question=True: added %s (%s), deferring config question",
                ctx.canonical_name, first_item.id[:8]
            )
            # Return a result without a message - just the updated order
            # The caller (process_items) will handle asking questions
            return StateMachineResult(message="", order=order)

        # Check if there are pending parsed items that haven't been added yet
        # If so, process them first (they were stored during disambiguation)
        if menu_item_handler._process_pending_parsed_items_callback:
            pending_result = menu_item_handler._process_pending_parsed_items_callback(order)
            if pending_result:
                # Queue this item for later and return the pending result
                order.queue_item_for_config(first_item.id, item_name=ctx.canonical_name)
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
            order.queue_item_for_config(first_item.id, item_name=ctx.canonical_name)
            logger.info(
                "Queued newly selected item %s (%s) - processing queued item first",
                ctx.canonical_name, first_item.id[:8]
            )
            # Start config for the first queued item
            queued_result = process_next_queued_item(
                order, menu_item_handler, "before new item"
            )
            if queued_result:
                return queued_result

        # Start configuration flow for this item
        return menu_item_handler.get_first_question(first_item, order)

    def _complete_non_configurable_item(
        self,
        ctx: ItemBuildContext,
        first_item: MenuItemTask,
    ) -> StateMachineResult:
        """Complete a non-configurable item and return confirmation.

        Handles clearing pending state, skip-first-question deferral,
        processing queued config items, and building the confirmation message.

        Args:
            ctx: The build context.
            first_item: The first item created.

        Returns:
            StateMachineResult with confirmation or queued item question.
        """
        order = ctx.order
        order.clear_pending()

        # If skip_first_question=True, return without confirmation message.
        # This is used when adding multiple items - confirmation comes after all added.
        if ctx.skip_first_question:
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
            order, self._parent.menu_item_handler, "after non-configurable"
        )
        if queued_result:
            return queued_result

        # No queued items - return confirmation
        # Use get_display_name() to include unit suffix (e.g., "(3 pack)")
        display_name = first_item.get_display_name()
        if ctx.quantity > 1:
            message = got_it_anything_else(f"{ctx.quantity} {display_name}")
        else:
            message = got_it_anything_else(display_name)

        # Prepend note for inapplicable attributes (e.g., "large coke")
        note = build_inapplicable_note(first_item)
        if note:
            message = note + " " + message

        return StateMachineResult(message=message, order=order)
