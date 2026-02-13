"""
Item Cancellation Handler.

This module handles item and modifier cancellation operations including:
- Modifier removal: "remove the bacon", "no cheese"
- Last item removal: "cancel that", "remove it"
- All items removal: "cancel everything", "remove all"
- Reduce to one: "just one bagel", "only one"
- Ordinal removal: "remove the second bagel"
- Name-based removal: "cancel the coke", "remove the bagel"

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize, get_singular_plural_variants

from .models import OrderTask, MenuItemTask, TaskStatus
from .schemas import StateMachineResult, OpenInputResponse
from .checkout_messages import ok_removed_anything_else, ErrorMessages, item_not_found_in_order
from .handler_utils import get_last_item, remove_item_from_order
from .utils.text import strip_leading_article
from .modifier_operations import (
    find_modifier_on_any_item,
    remove_modifier_from_item,
    find_default_ingredient_on_any_item,
    remove_default_ingredient_from_item,
)
from .config.attribute_resolver import get_mandatory_attributes
from .utils.pricing_utils import safe_recalculate_price

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


def extract_ordinal_reference(cancel_desc: str) -> tuple[int | None, str]:
    """Extract ordinal reference from cancellation description.

    Examples:
        "second bagel" -> (2, "bagel")
        "3rd coffee" -> (3, "coffee")
        "bagel 2" -> (2, "bagel")
        "coffee #3" -> (3, "coffee")
        "the bagel" -> (None, "bagel")

    Returns:
        Tuple of (ordinal_index, item_type_keyword).
        ordinal_index is 1-based (1st, 2nd, etc.) or None if no ordinal found.
    """
    import re
    from .parsers.selection_patterns import ORDINAL_WORDS

    desc_lower = cancel_desc.lower().strip()
    words = desc_lower.split()

    ordinal_index = None
    item_keyword = desc_lower

    for i, word in enumerate(words):
        # Check word-based ordinals (first, second, etc.)
        if word in ORDINAL_WORDS:
            ordinal_index = ORDINAL_WORDS[word]
            item_keyword = " ".join(words[i + 1:]) if i + 1 < len(words) else ""
            break

        # Check numeric ordinals (1st, 2nd, 3rd, etc.)
        ordinal_match = re.match(r"(\d+)(?:st|nd|rd|th)", word)
        if ordinal_match:
            ordinal_index = int(ordinal_match.group(1))
            item_keyword = " ".join(words[i + 1:]) if i + 1 < len(words) else ""
            break

    # Check for trailing number patterns: "bagel 2" or "coffee #3"
    if ordinal_index is None and len(words) >= 2:
        last_word = words[-1]
        # Match plain number or #number at end
        trailing_match = re.match(r"#?(\d+)$", last_word)
        if trailing_match:
            ordinal_index = int(trailing_match.group(1))
            item_keyword = " ".join(words[:-1])

    return ordinal_index, item_keyword.strip()


def find_nth_item_of_type(
    active_items: list,
    item_type_keyword: str,
    ordinal_index: int,
) -> tuple | None:
    """Find the Nth item of a specific type in the cart.

    Args:
        active_items: List of active items in the cart
        item_type_keyword: The type of item to find (e.g., "bagel", "coffee")
        ordinal_index: 1-based index (1 = first, 2 = second, etc.)

    Returns:
        Tuple of (item, actual_index) if found, None otherwise.
    """
    keyword_lower = item_type_keyword.lower()
    variants = get_singular_plural_variants(keyword_lower)

    # Also check if keyword maps to an item type
    mapped_type = None
    for variant in variants:
        category_mapping = menu_cache.get_category_keyword_mapping(variant)
        if category_mapping:
            mapped_type = category_mapping.get("slug")
            break

    count = 0
    for idx, item in enumerate(active_items):
        item_summary = item.get_summary().lower()
        item_name = getattr(item, 'menu_item_name', '') or ''
        item_name_lower = item_name.lower()
        menu_item_type = getattr(item, 'menu_item_type', '') or ''

        # Check for matches
        matches = False
        if any(v in item_summary for v in variants):
            matches = True
        elif item_name_lower and any(v in item_name_lower for v in variants):
            matches = True
        elif menu_item_type and any(v == menu_item_type for v in variants):
            matches = True
        elif mapped_type and menu_item_type == mapped_type:
            matches = True
        # Generic "item" or "one" matches any item
        elif keyword_lower in ("item", "items", "one", "thing", "things"):
            matches = True

        if matches:
            count += 1
            if count == ordinal_index:
                return (item, idx)

    return None


class ItemCancellationHandler:
    """
    Handles item and modifier cancellation operations.

    Manages removal of items and modifiers from the cart based on
    various user patterns like "cancel that", "remove the bacon", etc.
    """

    def __init__(
        self,
        pricing: "PricingEngine",
        configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the item cancellation handler.

        Args:
            pricing: PricingEngine for recalculating prices after modifications.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
        """
        self.pricing = pricing
        self._configure_next_incomplete_item = configure_next_incomplete_item

    def _build_removal_response(
        self,
        order: OrderTask,
        removed_name: str,
        has_remaining_items: bool,
    ) -> StateMachineResult:
        """Build response after item removal, continuing config if needed.

        If there are remaining incomplete items (status=IN_PROGRESS), returns
        the next configuration question for that item. Otherwise returns
        "Anything else?" or "What would you like to order?".
        """
        # Check for incomplete items that need configuration
        if has_remaining_items and self._configure_next_incomplete_item:
            for item in order.items.get_active_items():
                if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                    # Get the next config question and prepend removal confirmation
                    config_result = self._configure_next_incomplete_item(order)
                    return StateMachineResult(
                        message=f"OK, I've removed the {removed_name}. {config_result.message}",
                        order=order,
                    )

        # No incomplete items - ask "Anything else?" or "What would you like?"
        if has_remaining_items:
            return StateMachineResult(
                message=ok_removed_anything_else(removed_name),
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"OK, I've removed the {removed_name}. What would you like to order?",
                order=order,
            )

    def handle_item_cancellation(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle item/modifier cancellation: 'cancel the coke', 'remove bacon', etc.

        Handles:
        - Modifier removal: "remove the bacon", "no cheese"
        - Last item removal: "cancel that", "remove it"
        - All items removal: "cancel everything", "remove all"
        - Reduce to one: "just one bagel", "only one"
        - Ordinal removal: "remove the second bagel"
        - Name-based removal: "cancel the coke", "remove the bagel"

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.cancel_item:
            return None

        active_items = order.items.get_active_items()

        # First, try modifier removal: "remove the bacon", "no cheese", etc.
        result = self._try_modifier_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__last_item__" value for "cancel that", "remove it", etc.
        result = self._try_last_item_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__all_items__" value for "remove all", "cancel everything", etc.
        result = self._try_all_items_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__last_n_items_N__" value for "remove the last 2", etc.
        result = self._try_last_n_items_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__reduce_to_one__" value for "just one bagel", "only one", etc.
        result = self._try_reduce_to_one(parsed, order, active_items)
        if result:
            return result

        # Normal item cancellation by description
        if not active_items:
            logger.info("Cancellation requested but no items in cart")
            return StateMachineResult(
                message=ErrorMessages.NO_ITEMS_YET,
                order=order,
            )

        # Check for ordinal reference (e.g., "second bagel", "3rd coffee")
        result = self._try_ordinal_removal(parsed, order, active_items)
        if result:
            return result

        # Name-based removal: "cancel the coke", "remove the bagel"
        return self._try_name_based_removal(parsed, order, active_items)

    def _try_modifier_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Try to remove a modifier from an item.

        Skip modifier removal if the cancel term matches an ITEM TYPE (e.g., "bagel").
        This prevents "remove the bagel" from removing the "plain_bagel" bread modifier
        instead of removing the bagel item from the cart.
        """
        if not active_items:
            return None

        # Check if cancel term matches an item type - if so, skip modifier removal
        # User wants to remove an item, not a modifier
        # Only skip if lookup_type is "item_type" (e.g., "bagel", "coffee")
        # Don't skip for lookup_type="category" (e.g., "cheese") - those should attempt modifier removal
        cancel_variants = get_singular_plural_variants(parsed.cancel_item)
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping and category_mapping.get("lookup_type") == "item_type":
                logger.info(
                    "Cancellation: '%s' matches item type '%s' - skipping modifier removal",
                    parsed.cancel_item, category_mapping.get("slug")
                )
                return None  # Skip modifier removal, let item removal handle it

        # Check if cancel term matches a modifier CATEGORY (like "cream cheese" → spreads)
        # This handles "remove cream cheese" when the stored value is "blueberry" (the flavor)
        cancel_term_lower = parsed.cancel_item.lower().strip()
        # Normalize multiple spaces to single space (common voice transcription artifact)
        cancel_term_lower = ' '.join(cancel_term_lower.split())
        # Strip leading "the " if present
        cancel_term_lower = strip_leading_article(cancel_term_lower)

        modifier_category_slug = menu_cache.get_modifier_category_by_alias(cancel_term_lower)
        if modifier_category_slug:
            # Map modifier_category slug to attribute category
            # "spreads" → "spread" (remove trailing 's')
            attr_category = modifier_category_slug.rstrip('s') if modifier_category_slug.endswith('s') else modifier_category_slug

            for item in active_items:
                if isinstance(item, MenuItemTask) and item.get(attr_category):
                    removed_value = item.get(attr_category)
                    item.remove_selection(attr_category)
                    safe_recalculate_price(self.pricing, item, "after removing category")

                    # Format display name from slug
                    from .normalization import format_slug_for_display
                    display_name = format_slug_for_display(str(removed_value), check_cache=False)
                    updated_summary = item.get_summary()
                    logger.info(
                        "Cancellation: removed %s category '%s' (value: '%s') via alias '%s'",
                        attr_category, modifier_category_slug, removed_value, cancel_term_lower
                    )
                    return StateMachineResult(
                        message=f"OK, I've removed the {display_name}. Your order is now {updated_summary}. Anything else?",
                        order=order,
                    )
            # No items had that category
            logger.debug("Cancellation: category '%s' matched but no items have that category", attr_category)

        modifier_match = find_modifier_on_any_item(active_items, parsed.cancel_item)
        if modifier_match:
            # If the match is on a required attribute and removing it would leave
            # the item with no filled mandatory attributes, the user is referring
            # to the item by its attribute (e.g., "remove one pound" means remove
            # the 1-lb item, not strip the weight attribute).
            if modifier_match.attribute_key and isinstance(modifier_match.item, MenuItemTask):
                item_type = modifier_match.item.menu_item_type
                if item_type:
                    mandatory_attrs = get_mandatory_attributes(item_type)
                    mandatory_slugs = {attr['slug'] for attr in mandatory_attrs}
                    if modifier_match.attribute_key in mandatory_slugs:
                        attr_values = modifier_match.item.attribute_values or {}
                        filled_mandatory = sum(
                            1 for slug in mandatory_slugs if slug in attr_values
                        )
                        if filled_mandatory <= 1:
                            removed_name = modifier_match.item.get_summary()
                            remove_item_from_order(order, modifier_match.item)
                            remaining = order.items.get_active_items()
                            logger.info(
                                "Cancellation: '%s' matched required attr '%s' on '%s' "
                                "- removing entire item (only %d mandatory filled)",
                                parsed.cancel_item, modifier_match.attribute_key,
                                removed_name, filled_mandatory,
                            )
                            return self._build_removal_response(
                                order, removed_name, bool(remaining)
                            )

            result = remove_modifier_from_item(modifier_match.item, modifier_match)
            if result.success:
                safe_recalculate_price(self.pricing, modifier_match.item, "after removing modifier")

                updated_summary = modifier_match.item.get_summary()
                return StateMachineResult(
                    message=f"{result.message} Your order is now {updated_summary}. Anything else?",
                    order=order,
                )
        else:
            # Check if it's a default ingredient of a signature/menu item
            default_match = find_default_ingredient_on_any_item(active_items, parsed.cancel_item)
            if default_match:
                result = remove_default_ingredient_from_item(default_match.item, default_match)
                if result.success:
                    updated_summary = default_match.item.get_summary()
                    return StateMachineResult(
                        message=f"{result.message} Your order is now {updated_summary}. Anything else?",
                        order=order,
                    )

        return None

    def _try_last_item_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'cancel that', 'remove it', etc."""
        if parsed.cancel_item != "__last_item__" or not active_items:
            return None

        last_item = get_last_item(active_items)
        removed_name = last_item.get_summary()
        remove_item_from_order(order, last_item)
        logger.info("Cancellation: removed last item from cart: %s", removed_name)

        remaining_items = order.items.get_active_items()
        return self._build_removal_response(order, removed_name, bool(remaining_items))

    def _try_all_items_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove all', 'cancel everything', etc."""
        if parsed.cancel_item != "__all_items__":
            return None

        if active_items:
            num_items = len(active_items)
            for item in active_items:
                remove_item_from_order(order, item)
            logger.info("Cancellation: removed ALL %d items from cart", num_items)
            return StateMachineResult(
                message="OK, I've cleared your order. What would you like to order?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="Your order is already empty. What would you like to order?",
                order=order,
            )

    def _try_last_n_items_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove the last 2', 'cancel last three items', etc."""
        import re
        match = re.match(r"^__last_n_items_(\d+)__$", parsed.cancel_item)
        if not match:
            return None

        count = int(match.group(1))

        if not active_items:
            return StateMachineResult(
                message="Your order is empty. What would you like to order?",
                order=order,
            )

        # Can only remove up to the number of items we have
        actual_count = min(count, len(active_items))

        # Remove the last N items (from the end of the list)
        items_to_remove = active_items[-actual_count:]
        removed_names = []
        for item in items_to_remove:
            removed_names.append(item.get_summary())
            remove_item_from_order(order, item)

        logger.info("Cancellation: removed last %d items from cart: %s", actual_count, removed_names)

        remaining_items = order.items.get_active_items()

        if actual_count == 1:
            return self._build_removal_response(order, removed_names[0], bool(remaining_items))

        if remaining_items:
            return StateMachineResult(
                message=f"OK, I've removed the last {actual_count} items. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"OK, I've removed the last {actual_count} items. What would you like to order?",
                order=order,
            )

    def _try_reduce_to_one(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'just one bagel', 'only one', etc."""
        if not parsed.cancel_item.startswith("__reduce_to_one"):
            return None

        if not active_items:
            return StateMachineResult(
                message="Your order is empty. What would you like to order?",
                order=order,
            )

        item_type = None
        if parsed.cancel_item != "__reduce_to_one__":
            parts = parsed.cancel_item.replace("__", "").replace("reduce_to_one_", "")
            if parts:
                item_type = parts.strip()

        items_to_check = active_items
        if item_type:
            type_attrs = menu_cache.get_item_type_attributes(item_type)
            if type_attrs:
                primary_attr = type_attrs[0] if type_attrs else None
                if primary_attr:
                    items_to_check = [
                        i for i in active_items
                        if isinstance(i, MenuItemTask) and i.has_attribute(primary_attr)
                    ]
                else:
                    items_to_check = [i for i in active_items if isinstance(i, MenuItemTask)]
            else:
                items_to_check = [i for i in active_items if isinstance(i, MenuItemTask)]

        if len(items_to_check) > 1:
            items_to_remove = items_to_check[1:]
            removed_count = 0
            removed_names = []
            for item in items_to_remove:
                removed_name = item.get_summary()
                remove_item_from_order(order, item)
                removed_count += 1
                removed_names.append(removed_name)

            kept_item = items_to_check[0].get_summary()
            logger.info(
                "Reduce to one: kept '%s', removed %d items: %s",
                kept_item, removed_count, removed_names
            )

            if removed_count == 1:
                return StateMachineResult(
                    message=f"OK, I've removed the extra {item_type or 'item'}. You have {kept_item}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_count} items. You have {kept_item}. Anything else?",
                    order=order,
                )
        elif len(items_to_check) == 1:
            kept_item = items_to_check[0].get_summary()
            return StateMachineResult(
                message=f"You already have just one {item_type or 'item'}: {kept_item}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"I don't see any {item_type or 'items'} in your order. What would you like?",
                order=order,
            )

    def _try_ordinal_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove the second bagel', '3rd coffee', etc."""
        cancel_item_desc = parsed.cancel_item.lower()
        ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_item_desc)

        if ordinal_index is None or not item_type_keyword:
            return None

        result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
        if result:
            item_to_remove, _ = result
            removed_name = item_to_remove.get_summary()
            remove_item_from_order(order, item_to_remove)

            logger.info(
                "Cancellation: removed %s #%d from cart: %s",
                item_type_keyword, ordinal_index, removed_name
            )

            remaining_items = order.items.get_active_items()
            return self._build_removal_response(order, removed_name, bool(remaining_items))
        else:
            logger.info(
                "Cancellation: couldn't find %s #%d in cart",
                item_type_keyword, ordinal_index
            )
            if item_type_keyword.lower() in ("item", "items", "one", "thing"):
                not_found_msg = f"I couldn't find item #{ordinal_index} in your order."
            else:
                not_found_msg = f"I couldn't find a {item_type_keyword} #{ordinal_index} in your order."
            return StateMachineResult(
                message=f"{not_found_msg} What would you like to do?",
                order=order,
            )

    def _try_name_based_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult:
        """Handle name-based removal: 'cancel the coke', 'remove the bagel'."""
        cancel_item_desc = parsed.cancel_item.lower()

        # Check if plural removal (e.g., "coffees", "bagels")
        singular_desc = singularize(cancel_item_desc)
        is_plural = singular_desc != cancel_item_desc.lower()

        # Get all variants for matching
        cancel_variants = get_singular_plural_variants(cancel_item_desc)

        # Map user category terms to item_type via database
        mapped_item_type = None
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping:
                mapped_item_type = category_mapping.get("slug")
                break

        # Resolve aliases to canonical names
        resolved_name, _ = menu_cache.resolve_alias(singular_desc)
        canonical_name_lower = resolved_name.lower() if resolved_name else None

        # Find matching items
        items_to_remove = []
        for item in reversed(active_items):
            item_summary = item.get_summary().lower()
            item_name = getattr(item, 'menu_item_name', '') or ''
            item_name_lower = item_name.lower()
            item_type = getattr(item, 'item_type', '') or ''
            menu_item_type = getattr(item, 'menu_item_type', '') or ''

            # Check for matches using all variants
            matches = False
            if any(v in item_summary for v in cancel_variants):
                matches = True
            elif item_name_lower and any(v in item_name_lower for v in cancel_variants):
                matches = True
            elif item_name_lower and item_name_lower in cancel_item_desc:
                matches = True
            elif item_type and any(v == item_type for v in cancel_variants):
                matches = True
            elif menu_item_type and any(v == menu_item_type for v in cancel_variants):
                matches = True
            elif mapped_item_type and menu_item_type == mapped_item_type:
                matches = True
            elif canonical_name_lower and canonical_name_lower == item_name_lower:
                matches = True
            else:
                # Fallback: check if ALL significant words from cancel description
                # appear in item summary. This is more restrictive than "any word"
                # to prevent "cinnamon babka" from matching "Chocolate Babka" (shares "babka").
                filler_words = {"the", "a", "an", "my", "that", "this"}
                significant_words = [
                    w for w in cancel_item_desc.split()
                    if w and w not in filler_words
                ]
                if significant_words and all(word in item_summary for word in significant_words):
                    matches = True

            if matches:
                items_to_remove.append(item)
                if not is_plural:
                    break

        if items_to_remove:
            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                remove_item_from_order(order, item)

            logger.info("Cancellation: removed %d item(s) from cart: %s", len(removed_names), removed_names)

            remaining_items = order.items.get_active_items()

            # For single item removal, use helper to potentially continue configuration
            if len(removed_names) == 1:
                return self._build_removal_response(order, removed_names[0], bool(remaining_items))

            # For multiple items, build message manually but still check for incomplete items
            removed_str = f"the {len(removed_names)} {singular_desc}s"
            if remaining_items and self._configure_next_incomplete_item:
                for item in remaining_items:
                    if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                        config_result = self._configure_next_incomplete_item(order)
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. {config_result.message}",
                            order=order,
                        )

            if remaining_items:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. What would you like to order?",
                    order=order,
                )
        else:
            logger.info("Cancellation: couldn't find item matching '%s'", cancel_item_desc)
            return StateMachineResult(
                message=item_not_found_in_order(parsed.cancel_item),
                order=order,
            )
