"""
Modification Interceptor for Configuring Item Handler.

Handles modification-level intercepts during item configuration:
- Modifier change requests (swap, remove, replace)
- Bundle child modifications
- "Can you make it X?" requests
- "Add X" modifier patterns
- Cross-attribute option matching
- Boolean attribute matching for non-pending attributes

These run after priority intercepts but before fallback checks.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .models.utilities import parse_pending_field
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .config.parsers.boolean_parser import BooleanParser
from .utils.pricing_utils import safe_recalculate_price
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .modifier_change_handler import ModifierChangeHandler
    from .bundle_modification_handler import BundleModificationHandler
    from .config_modification_handler import ConfigModificationHandler
    from .modifier_addition_handler import ModifierAdditionHandler
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler

logger = logging.getLogger(__name__)


class ConfigModificationInterceptor:
    """Handles modification intercepts during item configuration.

    Modification intercepts include modifier changes, bundle child mods,
    "can you make it X?" requests, "add X" patterns, cross-attribute matching,
    and boolean attribute matching.
    """

    def __init__(
        self,
        modifier_change_handler: "ModifierChangeHandler",
        bundle_modification_handler: "BundleModificationHandler",
        config_modification_handler: "ConfigModificationHandler",
        modifier_addition_handler: "ModifierAdditionHandler",
        config_helper_handler: "ConfigHelperHandler",
        checkout_utils_handler: "CheckoutUtilsHandler",
    ) -> None:
        """Initialize the modification interceptor.

        Args:
            modifier_change_handler: Handler for modifier change detection and pricing.
            bundle_modification_handler: Handler for bundle child mods and cross-attribute matching.
            config_modification_handler: Handler for "can you make it X?" and item switch.
            modifier_addition_handler: Handler for "add X" modifier patterns.
            config_helper_handler: Handler for config helpers (questions).
            checkout_utils_handler: Handler for checkout utilities.
        """
        self.modifier_change_handler = modifier_change_handler
        self.bundle_modification_handler = bundle_modification_handler
        self.config_modification_handler = config_modification_handler
        self.modifier_addition_handler = modifier_addition_handler
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler

    def check_modification_intercepts(
        self, user_input: str, item: MenuItemTask, order: OrderTask, is_valid_answer: bool
    ) -> StateMachineResult | None:
        """Check for modification intercepts during item configuration.

        Handles modifier changes, bundle child modifications, "can you make it X?",
        "add X" patterns, cross-attribute matches, and boolean attribute matches.

        Args:
            user_input: Raw user input string.
            item: The current MenuItemTask being configured.
            order: Current order state.
            is_valid_answer: Whether input could be a valid answer for the pending field.
        """
        # Check for modifier change requests during configuration
        # If detected, try to apply immediately instead of deferring
        change_request = None if is_valid_answer else self.modifier_change_handler.detect_change_request(user_input)
        if change_request:
            result = self.bundle_modification_handler.apply_modification_during_config(change_request, item, order)
            if result:
                return result
            # If couldn't apply as attribute/modifier, try as cross-type menu item replacement
            result = self.config_modification_handler._try_replace_with_any_menu_item(
                change_request.new_value, item, order
            )
            if result:
                return result
            # If still couldn't apply, fall through to normal processing

        # Check for modifications targeting a bundled child item by name
        # e.g., "make the fruit salad a large" while configuring parent omelette
        if not is_valid_answer:
            bundle_mod_result = self.bundle_modification_handler.handle_modify_bundle_child(
                user_input, item, order
            )
            if bundle_mod_result:
                return bundle_mod_result

        # Check for "can you make it X?" style requests (e.g., "can you make it iced?")
        # Skip at customization_checkpoint - let the checkpoint handler use direct_option_matcher
        # which properly handles pricing/upcharges (e.g., "make it 3 eggs" -> upcharge for extra egg)
        if (not is_valid_answer
            and order.pending_field != PendingField.CUSTOMIZATION_CHECKPOINT):
            can_you_make_it_result = self.config_modification_handler.handle_can_you_make_it(user_input, item, order)
            if can_you_make_it_result:
                return can_you_make_it_result

        # Check for "add X" patterns during configuration (e.g., "add bacon and cheese")
        # Parse and apply the modifiers to the current item, then continue with config
        if not is_valid_answer:
            add_result = self.modifier_addition_handler.handle_add_modifiers_during_config(user_input, item, order)
            if add_result:
                return add_result

        # Check if input matches a DIFFERENT attribute's option (e.g., "veggie cream cheese"
        # when asked about cheese -> matches spread attribute).
        # Runs regardless of is_valid_answer because inputs like "veggie cream cheese" may
        # pass is_valid_answer for cheese (loads_from_ingredients) while actually being a
        # spread answer. The exact_only matching prevents false positives.
        cross_attr_result = self.bundle_modification_handler.handle_cross_attribute_match(
            user_input, item, order
        )
        if cross_attr_result:
            return cross_attr_result

        # Check for bare boolean attribute values (e.g., "not toasted" while being asked about bread)
        # Guard: only on short inputs (<=4 words) to avoid intercepting multi-attribute phrases
        if not is_valid_answer and len(user_input.split()) <= 4:
            bool_result = self._check_boolean_attribute_match(user_input, item, order)
            if bool_result:
                return bool_result

        return None

    def _check_boolean_attribute_match(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult | None:
        """Check if input matches a boolean attribute that isn't the pending field.

        Handles cases like "not toasted" when the pending question is about bread.
        Only accepts specific alias/negation matches to avoid false positives
        (e.g., "yes" accidentally setting an unrelated boolean).

        Args:
            user_input: Raw user input string.
            item: The current item being configured.
            order: Current order state.

        Returns:
            StateMachineResult if a boolean attribute was matched, None otherwise.
        """
        item_type = item.menu_item_type
        if not item_type:
            return None

        # Parse the currently pending attribute so we can skip it
        pending_item_type, pending_attr = parse_pending_field(order.pending_field)

        all_attrs = menu_cache.get_item_type_attributes(item_type)
        parser = BooleanParser()

        for attr_slug, attr_config in all_attrs.items():
            if attr_config.get("input_type") != "boolean":
                continue
            # Skip the currently pending attribute (it will be handled by its own handler)
            if attr_slug == pending_attr:
                continue

            result = parser.parse(user_input, attr_config)
            if result.value is None:
                continue

            # Safety guard: only accept specific alias/negation matches.
            # Reject generic yes_pattern/no_pattern to prevent "yes" from
            # accidentally setting an unrelated boolean attribute.
            safe_match_types = ("true_alias", "false_alias", "negation_pattern")
            if result.matched_by not in safe_match_types:
                continue

            # Apply the boolean value
            item[attr_slug] = result.value

            # Recalculate price
            pricing = self.modifier_change_handler.pricing if self.modifier_change_handler else None
            safe_recalculate_price(pricing, item, f"after boolean {attr_slug} change")

            # Build acknowledgment
            display_name = attr_config.get("display_name", attr_slug)
            if result.value:
                ack = f"Got it, {display_name.lower()}."
            else:
                ack = f"Got it, no {display_name.lower()}."

            # Also check if the input answers the pending boolean question.
            # e.g., "yes and scoop" → "scoop" matched scooped (non-pending),
            # but "yes" should also answer the pending toasted question.
            if pending_attr:
                pending_config = all_attrs.get(pending_attr, {})
                if pending_config.get("input_type") == "boolean":
                    pending_result = parser.parse(user_input, pending_config)
                    if pending_result.value is not None:
                        item[pending_attr] = pending_result.value
                        safe_recalculate_price(pricing, item, f"after boolean {pending_attr} change")
                        # Clear pending_field so it advances past the now-answered attribute
                        order.pending_field = None
                        pending_display = pending_config.get("display_name", pending_attr)
                        if pending_result.value:
                            ack += f" {pending_display}."
                        else:
                            ack += f" Not {pending_display.lower()}."

            # Get next question (pending_field cleared above if pending was answered)
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                return StateMachineResult(message=f"{ack} {current_question}", order=order)

            # Item is complete, move on
            return self.checkout_utils_handler.get_next_question(order)

        return None
