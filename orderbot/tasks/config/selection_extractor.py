"""
Selection Extractor for Menu Item Configuration.

Handles extracting selections from user input and applying them to items
during configuration. Uses data-driven extraction based on item type attributes.

Extracted from menu_item_config_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from ..schemas import Selection
from ..parsers.deterministic import get_pipeline
from ..normalization import format_slug_for_display
from ..utils.text import format_english_list

if TYPE_CHECKING:
    from ..models import MenuItemTask
    from ..pricing import PricingEngine

logger = logging.getLogger(__name__)

# Get shared pipeline instance
_pipeline = get_pipeline()

__all__ = ["SelectionExtractor"]


class SelectionExtractor:
    """
    Extracts and applies selections during menu item configuration.

    Provides methods for:
    - Extracting selections from user input based on item type
    - Applying selections to menu items with price lookups
    - Combined extract-and-apply convenience method
    """

    def __init__(self, pricing: "PricingEngine | None" = None) -> None:
        """Initialize the selection extractor.

        Args:
            pricing: PricingEngine for looking up modifier prices.
        """
        self.pricing = pricing

    def extract_selections_from_input(
        self, user_input: str, item_type: str
    ) -> list[Selection]:
        """
        Extract selections from user input based on item type.

        Uses the ExtractionPipeline with typed results for cleaner extraction.
        Queries the database for what attributes the item type accepts and
        extracts matching values from the input.

        Args:
            user_input: Raw user input string
            item_type: The item type slug (e.g., "deli_sandwich", "espresso")

        Returns:
            List of Selection objects, empty if no selections found
        """
        # Use ExtractionPipeline for typed results
        result = _pipeline.extract_attributes(user_input, item_type)

        if not result.values:
            return []

        selections: list[Selection] = []

        for attr_slug, value in result.values.items():
            if isinstance(value, list):
                # Multi-select attribute: list of {slug, quantity, display_name, ...}
                for item in value:
                    if isinstance(item, dict):
                        slug = item.get("slug", "")
                        quantity = item.get("quantity", 1)
                        category = item.get("category") or attr_slug
                        price = item.get("price", 0.0)
                        display_name = item.get("display_name")
                        if slug:
                            selections.append(Selection(
                                slug=slug,
                                category=category,
                                quantity=quantity,
                                price=price,
                                display_name=display_name,
                            ))
            elif isinstance(value, bool):
                # Boolean attribute - store as yes/no slug
                selections.append(Selection(
                    slug="yes" if value else "no",
                    category=attr_slug,
                    quantity=1,
                ))
            elif isinstance(value, str):
                # Single-select attribute: just the slug
                selections.append(Selection(
                    slug=value,
                    category=attr_slug,
                    quantity=1,
                ))

        if selections:
            logger.debug("Extracted selections from input: %s", selections)

        return selections

    def apply_selections(
        self, item: "MenuItemTask", selections: list[Selection]
    ) -> str | None:
        """
        Apply selections to a menu item in a data-driven way.

        Iterates through all selections and applies them generically using the
        item's add_selection() method. Note: Prices are NOT looked up here -
        they are calculated centrally in PricingEngine.recalculate_item_price()
        using GlobalAttributeOption.price_modifier as the single source of truth.

        Args:
            item: The menu item to apply selections to
            selections: List of Selection objects from user input

        Returns:
            Acknowledgment string if selections were applied, None otherwise
        """
        added_items = []

        for sel in selections:
            # Use add_selection for unified storage
            # Note: price is NOT passed - calculated in recalculate_item_price()
            item.add_selection(sel.slug, sel.category, sel.quantity)

            # Build display name for acknowledgment using database lookup
            display_name = sel.display_name or menu_cache.get_ingredient_display_name(sel.slug)
            added_items.append(display_name or format_slug_for_display(sel.slug, check_cache=False))

        # Build acknowledgment string
        if not added_items:
            return None

        items_str = format_english_list(added_items)
        return f"I've added {items_str}. "

    def extract_and_apply_selections(
        self, user_input: str, item: "MenuItemTask"
    ) -> str | None:
        """
        Extract selections from user input and apply them to the item.

        This is a convenience method that combines extraction and application.
        Call this after successfully handling an attribute input to capture
        any additional selections mentioned with the answer.

        Args:
            user_input: Raw user input string
            item: The menu item to apply selections to

        Returns:
            Acknowledgment string if selections were applied, None otherwise
        """
        item_type = item.menu_item_type
        if not item_type:
            return None

        selections = self.extract_selections_from_input(user_input, item_type)
        if selections:
            logger.info("Applying extracted selections to %s: %s", item.menu_item_name, selections)
            return self.apply_selections(item, selections)

        return None
