"""
Parsed Item Processor Module.

Handles processing of ParsedItemEntry objects and adding them to orders.
Provides a unified data-driven approach for all item types.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache
from .models import TaskStatus
from .schemas.phases import OrderPhase
from .schemas import (
    StateMachineResult,
    Selection,
    ParsedItemEntry,
    ParsedItem,
)
from .checkout_messages import got_it_anything_else
from .utils.text import format_english_list
from .utils.constants import is_price_metadata_key

if TYPE_CHECKING:
    from .models import OrderTask, MenuItemTask
    from .pricing import PricingEngine
    from .item_adder_handler import ItemAdderHandler
    from .schemas import OpenInputResponse

logger = logging.getLogger(__name__)

__all__ = [
    "get_selections_from_parsed_item",
    "build_item_summary",
    "has_any_selections",
    "ParsedItemProcessor",
]


# =============================================================================
# Module-Level Helper Functions
# =============================================================================

def get_selections_from_parsed_item(item: ParsedItemEntry) -> list[Selection]:
    """Get selections from a ParsedItemEntry.

    Works for ALL item types - uses unified selections list.

    Args:
        item: The parsed item entry

    Returns:
        List of Selection objects from the item
    """
    return list(item.modifiers)


def build_item_summary(item: ParsedItemEntry) -> str:
    """Build human-readable summary for a parsed item (data-driven).

    Returns uniform format: "{quantity}x {item_name}, {attr1}, {attr2}, ..."

    Args:
        item: The parsed item entry

    Returns:
        Summary string

    Examples:
        "Everything Bagel, toasted, cream cheese"
        "2x Latte, large, iced, oat milk"
    """
    # Use item_name if present, otherwise item_type display name
    if item.item_name:
        base = item.item_name
    else:
        base = menu_cache.get_item_type_display_name(item.item_type) or item.item_type

    # Add quantity prefix if more than 1
    if item.quantity > 1:
        base = f"{item.quantity}x {base}"

    # Collect attribute display values uniformly
    attr_displays = []
    for key, value in item.attribute_values.items():
        # Skip internal storage fields
        if is_price_metadata_key(key):
            continue

        if value is True:
            # Boolean - use key as display (e.g., "toasted")
            attr_displays.append(key)
        elif value is False or value is None:
            continue
        elif isinstance(value, list):
            # Multi-select - show all values
            for v in value:
                if isinstance(v, str):
                    attr_displays.append(v)
        else:
            # Single-select - show value
            attr_displays.append(str(value))

    # Add modifiers if present (selections converted to display names)
    if item.modifiers:
        for sel in item.modifiers:
            display = sel.display_name or sel.slug
            if sel.quantity > 1:
                display = f"{sel.quantity}x {display}"
            attr_displays.append(display)

    # Build final summary
    if attr_displays:
        return f"{base}, {', '.join(attr_displays)}"
    return base


def has_any_selections(selections: list[Selection] | None) -> bool:
    """Check if selections list has any content worth passing.

    Args:
        selections: The list of selections

    Returns:
        True if there are any selections
    """
    return bool(selections)


# =============================================================================
# ParsedItemProcessor Class
# =============================================================================

class ParsedItemProcessor:
    """
    Processor for ParsedItemEntry objects.

    Handles adding parsed items to orders using a unified data-driven approach.
    Works for all item types without type-specific branching.
    """

    def __init__(
        self,
        item_adder_handler: "ItemAdderHandler | None" = None,
        pricing: "PricingEngine | None" = None,
    ) -> None:
        """Initialize the parsed item processor.

        Args:
            item_adder_handler: Handler for adding items to orders.
            pricing: PricingEngine for price calculations.
        """
        self.item_adder_handler = item_adder_handler
        self.pricing = pricing

    def add_parsed_item_entry(
        self, item: ParsedItemEntry, order: "OrderTask"
    ) -> tuple["OrderTask", str, StateMachineResult | None]:
        """
        Handle ParsedItemEntry using unified data-driven approach.

        This method works for ALL item types without branching on specific
        item_type slugs. It:
        1. Gets selections from the parsed item
        2. Passes all attribute_values to add_item (receiver filters to valid attrs)
        3. Builds summary using item_name or item_type display name

        Args:
            item: The ParsedItemEntry to add.
            order: The current order task.

        Returns:
            Tuple of (updated_order, item_summary_string, disambiguation_result).
            The third element is non-None when disambiguation is needed.
        """
        # 1. Get selections from parsed item (data-driven, works for all item types)
        selections = get_selections_from_parsed_item(item)

        # 2. Track item count to detect if item was actually added
        #    (disambiguation returns without adding to order)
        items_before = len(order.items.items)

        # 3. Call add_item with all attribute_values as kwargs
        #    The receiver (_extract_pre_filled_attributes) filters to valid attributes
        #    Pass unavailable_selections so it's set BEFORE get_first_question() is called
        result = self.item_adder_handler.add_item(
            item_type=item.item_type,
            order=order,
            quantity=item.quantity,
            item_name=item.item_name,
            extracted_selections=selections if has_any_selections(selections) else None,
            original_input=item.original_text,
            unavailable_selections=item.unavailable_selections if item.unavailable_selections else None,
            **item.attribute_values,  # Data-driven: pass all, receiver filters (backward compat)
        )
        order = result.order

        # 4. Check if disambiguation was triggered (message present, no item added)
        items_after = len(order.items.items)
        if result.message and items_after == items_before and order.pending_field:
            # Disambiguation result - return it to be handled by caller
            return order, "", result

        # 5. Build summary if item was added
        if items_after > items_before:
            # Note: unavailable_selections is now passed to add_item and set before
            # get_first_question() is called, so it's already on the MenuItemTask

            summary = build_item_summary(item)
            # Don't return result here - process_items() handles config questions
            # for ALL items after the loop. Returning here caused early exit,
            # preventing subsequent items from being processed.
            # (unavailable_selections messages are handled by get_first_question())
            return order, summary, None

        # Item wasn't added (error case) - return empty summary
        return order, "", None

    def add_parsed_item(
        self, item: ParsedItem, order: "OrderTask"
    ) -> tuple["OrderTask", str, StateMachineResult | None]:
        """
        Dispatch a parsed item to the appropriate handler.

        Args:
            item: The parsed item to add.
            order: The current order task.

        Returns:
            Tuple of (updated_order, item_summary_string, disambiguation_result).
            The third element is non-None when disambiguation is needed.
        """
        # Handle unified ParsedItemEntry type (data-driven)
        if isinstance(item, ParsedItemEntry):
            return self.add_parsed_item_entry(item, order)

        return order, "", None

    def process_items(
        self,
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """
        Process all items from parsed_items list (unified path for 1 or N items).

        This is the primary code path for adding items to the order. All parsing
        now populates parsed_items, making this the single unified processing path.

        Flow:
        1. Add all items to the order
        2. Find all items needing configuration (toasted questions, etc.)
        3. Queue items 2+ for later config, each with their display name
        4. Ask first config question: "Got it! Would you like the [Item1] toasted?"
        5. Follow-up questions use abbreviated form: "And the [Item2]?"
        6. Final summary after all configured: "Great, [summary]. Anything else?"

        Args:
            parsed: The parsed open input response.
            order: The current order task.

        Returns:
            StateMachineResult if items were processed, None if parsed_items is empty.
        """
        if not parsed.parsed_items:
            return None

        logger.info("Processing %d items via parsed_items list", len(parsed.parsed_items))

        # Track added items with their IDs and names for config queueing
        added_items: list[tuple[str, str, str]] = []  # (item_id, item_name, item_type)
        summaries = []

        # Clear any previous error
        order.last_add_error = None

        for idx, parsed_item in enumerate(parsed.parsed_items):
            items_before_count = len(order.items.items)
            order, summary, disambiguation_result = self.add_parsed_item(parsed_item, order)

            # Check if disambiguation was triggered - return immediately
            if disambiguation_result:
                logger.info("Disambiguation triggered for item, returning result")
                # Before returning, queue any items already added that need configuration.
                # This ensures they're not forgotten when disambiguation resolves.
                # Example: "everything bagel and a latte" - bagel is added first,
                # then latte triggers disambiguation. Without this, bagel config is skipped.
                for item_id, display_name, item_type in added_items:
                    item = order.items.get_item_by_id(item_id)
                    if item and item.status == TaskStatus.IN_PROGRESS:
                        order.queue_item_for_config(item_id, item_type, item_name=display_name)
                        logger.info("Queued %s (%s) for config before disambiguation", display_name, item_id[:8])

                # Store remaining parsed items that haven't been processed yet
                # Example: "latte and bagel" - latte triggers disambiguation, bagel is stored
                remaining_items = parsed.parsed_items[idx + 1:]
                if remaining_items:
                    order.pending_parsed_items = [
                        item.model_dump() if hasattr(item, 'model_dump') else item.__dict__
                        for item in remaining_items
                    ]
                    logger.info("Stored %d remaining parsed items for later: %s",
                        len(remaining_items),
                        [getattr(item, 'item_name', None) or getattr(item, 'item_type', 'unknown') for item in remaining_items]
                    )

                    # Modify message to acknowledge full order (user needs feedback that all items were heard)
                    # Build simple summary of ALL parsed items (just item names, not full details)
                    all_item_names = []
                    for p in parsed.parsed_items:
                        # Use item_name if available, otherwise item_type display name
                        name = p.item_name or menu_cache.get_item_type_display_name(p.item_type) or p.item_type
                        # Add quantity prefix if more than 1
                        if p.quantity > 1:
                            name = f"{p.quantity} {name}s" if not name.endswith('s') else f"{p.quantity} {name}"
                        all_item_names.append(name)
                    full_order_summary = format_english_list(all_item_names)

                    # Replace "Got it, " prefix with full acknowledgment
                    # Original: "Got it, for the Plain Bagel. Would you like it scooped?"
                    # Target: "Got it, a bagel and a latte. For the Plain Bagel, would you like it scooped?"
                    msg = disambiguation_result.message
                    if msg.startswith("Got it, for the "):
                        # Extract item reference and question
                        rest = msg[16:]  # Remove "Got it, for the "
                        # rest is now "Plain Bagel. Would you like it scooped?"
                        # Replace the first ". " with ", " and lowercase the next character
                        period_pos = rest.find(". ")
                        if period_pos != -1:
                            item_ref = rest[:period_pos]  # "Plain Bagel"
                            question = rest[period_pos + 2:]  # "Would you like it scooped?"
                            # Lowercase first char of question
                            if question:
                                question = question[0].lower() + question[1:]
                            rest = f"{item_ref}, {question}"
                        msg = f"Got it, {full_order_summary}. For the {rest}"
                        disambiguation_result = StateMachineResult(
                            message=msg,
                            order=disambiguation_result.order,
                        )
                    elif msg.startswith("Got it, "):
                        # Fallback for other "Got it, " formats
                        msg = f"Got it, {full_order_summary}. " + msg[8:].capitalize()
                        disambiguation_result = StateMachineResult(
                            message=msg,
                            order=disambiguation_result.order,
                        )

                return disambiguation_result

            # Check if add failed (e.g., item not found on menu)
            if order.last_add_error is not None:
                # Return the error message instead of continuing
                error_result = order.last_add_error
                order.last_add_error = None  # Clear it
                return error_result

            if summary:
                summaries.append(summary)
                # Capture ALL newly added items (quantity>1 creates multiple MenuItemTasks)
                new_items = order.items.items[items_before_count:]
                for new_item in new_items:
                    added_items.append((new_item.id, new_item.get_display_name(), parsed_item.item_type))
                if new_items:
                    logger.info(
                        "Added item via parsed_items: %s (%d tasks, first id=%s)",
                        summary, len(new_items), new_items[0].id[:8],
                    )

        if not summaries:
            return None

        # Find items that need configuration (IN_PROGRESS status)
        # Data-driven: let MenuItemConfigHandler determine what to ask
        items_needing_config: list[tuple[str, str, str]] = []  # (item_id, display_name, item_type)
        for item_id, display_name, item_type in added_items:
            item = order.items.get_item_by_id(item_id)
            if item and item.status == TaskStatus.IN_PROGRESS:
                items_needing_config.append((item_id, display_name, item_type))

        logger.info("Items needing configuration: %d", len(items_needing_config))

        # If no items need configuration, return simple confirmation
        if not items_needing_config:
            items_str = format_english_list(summaries)
            return StateMachineResult(message=got_it_anything_else(items_str), order=order)

        # Queue items 2+ for later configuration
        order.multi_item_config_names = [name for _, name, _ in items_needing_config]
        for item_id, item_name, item_type in items_needing_config[1:]:
            order.queue_item_for_config(item_id, item_type, item_name=item_name)
            logger.info("Queued %s (%s) for config", item_name, item_id[:8])

        # Get first item and delegate question to MenuItemConfigHandler
        first_item_id, first_item_name, first_item_type = items_needing_config[0]
        first_item = order.items.get_item_by_id(first_item_id)

        from .models import MenuItemTask
        if isinstance(first_item, MenuItemTask) and self.item_adder_handler and self.item_adder_handler.menu_item_handler:
            return self.item_adder_handler.menu_item_handler.get_first_question(first_item, order)

        # Fallback if handler not available
        order.pending_item_id = first_item_id
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        return StateMachineResult(
            message=f"Got it, {first_item_name}! Any preferences?",
            order=order,
        )
