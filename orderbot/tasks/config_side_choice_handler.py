"""
Side Choice Handler for Order State Machine.

Handles component slot choices (e.g., "Would you like a side?") which create
bundled child MenuItemTask items linked to a parent item.

Extracted from config_helper_handler.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import OrderPhase, StateMachineResult
from .parsers import parse_side_choice, extract_attribute_values
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)


class ConfigSideChoiceHandler:
    """
    Handles component slot choices that create bundled child items.

    This is a data-driven handler that works with component slots from the
    database. The chosen option becomes a separate MenuItemTask linked to
    the parent via bundle fields.
    """

    def __init__(
        self,
        config: "HandlerConfig",
    ):
        """
        Initialize the side choice handler.

        Args:
            config: HandlerConfig with shared dependencies.
        """
        self.model = config.model
        self._get_next_question = config.get_next_question

    def handle_side_choice(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle component slot choice - creates bundled child MenuItemTask.

        This is a data-driven handler that works with component slots from the
        database. The chosen option becomes a separate MenuItemTask linked to
        the parent via bundle fields.

        Flow:
        1. Load component slot options from database
        2. Parse user's choice using generic parser
        3. Create bundled child MenuItemTask with proper price_rule
        4. Let slot orchestrator pick up the new incomplete child item (if configurable)
        """
        # Import here to avoid circular dependency
        from .state_machine import _check_redirect_to_pending_item

        parent_item_type = item.menu_item_type
        question_text = f"Would you like a side with your {item.menu_item_name}?"

        # Load component slot from database (data-driven)
        slot_config = menu_cache.get_component_slot(parent_item_type, "side") if parent_item_type else None

        # Build valid_answers and options list from component slot options
        valid_answers: set[str] = set()
        valid_options: list[dict] = []
        slot_options_by_slug: dict[str, dict] = {}

        if slot_config:
            question_text = slot_config.get("prompt_text") or question_text
            slot_options = slot_config.get("options", [])

            for opt in slot_options:
                # Option can reference an item_type or a specific menu_item
                opt_type = opt.get("allowed_item_type")
                opt_menu_item_id = opt.get("allowed_menu_item_id")
                display_name = opt.get("display_name", "")
                price_rule = opt.get("price_rule", "included")

                if opt_type:
                    # Item type option (e.g., "bagel")
                    slug = opt_type
                    if not display_name:
                        display_name = menu_cache.get_item_type_display_name(opt_type)
                elif opt_menu_item_id:
                    # Specific menu item option (e.g., fruit salad)
                    slug = f"menu_item_{opt_menu_item_id}"
                    # Look up display name from menu item if not provided
                    if not display_name:
                        menu_item_info = menu_cache.get_menu_item_by_id(opt_menu_item_id)
                        if menu_item_info:
                            display_name = menu_item_info.get("name", f"Item {opt_menu_item_id}")
                else:
                    continue  # Skip invalid options

                # Store for lookup after parsing
                slot_options_by_slug[slug.lower()] = {
                    **opt,
                    "slug": slug,
                    "display_name": display_name,
                }

                # Build parser options
                valid_answers.add(slug.lower())
                valid_answers.add(display_name.lower())
                # Use set to avoid duplicate aliases (e.g. when slug="bagel" and display_name="Bagel")
                aliases = list({slug.lower(), display_name.lower()})
                valid_options.append({
                    "slug": slug,
                    "display_name": display_name,
                    "aliases": aliases,
                })

        redirect = _check_redirect_to_pending_item(
            user_input, item, order, question_text,
            valid_answers=valid_answers if valid_answers else None
        )
        if redirect:
            return redirect

        # Parse the side choice using generic data-driven parser
        parsed = parse_side_choice(
            user_input,
            item.menu_item_name,
            valid_options=valid_options,
            question_text=question_text,
            model=self.model,
        )

        if parsed.wants_cancel:
            item.mark_skipped()
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message="No problem, I've removed that. Anything else?",
                order=order,
            )

        if parsed.unclear or not parsed.value:
            return StateMachineResult(
                message=f"{question_text.replace(' with it?', '')} with your {item.menu_item_name}?",
                order=order,
            )

        # Look up the matched option
        chosen_slug = str(parsed.value).lower()
        chosen_option = slot_options_by_slug.get(chosen_slug)

        if not chosen_option:
            # Try matching by display name
            for opt_slug, opt_data in slot_options_by_slug.items():
                if opt_data.get("display_name", "").lower() == chosen_slug:
                    chosen_option = opt_data
                    break

        if not chosen_option:
            # Fallback - couldn't match option
            return StateMachineResult(
                message=f"I didn't quite catch that. {question_text}",
                order=order,
            )

        # Initialize bundle on parent if not already done
        bundle_id = item.bundle_id
        if not bundle_id:
            bundle_id = item.start_bundle()

        # Create child MenuItemTask based on option type
        price_rule = chosen_option.get("price_rule", "included")
        opt_item_type = chosen_option.get("allowed_item_type")
        opt_menu_item_id = chosen_option.get("allowed_menu_item_id")

        # Convert included_price_cents to dollars (None means entire base is free)
        included_price_cents = chosen_option.get("included_price_cents")
        bundle_included_price = included_price_cents / 100.0 if included_price_cents else None

        if opt_item_type:
            # Configurable item type (e.g., bagel - needs bread choice)
            child_display_name = menu_cache.get_item_type_display_name(opt_item_type)

            # Extract attributes from the side choice input (e.g., "plain bagel" -> bread=plain)
            # This prevents re-asking about attributes the user already specified
            pre_filled_attrs, _ = extract_attribute_values(user_input, opt_item_type)
            logger.info(
                "SIDE_CHOICE: Extracted attributes from '%s' for type '%s': %s",
                user_input, opt_item_type, pre_filled_attrs
            )

            child_item = MenuItemTask(
                menu_item_name=child_display_name,
                menu_item_type=opt_item_type,
                unit_price=0.0 if price_rule == "included" else None,  # Base is free for included
                bundle_id=bundle_id,
                bundle_parent_item_id=item.id,
                bundle_slot="side",
                bundle_price_rule=price_rule,
                bundle_included_price=bundle_included_price,
            )

            # Apply pre-filled attributes to the child item
            for attr_name, attr_value in pre_filled_attrs.items():
                if attr_value is not None:
                    child_item[attr_name] = attr_value

            # Check if the item type requires configuration
            # Look for attributes that are required and need to be asked
            side_attrs = menu_cache.get_item_type_attributes(opt_item_type)
            has_required_attrs = any(
                attr_config.get("is_required", False) and attr_config.get("ask_in_conversation", False)
                for attr_config in side_attrs.values()
            )

            # Fallback: if no explicit is_required, check if there are any single_select
            # attributes that ask_in_conversation - these typically need user input
            if not has_required_attrs:
                has_required_attrs = any(
                    attr_config.get("ask_in_conversation", False)
                    and attr_config.get("input_type") == "single_select"
                    for attr_config in side_attrs.values()
                )

            if has_required_attrs:
                child_item.mark_in_progress()  # Needs configuration
            else:
                child_item.mark_complete()  # No configuration needed

        else:
            # Specific menu item (e.g., fruit salad - no configuration needed)
            menu_item_info = menu_cache.get_menu_item_by_id(opt_menu_item_id)
            child_display_name = menu_item_info.get("name", "Side") if menu_item_info else "Side"
            child_item_type = menu_item_info.get("item_type_slug") if menu_item_info else None

            child_item = MenuItemTask(
                menu_item_name=child_display_name,
                menu_item_id=opt_menu_item_id,
                menu_item_type=child_item_type,
                unit_price=0.0 if price_rule == "included" else (menu_item_info.get("base_price", 0) if menu_item_info else 0),
                bundle_id=bundle_id,
                bundle_parent_item_id=item.id,
                bundle_slot="side",
                bundle_price_rule=price_rule,
                bundle_included_price=bundle_included_price,
            )
            child_item.mark_complete()  # Specific menu items don't need configuration

        # Add the child item to the order
        order.items.add_item(child_item)

        # Check if parent item has remaining mandatory attributes to ask
        # (e.g., omelette still needs cheese, toppings after side_choice is done)
        parent_item_type = item.menu_item_type
        if parent_item_type:
            parent_attrs = menu_cache.get_item_type_attributes(parent_item_type)
            # Find attributes that are ask_in_conversation and not yet answered
            # Exclude side_choice since we just answered it
            unanswered_parent_attrs = []
            for attr_slug, attr_config in parent_attrs.items():
                if attr_slug == "side_choice":
                    continue  # Just answered
                if not attr_config.get("ask_in_conversation", False):
                    continue  # Not asked in conversation
                # Check if this attribute has been answered
                if attr_slug not in item.attribute_values:
                    unanswered_parent_attrs.append(attr_slug)

            # Mark side_choice as answered on the parent
            side_choice_value = chosen_option.get("slug") or chosen_option.get("display_name")
            item["side_choice"] = side_choice_value

            # If side choice is a configurable item type (e.g., bagel), and parent has an
            # attribute with the same name, mark it as declined. The child item handles its
            # own configuration, so we don't want to ask the same question on the parent.
            # E.g., omelette has both side_choice=bagel AND a "bagel" attribute - redundant.
            if opt_item_type and opt_item_type in unanswered_parent_attrs:
                item[opt_item_type] = None  # Mark as declined/not applicable
                unanswered_parent_attrs.remove(opt_item_type)
                logger.info(
                    "SIDE_CHOICE: Marked parent's '%s' attribute as declined (child handles it)",
                    opt_item_type
                )

            if unanswered_parent_attrs:
                # Parent still has questions - keep it in progress
                logger.info(
                    "SIDE_CHOICE: Parent %s has %d unanswered attributes: %s - keeping IN_PROGRESS",
                    item.menu_item_name, len(unanswered_parent_attrs), unanswered_parent_attrs
                )
                item.mark_in_progress()  # Keep parent in progress
            else:
                # No more questions for parent - mark complete
                item.mark_complete()
        else:
            # No item type - mark complete (shouldn't happen but fallback)
            item.mark_complete()

        # Clear pending state
        order.clear_pending()

        # Let slot orchestrator pick up the next incomplete item
        # Priority: child item if it needs config, then parent if it needs more questions
        if self._get_next_question:
            return self._get_next_question(order)

        # Fallback: return simple acknowledgment
        return StateMachineResult(
            message="Got it. Anything else?",
            order=order,
        )
