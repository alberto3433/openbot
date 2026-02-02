"""
Disambiguation Handler for Menu Item Configuration.

Handles resolving ambiguous user selections during item configuration,
such as when "bacon" could match "Bacon", "Turkey Bacon", or "Applewood Smoked Bacon".

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache
from .schemas import StateMachineResult
from .parsers.constants import extract_quantity_for_pattern
from .utils.disambiguation_utils import (
    normalize_input,
    match_by_ordinal,
    match_by_name_exact,
    match_by_alias_exact,
    match_by_name_in_input,
    get_aliases,
)

if TYPE_CHECKING:
    from .models import OrderTask, MenuItemTask

logger = logging.getLogger(__name__)

__all__ = ["ConfigDisambiguationHandler"]


class ConfigDisambiguationHandler:
    """
    Handles disambiguation resolution during menu item configuration.

    Provides methods for:
    - Resolving user's selection from disambiguation options
    - Processing disambiguation responses and applying selections
    - Applying stored modifiers after disambiguation resolves
    """

    def __init__(
        self,
        get_item_type_attributes: Callable[[str], dict],
        format_display_list: Callable[[list[dict]], str],
        extract_qualifier_for_option: Callable[[str, str], str | None],
        advance_to_next_question: Callable[["MenuItemTask", "OrderTask", dict, str], StateMachineResult],
        get_next_question: Callable[["OrderTask"], StateMachineResult],
    ) -> None:
        """Initialize the disambiguation handler.

        Args:
            get_item_type_attributes: Callback to get attributes for an item type.
            format_display_list: Callback to format a list of options for display.
            extract_qualifier_for_option: Callback to extract qualifiers like "extra" or "on the side".
            advance_to_next_question: Callback to advance to the next question after resolution.
            get_next_question: Callback to get the next question when disambiguation is cleared.
        """
        self._get_item_type_attributes = get_item_type_attributes
        self._format_display_list = format_display_list
        self._extract_qualifier_for_option = extract_qualifier_for_option
        self._advance_to_next_question = advance_to_next_question
        self._get_next_question = get_next_question

    def resolve_disambiguation(
        self,
        user_input: str,
        options: list[dict],
    ) -> dict | None:
        """
        Resolve user's selection from disambiguation options using STRICT matching.

        Uses shared matching utilities but with strict rules:
        - Matches ordinals ("1", "first")
        - Matches exact name/slug/alias
        - Matches if full option name is in input ("black forest ham please" -> "Black Forest Ham")
        - Does NOT match if input is substring of name ("ham" should NOT match "Black Forest Ham")

        Args:
            user_input: User's response (e.g., "ham", "black forest ham", "first", "1")
            options: List of option dicts with display_name and slug fields

        Returns:
            Selected option dict if matched, None if no match found.
        """
        import re

        # Try raw exact match FIRST (before normalization)
        # This handles cases like "Sugar in the Raw" where normalization would
        # strip "the" and break the exact match
        raw_lower = user_input.lower().strip()
        for opt in options:
            if opt.get("display_name", "").lower() == raw_lower:
                return opt
            slug_readable = opt.get("slug", "").replace("_", " ")
            if slug_readable == raw_lower:
                return opt

        input_lower = normalize_input(user_input)

        # Try ordinal matching first
        match = match_by_ordinal(input_lower, options, name_key="display_name")
        if match:
            return match

        # Try exact name/slug matching (with normalized input)
        match = match_by_name_exact(input_lower, options, name_key="display_name", slug_key="slug")
        if match:
            return match

        # Try exact alias matching
        match = match_by_alias_exact(input_lower, options)
        if match:
            return match

        # Try if FULL option name is in user input
        # ("black forest ham please" -> "Black Forest Ham")
        match = match_by_name_in_input(input_lower, options, name_key="display_name")
        if match:
            return match

        # Try if FULL alias is in user input using word-boundary matching
        # This prevents "sugar" from matching "sugar in raw" incorrectly
        for opt in options:
            for alias in get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3:
                    # Use word-boundary matching instead of substring
                    pattern = r'\b' + re.escape(alias_lower) + r'\b'
                    if re.search(pattern, input_lower):
                        return opt

        # NO substring matching in the other direction!
        # We deliberately don't check if input_lower is in display_name
        # because that would make "ham" match "Black Forest Ham"

        return None

    def handle_disambiguation_response(
        self, user_input: str, order: "OrderTask"
    ) -> StateMachineResult | None:
        """
        Handle user response to an attribute disambiguation question.

        Checks if there's a pending disambiguation, attempts to resolve
        the user's selection, applies any stored modifiers, and returns
        the next question.

        Args:
            user_input: User's response to disambiguation question
            order: Current order state

        Returns:
            StateMachineResult if disambiguation was handled, None if no disambiguation pending
        """
        from .models import MenuItemTask

        disambiguation = order.pending_attr_disambiguation
        if not disambiguation:
            return None

        options = disambiguation.get("options", [])
        attr_slug = disambiguation.get("attr_slug")
        stored_modifiers = disambiguation.get("modifiers", {})
        item_id = disambiguation.get("item_id")

        # Find the item being configured
        item = order.items.get_item_by_id(item_id) if item_id else None
        if not item or not isinstance(item, MenuItemTask):
            logger.warning("Disambiguation item not found: %s", item_id)
            order.pending_attr_disambiguation = None
            return self._get_next_question(order)

        # Try to resolve the selection
        selected = self.resolve_disambiguation(user_input, options)

        if not selected:
            # Couldn't match - ask again
            options_text = self._format_display_list(options)
            return StateMachineResult(
                message=f"Sorry, I didn't catch that. Did you mean {options_text}?",
                order=order,
            )

        # Clear disambiguation state
        order.pending_attr_disambiguation = None

        # Get the attribute info
        item_type = item.menu_item_type
        attrs = self._get_item_type_attributes(item_type)
        attr = attrs.get(attr_slug, {})

        # Re-extract quantity from user's clarification input (not stored value)
        # This handles cases like "2 hazelnut syrups" after disambiguation
        user_lower = user_input.lower()

        # Only extract numeric quantity if category supports it (has quantity_unit)
        # Use ingredient_category (from Ingredient.category) to look up quantity_unit
        mod_category = selected.get("ingredient_category") or attr_slug
        quantity_unit = menu_cache.get_ingredient_category_quantity_unit(mod_category)

        quantity = 1
        if quantity_unit:
            quantity = extract_quantity_for_pattern(user_lower, selected["display_name"].lower())
            if quantity == 1:
                quantity = extract_quantity_for_pattern(user_lower, selected["slug"].replace("_", " "))
            if quantity == 1 and selected.get("aliases"):
                # Also try with ingredient aliases (e.g., "sugar" for "domino_sugar")
                for alias in selected["aliases"]:
                    alias_qty = extract_quantity_for_pattern(user_lower, alias.lower())
                    if alias_qty > 1:
                        quantity = alias_qty
                        break

        # Use stored quantity as fallback if no quantity found in clarification
        # (e.g., user said "4 syrups", then answered "caramel" without quantity)
        stored_qty = stored_modifiers.pop("_quantity", None)
        if quantity == 1 and stored_qty and stored_qty > 1:
            quantity = stored_qty
        qualifier = self._extract_qualifier_for_option(user_input, selected["display_name"])

        opt_price = selected.get("price") or selected.get("price_modifier") or 0
        selection = {
            "slug": selected["slug"],
            "display_name": selected["display_name"],
            "price": opt_price,
            "quantity": quantity,
        }
        if qualifier:
            selection["qualifier"] = qualifier

        # Add selection using the unified API
        item.add_selection(
            selected["slug"],
            attr_slug,
            quantity=quantity,
            price=opt_price,
            display_name=selected["display_name"],
            ingredient_category=selected.get("ingredient_category"),
        )

        # Apply any stored modifiers (e.g., milk type, sweetener extracted before disambiguation)
        if stored_modifiers:
            self.apply_stored_modifiers(item, stored_modifiers)

        # Build acknowledgment
        ack_name = selected["display_name"]
        if qualifier:
            ack_name = f"{ack_name} ({qualifier})"
        ack_text = f"{quantity} {ack_name}" if quantity > 1 else ack_name

        logger.info(
            "DISAMBIGUATION RESOLVED: %s -> %s for attr=%s, stored_mods=%s",
            user_input, selected["display_name"], attr_slug, stored_modifiers
        )

        return self._advance_to_next_question(item, order, attr, ack_text)

    def apply_stored_modifiers(self, item: "MenuItemTask", modifiers: dict) -> None:
        """
        Apply stored modifiers from disambiguation to the item.

        Uses data-driven approach: gets is_multi_select from ingredient_categories
        table to determine whether to use add_modifier() vs dict-style access.

        Args:
            item: The item to apply modifiers to
            modifiers: Dict of modifier values to apply
        """
        if not modifiers:
            return

        # Keys that are special metadata, not actual modifier fields
        skip_keys = {"_quantity"}
        # Suffix for quantity keys (e.g., "sweetener_quantity")
        quantity_suffix = "_quantity"

        # Track processed keys to avoid double-processing
        processed: set[str] = set()

        for key, value in modifiers.items():
            # Skip special keys, quantity suffixes, and already-processed keys
            if key in skip_keys or key.endswith(quantity_suffix) or key in processed:
                continue

            # Normalize key using data-driven field mapping from database
            normalized_key = menu_cache.resolve_field_to_slug(item.menu_item_type, key)

            # Get field config to determine if this is a multi-select field
            field_config = menu_cache.get_ingredient_category_field_config(normalized_key)
            is_multi_select = field_config.get("is_multi_select", False) if field_config else False

            if is_multi_select:
                # Multi-select: use add_selection with quantity
                quantity = modifiers.get(f"{key}{quantity_suffix}", 1)
                item.add_selection(value, normalized_key, quantity, 0.0)
            else:
                # Single-select or boolean: use dict-style access
                item[normalized_key] = value

            processed.add(key)


