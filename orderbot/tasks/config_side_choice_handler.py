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
from .config.attribute_resolver import get_unanswered_mandatory
from .parsers.validators import parse_side_choice_deterministic as parse_side_choice
from .parsers.deterministic import get_pipeline
from .handler_config import BaseHandler
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)

# Centralized constants linking the "side_choice" attribute to the "side"
# component slot. These live here (not in a generic constants module) because
# the relationship is specific to the component-slot subsystem. A full
# data-driven solution would add a DB FK from attribute -> slot; until then,
# these constants are the single place to change.
SIDE_CHOICE_ATTR_SLUG = "side_choice"
SIDE_SLOT_NAME = "side"

# Get shared pipeline instance
_pipeline = get_pipeline()


class ConfigSideChoiceHandler(BaseHandler):
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
        super().__init__(config)

    def _load_side_choice_options(
        self,
        parent_item_type: str | None,
        item_name: str,
    ) -> tuple[set[str], list[dict], dict[str, dict], str]:
        """Load component slot options from DB.

        Returns (valid_answers, valid_options, slot_options_by_slug, question_text).
        """
        question_text = f"Would you like a side with your {item_name}?"
        valid_answers: set[str] = set()
        valid_options: list[dict] = []
        slot_options_by_slug: dict[str, dict] = {}

        slot_config = menu_cache.get_component_slot(parent_item_type, SIDE_SLOT_NAME) if parent_item_type else None
        if not slot_config:
            return valid_answers, valid_options, slot_options_by_slug, question_text

        question_text = slot_config.get("prompt_text") or question_text
        slot_options = slot_config.get("options", [])

        for opt in slot_options:
            opt_type = opt.get("allowed_item_type")
            opt_menu_item_id = opt.get("allowed_menu_item_id")
            display_name = opt.get("display_name", "")

            if opt_type:
                slug = opt_type
                if not display_name:
                    display_name = menu_cache.get_item_type_display_name(opt_type)
            elif opt_menu_item_id:
                slug = f"menu_item_{opt_menu_item_id}"
                if not display_name:
                    menu_item_info = menu_cache.get_menu_item_by_id(opt_menu_item_id)
                    if menu_item_info:
                        display_name = menu_item_info.get("name", f"Item {opt_menu_item_id}")
            else:
                continue

            slot_options_by_slug[slug.lower()] = {
                **opt,
                "slug": slug,
                "display_name": display_name,
            }
            valid_answers.add(slug.lower())
            valid_answers.add(display_name.lower())
            aliases = list({slug.lower(), display_name.lower()})
            valid_options.append({
                "slug": slug,
                "display_name": display_name,
                "aliases": aliases,
            })

        return valid_answers, valid_options, slot_options_by_slug, question_text

    def _create_configurable_child(
        self,
        user_input: str,
        item: MenuItemTask,
        chosen_option: dict,
        bundle_id: str,
        default_modifiers: list[dict],
    ) -> MenuItemTask:
        """Create a child MenuItemTask for a configurable item type (e.g., bagel)."""
        opt_item_type = chosen_option.get("allowed_item_type")
        price_rule = chosen_option.get("price_rule", "included")
        included_price_cents = chosen_option.get("included_price_cents")
        bundle_included_price = included_price_cents / 100.0 if included_price_cents else None

        child_display_name = menu_cache.get_item_type_display_name(opt_item_type)

        result = _pipeline.extract_attributes(user_input, opt_item_type)
        pre_filled_attrs = result.values
        logger.info(
            "SIDE_CHOICE: Extracted attributes from '%s' for type '%s': %s",
            user_input, opt_item_type, pre_filled_attrs
        )

        child_item = MenuItemTask(
            menu_item_name=child_display_name,
            menu_item_type=opt_item_type,
            unit_price=0.0 if price_rule == "included" else None,
            bundle_id=bundle_id,
            bundle_parent_item_id=item.id,
            bundle_slot=SIDE_SLOT_NAME,
            bundle_price_rule=price_rule,
            bundle_included_price=bundle_included_price,
        )

        _apply_default_modifiers(child_item, default_modifiers, opt_item_type)

        for attr_name, attr_value in pre_filled_attrs.items():
            if attr_value is not None:
                child_item[attr_name] = attr_value

        side_attrs = menu_cache.get_item_type_attributes(opt_item_type)
        has_required_attrs = any(
            attr_config.get("is_required", False) and attr_config.get("ask_in_conversation", False)
            for attr_config in side_attrs.values()
        )
        if not has_required_attrs:
            has_required_attrs = any(
                attr_config.get("ask_in_conversation", False)
                and attr_config.get("input_type") == "single_select"
                for attr_config in side_attrs.values()
            )

        if has_required_attrs:
            child_item.mark_in_progress()
        else:
            child_item.mark_complete()

        return child_item

    def _create_specific_child(
        self,
        item: MenuItemTask,
        chosen_option: dict,
        bundle_id: str,
        default_modifiers: list[dict],
    ) -> MenuItemTask:
        """Create a child MenuItemTask for a specific menu item (e.g., fruit salad)."""
        opt_menu_item_id = chosen_option.get("allowed_menu_item_id")
        price_rule = chosen_option.get("price_rule", "included")
        included_price_cents = chosen_option.get("included_price_cents")
        bundle_included_price = included_price_cents / 100.0 if included_price_cents else None

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
            bundle_slot=SIDE_SLOT_NAME,
            bundle_price_rule=price_rule,
            bundle_included_price=bundle_included_price,
        )

        if default_modifiers and child_item_type:
            _apply_default_modifiers(child_item, default_modifiers, child_item_type)

        child_item.mark_complete()
        return child_item

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
        from .state_machine import _check_redirect_to_pending_item

        parent_item_type = item.menu_item_type
        valid_answers, valid_options, slot_options_by_slug, question_text = (
            self._load_side_choice_options(parent_item_type, item.menu_item_name)
        )

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
            # User declined the side choice — skip it, don't remove the item
            if parent_item_type:
                item.selections = [m for m in item.selections if m.get("category") != SIDE_CHOICE_ATTR_SLUG]
                item.add_selection("no_side", SIDE_CHOICE_ATTR_SLUG, display_name="No Side")

                # Mark all item-type-based side options as declined on parent
                # (e.g., if options include "bagel", mark parent's "bagel" attr as declined)
                parent_attrs = menu_cache.get_item_type_attributes(parent_item_type)
                for _opt_slug, opt_data in slot_options_by_slug.items():
                    opt_item_type = opt_data.get("allowed_item_type")
                    if opt_item_type and opt_item_type in parent_attrs:
                        item[opt_item_type] = None
                        logger.info(
                            "SIDE_CHOICE_DECLINE: Marked parent's '%s' attribute as declined",
                            opt_item_type,
                        )

                # Check remaining unanswered mandatory attributes
                unanswered = get_unanswered_mandatory(item, parent_item_type)
                if unanswered:
                    item.mark_in_progress()
                else:
                    item.mark_complete()

            order.clear_pending()

            # Let slot orchestrator pick up next question
            if self._get_next_question:
                return self._get_next_question(order)

            return StateMachineResult(
                message="No problem! Anything else?",
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
        opt_item_type = chosen_option.get("allowed_item_type")
        default_modifiers = chosen_option.get("default_modifiers", [])

        if opt_item_type:
            child_item = self._create_configurable_child(
                user_input, item, chosen_option, bundle_id, default_modifiers,
            )
        else:
            child_item = self._create_specific_child(
                item, chosen_option, bundle_id, default_modifiers,
            )

        # Add the child item to the order
        order.items.add_item(child_item)

        # Set side_choice and decline redundant parent attrs BEFORE checking
        # unanswered, so get_unanswered_mandatory correctly excludes them.
        if parent_item_type:
            # Mark side_choice as answered on the parent
            # Normalize the value to use global attribute option slug for skip rule matching
            side_choice_value = self._normalize_side_choice_value(
                chosen_option, parent_item_type
            )
            item[SIDE_CHOICE_ATTR_SLUG] = side_choice_value

            # If side choice is a configurable item type (e.g., bagel), and parent has an
            # attribute with the same name, mark it as declined. The child item handles its
            # own configuration, so we don't want to ask the same question on the parent.
            # E.g., omelette has both side_choice=bagel AND a "bagel" attribute - redundant.
            if opt_item_type:
                parent_attrs = menu_cache.get_item_type_attributes(parent_item_type)
                if opt_item_type in parent_attrs:
                    item[opt_item_type] = None  # Mark as declined/not applicable
                    logger.info(
                        "SIDE_CHOICE: Marked parent's '%s' attribute as declined (child handles it)",
                        opt_item_type
                    )

            # Use get_unanswered_mandatory which correctly handles:
            # - skip rules from the side_choice value
            # - auto-populated defaults (is_default=True) treated as unanswered
            unanswered = get_unanswered_mandatory(item, parent_item_type)

            if unanswered:
                # Parent still has questions - keep it in progress
                logger.info(
                    "SIDE_CHOICE: Parent %s has %d unanswered attributes: %s - keeping IN_PROGRESS",
                    item.menu_item_name, len(unanswered),
                    [a["slug"] for a in unanswered]
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

    def _normalize_side_choice_value(
        self,
        chosen_option: dict,
        parent_item_type: str | None,
    ) -> str:
        """Normalize side_choice value to use global attribute option slug.

        This ensures skip rules can match. Component slot options may have
        slugs like "menu_item_9927" but the skip rules are keyed by
        global_attribute_options slugs like "fruit_salad".

        Falls back to the chosen option's slug or display_name if no match.
        """
        # Get the display name to match against global attribute options
        display_name = chosen_option.get("display_name", "")

        # Try to find matching global attribute option by display name
        if parent_item_type:
            side_choice_attrs = menu_cache.get_item_type_attributes(parent_item_type)
            side_choice_config = side_choice_attrs.get(SIDE_CHOICE_ATTR_SLUG, {})
            options = side_choice_config.get("options", [])

            for opt in options:
                # Match by display name (case-insensitive)
                opt_display = opt.get("display_name", "")
                if opt_display.lower() == display_name.lower():
                    opt_slug = opt.get("slug")
                    if opt_slug:
                        logger.info(
                            "SIDE_CHOICE: Normalized '%s' to global attr option slug '%s'",
                            display_name, opt_slug
                        )
                        return opt_slug

        # Fallback to component slot slug or display name
        return chosen_option.get("slug") or display_name


def _apply_default_modifiers(
    child_item: MenuItemTask,
    default_modifiers: list[dict],
    item_type_slug: str,
) -> None:
    """Apply default modifiers from slot option configuration to a child item.

    These are pre-configured defaults (e.g., size=small for included fruit salad,
    or butter for included bagel) that get applied when the option is selected.

    Args:
        child_item: The newly created MenuItemTask to apply defaults to.
        default_modifiers: List of resolved modifier dicts from cache.
        item_type_slug: The item type slug for attribute lookups.
    """
    for default in default_modifiers:
        mod_type = default.get("type")

        if mod_type == "attribute_option":
            attr_slug = default.get("attribute_slug")
            opt_slug = default.get("option_slug")
            if attr_slug and opt_slug:
                child_item[attr_slug] = opt_slug
                logger.info(
                    "SIDE_CHOICE_DEFAULT: Applied attribute default %s=%s to %s",
                    attr_slug, opt_slug, child_item.menu_item_name,
                )

        elif mod_type == "ingredient":
            ing_slug = default.get("ingredient_slug")
            ing_category = default.get("ingredient_category")
            quantity = default.get("quantity", 1)
            if ing_slug and ing_category:
                # Find the attribute slug that corresponds to this ingredient category
                item_attrs = menu_cache.get_item_type_attributes(item_type_slug)
                target_attr = None
                for attr_slug, attr_config in item_attrs.items():
                    if attr_config.get("ingredient_category") == ing_category:
                        target_attr = attr_slug
                        break

                if target_attr:
                    child_item.add_selection(
                        slug=ing_slug,
                        category=target_attr,
                        quantity=quantity,
                        is_default=True,
                    )
                    logger.info(
                        "SIDE_CHOICE_DEFAULT: Applied ingredient default %s (category=%s) to %s",
                        ing_slug, target_attr, child_item.menu_item_name,
                    )
