"""
Display formatting mixin for MenuItemTask.

Provides methods for generating display names and summaries,
including handling of default ingredients, name-forming categories,
and unit suffixes.
"""

import logging

from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from .utilities import (
    pluralize_display_name,
    is_name_forming_category,
)

logger = logging.getLogger(__name__)


class DisplayFormattingMixin:
    """Mixin providing display formatting methods for MenuItemTask.

    Expects the host class to define:
    - self.selections: list[dict]
    - self.menu_item_name: str
    - self.menu_item_id: int | None
    - self.quantity: int
    - self.modifications: list[str]
    - self.removed_ingredients: list[str]
    """

    def has_default_ingredients(self) -> bool:
        """Check if this item has default ingredients loaded.

        Returns True if any modifier has is_default=True, indicating this is
        a pre-configured item (like signature sandwiches or omelettes) whose
        name should remain fixed and ingredients shown as sub-lines.

        This is data-driven - it's based
        on whether the item actually has menu_item_ingredients defined.
        """
        return any(mod.get("is_default", False) for mod in self.selections)

    def has_default_ingredients_resolved(self) -> bool:
        """Check if this item has default ingredients, checking both selections and DB.

        Unlike has_default_ingredients() which only checks loaded selections,
        this also checks the database for items where defaults exist but weren't
        mapped to selections (e.g., Maple Raisin Walnut Cream Cheese Sandwich).
        """
        if self.has_default_ingredients():
            return True
        if self.menu_item_id:
            try:
                db_defaults = menu_cache.get_menu_item_default_ingredients(
                    self.menu_item_id
                )
                return bool(db_defaults)
            except (MenuDataNotLoadedError, Exception):
                pass
        return False

    def get_display_name(self) -> str:
        """Get display name for this menu item.

        For items with default ingredients (signature items, omelettes, etc.),
        always returns the menu item name (e.g., "The Classic BEC") -
        bread/ingredients appear as modifier sub-lines instead.

        For configurable items without defaults (like generic "Bagel"),
        uses the name-forming modifier's display name instead.

        For pack items, appends the pack size (e.g., "Macaroons (3 pack)").

        Example: A "Bagel" with bread="garlic_bagel" returns "Garlic Bagel"
        """
        # Compute base display name
        base_name = self._get_base_display_name()

        # Append unit suffix for pack items (e.g., "(3 pack)")
        return self._append_unit_suffix(base_name)

    def _get_base_display_name(self) -> str:
        """Get the base display name without unit suffix."""
        # Items with default ingredients keep their fixed name
        # (e.g., "The Classic BEC", "The Leo Omelette")
        if self.has_default_ingredients_resolved():
            return self.menu_item_name

        # Check for name-forming category modifiers (e.g., bread type, tea flavor)
        for sel in self.selections:
            category = sel.get("category", "")
            if is_name_forming_category(category, sel.get("slug")):
                # Use the ingredient's display name if available
                display_name = sel.get("display_name")
                if display_name:
                    return display_name
                # Fall back to looking up from cache
                slug = sel.get("slug", "")
                if slug:
                    try:
                        ingredient_name = menu_cache.get_ingredient_display_name(slug)
                        if ingredient_name:
                            return ingredient_name
                    except MenuDataNotLoadedError:
                        logger.debug("Menu cache not loaded when getting display name for slug: %s", slug)
        # Default to menu item name
        return self.menu_item_name

    def _append_unit_suffix(self, name: str) -> str:
        """Append unit display suffix to item name if applicable.

        For pack items (e.g., macaroons sold in 3-packs), appends "(3 pack)".
        For dozen items, appends "(dozen)".
        For regular items, returns the name unchanged.
        """
        if not self.menu_item_name:
            return name
        try:
            unit_type, qty = menu_cache.get_menu_item_unit_info(self.menu_item_name)
            suffix = menu_cache.format_unit_display(unit_type, qty)
            if suffix:
                return f"{name} {suffix}"
        except MenuDataNotLoadedError:
            pass
        return name

    def get_summary(self) -> str:
        """Get a summary description of this menu item.

        Returns uniform summary in format:
        "{quantity}x {menu_item_name}, {selection1}, {selection2}, ..."

        Examples:
            "Everything Bagel, Toasted, Scallion Cream Cheese"
            "Latte, Large, Iced, Oat Milk"
            "2x Turkey Club, Sourdough, Bacon"
        """
        base_name = self.get_display_name()
        if self.quantity > 1:
            base_name = f"{self.quantity}x {base_name}"

        # Collect display names from selections
        displays = []
        for sel in self.selections:
            slug = sel.get("slug", "")
            category = sel.get("category", "")
            display_name = sel.get("display_name", "")
            quantity = sel.get("quantity", 1)

            # Skip selections marked as hidden (e.g., tracking entries for quantity modifiers)
            if sel.get("_skip_display"):
                continue

            # Skip "no" and "_declined" selections (user declined)
            if slug in ("no", "_declined"):
                continue

            # Skip name-forming categories (already part of base name)
            if is_name_forming_category(category, slug):
                continue

            # Skip default ingredients (already implied by the signature item name)
            if sel.get("is_default"):
                continue

            if display_name:
                if quantity > 1:
                    plural_name = pluralize_display_name(display_name)
                    displays.append(f"{quantity}x {plural_name}")
                else:
                    displays.append(display_name)

        # Build final summary
        if displays:
            summary = f"{base_name}, {', '.join(displays)}"
        else:
            summary = base_name

        # Add modifications in parentheses
        if self.modifications:
            summary += f" ({', '.join(self.modifications)})"

        # Add removed ingredients
        if self.removed_ingredients:
            removed_parts = [f"no {ing}" for ing in self.removed_ingredients]
            summary += f" ({', '.join(removed_parts)})"

        return summary
