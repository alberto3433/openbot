"""
Dietary Inquiry Handler for Order State Machine.

This module handles dietary and allergen-related inquiries including:
- Dietary options inquiries ("do you have vegan options?")
- Specific item dietary inquiries ("is the classic gluten-free?")
- Allergen inquiries ("does X contain nuts?")
- Allergen-free options inquiries ("anything nut-free?")
- Availability inquiries ("do you have X in stock?")
- Customization inquiries ("can I customize X?")

Extracted as a specialized handler for dietary/allergen concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .mixins import MenuDataMixin
from .dietary_operations import DietaryOperations
from .dietary_operations import DIETARY_DISPLAY_NAMES  # noqa: F401 — re-export
from .dietary_operations import _allergen_display_name  # noqa: F401 — re-export
from .availability_operations import AvailabilityOperations
from .availability_operations import _SOMETHING_WITH_RE  # noqa: F401 — re-export

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .unrecognized_item_handler import UnrecognizedItemHandler

logger = logging.getLogger(__name__)


class DietaryInquiryHandler(MenuDataMixin):
    """
    Handles dietary and allergen-related inquiries.

    Manages dietary options listings, allergen inquiries, availability checks,
    and customization questions.
    """

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        unrecognized_handler: "UnrecognizedItemHandler | None" = None,
    ):
        """
        Initialize the dietary inquiry handler.

        Args:
            config: HandlerConfig with shared dependencies.
            unrecognized_handler: Handler for unrecognized item suggestions.
        """
        self._menu_data = config.menu_data if config else {}
        self._unrecognized_handler = unrecognized_handler
        self._dietary_ops = DietaryOperations(self)
        self._availability_ops = AvailabilityOperations(self)

    def _resolve_category_to_item_types(self, category: str) -> list[str] | None:
        """Resolve a category term to a list of item type slugs.

        Tries multiple resolution strategies:
        1. Display group lookup (e.g., "drinks" -> display group -> item types)
        2. Category keyword mapping (e.g., "bagels" -> item type "bagel")

        Args:
            category: User category term (e.g., "drinks", "bagels", "sandwiches")

        Returns:
            List of item type slugs, or None if category can't be resolved.
        """
        if not category:
            return None

        # Try display group lookup first
        display_group = menu_cache.get_display_group_by_slug(category)
        if display_group:
            item_types = menu_cache.get_item_types_in_display_group(display_group["slug"])
            if item_types:
                return item_types

        # Try category keyword mapping
        keyword_info = menu_cache.get_category_keyword_mapping(category)
        if keyword_info and keyword_info.get("slug"):
            return [keyword_info["slug"]]

        return None

    def handle_dietary_options_inquiry(
        self,
        dietary_type: str,
        order: OrderTask,
        category: str | None = None,
    ) -> StateMachineResult:
        return self._dietary_ops.handle_dietary_options_inquiry(dietary_type, order, category)

    def handle_dietary_item_inquiry(
        self,
        item_name: str,
        dietary_type: str,
        order: OrderTask,
    ) -> StateMachineResult:
        return self._dietary_ops.handle_dietary_item_inquiry(item_name, dietary_type, order)

    def handle_allergen_inquiry(
        self,
        item_name: str,
        allergen_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        return self._dietary_ops.handle_allergen_inquiry(item_name, allergen_type, order)

    def handle_allergen_free_options_inquiry(
        self,
        allergen_type: str,
        order: OrderTask,
    ) -> StateMachineResult:
        return self._dietary_ops.handle_allergen_free_options_inquiry(allergen_type, order)

    def _search_category_items(self, term: str) -> list[dict]:
        return self._availability_ops._search_category_items(term)

    def _handle_ingredient_items_search(
        self,
        ingredient_term: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        return self._availability_ops._handle_ingredient_items_search(ingredient_term, order)

    def handle_availability_inquiry(
        self,
        item_name: str,
        order: OrderTask,
    ) -> StateMachineResult:
        return self._availability_ops.handle_availability_inquiry(item_name, order)

    def handle_customization_inquiry(
        self,
        item_name: str,
        order: OrderTask,
    ) -> StateMachineResult:
        return self._availability_ops.handle_customization_inquiry(item_name, order)
