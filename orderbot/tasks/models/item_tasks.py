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

    All customizations (attribute choices and add-ons) are stored in a unified
    `selections` list using the standard selection format.

    Access methods:
    - get_selection(category): Get first selection for a category
    - get_selections(category): Get all selections for a category
    - get_selection_value(category): Get slug of first selection
    - has_selection(category): Check if any selection exists
    - add_selection(...): Add a new selection
    - remove_selection(...): Remove selection(s)
    - duplicate(): Create a deep copy with a new UUID

    Examples:
        item.add_selection("everything", "bread", display_name="Everything")
        item.add_selection("yes", "toasted", display_name="Toasted")
        item.add_selection("bacon", "protein", quantity=2)  # price calculated later

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

    # Track unmatched tokens user mentioned that don't match any option
    # Map of attr_slug -> {tokens: list[str]}
    # Used to show "We don't have X. We have A, B, C..." with pagination
    unmatched_selections: dict[str, dict] = Field(default_factory=dict)

    # Unified selections list - all customizations (attribute choices and add-ons)
    # Renamed from "modifiers" to "selections" for clarity - everything is a selection
    selections: list[dict] = Field(default_factory=list)  # Stored as dict for serialization

    # Track if customization checkpoint has been offered
    customization_offered: bool = False

    # Side item linking - if this item is a side (e.g., bagel with omelette),
    # this holds the ID of the parent item
    side_of_item_id: str | None = None

    # Item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions: list[str] = Field(default_factory=list)

    # Bundle fields - for items that include configurable sub-items (e.g., omelette + bagel)
    # bundle_id groups related items (parent + children share same bundle_id)
    bundle_id: str | None = None
    # bundle_parent_item_id points to the parent item's id (None for parent items)
    bundle_parent_item_id: str | None = None
    # bundle_slot identifies which slot this fills (e.g., "side")
    bundle_slot: str | None = None
    # bundle_price_rule determines pricing: "included" (base=0), "full_price", "fixed", etc.
    bundle_price_rule: str | None = None
    # bundle_included_price: dollar amount included in parent's price (for differential pricing)
    # None = entire base is free (e.g., bagel side), value = amount included (e.g., small fruit salad)
    bundle_included_price: float | None = None

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
    # Bundle helpers
    # -------------------------------------------------------------------------

    def is_bundle_parent(self) -> bool:
        """Check if this item is a bundle parent (has bundle_id but no parent_item_id)."""
        return self.bundle_id is not None and self.bundle_parent_item_id is None

    def is_bundle_child(self) -> bool:
        """Check if this item is a bundle child (has both bundle_id and parent_item_id)."""
        return self.bundle_id is not None and self.bundle_parent_item_id is not None

    def is_included_in_bundle(self) -> bool:
        """Check if this item's base price is included in a parent's price."""
        return self.bundle_price_rule == "included"

    def start_bundle(self) -> str:
        """Initialize this item as a bundle parent.

        Returns:
            The generated bundle_id
        """
        self.bundle_id = str(uuid.uuid4())
        return self.bundle_id

    # -------------------------------------------------------------------------
    # Backward compatibility alias
    # -------------------------------------------------------------------------

    @property
    def modifiers(self) -> list[dict]:
        """DEPRECATED: Use `selections` instead. This alias exists for backward compatibility."""
        return self.selections

    @modifiers.setter
    def modifiers(self, value: list[dict]) -> None:
        """DEPRECATED: Use `selections` instead. This alias exists for backward compatibility."""
        self.selections = value

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
        for sel in self.selections:
            if sel.get("category") == category:
                return sel
        return None

    def get_selections(self, category: str) -> list[dict]:
        """Get all selections for a category (for multi-select).

        Excludes declined markers (_declined) which are only used for tracking
        that an attribute was explicitly answered.

        Args:
            category: The category to filter by

        Returns:
            List of Selection dicts matching the category
        """
        return [
            sel for sel in self.selections
            if sel.get("category") == category and sel.get("slug") != "_declined"
        ]

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
        return any(sel.get("category") == category for sel in self.selections)

    def get_missing_required_fields(self, field_configs: dict) -> list:
        """Get list of required fields that are missing values.

        Override for MenuItemTask: checks selections instead of direct attributes.
        """
        missing = []
        for field_name, config in field_configs.items():
            if not config.required:
                continue
            # Check selections for this field (e.g., "bread", "toasted")
            if not self.has_selection(field_name) and config.default is None:
                missing.append(config)
        return missing

    def get_fields_to_ask(self, field_configs: dict) -> list:
        """Get list of fields that need to be asked about.

        Override for MenuItemTask: checks selections instead of direct attributes.
        """
        to_ask = []
        for field_name, config in field_configs.items():
            # Get current value from selections
            current_value = self.get_selection_value(field_name)
            if config.needs_asking(current_value):
                to_ask.append(config)
        return to_ask

    def get_progress(self, field_configs: dict) -> float:
        """Get completion progress as a percentage (0.0 to 1.0).

        Override for MenuItemTask: checks selections instead of direct attributes.
        """
        if not field_configs:
            return 1.0 if self.is_complete() else 0.0

        required_fields = [f for f in field_configs.values() if f.required]
        if not required_fields:
            return 1.0 if self.is_complete() else 0.0

        filled = 0
        for config in required_fields:
            # Check selections for this field
            if self.has_selection(config.name) or config.default is not None:
                filled += 1

        return filled / len(required_fields)

    def add_selection(
        self,
        slug: str,
        category: str,
        quantity: int = 1,
        price: float = 0.0,  # DEPRECATED: Price is now calculated in recalculate_item_price()
        display_name: str | None = None,
        ingredient_category: str | None = None,
        is_default: bool = False,
        _skip_display: bool = False,
    ) -> None:
        """Add a selection to the item.

        Note: The `price` parameter is DEPRECATED and ignored. Prices are now
        calculated centrally in PricingEngine.recalculate_item_price() using
        GlobalAttributeOption.price_modifier as the single source of truth.
        This prevents double-counting bugs from storing prices at multiple points.

        Args:
            slug: Selected option identifier (e.g., "plain", "bacon", "yes")
            category: What type of selection (e.g., "bread", "protein", "toasted")
            quantity: How many (default 1)
            price: DEPRECATED - ignored, kept for backward compatibility
            display_name: Human-readable name (looked up from cache if not provided)
            ingredient_category: The ingredient's category (e.g., "syrup", "sweetener")
                for quantity unit lookup. Different from category (attribute slug).
            is_default: True if this selection is a default ingredient for a signature item.
                Used for "already comes with X" messaging when user mentions a default.
            _skip_display: If True, this selection won't appear in get_summary().
                Used for tracking entries where display is handled elsewhere.
        """
        # Check if already present (same slug and category)
        for existing in self.selections:
            if existing.get("slug") == slug and existing.get("category") == category:
                # Update quantity if new quantity is explicitly set (> 1)
                # This handles the case where pre_filled adds with qty=1, then
                # extracted_selections tries to add with the actual qty
                if quantity > 1 and existing.get("quantity", 1) == 1:
                    existing["quantity"] = quantity
                # Price updates are no longer done here - all pricing happens in recalculate_item_price()
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

        # Build selection entry - price starts at 0, calculated later in recalculate_item_price()
        selection = {
            "slug": slug,
            "category": category,
            "quantity": quantity,
            "price": 0.0,  # Always 0 - real price calculated in recalculate_item_price()
            "display_name": display_name,
        }
        if ingredient_category:
            selection["ingredient_category"] = ingredient_category
        if is_default:
            selection["is_default"] = True
        if _skip_display:
            selection["_skip_display"] = True

        self.selections.append(selection)
        # Note: unit_price is NOT updated here - it's calculated in recalculate_item_price()

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
        while i < len(self.selections):
            sel = self.selections[i]
            if sel.get("category") == category:
                if slug is None or sel.get("slug") == slug:
                    removed = self.selections.pop(i)
                    # Subtract price from unit_price
                    price = removed.get("price", 0)
                    if price > 0:
                        self.unit_price -= price * removed.get("quantity", 1)
                    removed_any = True
                    continue  # Don't increment i since we removed an element
            i += 1
        return removed_any

    def find_modifier_by_slug(self, slug: str) -> dict | None:
        """Find a modifier by its slug.

        Args:
            slug: The slug to search for (e.g., "egg", "bacon")

        Returns:
            The modifier dict if found, None otherwise
        """
        for mod in self.selections:
            if mod.get("slug") == slug:
                return mod
        return None

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
        for sel in self.selections:
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
        # Check if we're setting a value that already exists as a default ingredient
        # If so, skip - the default is already there with the correct pricing (included in base)
        if value and not isinstance(value, bool):
            slugs_to_set = [str(value)] if not isinstance(value, list) else [str(v) for v in value if isinstance(v, str)]
            existing_defaults = [
                m for m in self.selections
                if m.get("category") == key and m.get("is_default") and m.get("slug") in slugs_to_set
            ]
            if existing_defaults:
                # All values we're trying to set are already defaults
                if len(existing_defaults) == len(slugs_to_set):
                    # User explicitly selected the same option as the default
                    # Mark as user-selected (not auto-populated) so it's not re-asked
                    for sel in existing_defaults:
                        sel["is_default"] = False
                    return
                # Some values are defaults, some aren't - only add the non-defaults
                default_slugs = {m.get("slug") for m in existing_defaults}
                slugs_to_set = [s for s in slugs_to_set if s not in default_slugs]
                if not slugs_to_set:
                    return
                # Update value to only include non-defaults
                value = slugs_to_set if isinstance(value, list) else slugs_to_set[0]

        # Remove existing selections for this category
        # For single-select attributes: remove ALL (including defaults) - user's choice replaces default
        # For multi-select attributes: only remove non-defaults (user is adding to the list)
        is_multi_select = menu_cache.is_multi_select_attribute(key)
        if is_multi_select:
            # Multi-select: preserve defaults, only remove non-defaults
            self.selections = [
                m for m in self.selections
                if not (m.get("category") == key and not m.get("is_default"))
            ]
        else:
            # Single-select: user's explicit choice replaces any existing (including default)
            self.selections = [
                m for m in self.selections
                if m.get("category") != key
            ]

        # Treat None and integer 0 as "declined" (answered but no selection)
        # This handles quantity attributes where user says "no" (e.g., "no extra shots" = 0)
        if value is None or value == 0:
            # Mark as explicitly declined (so it's considered "answered")
            self.selections.append({
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
                elif isinstance(item, dict) and "slug" in item:
                    # Handle dict entries from extraction (e.g., spread modifiers)
                    self.add_selection(
                        slug=item["slug"],
                        category=key,
                        quantity=item.get("quantity", 1),
                        display_name=item.get("display_name"),
                        ingredient_category=item.get("category"),
                    )
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

    def has_default_ingredients(self) -> bool:
        """Check if this item has default ingredients loaded.

        Returns True if any modifier has is_default=True, indicating this is
        a pre-configured item (like signature sandwiches or omelettes) whose
        name should remain fixed and ingredients shown as sub-lines.

        This is more data-driven than checking is_signature flag - it's based
        on whether the item actually has menu_item_ingredients defined.
        """
        return any(mod.get("is_default", False) for mod in self.selections)

    def get_display_name(self) -> str:
        """Get display name for this menu item.

        For items with default ingredients (signature items, omelettes, etc.),
        always returns the menu item name (e.g., "The Classic BEC") -
        bread/ingredients appear as modifier sub-lines instead.

        For configurable items without defaults (like generic "Bagel"),
        uses the name-forming modifier's display name instead.

        Example: A "Bagel" with bread="garlic_bagel" returns "Garlic Bagel"
        """
        # Items with default ingredients keep their fixed name
        # (e.g., "The Classic BEC", "The Leo Omelette")
        # Check both selections AND database - defaults may exist in DB
        # even if they weren't successfully mapped to selections
        if self.has_default_ingredients():
            return self.menu_item_name

        # Also check database for defaults (e.g., Maple Raisin Walnut Cream
        # Cheese Sandwich has defaults but they may not map to attributes)
        if self.menu_item_id:
            try:
                db_defaults = menu_cache.get_menu_item_default_ingredients(
                    self.menu_item_id
                )
                if db_defaults:
                    return self.menu_item_name
            except MenuDataNotLoadedError:
                pass  # Fall through to name-forming logic

        # Check for name-forming category modifiers (e.g., bread type)
        for sel in self.selections:
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
