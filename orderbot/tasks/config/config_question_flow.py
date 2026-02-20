from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize
from ..models import OrderTask, MenuItemTask
from ..pending_fields import PendingField
from ..schemas import StateMachineResult, OrderPhase
from ..parsers.constants import DEFAULT_PAGINATION_SIZE
from ..checkout_messages import got_it_anything_else
from ..utils.text import format_display_list
from .attribute_resolver import (
    get_unanswered_mandatory,
    get_unanswered_optional,
)

if TYPE_CHECKING:
    from .handler import MenuItemConfigHandler
    from ..models.pending_states import PendingUnmatchedPagination

logger = logging.getLogger(__name__)


class ConfigQuestionFlow:

    def __init__(self, parent: MenuItemConfigHandler) -> None:
        self._parent = parent

    def configure_next_incomplete_item(
        self, order: OrderTask, item_type: str | None = None
    ) -> StateMachineResult:
        """
        Find and configure the next incomplete menu item of supported types.

        This method provides multi-item orchestration similar to bagel/coffee handlers.
        It iterates through items, asks required questions, and tracks progress.

        Args:
            order: The order task containing all items
            item_type: Optional specific item type to configure. If None,
                      configures all supported item types.

        Returns:
            StateMachineResult with next question or completion message
        """
        from ..models import TaskStatus
        from ..message_builder import MessageBuilder

        # Determine which item types to process
        # Get configurable item types from database (item types with linked attributes)
        configurable_types = menu_cache.get_configurable_item_types()
        if item_type:
            target_types = {item_type} & configurable_types
        else:
            target_types = configurable_types

        if not target_types:
            # No supported types to configure
            return self._parent._get_next_question(order)

        # Collect all items of the target types
        target_items = [
            item for item in order.items.items
            if isinstance(item, MenuItemTask)
            and item.menu_item_type in target_types
        ]

        if not target_items:
            return self._parent._get_next_question(order)

        # Group items by type for ordinal messaging
        items_by_type: dict[str, list[MenuItemTask]] = {}
        for item in target_items:
            t = item.menu_item_type
            if t not in items_by_type:
                items_by_type[t] = []
            items_by_type[t].append(item)

        # Process each incomplete item
        for item in target_items:
            if item.status != TaskStatus.IN_PROGRESS:
                continue

            item_type_slug = item.menu_item_type
            same_type_items = items_by_type.get(item_type_slug, [item])
            same_type_count = len(same_type_items)

            # Build ordinal descriptor if multiple items of same type
            if same_type_count > 1:
                item_num = next(
                    (i + 1 for i, it in enumerate(same_type_items) if it.id == item.id),
                    1
                )
                ordinal = MessageBuilder.get_ordinal(item_num)
                item_desc = f"the {ordinal} {item.menu_item_name}"
            else:
                item_desc = f"your {item.menu_item_name}"

            # Get unanswered mandatory attributes
            unanswered = get_unanswered_mandatory(item, item_type_slug)

            if unanswered:
                first_attr = unanswered[0]
                # Ensure multi_item_config_names is set when multiple same-type
                # items exist, so _ask_attribute_question generates ordinals.
                if same_type_count > 1 and not order.multi_item_config_names:
                    order.multi_item_config_names = [
                        it.get_display_name() for it in same_type_items
                    ]
                return self._ask_attribute_question(item, order, first_attr, is_first_question=False)

            # No mandatory questions left - check if customization was offered
            if not item.customization_offered:
                return self._ask_customization_checkpoint(item, order)

            # Item is complete - recalculate price and mark complete
            self._parent._recalculate_item_price(item)
            item.mark_complete()

        # All target items are complete - summarize and return
        completed_items = [
            item for item in target_items
            if item.status == TaskStatus.COMPLETE
        ]

        if completed_items:
            last_item = completed_items[-1]
            summary = last_item.get_summary()

            # Count identical items at the end for pluralization
            count = 0
            for item in reversed(completed_items):
                if item.get_summary() == summary:
                    count += 1
                else:
                    break

            if count > 1:
                summary = f"{count} {summary}s" if not summary.endswith("s") else f"{count} {summary}"

            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message=got_it_anything_else(summary),
                order=order,
            )

        # Fallback to generic next question
        return self._parent._get_next_question(order)

    def _advance_to_next_question(
        self, item: MenuItemTask, order: OrderTask, current_attr: dict,
        matched_choice: str | None = None,
        use_multi_item_orchestration: bool = False
    ) -> StateMachineResult:
        """Advance to the next question after answering current attribute.

        Args:
            item: The menu item being configured
            order: The current order
            current_attr: The attribute that was just answered
            matched_choice: The display name of the choice the user made (for acknowledgment)
            use_multi_item_orchestration: If True, use configure_next_incomplete_item()
                to handle multiple items of the same type
        """
        item_type = item.menu_item_type
        logger.info(
            "ADVANCE_TO_NEXT: after attr=%s, item_type=%s, attribute_values=%s",
            current_attr.get("slug"), item_type, item.attribute_values
        )

        # Recalculate price after each attribute answer (data-driven pricing)
        # This handles variant pricing (size), upcharges, and any pricing model
        self._parent._recalculate_item_price(item)

        # Check if we're in mandatory phase or optional phase
        if current_attr.get("ask_in_conversation", True):
            # Just answered a mandatory question, check for more
            unanswered_mandatory = get_unanswered_mandatory(item, item_type)
            if unanswered_mandatory:
                next_attr = unanswered_mandatory[0]
                result = self._ask_attribute_question(item, order, next_attr)
                # Prepend acknowledgment if provided
                if matched_choice and result.message:
                    result.message = f"Got it, {matched_choice}. {result.message}"
                return result
            else:
                # All mandatory done for this item
                if use_multi_item_orchestration:
                    # Use multi-item orchestration to check for more items
                    result = self.configure_next_incomplete_item(order, item_type)
                    if matched_choice and result.message:
                        # Strip leading "Got it, " from result to avoid double "Got it"
                        msg = result.message
                        if msg.startswith("Got it, "):
                            msg = msg[len("Got it, "):]
                        result.message = f"Got it, {matched_choice}. {msg}"
                    return result
                else:
                    # Single-item flow - go to checkpoint
                    return self._ask_customization_checkpoint(item, order, acknowledgment=matched_choice)
        else:
            # Just answered an optional question, ask for more customizations
            return self._ask_more_customizations(item, order, matched_choice)

    def _ask_attribute_question(
        self, item: MenuItemTask, order: OrderTask, attr: dict,
        is_first_question: bool = False
    ) -> StateMachineResult:
        """
        Ask the question for a specific attribute.

        Does NOT list options by default - user must ask "what options?" to see them.
        For boolean attributes (like toasted), uses simple yes/no question.
        Uses DB's question_text if configured, otherwise generates a natural question.

        For multi-item configurations, uses ordinal references like "the first one", "the second one".
        """
        # Handle unavailable selection (early return if applicable)
        unavail_result = self._parent._question_builder.handle_unavailable_selection(item, order, attr)
        if unavail_result:
            return unavail_result

        # Handle unmatched selection (tokens that don't match any option)
        unmatched_result = self._parent._question_builder.handle_unmatched_selection(item, order, attr)
        if unmatched_result:
            return unmatched_result

        # Generate note for inapplicable attributes (e.g., "Heads up, only comes in one size")
        inapplicable_note = self._parent._question_builder.handle_inapplicable_attributes(item)

        # Calculate ordinal position and context for multi-item orders
        ordinal, item_num, has_duplicates = self._parent._question_builder.calculate_item_ordinal(item, order)
        multi_count = len(order.multi_item_config_names) if order.multi_item_config_names else 1
        item_ref = item.get_display_name()

        # Build base question text
        base_question = self._parent._question_builder.build_base_question(
            attr, item_ref, ordinal, has_duplicates, multi_count,
        )
        question = base_question

        # Add acknowledgment prefix for first question of each item
        if is_first_question:
            prefix = self._parent._question_builder.build_first_question_prefix(
                item, order, attr, ordinal, item_num, has_duplicates,
            )
            if prefix:
                # For subsequent items or first-with-duplicates, prefix IS the full question
                if multi_count > 1 and (item_num > 1 or has_duplicates):
                    question = prefix
                else:
                    question = prefix + question

        # Prepend notes before the question
        if inapplicable_note:
            question = inapplicable_note + " " + question

        # Set up order state for receiving the answer
        order.setup_pending_config(item.id, f"{item.menu_item_type}:{attr['slug']}")

        # Build quick replies and optional question suffix via QuickReplyBuilder
        qr, question_suffix, rebuilt_base = self._parent._quick_reply_builder.build(
            attr, base_question, item.menu_item_type,
        )
        if question_suffix:
            question += question_suffix
        if rebuilt_base:
            question = question.replace(base_question, rebuilt_base)

        return StateMachineResult(message=question, order=order, quick_replies=qr)

    def _ask_customization_checkpoint(
        self, item: MenuItemTask, order: OrderTask, acknowledgment: str | None = None
    ) -> StateMachineResult:
        """Ask if user wants to customize with optional attributes.

        Args:
            item: The menu item being configured
            order: The current order
            acknowledgment: Optional acknowledgment message to prepend (e.g., "Butter added")
        """
        item_type = item.menu_item_type
        unanswered_optional = get_unanswered_optional(item, item_type)

        # Always recalculate price after adding a modifier
        # This ensures upcharges are applied immediately, not just when config is complete
        self._parent._recalculate_item_price(item)

        # Build acknowledgment prefix if provided
        ack_prefix = f"Got it, {acknowledgment}. " if acknowledgment else ""

        if not unanswered_optional or item.customization_declined:
            # No optional attributes available (or user explicitly declined customization
            # e.g., "nothing else" in initial input) - complete the item
            item.customization_offered = True
            item.mark_complete()
            order.clear_pending()

            # Check if there are pending parsed items that haven't been added yet
            # This handles the case where disambiguation was triggered and remaining items
            # in the order were stored (e.g., "latte and bagel" - bagel is stored while
            # we disambiguate and configure latte)
            if self._parent._process_pending_parsed_items_callback:
                pending_result = self._parent._process_pending_parsed_items_callback(order)
                if pending_result:
                    return pending_result

            # Check if there are other items queued for configuration
            # This handles the case where disambiguation was triggered after other items
            # were already added (e.g., "an everything bagel and a latte")
            from ..handler_utils import process_next_queued_item
            queued_result = process_next_queued_item(
                order, self._parent, f"after completing {item.get_display_name()}"
            )
            if queued_result:
                return queued_result

            # Check for other incomplete items that need configuration
            # This handles duplicated items (e.g., "make it two hot teas")
            next_result = self._parent._get_next_question(order)
            if next_result and next_result.order.pending_field:
                # Prepend acknowledgment to the next question
                summary = item.get_summary()
                if ack_prefix:
                    return StateMachineResult(
                        message=f"{ack_prefix}{summary}. {next_result.message}",
                        order=next_result.order,
                        quick_replies=next_result.quick_replies,
                    )
                return StateMachineResult(
                    message=f"Got it, {summary}. {next_result.message}",
                    order=next_result.order,
                    quick_replies=next_result.quick_replies,
                )

            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"{ack_prefix}{item.get_summary()}. Anything else?" if ack_prefix else got_it_anything_else(item.get_summary()),
                order=order,
            )

        # Mark that we've reached the checkpoint
        item.customization_offered = True

        order.setup_pending_config(item.id, PendingField.CUSTOMIZATION_CHECKPOINT)

        # List available customization options as individual questions
        options_questions, quick_replies = self._format_checkpoint_questions(unanswered_optional)

        return StateMachineResult(
            message=f"{ack_prefix}Any more changes? {options_questions}",
            order=order,
            quick_replies=quick_replies,
        )

    def _ask_optional_attribute(
        self, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        """Ask the question for a specific optional attribute."""
        options = attr.get("options", [])
        db_question = attr.get("question_text")

        qr = None
        if db_question:
            question = db_question
        elif attr.get("input_type") == "boolean":
            question = f"{attr['display_name']}?"
        elif options:
            # Only list options if there are few enough to be helpful
            if len(options) <= DEFAULT_PAGINATION_SIZE:
                options_text = format_display_list(options)
                question = f"What kind of {attr['display_name'].lower()}? ({options_text})"
                # Build quick replies for inline clickable text
                qr = [{"label": o["display_name"], "value": o["display_name"]} for o in options]
            else:
                # Too many to list in text, but still provide quick replies for clickability
                question = f"What kind of {attr['display_name'].lower()}?"
                qr = [{"label": o["display_name"], "value": o["display_name"]} for o in options]
        else:
            question = f"What {attr['display_name']}?"

        order.setup_pending_config(item.id, f"{item.menu_item_type}:{attr['slug']}")

        return StateMachineResult(message=question, order=order, quick_replies=qr)

    def _ask_more_customizations(
        self, item: MenuItemTask, order: OrderTask, matched_choice: str | None = None
    ) -> StateMachineResult:
        """Ask if user wants more customizations after completing one.

        Args:
            item: The menu item being configured
            order: The current order
            matched_choice: The display name of the choice just made (for acknowledgment)
        """
        item_type = item.menu_item_type
        unanswered = get_unanswered_optional(item, item_type)

        # Always recalculate price after adding a modifier
        # This ensures upcharges are applied immediately, not just when config is complete
        self._parent._recalculate_item_price(item)

        # Build acknowledgment prefix if we have a choice to acknowledge
        ack_prefix = f"Okay, {matched_choice}. " if matched_choice else ""

        if not unanswered:
            # No more options - price already recalculated above, just complete
            item.mark_complete()
            order.clear_pending()

            # Check for other incomplete items that need configuration
            # This handles duplicated items (e.g., "make it two hot teas")
            next_result = self._parent._get_next_question(order)
            if next_result and next_result.order.pending_field:
                # Prepend acknowledgment to the next question
                summary = item.get_summary()
                if ack_prefix:
                    return StateMachineResult(
                        message=f"{ack_prefix}{summary}. {next_result.message}",
                        order=next_result.order,
                        quick_replies=next_result.quick_replies,
                    )
                return StateMachineResult(
                    message=f"Got it, {summary}. {next_result.message}",
                    order=next_result.order,
                    quick_replies=next_result.quick_replies,
                )

            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"{ack_prefix}{item.get_summary()}. Anything else?" if ack_prefix else got_it_anything_else(item.get_summary()),
                order=order,
            )

        # List remaining options as individual questions
        options_questions, quick_replies = self._format_checkpoint_questions(unanswered)

        order.setup_pending_config(item.id, PendingField.CUSTOMIZATION_CHECKPOINT)

        return StateMachineResult(
            message=f"{ack_prefix}Any more changes? {options_questions}",
            order=order,
            quick_replies=quick_replies,
        )

    def _format_checkpoint_questions(self, attrs: list[dict]) -> tuple[str, list[dict[str, str]]]:
        """Format unanswered optional attributes as individual questions with quick replies.

        Prepends a clickable "No?" link so the user can quickly decline all remaining options.
        """
        questions = []
        quick_replies: list[dict[str, str]] = [{"label": "No?", "value": "no"}]
        for attr in attrs:
            q = attr.get("offer_question_text") or attr.get("question_text")
            if not q:
                display = attr.get("display_name") or attr["slug"]
                q = f"Add {display}?"
            questions.append(q)
            display = attr.get("display_name") or attr["slug"]
            quick_replies.append({
                "label": q,
                "value": f"What {pluralize(display.lower())} do you have?",
            })
        return "No? " + " ".join(questions), quick_replies

    def _handle_ambiguous_selection(
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult | None:
        """
        Handle ambiguous selections that need user disambiguation.

        When user says something like "syrup" without specifying which one,
        we need to ask "Which syrup? Vanilla, Hazelnut, Caramel, or Peppermint?"

        Returns StateMachineResult if disambiguation is needed, None otherwise.
        """
        if not item.ambiguous_selections:
            return None

        # Get the first ambiguous selection to resolve
        ambig = item.ambiguous_selections[0]
        attr_slug = ambig.get("attr_slug", "")
        token = ambig.get("token", "")
        matching_options = ambig.get("matching_options", [])

        if not matching_options:
            # No options to disambiguate - shouldn't happen, but clear and continue
            item.ambiguous_selections.pop(0)
            return None

        # Build list of option display names
        from ..utils.text import format_english_list
        option_names = [opt.get("display_name", opt.get("slug", "")) for opt in matching_options]

        # Format options as "Vanilla Syrup, Hazelnut Syrup, Caramel Syrup, or Peppermint Syrup"
        options_str = format_english_list(option_names, conjunction="or")

        # Build the disambiguation question
        # Use the token (e.g., "syrup") in the question
        item_name = item.get_display_name()
        question = f"Got it, for the {item_name}. Which {token}? {options_str}?"

        # Store state for handling the user's response
        # pending_field format: "item_type:attr_slug" so the router knows what attribute this is for
        order.setup_pending_config(item.id, PendingField.AMBIGUOUS_SELECTION)
        # Store the ambiguous selection info so we can process the response
        order.pending_config_queue = [ambig]  # Store as list for compatibility

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in option_names]
        return StateMachineResult(message=question, order=order, quick_replies=qr)

    def _advance_from_pagination(
        self, pagination: PendingUnmatchedPagination, item: MenuItemTask, order: OrderTask,
        matched_choice: str | None = None,
    ) -> StateMachineResult:
        """Look up the attribute from pagination context and advance to next question.

        Delegates to ConfigPaginationHandler.
        """
        return self._parent._pagination_handler.advance_from_pagination(
            pagination, item, order, matched_choice
        )

    def _handle_unmatched_pagination(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle pagination responses for unmatched token messages.

        Delegates to ConfigPaginationHandler.
        """
        return self._parent._pagination_handler.handle_unmatched_pagination(
            user_input, item, order
        )
