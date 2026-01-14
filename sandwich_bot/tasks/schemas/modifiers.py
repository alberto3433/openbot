"""
Modifier Extraction Data Structures.

This module contains the unified ExtractedModifiers class for holding
extracted modifiers from user input. The class uses category-based storage
where categories are data-driven from the database (proteins, cheeses,
toppings, spreads, sweeteners, syrups, milks, etc.).
"""

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class QuantifiedModifier:
    """A modifier with an optional quantity.

    Examples:
        QuantifiedModifier("bacon", 1)  # 1 bacon
        QuantifiedModifier("sugar", 2)  # 2 sugars
        QuantifiedModifier("vanilla", 3)  # 3 vanilla syrups
    """
    name: str
    quantity: int = 1


class ExtractedModifiers:
    """
    Generic container for modifiers extracted from user input.

    Works for any item type - categories come from the database.
    Supports both food-style modifiers (proteins, cheeses, toppings, spreads)
    and beverage-style modifiers (sweeteners, syrups, milks, styles).

    All modifiers can have quantities (e.g., "2 sugars", "double bacon").

    Category mapping from old fields:
        - proteins -> "protein"
        - cheeses -> "cheese"
        - toppings -> "topping"
        - spreads -> "spread"
        - sweetener -> "sweetener"
        - flavor_syrup -> "syrup"
        - milk -> "milk"
        - cream_level -> "style"

    Examples:
        # Food modifiers
        mods = ExtractedModifiers()
        mods.add("protein", "bacon", 2)  # double bacon
        mods.add("cheese", "american")
        mods.add("topping", "tomato")

        # Beverage modifiers
        mods = ExtractedModifiers()
        mods.add("sweetener", "sugar", 2)  # 2 sugars
        mods.add("syrup", "vanilla")
        mods.add("milk", "oat")
        mods.add("style", "light")  # light cream
    """

    def __init__(self):
        # Modifiers by category, each with optional quantity
        # e.g., {"protein": [QM("bacon", 2)], "sweetener": [QM("sugar", 2)]}
        self._by_category: dict[str, list[QuantifiedModifier]] = defaultdict(list)

        # Special instructions (free-form text like "light", "extra", "on the side")
        self.special_instructions: list[str] = []

        # Categories that need clarification (e.g., user said "cheese" without type)
        # Replaces: needs_cheese_clarification, wants_syrup
        self.needs_clarification: dict[str, bool] = {}

    def add(self, category: str, name: str, quantity: int = 1) -> None:
        """Add a modifier to a category.

        Args:
            category: The category slug (e.g., "protein", "sweetener", "milk")
            name: The modifier name (e.g., "bacon", "sugar", "oat")
            quantity: Optional quantity (default 1)
        """
        self._by_category[category].append(QuantifiedModifier(name, quantity))

    def get(self, category: str) -> list[QuantifiedModifier]:
        """Get all modifiers for a category.

        Args:
            category: The category slug

        Returns:
            List of QuantifiedModifier objects (empty list if category not present)
        """
        return self._by_category.get(category, [])

    def get_names(self, category: str) -> list[str]:
        """Get just modifier names for a category (ignoring quantities).

        Useful when you only need the list of items without quantities.

        Args:
            category: The category slug

        Returns:
            List of modifier names
        """
        return [m.name for m in self._by_category.get(category, [])]

    def get_first(self, category: str) -> QuantifiedModifier | None:
        """Get the first modifier for a category.

        Useful for single-select categories like milk, style.

        Args:
            category: The category slug

        Returns:
            First QuantifiedModifier or None if category is empty
        """
        items = self._by_category.get(category, [])
        return items[0] if items else None

    def get_first_name(self, category: str) -> str | None:
        """Get the name of the first modifier for a category.

        Convenience method for single-select categories.

        Args:
            category: The category slug

        Returns:
            First modifier name or None if category is empty
        """
        first = self.get_first(category)
        return first.name if first else None

    def has_modifiers(self) -> bool:
        """Check if any modifiers were extracted."""
        return bool(self._by_category)

    def has_category(self, category: str) -> bool:
        """Check if a specific category has modifiers."""
        return bool(self._by_category.get(category))

    def categories(self) -> set[str]:
        """Get all categories that have modifiers."""
        return set(self._by_category.keys())

    def has_special_instructions(self) -> bool:
        """Check if any special instructions were extracted."""
        return bool(self.special_instructions)

    def get_special_instructions_string(self) -> str | None:
        """Get special instructions as a single comma-separated string."""
        if self.special_instructions:
            return ", ".join(self.special_instructions)
        return None

    def __repr__(self):
        parts = []
        for category in sorted(self._by_category.keys()):
            items = self._by_category[category]
            items_str = ", ".join(
                f"{m.name}x{m.quantity}" if m.quantity > 1 else m.name
                for m in items
            )
            parts.append(f"{category}=[{items_str}]")
        if self.special_instructions:
            parts.append(f"special_instructions={self.special_instructions}")
        if self.needs_clarification:
            parts.append(f"needs_clarification={self.needs_clarification}")
        return f"ExtractedModifiers({', '.join(parts)})"
