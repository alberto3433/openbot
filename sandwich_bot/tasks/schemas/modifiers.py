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
        self.notes: list[str] = []  # Free-form notes for qualifiers like "light", "extra"
        self.needs_cheese_clarification: bool = False  # True if user said "cheese" without type

    def has_modifiers(self) -> bool:
        """Check if any modifiers were extracted."""
        return bool(self.proteins or self.cheeses or self.toppings or self.spreads)

    def has_notes(self) -> bool:
        """Check if any notes were extracted."""
        return bool(self.notes)

    def get_notes_string(self) -> str | None:
        """Get notes as a single comma-separated string."""
        if self.notes:
            return ", ".join(self.notes)
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
        if self.notes:
            parts.append(f"notes={self.notes}")
        return f"ExtractedModifiers({', '.join(parts)})"


@dataclass
class ExtractedCoffeeModifiers:
    """Container for coffee modifiers extracted from user input."""
    sweetener: str | None = None
    sweetener_quantity: int = 1
    flavor_syrup: str | None = None
    milk: str | None = None  # Milk type: whole, skim, oat, almond, etc.
    notes: list[str] = None  # Free-form notes for qualifiers like "light", "extra"

    def __post_init__(self):
        if self.notes is None:
            self.notes = []

    def has_notes(self) -> bool:
        """Check if any notes were extracted."""
        return bool(self.notes)

    def get_notes_string(self) -> str | None:
        """Get notes as a single comma-separated string."""
        if self.notes:
            return ", ".join(self.notes)
        return None
