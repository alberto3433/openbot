"""
Item Lookup Handler for Order State Machine.

Handles menu item lookup with disambiguation logic when multiple items match.
Extracted from item_adder_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .disambiguation_handler import DisambiguationHandler
from .mixins import MenuDataMixin
from .attribute_inference import extract_generic_term
from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants
from .utils.text import normalize_text

if TYPE_CHECKING:
    from .menu_lookup import MenuLookup

logger = logging.getLogger(__name__)


class ItemLookupHandler(MenuDataMixin):
    """
    Handles menu item lookup with disambiguation.

    When a user's input matches multiple menu items (e.g., "coffee" matches
    "Hot Coffee" and "Iced Coffee"), this handler manages the disambiguation
    flow to help the user select the specific item they want.
    """

    def __init__(
        self,
        menu_lookup: "MenuLookup | None" = None,
        disambiguation_handler: DisambiguationHandler | None = None,
    ) -> None:
        """
        Initialize the item lookup handler.

        Args:
            menu_lookup: Menu lookup service for finding items.
            disambiguation_handler: Handler for disambiguation flows.
        """
        self.menu_lookup = menu_lookup
        self.disambiguation_handler = disambiguation_handler or DisambiguationHandler()
        self._menu_data: dict = {}

    def lookup_menu_item_with_disambiguation(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        modifiers: dict | None = None,
        pending_field: str = PendingField.ITEM_SELECTION,
        item_type_filter: str | None = None,
    ) -> tuple[dict | None, StateMachineResult | None]:
        """
        Look up a menu item, handling disambiguation if multiple matches.

        Uses DisambiguationHandler for unified disambiguation logic.

        Args:
            item_name: Name of item to look up
            quantity: Number of items (stored during disambiguation)
            order: Current order task
            modifiers: Optional dict of modifiers to store during disambiguation (for beverages)
            pending_field: The pending_field value to use (default: PendingField.ITEM_SELECTION)
            item_type_filter: Optional item type to filter matches (e.g., "sized_beverage")

        Returns:
            Tuple of (menu_item, result):
            - (menu_item, None): Single match found
            - (None, result): Disambiguation needed, result contains the question
            - (None, None): Item not found
        """
        item_lower = normalize_text(item_name)

        # Check for category reference (e.g., "drink", "beverage", "side", etc.)
        category_slug = menu_cache.is_category_reference(item_lower)
        if category_slug:
            # Generic category request - show items from that category
            category_items = menu_cache.get_items_by_category(category_slug)
            # Filter by item_type if specified
            if item_type_filter and category_items:
                category_items = [
                    d for d in category_items
                    if d.get("item_type_slug") == item_type_filter or d.get("item_type") == item_type_filter
                ]
            if category_items:
                logger.info("Generic category request '%s' (category=%s), showing %d items (filter: %s)",
                           item_name, category_slug, len(category_items), item_type_filter)
                result = self.disambiguation_handler.start_disambiguation(
                    item_name=category_slug,
                    matching_items=category_items,
                    order=order,
                    quantity=quantity,
                    pending_field=PendingField.ITEM_SELECTION,
                    modifiers=modifiers,
                    show_prices=False,
                )
                return (None, result)

        # Check for generic terms that match multiple items (data-driven)
        generic_term = extract_generic_term(item_name)
        # Input is "exact generic" if it directly matches multiple items (e.g., "chips")
        is_exact_generic = generic_term == item_lower

        # Step 1: Try to find matches
        matching_items = []
        search_term = generic_term if is_exact_generic else item_name

        if search_term:
            matching_items = self.menu_lookup.lookup_menu_items(search_term)

        # Filter by item_type if specified
        if item_type_filter and matching_items:
            matching_items = [
                item for item in matching_items
                if item.get("item_type") == item_type_filter
            ]

        # If no matches found but we have an item_type_filter, get all items of that type
        # This handles generic requests where user wants something of a specific type
        if not matching_items and item_type_filter:
            all_type_items = menu_cache.get_items_by_item_type(item_type_filter)
            if all_type_items:
                # Apply required_match_phrases filtering to these items
                # Items with restrictive match phrases should only match specific inputs
                filtered_items = []
                for item in all_type_items:
                    item_name_lower = item.get("name", "").lower()
                    # Look up required_match_phrases from cache
                    required_phrases = menu_cache._items_with_required_phrases.get(item_name_lower)
                    if required_phrases:
                        # Item has restrictive match phrases - check if user input qualifies
                        item_with_phrases = {**item, "required_match_phrases": required_phrases}
                        if self.menu_lookup._passes_match_filter(item_with_phrases, item_name):
                            filtered_items.append(item)
                    else:
                        # No filter - item passes (generic items like "Omelette")
                        filtered_items.append(item)
                matching_items = filtered_items
                logger.info("No text matches for '%s', using %d of %d items of type '%s' (after required_match_phrases filter)",
                           item_name, len(matching_items), len(all_type_items), item_type_filter)

                # If filtering reduced many items to just 1, it's a weak match
                # (the survivor is just the least restrictive item, not what the user asked for)
                if len(matching_items) == 1 and len(all_type_items) > 1:
                    logger.info(
                        "WEAK_FALLBACK: filtered %d -> 1 for type '%s', not auto-selecting",
                        len(all_type_items), item_type_filter,
                    )
                    matching_items = []

        # Step 2: Handle results
        if len(matching_items) == 1:
            # Single match - return it directly
            menu_item = matching_items[0]
            logger.info("Single match for '%s': %s", item_name, menu_item.get("name"))
            return (menu_item, None)

        elif len(matching_items) > 1:
            # Multiple matches - check for exact match first
            exact_match = self.disambiguation_handler.check_exact_match(item_name, matching_items)
            if exact_match:
                return (exact_match, None)

            # Check if user already has one in cart
            cart_match = self.disambiguation_handler.check_cart_match(matching_items, order)
            if cart_match:
                return (cart_match, None)

            # Need disambiguation
            logger.info("Multiple matches for '%s' (%d items), starting disambiguation",
                       item_name, len(matching_items))
            result = self.disambiguation_handler.start_disambiguation(
                item_name=item_name,
                matching_items=matching_items,
                order=order,
                quantity=quantity,
                pending_field=pending_field,
                modifiers=modifiers,
                show_prices=False,
            )
            return (None, result)

        # Step 3: No matches - try partial search with singular/plural variants
        search_terms = get_singular_plural_variants(item_lower)

        for term in search_terms:
            matching_items = self.menu_lookup.lookup_menu_items(term)
            if matching_items:
                break

        # Step 4: Try direct items_by_type search as fallback
        if not matching_items and self._menu_data:
            items_by_type = self._menu_data.get("items_by_type", {})
            for type_slug, type_items in items_by_type.items():
                for item in type_items:
                    item_name_db = item.get("name", "").lower()
                    for term in search_terms:
                        if term in item_name_db:
                            # Apply required_match_phrases filter
                            if self.menu_lookup._passes_match_filter(item, item_name):
                                matching_items.append(item)
                            break
            if matching_items:
                logger.info("Direct items_by_type search for %s: found %d items",
                           search_terms, len(matching_items))

        # Step 5: Handle partial match results
        if len(matching_items) == 1:
            menu_item = matching_items[0]
            logger.info("Single partial match for '%s': %s", item_name, menu_item.get("name"))
            return (menu_item, None)
        elif len(matching_items) > 1:
            # Check for exact match among partials
            exact_match = self.disambiguation_handler.check_exact_match(item_name, matching_items)
            if exact_match:
                return (exact_match, None)

            # Need disambiguation
            logger.info("Multiple partial matches for '%s' (%d items), starting disambiguation",
                       item_name, len(matching_items))
            result = self.disambiguation_handler.start_disambiguation(
                item_name=item_name,
                matching_items=matching_items,
                order=order,
                quantity=quantity,
                pending_field=pending_field,
                modifiers=modifiers,
                show_prices=False,
            )
            return (None, result)

        # Step 6: Still no match - try single item lookup as last resort
        menu_item = self.menu_lookup.lookup_menu_item(item_name)
        if menu_item:
            return (menu_item, None)

        # Not found
        logger.warning("Menu item not found: '%s'", item_name)
        return (None, None)

