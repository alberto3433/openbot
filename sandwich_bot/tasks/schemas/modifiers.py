"""
Modifier Extraction Data Structures.

This module contains dataclasses for holding extracted modifiers
from user input (bagel modifiers, coffee modifiers).
"""

from dataclasses import dataclass, field


class ExtractedModifiers:
    """Container for modifiers extracted from user input."""

    def __init__(self):
        self.proteins: list[str] = []
        self.cheeses: list[str] = []
        self.toppings: list[str] = []
        self.spreads: list[str] = []
        self.special_instructions: list[str] = []  # Qualifiers like "light", "extra", "splash of"
        self.needs_cheese_clarification: bool = False  # True if user said "cheese" without type

    def has_modifiers(self) -> bool:
        """Check if any modifiers were extracted."""
        return bool(self.proteins or self.cheeses or self.toppings or self.spreads)

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
        if self.proteins:
            parts.append(f"proteins={self.proteins}")
        if self.cheeses:
            parts.append(f"cheeses={self.cheeses}")
        if self.toppings:
            parts.append(f"toppings={self.toppings}")
        if self.spreads:
            parts.append(f"spreads={self.spreads}")
        if self.special_instructions:
            parts.append(f"special_instructions={self.special_instructions}")
        return f"ExtractedModifiers({', '.join(parts)})"


@dataclass
class ExtractedCoffeeModifiers:
    """Container for coffee modifiers extracted from user input."""
    sweetener: str | None = None
    sweetener_quantity: int = 1
    flavor_syrup: str | None = None
    syrup_quantity: int = 1  # Number of syrup pumps (e.g., 2 hazelnut syrups)
    milk: str | None = None  # Milk type: whole, skim, oat, almond, etc.
    special_instructions: list[str] = None  # Qualifiers like "splash of milk", "light sugar"

    def __post_init__(self):
        if self.special_instructions is None:
            self.special_instructions = []

    def has_special_instructions(self) -> bool:
        """Check if any special instructions were extracted."""
        return bool(self.special_instructions)

    def get_special_instructions_string(self) -> str | None:
        """Get special instructions as a single comma-separated string."""
        if self.special_instructions:
            return ", ".join(self.special_instructions)
        return None
