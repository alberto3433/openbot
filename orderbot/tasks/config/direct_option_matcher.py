"""
Direct Option Matcher for Menu Item Configuration.

Handles matching user input directly to attribute option values,
allowing users to specify options without naming the attribute first.
E.g., "add a little mayo" without saying "condiments" first.

Extracted from menu_item_config_handler.py to reduce file size.
"""

import logging
from typing import TYPE_CHECKING, Callable

from ..schemas import StateMachineResult, OrderPhase
from ..parsers.constants import extract_quantity_for_pattern
from ..parsers.quantity_utils import parse_numeric_input, extract_leading_quantity
from ..utils import OptionMatchingOrchestrator, OptionMatcher

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask

logger = logging.getLogger(__name__)


class DirectOptionMatcher:
    """
    Matches user input directly to option values within attributes.

    Handles the flow when users specify options without naming the
    attribute category first, including disambiguation when input
    matches multiple options.
    """

    def __init__(
        self,
        option_matcher: OptionMatcher,
        extract_qualifier_callback: Callable[[str, str], str | None],
        match_option_callback: Callable[[str, list[dict]], tuple[dict | None, list[dict]]],
        ask_more_customizations_callback: Callable[["MenuItemTask", "OrderTask", str | None], StateMachineResult],
    ):
        """
        Initialize the direct option matcher.

        Args:
            option_matcher: OptionMatcher instance for matching logic.
            extract_qualifier_callback: Callback to extract qualifiers (e.g., "extra", "on the side").
            match_option_callback: Callback for single option matching.
            ask_more_customizations_callback: Callback to ask about more customizations.
        """
        self._option_matcher = option_matcher
        self._orchestrator = OptionMatchingOrchestrator(option_matcher=option_matcher)
        self._extract_qualifier = extract_qualifier_callback
        self._match_option = match_option_callback
        self._ask_more_customizations = ask_more_customizations_callback

    def try_direct_option_match(
        self,
        user_input: str,
        unanswered: list[dict],
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """
        Try to match user input directly to option values within attributes.

        Called when attribute name matching fails. Allows users to say things like
        "add a little mayo" without needing to say "condiments" first.

        Args:
            user_input: User's input (e.g., "add a little mayo")
            unanswered: List of unanswered optional attributes
            item: The menu item being configured
            order: The order task

        Returns:
            StateMachineResult if an option was matched and applied, None otherwise
        """
        # Strip "add" prefix if present to get the core request
        user_clean = user_input.lower().strip()
        if user_clean.startswith("add "):
            user_clean = user_clean[4:].strip()

        # Try to match against options in each unanswered attribute
        for attr in unanswered:
            attr_slug = attr["slug"]
            options = attr.get("options", [])
            if not options:
                continue

            input_type = attr.get("input_type", "single_select")

            if input_type == "multi_select":
                result = self._handle_multi_select_match(
                    user_input, user_clean, attr, attr_slug, options, item, order
                )
                if result:
                    return result
            else:
                result = self._handle_single_select_match(
                    user_input, user_clean, attr, attr_slug, options, item, order
                )
                if result:
                    return result

        return None

    def _handle_multi_select_match(
        self,
        user_input: str,
        user_clean: str,
        attr: dict,
        attr_slug: str,
        options: list[dict],
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle multi-select option matching with disambiguation."""
        # Use disambiguation-aware matching
        matched, disambiguation = self._option_matcher.match_multiple_with_disambiguation(
            user_clean, options
        )

        if disambiguation:
            # Single ambiguous term matches multiple options - ask user to clarify
            return self._ask_disambiguation_for_options(
                item, order, attr, disambiguation, user_input
            )

        if not matched:
            return None

        # Get existing selections for this category
        existing_selections = item.get_selections(attr_slug)
        existing_slugs = {sel.get("slug") for sel in existing_selections}

        display_parts = []
        user_lower = user_input.lower()
        for opt in matched:
            if opt["slug"] in existing_slugs:
                continue  # Skip already added

            opt_name = opt["display_name"]
            qualifier = self._extract_qualifier(user_input, opt_name)
            # Extract quantity for this specific option
            opt_quantity = extract_quantity_for_pattern(user_lower, opt_name.lower())
            if opt_quantity == 1:
                opt_quantity = extract_quantity_for_pattern(user_lower, opt["slug"].replace("_", " "))

            if qualifier:
                display = f"{opt_name} ({qualifier})"
            else:
                display = opt_name

            if opt_quantity > 1:
                display = f"{opt_quantity} {display}"

            display_parts.append(display)

            # Add selection using unified API
            opt_price = opt.get("price") or opt.get("price_modifier") or 0
            item.add_selection(
                opt["slug"],
                attr_slug,
                quantity=opt_quantity,
                price=opt_price,
                display_name=opt_name,
            )

        if display_parts:
            logger.info(
                "Direct option match: added %s to %s (item %s)",
                [opt["slug"] for opt in matched], attr_slug, item.id
            )

            # Check for remaining options and re-offer or complete
            display_text = ", ".join(display_parts)
            return self._ask_more_customizations(item, order, f"{display_text} added")

        return None

    def _handle_single_select_match(
        self,
        user_input: str,
        user_clean: str,
        attr: dict,
        attr_slug: str,
        options: list[dict],
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle single-select option matching."""
        matched_opt, _ = self._match_option(user_clean, options)
        if matched_opt:
            opt_name = matched_opt["display_name"]
            qualifier = self._extract_qualifier(user_input, opt_name)
            opt_price = matched_opt.get("price") or matched_opt.get("price_modifier") or 0

            # Check if this attribute modifies an existing ingredient
            modifies_slug = attr.get("modifies_ingredient_slug")
            if modifies_slug:
                # Parse quantity from option slug (e.g., "3_eggs" -> 3)
                new_quantity = self._parse_quantity_from_slug(matched_opt["slug"])

                # Find and update existing modifier
                existing_mod = item.find_modifier_by_slug(modifies_slug)
                if existing_mod:
                    old_price = existing_mod.get("price", 0)

                    # Get or store the base quantity (original default from signature item)
                    # This is needed to calculate total upcharge from the baseline
                    base_quantity = existing_mod.get("_base_quantity")
                    if base_quantity is None:
                        # First time modifying - store the original quantity as baseline
                        base_quantity = existing_mod.get("quantity", 1)
                        existing_mod["_base_quantity"] = base_quantity

                    # Calculate TOTAL upcharge from baseline (not incremental)
                    # The option's price_modifier may be 0 if it's the default for another item type
                    # (e.g., 3_eggs is default for omelette but extra for egg_sandwich)
                    # So we calculate: (new_quantity - base_quantity) * per_unit_price
                    extra_from_base = new_quantity - base_quantity
                    if extra_from_base > 0:
                        # Get per-unit price from attribute options
                        per_unit_price = self._get_per_unit_price_from_options(attr.get("options", []))
                        total_upcharge = extra_from_base * per_unit_price
                    else:
                        total_upcharge = 0.0

                    existing_mod["quantity"] = new_quantity
                    # Set price on modifier for display purposes (total upcharge, not per-unit)
                    existing_mod["price"] = total_upcharge

                    # Update unit_price: add new upcharge minus previous upcharge
                    item.unit_price = (item.unit_price or 0.0) + total_upcharge - old_price

                    # Get base display name (without quantity prefix)
                    # e.g., "3 Eggs" -> "Egg", "Egg" -> "Egg"
                    import re
                    base_display = existing_mod.get("display_name", modifies_slug.title())
                    base_display = re.sub(r'^\d+\s+', '', base_display)  # Remove leading "N "
                    if base_display.endswith("s") and len(base_display) > 1:
                        base_display = base_display[:-1]  # Remove trailing 's' to get singular

                    # Format display based on quantity
                    if new_quantity > 1:
                        # Pluralize: "Egg" -> "Eggs"
                        if not base_display.endswith("s"):
                            display = f"{new_quantity} {base_display}s"
                        else:
                            display = f"{new_quantity} {base_display}"
                    else:
                        display = base_display
                    existing_mod["display_name"] = display

                    # Track in attribute_values via a modifier entry for this attr_slug
                    # We add a tracking entry WITHOUT price (to avoid double-counting)
                    # The price is already on the existing modifier
                    item.add_selection(
                        matched_opt["slug"],
                        attr_slug,
                        quantity=1,
                        price=0,  # Don't double-count price
                        display_name=display,
                    )

                    logger.info(
                        "Updated modifier %s quantity: %d -> %d (base=%d, via %s=%s, upcharge=$%.2f)",
                        modifies_slug, base_quantity, new_quantity, base_quantity, attr_slug, matched_opt["slug"], total_upcharge
                    )
                    return self._ask_more_customizations(item, order, f"{display}")

            # Default behavior for non-ingredient-modifying attributes
            if qualifier:
                display = f"{opt_name} ({qualifier})"
            else:
                display = opt_name

            # Add selection using unified API
            item.add_selection(
                matched_opt["slug"],
                attr_slug,
                quantity=1,
                price=opt_price,
                display_name=opt_name,
            )
            logger.info(
                "Direct option match: set %s = %s (item %s)",
                attr_slug, matched_opt["slug"], item.id
            )

            # Check for remaining options and re-offer or complete
            return self._ask_more_customizations(item, order, f"{display} added")

        # Try numeric matching for options with numeric slugs (e.g., shots: "1", "2", "3")
        numeric_slugs = {opt["slug"] for opt in options if opt["slug"].isdigit()}
        if numeric_slugs:
            parsed_num = parse_numeric_input(user_clean)
            if parsed_num is not None:
                target_slug = str(parsed_num)
                for opt in options:
                    if opt["slug"] == target_slug:
                        opt_price = opt.get("price") or opt.get("price_modifier") or 0.0
                        display_name = opt.get("display_name", f"{parsed_num}")
                        item.add_selection(
                            opt["slug"],
                            attr_slug,
                            quantity=1,
                            price=opt_price,
                            display_name=display_name,
                        )
                        logger.info(
                            "CHECKPOINT NUMERIC: %s=%s (price=$%.2f) from input '%s'",
                            attr_slug, opt["slug"], opt_price, user_input
                        )
                        # Check for remaining options and re-offer or complete
                        return self._ask_more_customizations(item, order, f"{display_name} added")

        return None

    def _parse_quantity_from_slug(self, slug: str) -> int:
        """Parse quantity from option slug like '3_eggs' -> 3.

        Supports formats:
        - '3_eggs' -> 3
        - '3eggs' -> 3
        - '3' -> 3

        Returns 1 if no quantity found.
        """
        import re
        match = re.match(r'^(\d+)', slug)
        if match:
            return int(match.group(1))
        return 1

    def _get_per_unit_price_from_options(self, options: list[dict]) -> float:
        """Calculate per-unit price from attribute options.

        Looks at consecutive options and calculates the price difference per unit.
        For example, if 4_eggs costs $1.50 and 5_eggs costs $3.00,
        the per-unit price is ($3.00 - $1.50) / (5 - 4) = $1.50.

        Returns 0.0 if cannot determine per-unit price.
        """
        if not options or len(options) < 2:
            return 0.0

        # Build list of (quantity, price) tuples
        qty_price_pairs = []
        for opt in options:
            qty = self._parse_quantity_from_slug(opt.get("slug", ""))
            price = opt.get("price_modifier") or opt.get("price") or 0.0
            if qty > 0:
                qty_price_pairs.append((qty, price))

        # Sort by quantity
        qty_price_pairs.sort(key=lambda x: x[0])

        # Find two consecutive options with different prices to calculate per-unit price
        for i in range(len(qty_price_pairs) - 1):
            qty1, price1 = qty_price_pairs[i]
            qty2, price2 = qty_price_pairs[i + 1]
            qty_diff = qty2 - qty1
            price_diff = price2 - price1
            if qty_diff > 0 and price_diff > 0:
                return price_diff / qty_diff

        # Fallback: if all options have prices, use the first non-zero price
        for qty, price in qty_price_pairs:
            if price > 0:
                # Assume this is the price for 1 extra unit
                return price

        return 0.0

    def _ask_disambiguation_for_options(
        self,
        item: "MenuItemTask",
        order: "OrderTask",
        attr: dict,
        candidates: list[dict],
        original_input: str,
    ) -> StateMachineResult:
        """Ask user to clarify which option they meant when input is ambiguous.

        Called when a single term like "bacon" matches multiple options
        (e.g., Bacon, Turkey Bacon, Applewood Smoked Bacon).

        Args:
            item: The menu item being configured
            order: Current order task
            attr: The attribute dict (e.g., meat attribute)
            candidates: List of options that matched the ambiguous input
            original_input: The original user input for context

        Returns:
            StateMachineResult asking user to choose between candidates
        """
        attr_slug = attr.get("slug", "option")
        attr_display = attr.get("display_name", attr_slug).lower()
        options_list = ", ".join(c["display_name"] for c in candidates)

        # Extract quantity from original input (e.g., "4 syrups" -> 4)
        quantity, _ = extract_leading_quantity(original_input)
        if quantity is None:
            quantity = 1

        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        order.pending_item_id = item.id
        order.pending_field = f"{item.menu_item_type}:{attr_slug}"

        # Use pending_attr_disambiguation pattern (consistent with select_input_handler)
        # This stores quantity so it can be applied when user answers
        order.pending_attr_disambiguation = {
            "options": candidates,
            "attr_slug": attr_slug,
            "modifiers": {"_quantity": quantity},
            "item_id": item.id,
        }

        return StateMachineResult(
            message=f"Which {attr_display} would you like? {options_list}",
            order=order,
        )
