"""
Selection management mixin for MenuItemTask.

Provides methods for querying, adding, and removing selections,
as well as field/progress tracking based on selections.
"""

import logging

from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.tasks.normalization import format_slug_for_display, normalize_to_slug

logger = logging.getLogger(__name__)


class SelectionManagementMixin:
    """Mixin providing selection management methods for MenuItemTask.

    Expects the host class to define:
    - self.selections: list[dict]
    - self._attr_cache: dict | None
    - self.menu_item_name: str
    """

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
        price: float = 0.0,  # Accepted for caller compat; ignored (pricing engine sets prices)
        display_name: str | None = None,
        ingredient_category: str | None = None,
        is_default: bool = False,
        _skip_display: bool = False,
        increment_if_exists: bool = False,
    ) -> None:
        """Add a selection to the item.

        Args:
            slug: Selected option identifier (e.g., "plain", "bacon", "yes")
            category: What type of selection (e.g., "bread", "protein", "toasted")
            quantity: How many (default 1)
            price: Ignored. Prices are calculated in recalculate_item_price().
            display_name: Human-readable name (looked up from cache if not provided)
            ingredient_category: The ingredient's category (e.g., "syrup", "sweetener")
                for quantity unit lookup. Different from category (attribute slug).
            is_default: True if this selection is a default ingredient for a signature item.
                Used for "already comes with X" messaging when user mentions a default.
            _skip_display: If True, this selection won't appear in get_summary().
                Used for tracking entries where display is handled elsewhere.
            increment_if_exists: If True and selection already exists, increment quantity
                instead of silently returning. Use for user "add X" commands.
        """
        self._attr_cache = None  # Invalidate cache

        # Check if already present (same slug and category)
        for existing in self.selections:
            if existing.get("slug") == slug and existing.get("category") == category:
                if increment_if_exists:
                    # User is explicitly adding more - increment quantity
                    existing["quantity"] = existing.get("quantity", 1) + quantity
                    return
                # Update quantity if new quantity is explicitly set (> 1)
                # This handles the case where pre_filled adds with qty=1, then
                # extracted_selections tries to add with the actual qty
                if quantity > 1 and existing.get("quantity", 1) == 1:
                    existing["quantity"] = quantity
                if display_name and existing.get("display_name") != display_name:
                    existing["display_name"] = display_name
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

        # Build selection entry - price calculated later in recalculate_item_price()
        selection = {
            "slug": slug,
            "category": category,
            "quantity": quantity,
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

    def remove_selection(
        self,
        category: str,
        slug: str | None = None,
        decrement_by: int | None = None,
    ) -> bool:
        """Remove selection(s) by category and optionally slug.

        Args:
            category: The category to remove from
            slug: If provided, only remove selection with this slug.
                  If None, removes ALL selections for this category.
            decrement_by: If provided, decrement quantity by this amount instead
                  of removing entirely. Only applies when slug is specified.
                  If resulting quantity <= 0, the selection is removed.
                  If None, removes the entire selection (existing behavior).

        Returns:
            True if any selections were removed or decremented, False otherwise
        """
        self._attr_cache = None  # Invalidate cache

        removed_any = False
        i = 0
        while i < len(self.selections):
            sel = self.selections[i]
            if sel.get("category") == category:
                if slug is None or sel.get("slug") == slug:
                    # Check if we should decrement instead of remove
                    if decrement_by is not None and slug is not None:
                        current_qty = sel.get("quantity", 1)
                        new_qty = current_qty - decrement_by
                        if new_qty > 0:
                            # Decrement quantity instead of removing
                            sel["quantity"] = new_qty
                            removed_any = True
                            i += 1  # Move to next, we didn't remove this one
                            continue
                        # new_qty <= 0: fall through to remove the entire selection

                    self.selections.pop(i)
                    removed_any = True
                    continue  # Don't increment i since we removed an element
            i += 1
        return removed_any

    def remove_selections_by_term(self, target: str) -> bool:
        """Remove selection(s) that contain the target term in slug or display name.

        Used for modifier change operations like "change vanilla syrup to caramel"
        where we need to find and remove any selection containing "vanilla".

        Args:
            target: The search term (e.g., "vanilla", "bacon")

        Returns:
            True if any selections were removed, False otherwise
        """
        if not target or not self.selections:
            return False

        self._attr_cache = None  # Invalidate cache

        target_slug = normalize_to_slug(target)
        removed_any = False
        i = 0
        while i < len(self.selections):
            sel = self.selections[i]
            slug_match = target_slug in sel.get("slug", "").replace("_", " ").lower()
            display_match = target_slug in sel.get("display_name", "").lower()
            if slug_match or display_match:
                self.selections.pop(i)
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
