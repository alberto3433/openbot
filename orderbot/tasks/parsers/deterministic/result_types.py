"""
Result Types for Extraction Pipeline.

Provides typed data classes for extraction results, making the API
cleaner and more self-documenting.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextSpan:
    """Represents a span of text with start and end positions."""

    start: int
    end: int

    def overlaps(self, other: "TextSpan") -> bool:
        """Check if this span overlaps with another."""
        return not (self.end <= other.start or self.start >= other.end)

    def overlaps_any(self, spans: list["TextSpan"]) -> bool:
        """Check if this span overlaps with any in a list."""
        return any(self.overlaps(s) for s in spans)

    def __iter__(self):
        """Allow unpacking as (start, end) tuple."""
        return iter((self.start, self.end))


@dataclass
class QuantityResult:
    """Result of quantity extraction."""

    quantity: int
    """Extracted quantity (default: 1)."""

    remaining_text: str
    """Text after quantity extraction."""

    span: TextSpan | None = None
    """Span of the quantity in original text, if found."""


@dataclass
class ModifierMatch:
    """A single matched modifier with metadata."""

    slug: str
    """Canonical slug of the modifier."""

    display_name: str
    """Human-readable name."""

    category: str
    """Modifier category."""

    quantity: int = 1
    """Quantity of this modifier."""

    price: float = 0.0
    """Price modifier amount."""

    qualifiers: list[str] = field(default_factory=list)
    """Applied qualifiers from database (amount, preparation, etc.)."""

    span: TextSpan | None = None
    """Span in original text where this was matched."""


@dataclass
class AttributeMatch:
    """A single matched attribute value."""

    attr_slug: str
    """Attribute slug from database."""

    value: Any
    """Matched value - can be:
    - str: option slug for single_select
    - bool: True/False for boolean
    - list[dict]: list of selections for multi_select
    - None: explicitly declined/negated
    """

    span: TextSpan | None = None
    """Span in original text where this was matched."""


@dataclass
class UnavailableSelection:
    """Tracks a user's attempt to select an unavailable option."""

    attr_slug: str
    """Attribute the unavailable option belongs to."""

    attempted_slug: str
    """Slug of the option user tried to select."""

    attempted_display: str
    """Display name of the option user tried to select."""


@dataclass
class UnmatchedToken:
    """Tracks a token that didn't match any known option."""

    attr_slug: str
    """Attribute category for the unmatched token."""

    tokens: list[str]
    """Unmatched token strings."""


@dataclass
class AttributeExtractionResult:
    """Complete result of attribute extraction."""

    values: dict[str, Any]
    """Extracted attribute values mapping slug to value."""

    matched_spans: list[TextSpan]
    """Spans consumed by attribute matching."""

    unavailable: list[UnavailableSelection] = field(default_factory=list)
    """Options user tried that aren't available."""

    unmatched: list[UnmatchedToken] = field(default_factory=list)
    """Tokens that didn't match any option."""

    def get(self, attr_slug: str, default: Any = None) -> Any:
        """Get an attribute value by slug."""
        return self.values.get(attr_slug, default)

    def to_legacy_format(self) -> tuple[dict[str, Any], list[tuple[int, int]]]:
        """Convert to legacy format for backward compatibility.

        Returns:
            Tuple of (attribute_values dict, matched_spans list of tuples)
        """
        # Merge unavailable selections back into values with _unavailable_ prefix
        result = dict(self.values)
        for unavail in self.unavailable:
            result[f"_unavailable_{unavail.attr_slug}"] = {
                "attempted_slug": unavail.attempted_slug,
                "attempted_display": unavail.attempted_display,
            }
        for unmatched in self.unmatched:
            result[f"_unmatched_{unmatched.attr_slug}"] = {
                "tokens": unmatched.tokens,
            }
        spans = [(s.start, s.end) for s in self.matched_spans]
        return result, spans


@dataclass
class ModifierExtractionResult:
    """Complete result of modifier extraction."""

    modifiers: list[ModifierMatch]
    """List of matched modifiers."""

    conflicts: list[tuple[str, str, str]] | None = None
    """Qualifier conflicts, if any (modifier, qual1, qual2)."""

    def get_formatted_list(self) -> list[str]:
        """Get list of formatted modifier strings with qualifiers."""
        result = []
        for mod in self.modifiers:
            if mod.qualifiers:
                result.append(f"{mod.display_name} ({', '.join(mod.qualifiers)})")
            else:
                result.append(mod.display_name)
        return result


@dataclass
class SpecialInstructionsResult:
    """Result of special instructions extraction."""

    instructions: list[str]
    """List of instruction strings."""

    def __bool__(self) -> bool:
        """Return True if there are any instructions."""
        return bool(self.instructions)

    def __iter__(self):
        """Allow iterating over instructions."""
        return iter(self.instructions)


@dataclass
class ItemTypeMatch:
    """Result of item type detection."""

    item_type: str | None
    """Detected item type slug, or None if not detected."""

    confidence: float = 1.0
    """Confidence score (0.0 to 1.0)."""

    trigger_word: str | None = None
    """The word/phrase that triggered the match."""

    span: TextSpan | None = None
    """Span of the trigger in original text."""

    def __bool__(self) -> bool:
        """Return True if an item type was detected."""
        return self.item_type is not None
