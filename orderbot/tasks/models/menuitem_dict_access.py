"""
Dict-style access mixin for MenuItemTask.

Provides property-based attribute_values access and dict-style
__getitem__, __setitem__, __delitem__, __contains__, and get() methods.
"""

from typing import Any

from orderbot.cache import menu_cache
from .utilities import _is_price_metadata_key


class DictAccessMixin:
    """Mixin providing dict-style access to selections for MenuItemTask.

    Expects the host class to define:
    - self.selections: list[dict]
    - self._attr_cache: dict | None
    - self.add_selection(...): method
    - self.remove_selection(...): method
    - self.has_selection(...): method
    """

    @property
    def attribute_values(self) -> dict[str, Any]:
        """Get selection values as a dict for display/serialization.

        Returns a dict with category->value mapping. Used for logging, display, and
        backward compatibility with code that reads attribute_values.
        """
        if self._attr_cache is not None:
            return self._attr_cache

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

        self._attr_cache = result
        return result

    @attribute_values.setter
    def attribute_values(self, value: dict[str, Any]) -> None:
        """Set selection values from a dict. Used for bulk initialization."""
        self._attr_cache = None  # Invalidate cache

        # Clear existing selections that would be overwritten
        # This is for backward compat when code sets attribute_values directly
        for key, val in value.items():
            # Skip metadata keys
            if _is_price_metadata_key(key):
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
        self._attr_cache = None  # Invalidate cache

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
                    # Value matches the default — keep is_default for pricing
                    # (included in base price) but mark as confirmed so
                    # configuration doesn't re-ask
                    for sel in existing_defaults:
                        sel["_confirmed"] = True
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
