"""
Extraction Pipeline.

Provides a unified, class-based API for text extraction operations.
Wraps the existing extraction functions with typed results.
"""

import logging
import re

from orderbot.cache import menu_cache

from .result_types import (
    TextSpan,
    QuantityResult,
    AttributeExtractionResult,
    SpecialInstructionsResult,
    ItemTypeMatch,
    UnavailableSelection,
    UnmatchedToken,
)
from .extraction import (
    extract_attribute_values as _extract_attribute_values,
    _extract_modifiers_generic,
)
from .instructions_extraction import extract_special_instructions_from_input
from .item_parsing import _detect_item_type, _detect_configurable_item_type
from ..quantity_utils import extract_leading_quantity
from ..intent_patterns import strip_conversational_fillers

logger = logging.getLogger(__name__)

__all__ = ["ExtractionPipeline"]


class ExtractionPipeline:
    """
    Unified extraction pipeline for parsing user input.

    Provides a clean, typed API for extracting structured data from text:
    - Quantities
    - Item types
    - Attribute values
    - Modifiers
    - Special instructions

    Example:
        pipeline = ExtractionPipeline()

        qty = pipeline.extract_quantity("2 items")
        # QuantityResult(quantity=2, remaining_text="items")

        item_type = pipeline.detect_item_type(text)
        # ItemTypeMatch(item_type="<item_type>", trigger_word="<trigger>")

        attrs = pipeline.extract_attributes(text, item_type.item_type)
        # AttributeExtractionResult(values={...}, matched_spans=[...])

        modifiers = pipeline.extract_modifiers_raw(text, item_type.item_type, attrs.matched_spans)
        # ["modifier_slug_1", "modifier_slug_2", ...]
    """

    def __init__(self):
        """Initialize the extraction pipeline."""
        pass

    def normalize(self, text: str) -> str:
        """Normalize input text for parsing.

        Removes conversational fillers and normalizes whitespace.

        Args:
            text: Raw user input

        Returns:
            Normalized text ready for parsing
        """
        # Strip conversational fillers
        normalized = strip_conversational_fillers(text)
        # Normalize whitespace
        normalized = " ".join(normalized.split())
        return normalized.strip()

    def extract_quantity(self, text: str) -> QuantityResult:
        """Extract quantity from the beginning of text.

        Handles numeric and word quantities (e.g., "2", "two", "a dozen").

        Args:
            text: Input text

        Returns:
            QuantityResult with quantity, remaining text, and span
        """
        quantity, remaining = extract_leading_quantity(text)

        # Calculate span if quantity was extracted
        span = None
        if quantity and remaining != text:
            # Find where the quantity ended
            prefix_len = len(text) - len(remaining.lstrip())
            if prefix_len > 0:
                span = TextSpan(start=0, end=prefix_len)

        return QuantityResult(
            quantity=quantity or 1,
            remaining_text=remaining.strip() if remaining else text,
            span=span,
        )

    def detect_item_type(self, text: str) -> ItemTypeMatch:
        """Detect the item type from text.

        Uses data-driven detection from item type triggers in database.

        Args:
            text: Input text

        Returns:
            ItemTypeMatch with detected type and trigger word
        """
        # Try the main detection function
        item_type = _detect_item_type(text)

        if item_type:
            # Get the trigger word that matched
            triggers = menu_cache.get_item_type_triggers(item_type)
            trigger_word = None
            span = None
            text_lower = text.lower()

            for trigger in triggers:
                pattern = re.compile(rf'\b{re.escape(trigger.lower())}\b', re.IGNORECASE)
                match = pattern.search(text_lower)
                if match:
                    trigger_word = trigger
                    span = TextSpan(start=match.start(), end=match.end())
                    break

            return ItemTypeMatch(
                item_type=item_type,
                confidence=1.0,
                trigger_word=trigger_word,
                span=span,
            )

        # Try configurable item type detection as fallback
        item_type = _detect_configurable_item_type(text)
        if item_type:
            return ItemTypeMatch(
                item_type=item_type,
                confidence=0.8,
                trigger_word=None,
                span=None,
            )

        return ItemTypeMatch(item_type=None)

    def extract_attributes(
        self,
        text: str,
        item_type: str,
        exclude_spans: list[TextSpan] | None = None,
    ) -> AttributeExtractionResult:
        """Extract attribute values from text for an item type.

        Uses the 6-phase extraction algorithm:
        1. Negation detection ("no spread", "without cheese")
        2. Boolean extraction ("toasted", "iced")
        3. Candidate collection from all attributes
        4. Longest-match-first sorting
        5. Application with overlap prevention
        6. Reverse matching for multi-select

        Args:
            text: Input text
            item_type: Item type slug
            exclude_spans: Spans to exclude from matching

        Returns:
            AttributeExtractionResult with values, spans, and unavailable/unmatched info
        """
        # Convert TextSpan to legacy tuple format
        legacy_spans = None
        if exclude_spans:
            legacy_spans = [(s.start, s.end) for s in exclude_spans]

        # Call existing extraction function
        values, matched_spans = _extract_attribute_values(text, item_type, legacy_spans)

        # Convert results to typed format
        result_spans = [TextSpan(start=s, end=e) for s, e in matched_spans]

        # Extract unavailable and unmatched from values
        unavailable = []
        unmatched = []
        clean_values = {}

        for key, value in values.items():
            if key.startswith("_unavailable_"):
                attr_slug = key[len("_unavailable_"):]
                unavailable.append(UnavailableSelection(
                    attr_slug=attr_slug,
                    attempted_slug=value.get("attempted_slug", ""),
                    attempted_display=value.get("attempted_display", ""),
                ))
            elif key.startswith("_unmatched_"):
                attr_slug = key[len("_unmatched_"):]
                unmatched.append(UnmatchedToken(
                    attr_slug=attr_slug,
                    tokens=value.get("tokens", []),
                ))
            else:
                clean_values[key] = value

        return AttributeExtractionResult(
            values=clean_values,
            matched_spans=result_spans,
            unavailable=unavailable,
            unmatched=unmatched,
        )

    def extract_modifiers_raw(
        self,
        text: str,
        item_type: str,
        exclude_spans: list[TextSpan] | list[tuple[int, int]] | None = None,
    ) -> list[str]:
        """Extract modifier slugs from text (lightweight, no metadata lookup).

        Returns just the slug strings without building full objects or
        looking up additional metadata.

        Args:
            text: Input text
            item_type: Item type slug
            exclude_spans: Spans to exclude from matching (TextSpan or tuple format)

        Returns:
            List of modifier slug strings
        """
        legacy_spans = None
        if exclude_spans:
            legacy_spans = []
            for span in exclude_spans:
                if isinstance(span, TextSpan):
                    legacy_spans.append((span.start, span.end))
                else:
                    legacy_spans.append(span)  # Already a tuple

        return _extract_modifiers_generic(text, item_type, legacy_spans)

    def extract_special_instructions(self, text: str) -> SpecialInstructionsResult:
        """Extract special instructions from text.

        Finds qualifier patterns (extra X, light X, no X) and standalone
        instructions (leave room, cut in half, etc.).

        Args:
            text: Input text

        Returns:
            SpecialInstructionsResult with instruction strings
        """
        instructions = extract_special_instructions_from_input(text)
        return SpecialInstructionsResult(instructions=instructions)
