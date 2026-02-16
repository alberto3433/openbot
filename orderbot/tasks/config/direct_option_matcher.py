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
from ..utils.text import normalize_text

if TYPE_CHECKING:
    from ..models import OrderTask, MenuItemTask
    from .context import ConfigHandlerContext

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
        option_matcher: "OptionMatcher | None" = None,
        ctx: "ConfigHandlerContext | None" = None,
        # Legacy parameters for backward compatibility (deprecated)
        extract_qualifier_callback: Callable[[str, str], str | None] | None = None,
        match_option_callback: Callable[[str, list[dict]], tuple[dict | None, list[dict]]] | None = None,
        ask_more_customizations_callback: Callable[["MenuItemTask", "OrderTask", str | None], StateMachineResult] | None = None,
    ):
        """
        Initialize the direct option matcher.

        Args:
            option_matcher: OptionMatcher instance for matching logic.
            ctx: ConfigHandlerContext with shared dependencies. If provided,
                 individual callback parameters are ignored.

        Deprecated args (use ctx instead):
            extract_qualifier_callback, match_option_callback, ask_more_customizations_callback
        """
        # Option matcher can come from ctx or be passed directly
        if ctx is not None and ctx.option_matcher is not None:
            self._option_matcher = ctx.option_matcher
        else:
            self._option_matcher = option_matcher

        self._orchestrator = OptionMatchingOrchestrator(option_matcher=self._option_matcher)

        if ctx is not None:
            self._extract_qualifier = ctx.extract_qualifier_for_option
            self._match_option = ctx.option_matcher.match_single if ctx.option_matcher else match_option_callback
            self._ask_more_customizations = ctx.ask_more_customizations
        else:
            # Legacy: individual parameters
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
        user_clean = normalize_text(user_input)
        if user_clean.startswith("add "):
            user_clean = user_clean[4:].strip()

        # Detect multi-token input (e.g., "pepper and sausage")
        tokens = self._option_matcher.normalizer.tokenize_multi_input(user_clean)
        if len(tokens) > 1:
            # Further split any space-separated tokens (e.g., "pepper salt sausage"
            # from "pepper salt sausage and bacon") into individual words
            tokens = self._expand_space_separated_tokens(tokens, unanswered)
            return self._handle_multi_token_direct_match(
                user_input, tokens, unanswered, item, order
            )

        # Fallback: detect space-separated options (e.g., "pepper salt sausage bacon").
        # tokenize_multi_input preserves spaces for compound names like "oat milk",
        # so we only split on spaces when 2+ individual words exactly match options.
        if ' ' in user_clean:
            space_tokens = user_clean.split()
            if len(space_tokens) > 1:
                exact_hits = self._count_exact_option_matches(space_tokens, unanswered)
                if exact_hits >= 2:
                    return self._handle_multi_token_direct_match(
                        user_input, space_tokens, unanswered, item, order
                    )

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

    def _count_exact_option_matches(
        self, tokens: list[str], unanswered: list[dict]
    ) -> int:
        """Count how many tokens exactly match an option across unanswered attributes.

        Uses exact-only matching (no partial) to avoid false positives from
        compound names like 'oat milk' being split into 'oat' + 'milk'.
        """
        count = 0
        for token in tokens:
            for attr in unanswered:
                options = attr.get("options", [])
                if not options:
                    continue
                matched, _ = self._option_matcher.match_single(
                    token, options, exact_only=True
                )
                if matched:
                    count += 1
                    break
        return count

    def _expand_space_separated_tokens(
        self, tokens: list[str], unanswered: list[dict]
    ) -> list[str]:
        """Expand multi-word tokens into individual words when they match options.

        After separator-based splitting, tokens like "pepper salt sausage" (from
        "pepper salt sausage and bacon") may still contain multiple space-separated
        options. This expands them using the same exact-match heuristic.
        """
        expanded: list[str] = []
        for token in tokens:
            if ' ' in token:
                words = token.split()
                if len(words) > 1:
                    exact_hits = self._count_exact_option_matches(words, unanswered)
                    if exact_hits >= 2:
                        expanded.extend(words)
                        continue
            expanded.append(token)
        return expanded

    def _handle_multi_token_direct_match(
        self,
        user_input: str,
        tokens: list[str],
        unanswered: list[dict],
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Handle multi-token input like 'pepper and sausage' across attributes.

        Each token is matched independently against all unanswered attributes,
        allowing tokens to resolve to different attribute categories.

        Args:
            user_input: Original user input (for qualifier extraction)
            tokens: Pre-split tokens (e.g., ["pepper", "sausage"])
            unanswered: List of unanswered optional attributes
            item: The menu item being configured
            order: The order task

        Returns:
            StateMachineResult if any token matched, None otherwise
        """
        display_parts: list[str] = []
        user_lower = user_input.lower()

        for token in tokens:
            token_clean = token.strip()
            if not token_clean:
                continue

            # Strip quantity prefixes for matching
            match_input = token_clean
            quantity_prefixes = ["extra ", "additional ", "more ", "double ", "triple "]
            for prefix in quantity_prefixes:
                if match_input.startswith(prefix):
                    match_input = match_input[len(prefix):].strip()
                    break

            for attr in unanswered:
                attr_slug = attr["slug"]
                options = attr.get("options", [])
                if not options:
                    continue

                input_type = attr.get("input_type", "single_select")

                if input_type == "multi_select":
                    matched, disambiguation = (
                        self._option_matcher.match_multiple_with_disambiguation(
                            match_input, options
                        )
                    )

                    if disambiguation:
                        # Ambiguous token — ask user to clarify before continuing
                        return self._ask_disambiguation_for_options(
                            item, order, attr, disambiguation, token_clean
                        )

                    if not matched:
                        continue

                    existing_selections = item.get_selections(attr_slug)
                    existing_slugs = {sel.get("slug") for sel in existing_selections}

                    for opt in matched:
                        if opt["slug"] in existing_slugs:
                            continue

                        opt_name = opt["display_name"]
                        qualifier = self._extract_qualifier(user_input, opt_name)
                        opt_quantity = extract_quantity_for_pattern(
                            user_lower, opt_name.lower()
                        )
                        if opt_quantity == 1:
                            opt_quantity = extract_quantity_for_pattern(
                                user_lower, opt["slug"].replace("_", " ")
                            )

                        display_name = (
                            f"{opt_name} ({qualifier})" if qualifier else opt_name
                        )
                        display = (
                            f"{opt_quantity} {display_name}"
                            if opt_quantity > 1
                            else display_name
                        )
                        display_parts.append(display)

                        item.add_selection(
                            opt["slug"],
                            attr_slug,
                            quantity=opt_quantity,
                            display_name=display_name,
                        )

                    break  # Token matched in this attribute, move to next token

                else:
                    # single_select
                    matched_opt, _ = self._match_option(match_input, options)
                    if not matched_opt:
                        continue

                    opt_name = matched_opt["display_name"]
                    qualifier = self._extract_qualifier(user_input, opt_name)

                    display_name = (
                        f"{opt_name} ({qualifier})" if qualifier else opt_name
                    )
                    display_parts.append(display_name)

                    item.remove_selection(attr_slug)
                    item.add_selection(
                        matched_opt["slug"],
                        attr_slug,
                        quantity=1,
                        display_name=display_name,
                    )

                    break  # Token matched, move to next token

        if display_parts:
            logger.info(
                "Multi-token direct match: added %s (item %s)",
                display_parts, item.id
            )
            display_text = ", ".join(display_parts)
            return self._ask_more_customizations(
                item, order, f"{display_text} added"
            )

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
        # Strip quantity prefixes for matching (preserve original for quantity extraction later)
        had_quantity_prefix = False
        match_input = user_clean
        quantity_prefixes = ["extra ", "additional ", "more ", "double ", "triple "]
        for prefix in quantity_prefixes:
            if match_input.startswith(prefix):
                match_input = match_input[len(prefix):].strip()
                had_quantity_prefix = True
                break

        # Use disambiguation-aware matching with cleaned input
        matched, disambiguation = self._option_matcher.match_multiple_with_disambiguation(
            match_input, options
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

        # When a SINGLE option matches and there are existing selections,
        # treat it as a REPLACEMENT rather than addition.
        # This handles "make it blueberry cream cheese" when plain cream cheese exists.
        # The "make it X" phrase implies transformation/change, not addition.
        # If user wanted to add, they would say "add X" or list multiple items.
        # Exception: quantity prefixes ("extra avocado") mean "more of the same", not replace.
        is_replacement = len(matched) == 1 and existing_selections and not had_quantity_prefix
        if is_replacement:
            # Clear existing selections before adding the new one
            item.remove_selection(attr_slug)
            existing_slugs = set()  # Reset so we don't skip the new option

        display_parts = []
        user_lower = user_input.lower()

        # Handle quantity prefix on existing selections (e.g., "extra avocado" when avocado exists)
        # Updates the existing modifier's quantity and tracks _base_quantity for pricing.
        if had_quantity_prefix and not is_replacement:
            for opt in matched:
                if opt["slug"] in existing_slugs:
                    existing_mod = next(
                        (m for m in item.selections if m.get("slug") == opt["slug"]),
                        None
                    )
                    if existing_mod:
                        opt_name = opt["display_name"]
                        opt_quantity = extract_quantity_for_pattern(user_lower, opt_name.lower())
                        if opt_quantity == 1:
                            opt_quantity = extract_quantity_for_pattern(
                                user_lower, opt["slug"].replace("_", " ")
                            )
                        # Track base quantity for pricing (first N are free)
                        base_qty = existing_mod.get("_base_quantity", existing_mod.get("quantity", 1))
                        existing_mod["_base_quantity"] = base_qty
                        existing_mod["quantity"] = opt_quantity
                        # Update display name with quantity prefix so to_dict()
                        # recognizes it and doesn't re-pluralize
                        qualifier = self._extract_qualifier(user_input, opt_name)
                        display_name = f"{opt_name} ({qualifier})" if qualifier else opt_name
                        display = f"{opt_quantity} {display_name}" if opt_quantity > 1 else display_name
                        existing_mod["display_name"] = display
                        display_parts.append(display)

            # If all matched options were handled as quantity updates, return early
            if display_parts:
                display_text = ", ".join(display_parts)
                return self._ask_more_customizations(item, order, f"Changed to {display_text}")

        for opt in matched:
            if opt["slug"] in existing_slugs:
                continue  # Skip already added

            opt_name = opt["display_name"]
            qualifier = self._extract_qualifier(user_input, opt_name)
            # Extract quantity for this specific option
            opt_quantity = extract_quantity_for_pattern(user_lower, opt_name.lower())
            if opt_quantity == 1:
                opt_quantity = extract_quantity_for_pattern(user_lower, opt["slug"].replace("_", " "))

            # Build display name with qualifier if present
            if qualifier:
                display_name_with_qualifier = f"{opt_name} ({qualifier})"
            else:
                display_name_with_qualifier = opt_name

            # Build display for ack message (may include quantity prefix)
            if opt_quantity > 1:
                display = f"{opt_quantity} {display_name_with_qualifier}"
            else:
                display = display_name_with_qualifier

            display_parts.append(display)

            # Add selection using unified API (with qualifier in display_name)
            item.add_selection(
                opt["slug"],
                attr_slug,
                quantity=opt_quantity,
                display_name=display_name_with_qualifier,
            )

        if display_parts:
            if is_replacement:
                logger.info(
                    "Direct option match: replaced %s with %s (item %s)",
                    attr_slug, matched[0]["slug"], item.id
                )
                display_text = ", ".join(display_parts)
                return self._ask_more_customizations(item, order, f"Changed to {display_text}")
            else:
                logger.info(
                    "Direct option match: added %s to %s (item %s)",
                    [opt["slug"] for opt in matched], attr_slug, item.id
                )
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
            opt_price = OptionMatcher.get_option_price(matched_opt)

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

                    # Store actual quantity for pricing but use 1 for display
                    # (display_name will include the quantity, e.g., "3 Eggs")
                    existing_mod["_actual_quantity"] = new_quantity
                    existing_mod["quantity"] = 1  # Prevents "3x 3 Eggs" in summary
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

                    # No separate tracking selection needed - the modified ingredient
                    # itself reflects the change (display_name, quantity, price)

                    logger.info(
                        "Updated modifier %s quantity: %d -> %d (base=%d, via %s=%s, upcharge=$%.2f)",
                        modifies_slug, base_quantity, new_quantity, base_quantity, attr_slug, matched_opt["slug"], total_upcharge
                    )
                    return self._ask_more_customizations(item, order, f"{display}")

            # Default behavior for non-ingredient-modifying attributes
            # Build display name with qualifier if present
            if qualifier:
                display_name = f"{opt_name} ({qualifier})"
            else:
                display_name = opt_name

            # For single_select attributes, REPLACE existing selection (not add)
            # This handles "make it blueberry cream cheese" when plain cream cheese exists
            item.remove_selection(attr_slug)

            # Add selection using unified API (with qualifier in display_name)
            item.add_selection(
                matched_opt["slug"],
                attr_slug,
                quantity=1,
                display_name=display_name,
            )
            logger.info(
                "Direct option match: set %s = %s (item %s)",
                attr_slug, matched_opt["slug"], item.id
            )

            # Check for remaining options and re-offer or complete
            return self._ask_more_customizations(item, order, f"{display_name} added")

        # Try numeric matching for options with numeric slugs (e.g., shots: "1", "2", "3")
        numeric_slugs = {opt["slug"] for opt in options if opt["slug"].isdigit()}
        if numeric_slugs:
            parsed_num = parse_numeric_input(user_clean)
            if parsed_num is not None:
                target_slug = str(parsed_num)
                for opt in options:
                    if opt["slug"] == target_slug:
                        display_name = opt.get("display_name", f"{parsed_num}")
                        item.add_selection(
                            opt["slug"],
                            attr_slug,
                            quantity=1,
                            display_name=display_name,
                        )
                        logger.info(
                            "CHECKPOINT NUMERIC: %s=%s from input '%s'",
                            attr_slug, opt["slug"], user_input
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
