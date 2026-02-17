"""
Result Types for Extraction Pipeline.

Provides typed data classes for extraction results, making the API
cleaner and more self-documenting.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParserContext:
    """Bundles keyword arguments passed through the parser pipeline.

    This replaces the loose **kwargs pattern used by parse_open_input_deterministic()
    and parse_open_input(), providing a single typed object that flows through
    the parsing pipeline.
    """

    modifier_category_keywords: dict[str, str] | None = None
    """Mapping of keywords to category slugs."""

    modifier_item_keywords: dict[str, str] | None = None
    """Mapping of item keywords to item type slugs."""

    ingredient_to_items: dict[str, list[dict]] | None = None
    """Mapping of ingredient names to menu items containing them."""


@dataclass
class TextSpan:
    """Represents a span of text with start and end positions."""

    start: int
    end: int

    def overlaps(self, other: "TextSpan") -> bool:
        """Check if this span overlaps with another."""
        return not (self.end <= other.start or self.start >= other.end)

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
class AmbiguousSelection:
    """Tracks a user's attempt to select an ambiguous option.

    Occurs when a generic term (like "syrup") matches multiple specific options
    (like "Vanilla Syrup", "Hazelnut Syrup", etc.).
    """

    attr_slug: str
    """Attribute the ambiguous token belongs to."""

    token: str
    """The ambiguous token/word from user input (e.g., "syrup")."""

    matching_options: list[dict]
    """List of options that the token matched. Each dict has 'slug' and 'display_name'."""


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

    ambiguous: list[AmbiguousSelection] = field(default_factory=list)
    """Tokens that matched multiple options (need disambiguation)."""

    def get(self, attr_slug: str, default: Any = None) -> Any:
        """Get an attribute value by slug."""
        return self.values.get(attr_slug, default)

    def merge_with(self, other: "AttributeExtractionResult") -> "AttributeExtractionResult":
        """Merge another result into this one (other values override self).

        Used for combining base + part attributes in split-quantity orders,
        or merging inferred attributes with extracted attributes.

        Args:
            other: The result to merge in (takes precedence for overlapping keys)

        Returns:
            New AttributeExtractionResult with merged data
        """
        merged_values = {**self.values, **other.values}
        return AttributeExtractionResult(
            values=merged_values,
            matched_spans=self.matched_spans + other.matched_spans,
            unavailable=self.unavailable + other.unavailable,
            unmatched=self.unmatched + other.unmatched,
            ambiguous=self.ambiguous + other.ambiguous,
        )


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
