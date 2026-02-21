"""
Core item type query mixin for MenuDataCache.

Contains methods for querying item types, configurable types, and type metadata.
"""

import logging

from .base import ensure_cache_loaded, normalize_text, pluralize

logger = logging.getLogger(__name__)


class ItemTypeCoreQueryMixin:
    """Mixin containing core item type query methods."""

    @ensure_cache_loaded
    def get_all_item_type_slugs(self) -> set[str]:
        """Get all available item type slugs.

        Returns:
            Set of item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return set(self._item_names_by_type.keys())

    @ensure_cache_loaded
    def get_item_type_names_for_regex(self) -> list[str]:
        """Get item type names/aliases for use in regex patterns.

        Returns names and aliases sorted by length (longest first) for
        proper regex matching.

        Returns:
            List of item type names/aliases for regex patterns.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        names = []
        for keyword, info in self._category_keywords.items():
            if info.get("lookup_type") == "item_type":
                names.append(keyword)
        return sorted(names, key=len, reverse=True)

    @ensure_cache_loaded
    def get_modifier_category(self, item_type_slug: str) -> str | None:
        """Get the modifier category for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")

        Returns:
            Modifier category ("food", "beverage", or None).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._item_type_modifier_categories.get(item_type_slug)

    @ensure_cache_loaded
    def get_item_keywords(self) -> set[str]:
        """Get all item keywords for disambiguation.

        Returns:
            Set of keywords including menu item names and item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._item_keywords.copy()

    @ensure_cache_loaded
    def get_configurable_item_types(self) -> set[str]:
        """Get item types that have attributes defined.

        Returns:
            Set of item type slugs that are configurable.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._configurable_item_types.copy()

    @ensure_cache_loaded
    def get_simple_item_types(self) -> set[str]:
        """Get item types that have no attributes to ask about.

        These are "simple" items like beverages, pastries, sides that
        can be added to an order without configuration questions.

        Returns:
            Set of item type slugs that are NOT configurable.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        all_types = self.get_all_item_type_slugs()
        configurable = self._configurable_item_types
        return all_types - configurable

    @ensure_cache_loaded
    def get_generic_item_types(self) -> set[str]:
        """Get item types flagged as generic (deprioritized in trigger matching).

        Returns:
            Set of item type slugs marked as generic in the database.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._generic_item_types.copy()

    @ensure_cache_loaded
    def item_type_has_side_choice(self, item_type_slug: str) -> bool:
        """Check if an item type has a side choice attribute.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has side choice.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        config = self._item_type_side_choice.get(item_type_slug, {})
        return config.get("has_side_choice", False)

    @ensure_cache_loaded
    def get_side_choice_attribute(self, item_type_slug: str) -> dict | None:
        """Get side choice attribute details for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict with slug, question_text, display_name, or None.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        config = self._item_type_side_choice.get(item_type_slug, {})
        return config.get("side_choice_attribute")

    # -------------------------------------------------------------------------
    # Component Slots (Bundled Items)
    # -------------------------------------------------------------------------

    @ensure_cache_loaded
    def item_type_has_component_slots(self, item_type_slug: str) -> bool:
        """Check if an item type has component slots (includes configurable sub-items).

        Args:
            item_type_slug: The item type slug (e.g., "omelette")

        Returns:
            True if this item type has component slots, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return item_type_slug in self._component_slots and len(self._component_slots[item_type_slug]) > 0

    @ensure_cache_loaded
    def get_component_slots(self, item_type_slug: str) -> dict[str, dict]:
        """Get all component slots for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "omelette")

        Returns:
            Dict mapping slot_name -> slot_config. Empty dict if no slots.
            Each slot_config contains:
            - display_name: Human-readable name for the slot
            - prompt_text: Question to ask user
            - is_required: Whether the slot must be filled
            - min_quantity, max_quantity: How many items can fill this slot
            - options: List of option dicts with:
              - allowed_item_type: Item type slug if this option is an item type
              - allowed_menu_item_id: Menu item ID if this option is a specific item
              - price_rule: "included", "full_price", "fixed", etc.
              - fixed_price: For fixed/discount pricing rules
              - display_name: Display name for this option

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._component_slots.get(item_type_slug, {}).copy()

    @ensure_cache_loaded
    def get_component_slot(self, item_type_slug: str, slot_name: str) -> dict | None:
        """Get a specific component slot configuration.

        Args:
            item_type_slug: The item type slug (e.g., "omelette")
            slot_name: The slot name (e.g., "side")

        Returns:
            Slot config dict or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        slots = self._component_slots.get(item_type_slug, {})
        return slots.get(slot_name)

    def get_component_slot_options(self, item_type_slug: str, slot_name: str) -> list[dict]:
        """Get the available options for a component slot.

        Args:
            item_type_slug: The item type slug (e.g., "omelette")
            slot_name: The slot name (e.g., "side")

        Returns:
            List of option dicts with allowed_item_type, price_rule, etc.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        slot = self.get_component_slot(item_type_slug, slot_name)
        if not slot:
            return []
        return slot.get("options", [])

    @ensure_cache_loaded
    def get_unfilled_component_slots(self, item_type_slug: str, filled_slots: set[str]) -> list[dict]:
        """Get component slots that haven't been filled yet.

        Args:
            item_type_slug: The item type slug (e.g., "omelette")
            filled_slots: Set of slot names that have been filled

        Returns:
            List of slot config dicts for unfilled required slots.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        slots = self._component_slots.get(item_type_slug, {})
        unfilled = []
        for slot_name, slot_config in slots.items():
            if slot_name not in filled_slots:
                unfilled.append({
                    "slot_name": slot_name,
                    **slot_config
                })
        return unfilled

    @ensure_cache_loaded
    def resolve_item_type_slug(self, name_or_alias: str) -> str:
        """Resolve an item type name or alias to its canonical database slug.

        Args:
            name_or_alias: Item type name or alias. Case-insensitive.

        Returns:
            The canonical item type slug from the database.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """

        name_lower = normalize_text(name_or_alias)
        category_info = self._category_keywords.get(name_lower)

        if category_info and "slug" in category_info:
            return category_info["slug"]

        return name_or_alias

    @ensure_cache_loaded
    def infer_item_type_from_text(self, text: str) -> dict | None:
        """Infer item type by checking if any category keyword appears in the text.

        Args:
            text: User input text like "orange juice" or "blueberry muffin"

        Returns:
            Dict with item type info if a keyword is found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """

        text_lower = text.lower()
        words = text_lower.split()

        for word in words:
            if word in self._category_keywords:
                return self._category_keywords[word]

        for keyword, info in self._category_keywords.items():
            if " " in keyword and keyword in text_lower:
                return info

        return None

    @ensure_cache_loaded
    def get_item_type_display_name(self, item_type_slug: str, plural: bool = False) -> str:
        """Get the display name for an item type slug.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")
            plural: If True, return plural form for suggestions

        Returns:
            Display name string. Returns slug if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """

        info = self._category_keywords.get(item_type_slug)
        if info:
            if plural:
                return info.get("display_name_plural", pluralize(info.get("display_name", item_type_slug)))
            return info.get("display_name", item_type_slug)

        return item_type_slug

    @ensure_cache_loaded
    def item_accepts_input_modifiers(self, item_type_slug: str) -> bool:
        """Check if an item type accepts input modifiers.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has a modifier category defined.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self.get_modifier_category(item_type_slug) is not None

    @ensure_cache_loaded
    def get_scannable_modifier_categories(self, item_type_slug: str) -> list[str]:
        """Get modifier categories that can be scanned for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            List of scannable modifier category slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        modifier_type = self.get_modifier_category(item_type_slug)
        if not modifier_type:
            return []
        return self.get_ordered_ingredient_categories(modifier_type)
