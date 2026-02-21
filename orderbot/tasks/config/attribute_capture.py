"""
Proactive Attribute Capture from User Input.

This module provides functionality to capture attributes mentioned in the initial
order input, pre-filling values before explicit questions are asked.

Example: "deli sandwich with scrambled egg on a plain bagel toasted"
- Captures bread=plain_bagel, toasted=True, protein=scrambled_egg

Extracted from handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from ..utils.text import normalize_text

if TYPE_CHECKING:
    from ..models import MenuItemTask
    from ..utils import OptionMatcher

logger = logging.getLogger(__name__)

__all__ = ["capture_attributes_from_input"]


def capture_attributes_from_input(
    user_input: str,
    item: "MenuItemTask",
    item_type_attributes: dict[str, dict],
    option_matcher: "OptionMatcher",
    skip_attribute: str | None = None,
) -> None:
    """
    Capture any attributes mentioned in the initial order input.

    Called when an item is first created to pre-fill attribute values
    from the user's natural language order.

    Args:
        user_input: The user's raw input (e.g., "plain bagel toasted with cream cheese")
        item: The menu item task to capture attributes for
        item_type_attributes: Dict of attribute configs keyed by slug
        option_matcher: OptionMatcher instance for matching options

    Examples:
        >>> capture_attributes_from_input(
        ...     "plain bagel toasted scooped with cream cheese",
        ...     bagel_item,
        ...     bagel_attributes,
        ...     option_matcher,
        ... )
        # Sets: bread=plain, toasted=True, scooped=True, spread=cream_cheese
    """
    user_lower = user_input.lower()

    for attr_slug, attr in item_type_attributes.items():
        # Skip if already answered
        if attr_slug in item:
            continue

        # Skip the attribute being directly answered (prevents double-interpretation)
        # e.g., when answering "What kind of bagel?" with "onion", we don't want
        # to also capture toppings=onions from "onion" containing "onion"
        if skip_attribute and attr_slug == skip_attribute:
            continue

        options = attr.get("options", [])
        input_type = attr.get("input_type", "single_select")

        if input_type == "boolean":
            _capture_boolean_attribute(user_lower, item, attr_slug, attr, options)
        elif input_type in ("single_select", "multi_select") and options:
            _capture_select_attribute(user_input, user_lower, item, attr_slug, options, option_matcher)


def _capture_boolean_attribute(
    user_lower: str,
    item: "MenuItemTask",
    attr_slug: str,
    attr: dict,
    options: list[dict],
) -> None:
    """Capture a boolean attribute value from user input.

    Checks option aliases first (e.g., "scoop it" -> true for scooped),
    then falls back to display name matching.

    Args:
        user_lower: Lowercase user input
        item: The menu item to update
        attr_slug: The attribute slug (e.g., "toasted", "scooped")
        attr: The attribute configuration dict
        options: List of attribute options (should have true/false options)
    """
    # Build alias lists from options
    true_aliases: list[str] = []
    false_aliases: list[str] = []

    for opt in options:
        opt_aliases = opt.get("aliases") or []
        if isinstance(opt_aliases, str):
            opt_aliases = [normalize_text(a) for a in opt_aliases.split(",")]
        else:
            opt_aliases = [a.lower() for a in opt_aliases]

        # Check for true/false slug - may be "true"/"false" or ingredient slug
        # like "scooped_option_true"/"scooped_option_false"
        opt_slug = opt.get("slug", "")
        if opt_slug == "true" or opt_slug.endswith("_option_true"):
            true_aliases = opt_aliases
        elif opt_slug == "false" or opt_slug.endswith("_option_false"):
            false_aliases = opt_aliases

    # Check for alias matches (check false first since "not scooped" contains "scooped")
    matched = False
    for alias in false_aliases:
        if alias in user_lower:
            item[attr_slug] = False
            logger.info("Captured %s=False from alias '%s'", attr_slug, alias)
            matched = True
            break

    if not matched:
        for alias in true_aliases:
            if alias in user_lower:
                item[attr_slug] = True
                logger.info("Captured %s=True from alias '%s'", attr_slug, alias)
                matched = True
                break

    # Fall back to display_name check
    if not matched:
        attr_name = attr["display_name"].lower()
        if f"not {attr_name}" in user_lower:
            item[attr_slug] = False
            logger.info("Captured %s=False from display name", attr_slug)
        elif attr_name in user_lower:
            item[attr_slug] = True
            logger.info("Captured %s=True from display name", attr_slug)


def _capture_select_attribute(
    user_input: str,
    user_lower: str,
    item: "MenuItemTask",
    attr_slug: str,
    options: list[dict],
    option_matcher: "OptionMatcher",
) -> None:
    """Capture a single/multi-select attribute value from user input.

    Uses option matching to find values mentioned in the input.

    Args:
        user_input: Original case user input (for option matching)
        user_lower: Lowercase user input
        item: The menu item to update
        attr_slug: The attribute slug
        options: List of attribute options
        option_matcher: OptionMatcher instance
    """
    # Try exact match first (phases 0-1)
    # exact_only=True prevents user input from matching option slugs
    # e.g., "omelette" matching "omelette_gf_everything_bagel"
    matched, _ = option_matcher.match_single(user_input, options, exact_only=True)

    # If no exact match, try Phase 3: check if any option name appears in user input
    # This is safe because we're looking for known option names, not arbitrary text
    # e.g., "cream cheese" appearing in "plain bagel toasted scooped with cream cheese"
    if not matched:
        matched = option_matcher._phase_partial_option_in_input(
            user_lower, options, user_input
        )

    if matched:
        # Check if the matched option is available
        if not matched.get("is_available", True):
            # Store as unavailable selection for helpful messaging
            item.unavailable_selections[attr_slug] = {
                "attempted_slug": matched["slug"],
                "attempted_display": matched.get("display_name", matched["slug"]),
            }
            logger.info(
                "Captured unavailable %s=%s from input (will prompt for alternative)",
                attr_slug, matched["slug"]
            )
            return  # Don't add the selection

        opt_price = matched.get("price") or matched.get("price_modifier") or 0
        item.add_selection(
            matched["slug"],
            attr_slug,
            price=opt_price,
            display_name=matched.get("display_name"),
        )
        logger.info("Captured %s=%s from input", attr_slug, matched["slug"])
