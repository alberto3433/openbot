"""
Package Input Handler for package selection.

Handles the package_multi_select input type which allows users to specify
item types for packages (e.g., "3 plain, 2 everything, 1 sesame").
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from ..models import OrderTask, MenuItemTask
from ..schemas import StateMachineResult
from ..utils.text import format_english_list, name_with_prefix

if TYPE_CHECKING:
    from ..utils import OptionMatcher, InputNormalizer

logger = logging.getLogger(__name__)


class PackageInputHandler:
    """
    Handles package_multi_select input type for packages.

    Parses input like "3 X, 2 Y, 1 Z" (quantities + option types) and stores
    structured selections in attribute_values['package_contents'].
    """

    def __init__(
        self,
        option_matcher: "OptionMatcher",
        input_normalizer: "InputNormalizer",
    ):
        """Initialize the package input handler."""
        self._option_matcher = option_matcher
        self._input_normalizer = input_normalizer

    def handle_package_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
        advance_callback,
    ) -> StateMachineResult:
        """Handle package_multi_select input type.

        Args:
            user_input: User's input string (e.g., "3 X, 2 Y, 1 Z")
            item: The MenuItemTask being configured
            order: Current order state
            attr: Attribute configuration dict
            options: List of available options (loaded from options_source_category)
            advance_callback: Callback to advance to next question

        Returns:
            StateMachineResult with response or next question
        """
        attr_slug = attr["slug"]  # "package_contents"

        # Get pack size from menu item
        pack_size = self._get_pack_size(item)
        if not pack_size:
            logger.warning("No pack_size found for item %s", item.menu_item_name)
            pack_size = 6  # Default fallback

        # Parse the package contents from user input
        logger.info(
            "PACKAGE_INPUT: Parsing '%s' with %d options, first 3: %s",
            user_input,
            len(options),
            [opt.get("display_name") for opt in options[:3]],
        )
        parsed = self._parse_package_contents(user_input, options, pack_size)
        logger.info("PACKAGE_INPUT: Parsed result: %s", parsed)

        if not parsed["selections"]:
            # No valid selections found - provide helpful message
            unit_name_plural = menu_cache.get_item_type_display_name(
                item.menu_item_type, plural=True
            ).lower() if item.menu_item_type else "items"
            available_names = [opt["display_name"] for opt in options[:6]]
            options_str = format_english_list(available_names, conjunction="or")
            # Build dynamic example from first two options
            example_parts = []
            half = pack_size // 2
            remainder = pack_size - half
            if len(options) >= 2:
                example_parts.append(f"{half} {options[0]['display_name']}")
                example_parts.append(f"{remainder} {options[1]['display_name']}")
            elif len(options) == 1:
                example_parts.append(f"{pack_size} {options[0]['display_name']}")
            example_str = " and ".join(example_parts) if example_parts else ""
            example_hint = f" For example, '{example_str}'." if example_str else ""
            return StateMachineResult(
                message=f"I didn't catch that. Please tell me which {unit_name_plural} you'd like."
                        f"{example_hint} We have {options_str}.",
                order=order,
            )

        # Check for existing partial selection and merge if present
        existing_selection = item.get_selection(attr_slug)
        if existing_selection and existing_selection.get("display_name"):
            existing_display = existing_selection.get("display_name", "")
            existing_selections = self._parse_display_to_selections(existing_display, options)
            if existing_selections:
                # Merge with new selections
                merged_selections = self._merge_selections(existing_selections, parsed["selections"])
                merged_total = sum(s["quantity"] for s in merged_selections)

                # Validate merged total
                if merged_total > pack_size:
                    # Merged total is over - ask to adjust (don't store anything)
                    unit_name_plural = menu_cache.get_item_type_display_name(
                        item.menu_item_type, plural=True
                    ).lower() if item.menu_item_type else "items"
                    return StateMachineResult(
                        message=f"That would be {merged_total} {unit_name_plural} total, but the "
                                f"{item.menu_item_name} includes {pack_size}. "
                                f"Please adjust your selection.",
                        order=order,
                    )

                # Update parsed with merged data
                parsed["selections"] = merged_selections
                parsed["total"] = merged_total

        # VALIDATION FIRST - check if over-specified BEFORE storing
        if parsed["total"] > pack_size:
            # Over-specified - do NOT store, ask to start over
            unit_name_plural = menu_cache.get_item_type_display_name(
                item.menu_item_type, plural=True
            ).lower() if item.menu_item_type else "items"
            return StateMachineResult(
                message=f"That's {parsed['total']} {unit_name_plural}, but {name_with_prefix('the', item.menu_item_name)} "
                        f"includes {pack_size}. Please tell me which {pack_size} {unit_name_plural} you'd like.",
                order=order,
            )

        # Valid count (exact or under) - NOW store selection
        # Remove any existing selection first (for merge case)
        item.remove_selection(attr_slug)
        item.add_selection(
            slug="_package_contents",
            category=attr_slug,
            quantity=1,
            price=0.0,
            display_name=self._format_selections_display(parsed["selections"], item),
        )

        # Check if total matches pack size
        if parsed["total"] < pack_size:
            remaining = pack_size - parsed["total"]
            unit_name = menu_cache.get_item_type_display_name(
                item.menu_item_type, plural=False
            ).lower() if item.menu_item_type else "item"
            unit_str = unit_name if remaining == 1 else menu_cache.get_item_type_display_name(
                item.menu_item_type, plural=True
            ).lower() if item.menu_item_type else "items"
            current_display = self._format_selections_display(parsed["selections"], item)
            return StateMachineResult(
                message=f"Got it, {current_display}. You still need {remaining} more {unit_str} "
                        f"to complete your {pack_size}-pack. What else would you like?",
                order=order,
            )

        # Exact match - advance
        display = self._format_selections_display(parsed["selections"], item)
        return advance_callback(item, order, attr, display)

    def _get_pack_size(self, item: MenuItemTask) -> int | None:
        """Get the pack size from menu item metadata."""
        _, quantity_per_unit = menu_cache.get_menu_item_unit_info(item.menu_item_name)
        return quantity_per_unit

    def _parse_package_contents(
        self,
        user_input: str,
        options: list[dict],
        pack_size: int,
    ) -> dict:
        """Parse package contents from user input.

        Handles inputs like:
        - "3 X, 2 Y, 1 Z" (quantity + option type)
        - "3 X and 3 Y"
        - "X, Y, Z" (defaults to 1 each)

        Returns:
            {
                "selections": [{"bread": slug, "quantity": N, "display_name": "..."}, ...],
                "total": sum of quantities,
                "remaining": pack_size - total,
                "is_valid": True if total == pack_size
            }
        """
        selections = []
        total = 0

        # Split by common delimiters
        # Split on: "and", comma, OR where a digit follows a word
        # "2 plain 2 blueberry" -> ["2 plain", "2 blueberry"]
        # The pattern (?<=\w)\s+(?=\d) splits on whitespace that follows a word and precedes a digit
        parts = re.split(r'\s+and\s+|\s*,\s*|(?<=\w)\s+(?=\d)', user_input.lower())

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Extract quantity and option type
            # Pattern: optional number + option type text
            quantity, option_text = self._input_normalizer.extract_leading_quantity(part)
            logger.debug(
                "PACKAGE_PARSE: part='%s' -> qty=%d, option_text='%s'",
                part, quantity, option_text
            )

            # Try to match the option type
            matched, partials = self._option_matcher.match_single(option_text.strip(), options)

            # If multiple partial matches, pick the simplest one (shortest name)
            # e.g., "plain" matches Plain Bagel, Plain Sourdough Bagel, etc.
            # We want Plain Bagel (the basic one)
            if not matched and partials:
                # Sort by display_name length, pick shortest
                partials_sorted = sorted(partials, key=lambda x: len(x.get("display_name", "")))
                matched = partials_sorted[0]
                logger.debug(
                    "PACKAGE_PARSE: picked shortest match '%s' from %d partials",
                    matched.get("slug"), len(partials),
                )

            logger.debug(
                "PACKAGE_PARSE: match_single('%s') -> matched=%s, partials=%d",
                option_text.strip(),
                matched.get("slug") if matched else None,
                len(partials),
            )

            if matched:
                selections.append({
                    "bread": matched["slug"],
                    "quantity": quantity,
                    "display_name": matched["display_name"],
                })
                total += quantity
            else:
                # Try matching without quantity extraction (maybe the whole thing is a bagel name)
                matched2, _ = self._option_matcher.match_single(part, options)
                if matched2:
                    selections.append({
                        "bread": matched2["slug"],
                        "quantity": 1,
                        "display_name": matched2["display_name"],
                    })
                    total += 1

        return {
            "selections": selections,
            "total": total,
            "remaining": pack_size - total if pack_size else 0,
            "is_valid": total == pack_size if pack_size else len(selections) > 0,
        }

    def _format_selections_display(
        self, selections: list[dict], item: MenuItemTask | None = None
    ) -> str:
        """Format selections for display.

        Strips the item type display name suffix (e.g., "Bagel" from "Plain Bagel")
        for cleaner display like "3 Plain, 2 Everything".
        """
        # Get the item type display name to strip as suffix (data-driven)
        suffix_to_strip = ""
        if item and item.menu_item_type:
            suffix_to_strip = menu_cache.get_item_type_display_name(
                item.menu_item_type, plural=False
            )

        parts = []
        for sel in selections:
            qty = sel.get("quantity", 1)
            name = sel.get("display_name", sel.get("bread", ""))
            # Remove item type suffix for cleaner display (data-driven)
            if suffix_to_strip:
                pattern = rf'\s*{re.escape(suffix_to_strip)}\s*$'
                name_clean = re.sub(pattern, '', name, flags=re.IGNORECASE)
            else:
                name_clean = name
            if qty > 1:
                parts.append(f"{qty} {name_clean}")
            else:
                parts.append(name_clean)
        return ", ".join(parts)

    def _merge_selections(
        self, existing: list[dict], new: list[dict]
    ) -> list[dict]:
        """Merge two selection lists, combining quantities for same bread type.

        Args:
            existing: Previously stored selections
            new: New selections from user input

        Returns:
            Merged list with combined quantities
        """
        merged: dict[str, dict] = {sel["bread"]: sel.copy() for sel in existing}
        for sel in new:
            bread = sel["bread"]
            if bread in merged:
                merged[bread]["quantity"] += sel["quantity"]
            else:
                merged[bread] = sel.copy()
        return list(merged.values())

    def _parse_display_to_selections(
        self, display: str, options: list[dict]
    ) -> list[dict]:
        """Parse display string like '2 Plain, 1 Everything' back to selections.

        Args:
            display: Display string from a previous selection
            options: Available options for matching

        Returns:
            List of selection dicts parsed from the display string
        """
        # Re-use existing parsing logic with a large pack_size to avoid validation
        result = self._parse_package_contents(display, options, pack_size=999)
        return result["selections"]

    def looks_like_package_contents(
        self,
        user_input: str,
        item: MenuItemTask,
        options_source_category: str | None = None,
    ) -> bool:
        """Check if user input looks like package contents specification.

        Returns True if input contains quantity+option patterns like "2 plain 1 blueberry".
        Used to detect when user skips the variety question and provides contents directly.

        Args:
            user_input: User's input string
            item: The MenuItemTask being configured (for pack size)
            options_source_category: Optional ingredient category to load options from.
                                    If not provided, uses 'bread' as default.

        Returns:
            True if input appears to be package contents
        """
        # Get options from the specified category (or default to 'bread')
        category = options_source_category or "bread"
        raw_options = menu_cache.get_ingredient_details(category)
        if not raw_options:
            # Try global attribute options as fallback
            raw_options = menu_cache.get_global_attribute_options(category)
        if not raw_options:
            return False

        # Transform to matcher format if needed
        options = []
        for opt in raw_options:
            if isinstance(opt, dict):
                options.append({
                    "slug": opt.get("slug"),
                    "display_name": opt.get("display_name") or opt.get("name"),
                    "aliases": opt.get("aliases") or opt.get("patterns", []),
                })
            else:
                options.append(opt)

        pack_size = self._get_pack_size(item) or 6

        # Try to parse package contents from input
        parsed = self._parse_package_contents(user_input, options, pack_size)

        # Input looks like package contents if we found at least one valid selection
        return len(parsed["selections"]) > 0

    def check_inline_specification(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        options_source_category: str | None = None,
        variety_attr_slug: str = "package_variety",
        variety_option_slug: str = "custom",
        variety_display_name: str = "Choose Types",
        contents_attr_slug: str = "package_contents",
    ) -> bool:
        """Check if user input contains inline package specification.

        Called during initial item parsing to detect patterns like:
        "6 bagel package with 3 plain and 3 everything"

        If detected, pre-fills contents attribute and marks variety attribute.
        This method is data-driven - all attribute slugs are configurable.

        Args:
            user_input: The user's input string
            item: The MenuItemTask being configured
            order: Current order state
            options_source_category: Ingredient category for options (default: 'bread')
            variety_attr_slug: Slug of the variety attribute
            variety_option_slug: Slug of the "custom" variety option
            variety_display_name: Display name for the variety option
            contents_attr_slug: Slug of the contents attribute

        Returns:
            True if inline specification was found and applied
        """
        # Get options from the specified category
        category = options_source_category or "bread"
        raw_options = menu_cache.get_ingredient_details(category)
        if not raw_options:
            raw_options = menu_cache.get_global_attribute_options(category)
        if not raw_options:
            return False

        # Transform to matcher format if needed
        options = []
        for opt in raw_options:
            if isinstance(opt, dict):
                options.append({
                    "slug": opt.get("slug"),
                    "display_name": opt.get("display_name") or opt.get("name"),
                    "aliases": opt.get("aliases") or opt.get("patterns", []),
                })
            else:
                options.append(opt)

        pack_size = self._get_pack_size(item)
        if not pack_size:
            return False

        # Try to parse package contents from input
        parsed = self._parse_package_contents(user_input, options, pack_size)

        # Only apply if we found valid selections that match pack size
        if parsed["selections"] and parsed["total"] == pack_size:
            # Set variety to custom
            item.add_selection(
                slug=variety_option_slug,
                category=variety_attr_slug,
                quantity=1,
                price=0.0,
                display_name=variety_display_name,
            )

            # Set package contents
            item.add_selection(
                slug="_package_contents",
                category=contents_attr_slug,
                quantity=1,
                price=0.0,
                display_name=self._format_selections_display(parsed["selections"], item),
            )

            logger.info(
                "INLINE_PACKAGE_SPEC: Applied %s from input: %s",
                self._format_selections_display(parsed["selections"], item),
                user_input,
            )
            return True

        return False
