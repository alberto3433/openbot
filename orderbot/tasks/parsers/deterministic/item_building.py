"""
Parsed Item Building Utilities.

This module provides the core function for building ParsedItemEntry objects
from parsed data. Used by all item parsing modules.
"""

from ...schemas import Selection, ParsedItemEntry


def build_parsed_item(
    item_type: str,
    *,
    item_name: str | None = None,
    quantity: int = 1,
    selections: list[Selection] | None = None,
    original_text: str | None = None,
    is_signature: bool = False,
    weight_unit: str | None = None,
    special_instructions: list[str] | None = None,
    attribute_values: dict | None = None,
    modifiers: list[Selection] | None = None,
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
        is_signature: Whether this is a signature/speed menu item
        weight_unit: For by-pound items (e.g., "1/4 lb")
        special_instructions: List of special instruction strings (e.g., "room for cream")
        attribute_values: Dict of attribute slug -> value (converted to selections)
        modifiers: List of Selection objects to add

    Returns:
        ParsedItemEntry with all fields populated
    """
    # Build the selections list
    final_selections: list[Selection] = []

    # Extract unavailable selections from attribute_values (keys like "_unavailable_size")
    # These are stored separately for helpful "We don't have X" messaging
    unavailable_selections: dict[str, dict] = {}
    clean_attribute_values: dict = {}
    if attribute_values:
        for key, value in attribute_values.items():
            if key.startswith("_unavailable_"):
                # Extract attr_slug from key (e.g., "_unavailable_size" -> "size")
                attr_slug = key[len("_unavailable_"):]
                unavailable_selections[attr_slug] = value
            else:
                clean_attribute_values[key] = value
    else:
        clean_attribute_values = {}

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
            elif isinstance(value, str):
                # Single-select: just the slug
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
        is_signature=is_signature,
        weight_unit=weight_unit,
        unavailable_selections=unavailable_selections,
        special_instructions=special_instructions or [],
    )
