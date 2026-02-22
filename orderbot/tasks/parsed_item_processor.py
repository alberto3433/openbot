"""
Parsed Item Processor Module.

Handles processing of ParsedItemEntry objects and adding them to orders.
Provides a unified data-driven approach for all item types.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from .models import TaskStatus
from .schemas.phases import OrderPhase
from .schemas import (
    StateMachineResult,
    Selection,
    ParsedItemEntry,
    ParsedItem,
)
from .checkout_messages import got_it_anything_else, build_inapplicable_note
from .utils.text import format_english_list
from .utils.constants import is_price_metadata_key

if TYPE_CHECKING:
    from .models import OrderTask
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
    return list(item.selections)


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
    if item.selections:
        for sel in item.selections:
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
        #    Pass skip_first_question=True so all items are added first, then config questions
        #    are asked by process_items() after all items are added
        result = self.item_adder_handler.add_item(
            item_type=item.item_type,
            order=order,
            quantity=item.quantity,
            skip_first_question=True,  # Defer config questions until all items are added
            item_name=item.item_name,
            extracted_selections=selections,
            original_input=item.original_text,
            unavailable_selections=item.unavailable_selections if item.unavailable_selections else None,
            unmatched_selections=item.unmatched_selections if item.unmatched_selections else None,
            ambiguous_selections=item.ambiguous_selections if item.ambiguous_selections else None,
            special_instructions=item.special_instructions if item.special_instructions else None,
            inapplicable_attributes=item.inapplicable_attributes if item.inapplicable_attributes else None,
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
            summary = build_item_summary(item)

            # If add_item returned a result with a message (e.g., "We don't have X"),
            # return it so it's not lost. This handles the case where _create_configurable_item
            # already called get_first_question and returned an "unavailable" message.
            # The caller (process_items) will return this message directly instead of
            # calling get_first_question again (which would lose the message since
            # unavailable_selections is cleared after generating the message).
            if result.message:
                return order, summary, result

            # Return None as third element so process_items() continues to add ALL items
            # before starting configuration. The third element is ONLY for true disambiguation
            # (when no item was added and we need to ask which item the user meant).
            # Config questions (like "Would you like it toasted?") are handled AFTER all items
            # are added, via items_needing_config logic in process_items().
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

        # Track disambiguation for items that need it - we'll handle it after
        # adding all items that CAN be added without disambiguation
        pending_disambiguation: StateMachineResult | None = None
        disambiguation_item_name: str | None = None

        for idx, parsed_item in enumerate(parsed.parsed_items):
            items_before_count = len(order.items.items)
            order, summary, disambiguation_result = self.add_parsed_item(parsed_item, order)

            # Check if disambiguation was triggered
            if disambiguation_result:
                # Store the first disambiguation result - we'll return it after processing all items
                if pending_disambiguation is None:
                    pending_disambiguation = disambiguation_result
                    disambiguation_item_name = parsed_item.item_name or parsed_item.item_type
                    logger.info("Disambiguation needed for '%s', continuing to process other items",
                               disambiguation_item_name)
                else:
                    # Multiple items need disambiguation - store this one for later
                    remaining_item = parsed_item.model_dump() if hasattr(parsed_item, 'model_dump') else parsed_item.__dict__
                    if not order.pending_parsed_items:
                        order.pending_parsed_items = []
                    order.pending_parsed_items.append(remaining_item)
                    logger.info("Stored additional disambiguation item for later: %s",
                               parsed_item.item_name or parsed_item.item_type)
                continue  # Continue processing other items

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

        # If disambiguation is pending, handle it now after processing all other items
        if pending_disambiguation:
            return self._build_disambiguation_response(
                pending_disambiguation, added_items, parsed, order,
            )

        if not summaries:
            return None

        result = self._start_item_configuration(added_items, summaries, order)

        # Prepend note about unrecognized items from multi-item input
        if parsed.unrecognized_item_names and result:
            names = format_english_list(parsed.unrecognized_item_names)
            if len(parsed.unrecognized_item_names) == 1:
                note = f"I don't have {names} on our menu."
            else:
                note = f"I don't have {names} on our menu."
            result = StateMachineResult(
                message=f"{note} {result.message}",
                order=result.order,
                quick_replies=result.quick_replies,
            )

        return result

    def _build_disambiguation_response(
        self,
        pending_disambiguation: StateMachineResult,
        added_items: list[tuple[str, str, str]],
        parsed: "OpenInputResponse",
        order: "OrderTask",
    ) -> StateMachineResult:
        """Queue added items for config and augment disambiguation message."""
        # Queue any items that were added and need configuration
        config_names = []
        for item_id, display_name, item_type in added_items:
            item = order.items.get_item_by_id(item_id)
            if item and item.status == TaskStatus.IN_PROGRESS:
                order.queue_item_for_config(item_id, item_name=display_name)
                config_names.append(display_name)
                logger.info("Queued %s (%s) for config before disambiguation", display_name, item_id[:8])
        if config_names:
            order.multi_item_config_names = config_names

        # Build message that acknowledges all items (both added and needing disambiguation)
        # Consolidate identical items: ["cookie", "cookie"] -> ["two cookies"]
        from collections import Counter
        item_counts: Counter[str] = Counter()
        for p in parsed.parsed_items:
            name = p.item_name or menu_cache.get_item_type_display_name(p.item_type) or p.item_type
            item_counts[name] += p.quantity if p.quantity > 1 else 1

        all_item_names = []
        for name, count in item_counts.items():
            if count > 1:
                from orderbot.cache.base import pluralize
                plural_name = pluralize(name) if not name.endswith('s') else name
                from orderbot.tasks.parsers.quantity_utils import NUM_TO_WORD
                count_word = NUM_TO_WORD.get(count, str(count))
                all_item_names.append(f"{count_word} {plural_name}")
            else:
                all_item_names.append(name)

        # Modify the disambiguation message to acknowledge the full order
        msg = pending_disambiguation.message
        if len(parsed.parsed_items) > 1:
            full_order_summary = format_english_list(all_item_names)
            if msg.startswith("We have a few options for "):
                msg = f"Got it, {full_order_summary}. {msg}"
            elif msg.startswith("Got it, for the "):
                rest = msg[16:]
                period_pos = rest.find(". ")
                if period_pos != -1:
                    item_ref = rest[:period_pos]
                    question = rest[period_pos + 2:]
                    if question:
                        question = question[0].lower() + question[1:]
                    rest = f"{item_ref}, {question}"
                msg = f"Got it, {full_order_summary}. For the {rest}"
            elif msg.startswith("Got it, "):
                msg = f"Got it, {full_order_summary}. " + msg[8:].capitalize()

            pending_disambiguation = StateMachineResult(
                message=msg,
                order=pending_disambiguation.order,
                quick_replies=pending_disambiguation.quick_replies,
            )

        logger.info("Returning disambiguation result after adding %d other items", len(added_items))
        return pending_disambiguation

    def _start_item_configuration(
        self,
        added_items: list[tuple[str, str, str]],
        summaries: list[str],
        order: "OrderTask",
    ) -> StateMachineResult:
        """Find items needing config, queue them, and delegate first question."""
        items_needing_config: list[tuple[str, str, str]] = []
        for item_id, display_name, item_type in added_items:
            item = order.items.get_item_by_id(item_id)
            if item and item.status == TaskStatus.IN_PROGRESS:
                items_needing_config.append((item_id, display_name, item_type))

        logger.info("Items needing configuration: %d", len(items_needing_config))

        if not items_needing_config:
            # Check added items for inapplicable attributes (e.g., "large coke")
            notes: list[str] = []
            for item_id, display_name, item_type in added_items:
                item = order.items.get_item_by_id(item_id)
                if item:
                    note = build_inapplicable_note(item)
                    if note:
                        notes.append(note)

            items_str = format_english_list(summaries)
            message = got_it_anything_else(items_str)
            if notes:
                message = " ".join(notes) + " " + message
            return StateMachineResult(message=message, order=order)

        # Queue items 2+ for later configuration
        order.multi_item_config_names = [name for _, name, _ in items_needing_config]
        for item_id, item_name, item_type in items_needing_config[1:]:
            order.queue_item_for_config(item_id, item_name=item_name)
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

