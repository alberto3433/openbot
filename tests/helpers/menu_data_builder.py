"""
Generic Menu Data Builder for Tests.

A fluent builder for creating test menu data structures. This builder has NO
domain-specific knowledge - tests define their own item types, attributes,
and options. This enables testing without coupling to any specific food domain.

IMPORTANT: This builder is ONLY for tests. It must NOT be imported by any code
in orderbot/ - production code must be data-driven from the database.

Example usage:
    menu = (MenuDataBuilder()
        .add_item_type("test_item", "Test Item")
        .add_attribute("test_item", "size", "Size",
            options=[
                {"slug": "small", "display_name": "Small", "price_modifier": 0.0},
                {"slug": "large", "display_name": "Large", "price_modifier": 1.0},
            ])
        .add_item("Test Product", "test_item", base_price=5.00)
        .build())
"""

from typing import Any


class MenuDataBuilder:
    """Generic fluent builder for test menu data.

    No domain-specific knowledge - tests define their own item types,
    attributes, and options. This makes the builder suitable for testing
    any restaurant or ordering domain.
    """

    def __init__(self):
        """Initialize an empty menu data builder."""
        self._item_types: dict[str, dict[str, Any]] = {}
        self._items: list[dict[str, Any]] = []
        self._categories: list[dict[str, str]] = []
        self._next_item_id: int = 1

    def add_item_type(
        self,
        slug: str,
        display_name: str,
        attributes: list[dict] | None = None,
    ) -> "MenuDataBuilder":
        """Add an item type with optional attributes.

        Args:
            slug: Unique identifier for the item type (e.g., "bagel", "beverage")
            display_name: Human-readable name (e.g., "Bagel", "Beverage")
            attributes: Optional list of attribute definitions

        Returns:
            self for method chaining
        """
        self._item_types[slug] = {
            "slug": slug,
            "display_name": display_name,
            "attributes": attributes or [],
        }
        return self

    def add_attribute(
        self,
        item_type_slug: str,
        attr_slug: str,
        display_name: str,
        input_type: str = "single_select",
        is_required: bool = True,
        ask_in_conversation: bool = True,
        question_text: str | None = None,
        display_order: int | None = None,
        options: list[dict] | None = None,
    ) -> "MenuDataBuilder":
        """Add an attribute to an existing item type.

        Args:
            item_type_slug: The item type to add the attribute to
            attr_slug: Unique identifier for the attribute (e.g., "size", "toasted")
            display_name: Human-readable name (e.g., "Size", "Toasted")
            input_type: One of "single_select", "multi_select", "boolean", "text"
            is_required: Whether this attribute is required
            ask_in_conversation: Whether to ask about this in conversation
            question_text: The question to ask (auto-generated if not provided)
            display_order: Order in which to ask (auto-assigned if not provided)
            options: List of option dicts with slug, display_name, price_modifier

        Returns:
            self for method chaining

        Raises:
            ValueError: If item_type_slug not found
        """
        if item_type_slug not in self._item_types:
            raise ValueError(f"Item type '{item_type_slug}' not found. "
                           f"Call add_item_type first.")

        # Auto-generate question text if not provided
        if question_text is None:
            question_text = f"What {display_name.lower()} would you like?"

        # Auto-assign display order if not provided
        if display_order is None:
            existing_attrs = self._item_types[item_type_slug]["attributes"]
            display_order = len(existing_attrs) + 1

        attr_def = {
            "slug": attr_slug,
            "display_name": display_name,
            "input_type": input_type,
            "is_required": is_required,
            "ask_in_conversation": ask_in_conversation,
            "question_text": question_text,
            "display_order": display_order,
            "options": options or [],
        }

        self._item_types[item_type_slug]["attributes"].append(attr_def)
        return self

    def add_option(
        self,
        item_type_slug: str,
        attr_slug: str,
        option_slug: str,
        display_name: str,
        price_modifier: float = 0.0,
        is_default: bool = False,
    ) -> "MenuDataBuilder":
        """Add an option to an existing attribute.

        Convenience method for adding options one at a time instead of
        providing them all in add_attribute.

        Args:
            item_type_slug: The item type containing the attribute
            attr_slug: The attribute to add the option to
            option_slug: Unique identifier for the option
            display_name: Human-readable name
            price_modifier: Price adjustment for this option
            is_default: Whether this is the default selection

        Returns:
            self for method chaining

        Raises:
            ValueError: If item_type or attribute not found
        """
        if item_type_slug not in self._item_types:
            raise ValueError(f"Item type '{item_type_slug}' not found")

        attrs = self._item_types[item_type_slug]["attributes"]
        for attr in attrs:
            if attr["slug"] == attr_slug:
                attr["options"].append({
                    "slug": option_slug,
                    "display_name": display_name,
                    "price_modifier": price_modifier,
                    "is_default": is_default,
                })
                return self

        raise ValueError(f"Attribute '{attr_slug}' not found on item type "
                        f"'{item_type_slug}'")

    def add_item(
        self,
        name: str,
        item_type: str,
        base_price: float = 0.0,
        category: str | None = None,
        item_id: int | None = None,
        **kwargs: Any,
    ) -> "MenuDataBuilder":
        """Add a menu item.

        Args:
            name: Display name of the item (e.g., "Plain Bagel", "Latte")
            item_type: The item type slug (e.g., "bagel", "beverage")
            base_price: Base price before modifiers
            category: Category for grouping (auto-derived from item_type if not set)
            item_id: Explicit ID (auto-assigned if not provided)
            **kwargs: Additional item properties

        Returns:
            self for method chaining
        """
        if item_id is None:
            item_id = self._next_item_id
            self._next_item_id += 1

        item = {
            "id": item_id,
            "name": name,
            "base_price": base_price,
            "item_type": item_type,
            "category": category or item_type,
            **kwargs,
        }
        self._items.append(item)
        return self

    def add_category(self, slug: str, name: str) -> "MenuDataBuilder":
        """Add a category.

        Args:
            slug: Unique identifier for the category
            name: Human-readable category name

        Returns:
            self for method chaining
        """
        self._categories.append({"slug": slug, "name": name})
        return self

    def build(self) -> dict[str, Any]:
        """Build the complete menu data structure.

        Returns:
            Dict with item_types, all_items, and categories, plus
            category-grouped item lists for backward compatibility.
        """
        # Build item_types in the expected format
        item_types_formatted = {}
        for slug, type_def in self._item_types.items():
            item_types_formatted[slug] = {
                "attributes": type_def["attributes"],
            }

        # Group items by category for backward compatibility
        items_by_category: dict[str, list[dict]] = {}
        for item in self._items:
            cat = item.get("category", "uncategorized")
            if cat not in items_by_category:
                items_by_category[cat] = []
            # Create a copy without the category key for category lists
            item_copy = {k: v for k, v in item.items() if k != "category"}
            items_by_category[cat].append(item_copy)

        result = {
            "item_types": item_types_formatted,
            "all_items": list(self._items),
            "categories": self._categories if self._categories else list(items_by_category.keys()),
        }

        # Add category-grouped lists for backward compatibility
        for cat, items in items_by_category.items():
            result[cat] = items

        return result

    def copy(self) -> "MenuDataBuilder":
        """Create a copy of this builder for variations.

        Useful for creating similar menus with small differences.

        Returns:
            A new MenuDataBuilder with copied data.
        """
        import copy
        new_builder = MenuDataBuilder()
        new_builder._item_types = copy.deepcopy(self._item_types)
        new_builder._items = copy.deepcopy(self._items)
        new_builder._categories = copy.deepcopy(self._categories)
        new_builder._next_item_id = self._next_item_id
        return new_builder
