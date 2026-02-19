"""
Parsed Item Building Utilities.

This module provides the core function for building ParsedItemEntry objects
from parsed data. Used by all item parsing modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...schemas import Selection, ParsedItemEntry

if TYPE_CHECKING:
    from .result_types import AttributeExtractionResult


def build_parsed_item(
    item_type: str,
    *,
    item_name: str | None = None,
    quantity: int = 1,
    selections: list[Selection] | None = None,
    original_text: str | None = None,
    weight_unit: str | None = None,
    special_instructions: list[str] | None = None,
    attribute_values: dict | None = None,
    attr_result: AttributeExtractionResult | None = None,
    modifiers: list[Selection] | None = None,
    unrecognized_ingredients: list[dict] | None = None,
) -> ParsedItemEntry:
    """
    Build a ParsedItemEntry from provided data.

    This is a pure data assembly function with no domain knowledge.
    It accepts any item_type, any attribute names, any modifier categories.

    All customizations should be provided via the `selections` parameter.
    The `attribute_values` parameter converts dict to selections internally.

    Args:
        item_type: The item type slug
        item_name: Specific menu item name if known
        quantity: Number of items
        selections: List of Selection objects (preferred)
        original_text: Original user input (for disambiguation context)
        weight_unit: For by-pound items (e.g., "1/4 lb")
        special_instructions: List of special instruction strings (e.g., "room for cream")
        attribute_values: Dict of attribute slug -> value (converted to selections).
            Only for simple dicts; use attr_result for full extraction results.
        attr_result: Typed AttributeExtractionResult (preferred over attribute_values).
            When provided, extracts values, unavailable, and unmatched directly.
        modifiers: List of Selection objects to add

    Returns:
        ParsedItemEntry with all fields populated
    """
    # Build the selections list
    final_selections: list[Selection] = []

    # Extract unavailable selections - stored separately for "We don't have X" messaging
    unavailable_selections: dict[str, dict] = {}
    # Extract unmatched selections - stored for "We don't have X. We have A, B, C..." messaging
    unmatched_selections: dict[str, dict] = {}
    # Extract ambiguous selections - for "Which syrup?" disambiguation
    ambiguous_selections: list[dict] = []
    clean_attribute_values: dict = {}

    # Handle typed AttributeExtractionResult (preferred path)
    if attr_result is not None:
        clean_attribute_values = attr_result.values
        unavailable_selections = {
            u.attr_slug: {"attempted_slug": u.attempted_slug, "attempted_display": u.attempted_display}
            for u in attr_result.unavailable
        }
        unmatched_selections = {
            u.attr_slug: {"tokens": u.tokens}
            for u in attr_result.unmatched
        }
        ambiguous_selections = [
            {
                "attr_slug": a.attr_slug,
                "token": a.token,
                "matching_options": a.matching_options,
            }
            for a in attr_result.ambiguous
        ]
    # Simple dict (for manual attribute assignment without extraction)
    elif attribute_values:
        clean_attribute_values = attribute_values

    # If selections provided directly, use them
    if selections:
        final_selections.extend(selections)

    # Convert attribute_values dict to selections
    if clean_attribute_values:
        for category, value in clean_attribute_values.items():
            if value is None:
                # Explicitly declined: create _declined marker so orchestrator won't ask
                final_selections.append(Selection(
                    slug="_declined",
                    category=category,
                    quantity=0,
                ))
            elif isinstance(value, bool):
                # Boolean attribute: use yes/no slugs
                final_selections.append(Selection(
                    slug="yes" if value else "no",
                    category=category,
                ))
            elif isinstance(value, list):
                # Multi-select: each item is a dict with slug, quantity, etc.
                for item in value:
                    if isinstance(item, dict):
                        # Use item's category if present and not None, otherwise use outer category
                        item_category = item.get("category") or category
                        final_selections.append(Selection(
                            slug=item.get("slug", ""),
                            category=item_category,
                            quantity=item.get("quantity", 1),
                            price=item.get("price", 0.0),
                            display_name=item.get("display_name"),
                        ))
                    else:
                        # Simple string value
                        final_selections.append(Selection(slug=str(item), category=category))
            elif isinstance(value, dict):
                # Single-select with quantity info (e.g., "2 shots")
                final_selections.append(Selection(
                    slug=value.get("slug", ""),
                    category=value.get("category") or category,
                    quantity=value.get("quantity", 1),
                    price=value.get("price", 0.0),
                    display_name=value.get("display_name"),
                ))
            elif isinstance(value, str):
                # Single-select: just the slug (default quantity=1)
                final_selections.append(Selection(slug=value, category=category))

    # Add modifiers if provided
    if modifiers:
        final_selections.extend(modifiers)

    return ParsedItemEntry(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        selections=final_selections,
        original_text=original_text,
        weight_unit=weight_unit,
        unavailable_selections=unavailable_selections,
        unmatched_selections=unmatched_selections,
        ambiguous_selections=ambiguous_selections,
        special_instructions=special_instructions or [],
        unrecognized_ingredients=unrecognized_ingredients or [],
    )
