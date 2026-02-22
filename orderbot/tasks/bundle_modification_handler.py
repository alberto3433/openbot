"""
Bundle Modification Handler for Order State Machine.

Handles bundle child modifications, cross-attribute matching, and applying
modifications during item configuration.
Split from config_modification_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult
from .parsers.intent_patterns import parse_make_named_item
from .pending_fields import PendingField, UNKNOWN_ATTRIBUTE_SLUG
from .modifier_change_handler import ChangeRequest
from orderbot.cache import menu_cache
from .utils.pricing_utils import safe_recalculate_price
from .utils.option_matcher import OptionMatcher
from .models.utilities import parse_pending_field
from .config.attribute_resolver import get_skipped_attributes
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
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)


class BundleModificationHandler:
    """
    Handles bundle child modifications, cross-attribute matching, and
    applying modifications during item configuration.
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
    ) -> None:
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self._taking_items_handler: "TakingItemsHandler | None" = None

    @property
    def taking_items_handler(self) -> "TakingItemsHandler | None":
        return self._taking_items_handler

    @taking_items_handler.setter
    def taking_items_handler(self, handler: "TakingItemsHandler | None") -> None:
        self._taking_items_handler = handler

    def _replace_or_add_modifier(self, item: MenuItemTask, match: dict, quantity: int = 1) -> None:
        pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
        _replace_or_add(item, match, pricing, quantity)

    def _apply_attribute_option_to_item(self, modifier_lower: str, item: MenuItemTask) -> str | None:
        return _apply_attr_option(modifier_lower, item)

    def _find_bundle_child_by_name(
        self,
        item_name: str,
        parent_item: MenuItemTask,
        order: OrderTask,
    ) -> MenuItemTask | None:
        """Find a bundled child item matching the given name."""
        if not parent_item.bundle_id:
            return None

        children = order.items.get_bundle_children(parent_item.id)
        if not children:
            return None

        name_lower = item_name.lower()
        for child in children:
            child_name = (child.menu_item_name or "").lower()
            child_type = (child.menu_item_type or "").lower()
            if (name_lower in child_name
                    or child_name in name_lower
                    or name_lower == child_type
                    or name_lower in child_type):
                return child

        return None

    # ─── Group 3: Bundle Child Modifications ─────────────────────────

    def handle_modify_bundle_child(
        self,
        user_input: str,
        parent_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle modifications targeting a bundled child item by name.

        When the user says "make the fruit salad a large" while configuring
        the parent omelette, this finds the fruit salad child item and
        applies the "large" modifier to it.
        """
        parsed = parse_make_named_item(user_input)
        if not parsed:
            return None

        item_name, modifier = parsed
        logger.info(
            "BUNDLE_CHILD_MOD: Detected named item modification: item='%s', modifier='%s'",
            item_name, modifier,
        )

        child = self._find_bundle_child_by_name(item_name, parent_item, order)
        if not child:
            logger.debug(
                "BUNDLE_CHILD_MOD: No bundle child matching '%s' found", item_name,
            )
            return None

        logger.info(
            "BUNDLE_CHILD_MOD: Found bundle child '%s' (id=%s), applying modifier '%s'",
            child.menu_item_name, child.id[:8], modifier,
        )

        modifier_lower = modifier.lower()
        applied_name = self._apply_attribute_option_to_item(modifier_lower, child)
        if applied_name:
            pricing = _get_handler_pricing(self)
            safe_recalculate_price(pricing, child, "after bundle child attribute change")
            return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                f"Sure, {applied_name}.", parent_item, order
            )

        logger.debug(
            "BUNDLE_CHILD_MOD: Modifier '%s' did not match any attribute on child '%s'",
            modifier, child.menu_item_name,
        )
        return None

    # ─── Group 4: Cross-Attribute Match ──────────────────────────────

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
        """
        item_type = item.menu_item_type
        if not item_type:
            return None

        _, pending_attr = parse_pending_field(order.pending_field)
        if not pending_attr:
            return None

        try:
            all_attrs = menu_cache.get_item_type_attributes(item_type)
        except (KeyError, ValueError, AttributeError):
            return None

        matcher = OptionMatcher()

        # Priority check: if input exact-matches an option on the PENDING attribute,
        # let the normal attribute handler process it instead of redirecting.
        # This prevents "onion" (valid bread option) from being stolen by toppings.
        pending_config = all_attrs.get(pending_attr)
        if pending_config:
            pending_options = pending_config.get("options", [])
            if pending_options:
                pending_match, _ = matcher.match_single(user_input, pending_options, exact_only=True)
                if pending_match:
                    logger.info(
                        "CROSS_ATTR_PRIORITY: '%s' matches pending attr %s (slug=%s), skipping cross-attr",
                        user_input, pending_attr, pending_match.get("slug"),
                    )
                    return None
                else:
                    slugs = [o.get("slug") for o in pending_options[:5]]
                    logger.info(
                        "CROSS_ATTR_PRIORITY: '%s' did NOT match pending attr %s options (sample slugs: %s)",
                        user_input, pending_attr, slugs,
                    )
            else:
                logger.info("CROSS_ATTR_PRIORITY: pending attr %s has no options", pending_attr)
        else:
            logger.info("CROSS_ATTR_PRIORITY: pending attr '%s' not found in all_attrs (keys: %s)",
                         pending_attr, list(all_attrs.keys()))

        matched_attr_slug: str | None = None
        matched_option: dict | None = None

        for attr_slug, attr_config in all_attrs.items():
            if attr_slug == pending_attr:
                continue

            options = attr_config.get("options", [])
            if not options:
                continue

            match, _ = matcher.match_single(user_input, options, exact_only=True)
            if match:
                if matched_attr_slug is not None:
                    logger.debug(
                        "CROSS_ATTR: Multiple attributes matched for '%s' (%s and %s), skipping",
                        user_input, matched_attr_slug, attr_slug,
                    )
                    return None
                matched_attr_slug = attr_slug
                matched_option = match

        if not matched_attr_slug or not matched_option:
            return None

        from .handler_utils import get_option_display_name
        display_name = get_option_display_name(matched_option)
        item[matched_attr_slug] = matched_option["slug"]

        pricing = _get_handler_pricing(self)
        safe_recalculate_price(pricing, item, "after cross-attribute match")

        logger.info(
            "CROSS_ATTR: Matched '%s' to %s=%s (pending was %s)",
            user_input, matched_attr_slug, matched_option["slug"], pending_attr,
        )

        skipped = get_skipped_attributes(item)
        if pending_attr in skipped:
            logger.info(
                "CROSS_ATTR: Skip rule triggered — %s skips %s, advancing",
                matched_attr_slug, pending_attr,
            )
            item[pending_attr] = None
            order.clear_pending()
            next_result = self.checkout_utils_handler.get_next_question(order)
            msg = f"Got it, {display_name}."
            if next_result and next_result.message:
                next_result.message = f"{msg} {next_result.message}"
            else:
                next_result = StateMachineResult(message=msg, order=order)
            return next_result

        return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
            f"Got it, {display_name}.", item, order
        )

    # ─── Group 7: Apply Modification During Config ───────────────────

    def apply_modification_during_config(
        self,
        change_request: ChangeRequest,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Apply a modification to the item being configured, then continue config.

        Handles the case where a user says something like "make it veggie cream cheese"
        during item configuration.
        """
        new_value = change_request.new_value
        logger.info("APPLY_MOD_DURING_CONFIG: Attempting to apply '%s' to item being configured", new_value)

        # Case 1: Unambiguous attribute change
        if not change_request.is_ambiguous and change_request.possible_attributes:
            attr_slug = change_request.possible_attributes[0]
            if attr_slug != UNKNOWN_ATTRIBUTE_SLUG:
                result = self.modifier_change_handler.apply_change(
                    order, item.id, attr_slug, new_value, target=change_request.target
                )
                if result.success:
                    logger.info("APPLY_MOD_DURING_CONFIG: Applied attribute change %s=%s", attr_slug, new_value)
                    return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                        f"Sure, I've changed that to {new_value}.", item, order
                    )

        # Case 2: Try as modifier
        matches = menu_cache.find_matching_ingredients(new_value.lower())

        if len(matches) == 1:
            match = matches[0]
            self._replace_or_add_modifier(item, match)
            logger.info("APPLY_MOD_DURING_CONFIG: Applied modifier change %s (%s)", match['name'], match['category'])
            return _continue_config(self.config_helper_handler, self.checkout_utils_handler,
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )

        if len(matches) > 1:
            logger.info("APPLY_MOD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation", new_value)
            return _start_disambig(new_value, matches, item, order)

        logger.debug("APPLY_MOD_DURING_CONFIG: Could not apply change for '%s'", new_value)
        return None
