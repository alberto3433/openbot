"""
Item task models for the hierarchical task system.
"""

import logging
from typing import Any, Literal
import uuid

from pydantic import Field

from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError

from .base import BaseTask
from .utilities import (
    format_slug_for_display,
    pluralize_display_name,
    is_name_forming_category,
    _get_is_price_metadata_key,
)

logger = logging.getLogger(__name__)


class ItemTask(BaseTask):
    """Base class for order items."""

    item_type: str
    quantity: int = 1
    unit_price: float = 0.0

    def get_display_name(self) -> str:
        """Get display name for this item."""
        raise NotImplementedError

    def get_summary(self) -> str:
        """Get a summary description of this item."""
        raise NotImplementedError


class MenuItemTask(ItemTask):
    """Task for a menu item ordered by name (e.g., 'The Chipotle Egg Omelette').

    All customizations (attribute choices and modifier add-ons) are stored in
    a unified `modifiers` list using the standard modifier format.

    Access methods:
    - get_selection(category): Get first modifier for a category
    - get_selections(category): Get all modifiers for a category
    - get_selection_value(category): Get slug of first modifier
    - has_selection(category): Check if any modifier exists
    - add_selection(...): Add a new modifier
    - remove_selection(...): Remove modifier(s)
    - duplicate(): Create a deep copy with a new UUID

    Examples:
        item.add_selection("everything", "bread", display_name="Everything")
        item.add_selection("yes", "toasted", display_name="Toasted")
        item.add_selection("bacon", "protein", quantity=2, price=1.50)

        bread = item.get_selection_value("bread")  # "everything"
        is_toasted = item.get_selection_value("toasted") == "yes"

        # Duplicate an item
        new_item = item.duplicate()
    """

    item_type: Literal["menu_item"] = "menu_item"

    # Menu item fields
    menu_item_name: str  # The name of the menu item
    menu_item_id: int | None = None  # Database ID if matched
    menu_item_type: str | None = None  # Type slug (e.g., "omelette", "sandwich")
    modifications: list[str] = Field(default_factory=list)  # User modifications
    removed_ingredients: list[str] = Field(default_factory=list)  # Default ingredients that were removed

    is_signature: bool = False  # Whether this is a signature/featured menu item

    # Track unavailable options user attempted to select
    # Map of attr_slug -> {attempted_slug, attempted_display}
    # Used to show helpful "We don't have X - we have Y or Z" messages
    unavailable_selections: dict[str, dict] = Field(default_factory=dict)

    # Unified modifiers list - all customizations (attributes and modifiers)
    modifiers: list[dict] = Field(default_factory=list)  # Stored as dict for serialization

    # Track if customization checkpoint has been offered
    customization_offered: bool = False

    # Side item linking - if this item is a side (e.g., bagel with omelette),
    # this holds the ID of the parent item
    side_of_item_id: str | None = None

    # Item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions: list[str] = Field(default_factory=list)

    # -------------------------------------------------------------------------
    # Side item helpers
    # -------------------------------------------------------------------------

    def duplicate(self, mark_complete: bool = True) -> "MenuItemTask":
        """Create a deep copy of this item with a new UUID.

        Args:
            mark_complete: If True, mark the new item as complete (default True)

        Returns:
            A new MenuItemTask with the same data but a unique ID
        """
        new_item = self.model_copy(deep=True)
        new_item.id = str(uuid.uuid4())
        if mark_complete:
            new_item.mark_complete()
        return new_item

    # -------------------------------------------------------------------------
    # Selection access methods
    # -------------------------------------------------------------------------

    def get_selection(self, category: str) -> dict | None:
        """Get first selection for a category (for single-select attributes).

        Args:
            category: The category to look up (e.g., "bread", "size", "toasted")

        Returns:
            Selection dict or None if not found
        """
        for sel in self.modifiers:
            if sel.get("category") == category:
                return sel
        return None

    def get_selections(self, category: str) -> list[dict]:
        """Get all selections for a category (for multi-select).

        Args:
            category: The category to filter by

        Returns:
            List of Selection dicts matching the category
        """
        return [sel for sel in self.modifiers if sel.get("category") == category]

    def get_selection_value(self, category: str) -> str | None:
        """Get the slug of the first selection for a category.

        Convenience method for single-select attributes.

        Args:
            category: The category to look up

        Returns:
            The slug value or None if not found
        """
        sel = self.get_selection(category)
        return sel.get("slug") if sel else None

    def has_selection(self, category: str) -> bool:
        """Check if any selection exists for a category.

        Args:
            category: The category to check

        Returns:
            True if at least one selection exists for this category
        """
        return any(sel.get("category") == category for sel in self.modifiers)

    def add_selection(
        self,
        slug: str,
        category: str,
        quantity: int = 1,
        price: float = 0.0,
        display_name: str | None = None,
        ingredient_category: str | None = None,
    ) -> None:
        """Add a selection to the item.

        Args:
            slug: Selected option identifier (e.g., "plain", "bacon", "yes")
            category: What type of selection (e.g., "bread", "protein", "toasted")
            quantity: How many (default 1)
            price: Price contribution per unit (default 0.0)
            display_name: Human-readable name (looked up from cache if not provided)
            ingredient_category: The ingredient's category (e.g., "syrup", "sweetener")
                for quantity unit lookup. Different from category (attribute slug).
        """
        # Check if already present (same slug and category)
        for existing in self.modifiers:
            if existing.get("slug") == slug and existing.get("category") == category:
                # Update quantity if new quantity is explicitly set (> 1)
                # This handles the case where pre_filled adds with qty=1, then
                # extracted_selections tries to add with the actual qty
                if quantity > 1 and existing.get("quantity", 1) == 1:
                    existing["quantity"] = quantity
                # Update price if new price is greater (0.0 means "unknown", positive means "known")
                # This handles the case where pre_filled adds with price=0, then
                # extracted_selections tries to add with the actual price
                if price > 0 and existing.get("price", 0) == 0:
                    existing["price"] = price
                    # Also update unit_price since we now have the real price
                    self.unit_price = (self.unit_price or 0.0) + (price * existing.get("quantity", 1))
                return

        # Look up display name from database if not provided
        if not display_name:
            try:
                # Try global attribute option lookup first (for bread, size, etc.)
                display_name = menu_cache.get_global_option_display_name(category, slug)
                if not display_name:
                    # Fall back to ingredient lookup
                    display_name = menu_cache.get_ingredient_display_name(slug)
            except MenuDataNotLoadedError:
                logger.debug("Menu cache not loaded when looking up display name for %s/%s", category, slug)

        # Fall back to title-cased slug if lookup failed
        if not display_name:
            # Handle boolean slugs specially
            if slug == "yes":
                display_name = format_slug_for_display(category)
            elif slug == "no":
                display_name = f"Not {format_slug_for_display(category)}"
            else:
                display_name = format_slug_for_display(slug)

        # Build selection entry
        selection = {
            "slug": slug,
            "category": category,
            "quantity": quantity,
            "price": price,
            "display_name": display_name,
        }
        if ingredient_category:
            selection["ingredient_category"] = ingredient_category

        self.modifiers.append(selection)

        # Update unit_price if selection has a price
        if price > 0:
            self.unit_price = (self.unit_price or 0.0) + (price * quantity)

    def remove_selection(self, category: str, slug: str | None = None) -> bool:
        """Remove selection(s) by category and optionally slug.

        Args:
            category: The category to remove from
            slug: If provided, only remove selection with this slug.
                  If None, removes ALL selections for this category.

        Returns:
            True if any selections were removed, False otherwise
        """
        removed_any = False
        i = 0
        while i < len(self.modifiers):
            sel = self.modifiers[i]
            if sel.get("category") == category:
                if slug is None or sel.get("slug") == slug:
                    removed = self.modifiers.pop(i)
                    # Subtract price from unit_price
                    price = removed.get("price", 0)
                    if price > 0:
                        self.unit_price -= price * removed.get("quantity", 1)
                    removed_any = True
                    continue  # Don't increment i since we removed an element
            i += 1
        return removed_any

    # -------------------------------------------------------------------------
    # Dict-style access API (primary interface)
    # -------------------------------------------------------------------------

    @property
    def attribute_values(self) -> dict[str, Any]:
        """Get selection values as a dict for display/serialization.

        Returns a dict with category->value mapping. Used for logging, display, and
        backward compatibility with code that reads attribute_values.
        """
        result: dict[str, Any] = {}
        for sel in self.modifiers:
            category = sel.get("category", "")
            slug = sel.get("slug", "")
            display_name = sel.get("display_name")
            price = sel.get("price", 0)

            # Handle declined attributes (user said "no" to optional question)
            if slug == "_declined":
                result[category] = None
                continue

            # For boolean categories, convert yes/no to True/False
            if slug == "yes":
                result[category] = True
            elif slug == "no":
                result[category] = False
            else:
                # Check if multi-select (already have a value for this category)
                if category in result:
                    existing = result[category]
                    if isinstance(existing, list):
                        existing.append(slug)
                    else:
                        result[category] = [existing, slug]
                else:
                    result[category] = slug

            # Store price
            if price > 0:
                result[f"{category}_price"] = price

        return result

    @attribute_values.setter
    def attribute_values(self, value: dict[str, Any]) -> None:
        """Set selection values from a dict. Used for bulk initialization."""
        # Clear existing selections that would be overwritten
        # This is for backward compat when code sets attribute_values directly
        for key, val in value.items():
            # Skip metadata keys
            if _get_is_price_metadata_key()(key):
                continue

            # Remove existing selections for this category
            self.remove_selection(key)

            # Add new selection(s)
            if isinstance(val, bool):
                self.add_selection("yes" if val else "no", key)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        self.add_selection(item, key)
            elif val is not None:
                self.add_selection(str(val), key)

    def __getitem__(self, key: str) -> Any:
        """Get selection value by category: item["size"], item["bread"], etc."""
        return self.attribute_values.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Set selection by category: item["size"] = "large"."""
        # Remove existing selection for this category
        self.remove_selection(key)

        if value is None:
            # Mark as explicitly declined (so it's considered "answered")
            self.modifiers.append({
                "slug": "_declined",
                "category": key,
                "quantity": 0,
                "price": 0,
                "display_name": "None",
            })
            return

        # Add new selection
        if isinstance(value, bool):
            self.add_selection("yes" if value else "no", key)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    self.add_selection(item, key)
        else:
            self.add_selection(str(value), key)

    def __delitem__(self, key: str) -> None:
        """Delete selection by category: del item["size"]."""
        self.remove_selection(key)

    def __contains__(self, key: str) -> bool:
        """Check if selection exists: "size" in item."""
        return self.has_selection(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Get selection value with default."""
        val = self.attribute_values.get(key)
        return val if val is not None else default

    # -------------------------------------------------------------------------
    # Attribute query method (data-driven)
    # -------------------------------------------------------------------------

    def has_attribute(self, attr_slug: str) -> bool:
        """Check if this item type has a specific attribute defined in the database.

        Args:
            attr_slug: The attribute slug to check for

        Returns:
            True if this item type has the specified attribute, False otherwise.
        """
        if not self.menu_item_type:
            return False
        attrs = menu_cache.get_item_type_attributes(self.menu_item_type)

        if attr_slug in attrs:
            return True

        # Check legacy aliases
        field_map = menu_cache.get_field_to_slug_map(self.menu_item_type) or {}
        db_slug = field_map.get(attr_slug)
        if db_slug and db_slug in attrs:
            return True

        return False

    # -------------------------------------------------------------------------
    # Display helpers
    # -------------------------------------------------------------------------

    def get_display_name(self) -> str:
        """Get display name for this menu item.

        For signature items, always returns the menu item name (e.g.,
        "The Classic BEC") - bread appears as a modifier sub-line instead.

        For non-signature items with name-forming modifiers (like bread type),
        uses the ingredient's display name instead of the generic menu item name.

        Example: A "Bagel" with bread="garlic_bagel" returns "Garlic Bagel"
        """
        # Signature items always keep their name
        if self.is_signature:
            return self.menu_item_name

        # Check for name-forming category modifiers (e.g., bread type)
        for sel in self.modifiers:
            category = sel.get("category", "")
            if is_name_forming_category(category):
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
        for sel in self.modifiers:
            slug = sel.get("slug", "")
            category = sel.get("category", "")
            display_name = sel.get("display_name", "")
            quantity = sel.get("quantity", 1)

            # Skip "no" and "_declined" selections (user declined)
            if slug in ("no", "_declined"):
                continue

            # Skip name-forming categories (already part of base name)
            if is_name_forming_category(category):
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
