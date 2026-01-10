"""
Menu Item Configuration Handler for Order State Machine.

This module handles the configuration of menu items (like deli sandwiches)
with DB-driven attributes. It supports:
- Mandatory attributes (ask_in_conversation=True) asked in sequence
- Customization checkpoint after mandatory attributes
- Optional attributes (ask_in_conversation=False) offered in a loop

Designed to be generic and work with any item type that has DB-defined attributes.
"""

import logging
import re
from typing import TYPE_CHECKING, Any

from sandwich_bot.menu_data_cache import menu_cache
from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)

# Word-to-number mapping for quantity extraction (for syrups, shots, etc.)
WORD_TO_NUM = {
    "one": 1, "a": 1, "an": 1,
    "two": 2, "double": 2,
    "three": 3, "triple": 3,
    "four": 4, "quad": 4, "quadruple": 4,
    "five": 5,
    "six": 6,
}


def _extract_quantity(user_input: str, pattern: str) -> int:
    """Extract quantity from user input for a given pattern.

    Handles both numeric ("2 vanilla") and word ("two vanilla") quantities.

    Args:
        user_input: The user's input string (lowercase)
        pattern: The pattern to look for (e.g., "vanilla", "vanilla syrup")

    Returns:
        The extracted quantity, defaulting to 1 if not found.
    """
    escaped_pattern = re.escape(pattern)

    # Try digit match first: "2 vanilla syrups"
    digit_match = re.search(rf'(\d+)\s*{escaped_pattern}s?', user_input)
    if digit_match:
        return int(digit_match.group(1))

    # Try word match: "two vanilla syrups"
    word_pattern = r'(one|two|three|four|five|six|double|triple|quad|quadruple)\s+' + escaped_pattern + r's?'
    word_match = re.search(word_pattern, user_input)
    if word_match:
        return WORD_TO_NUM.get(word_match.group(1).lower(), 1)

    return 1


class MenuItemConfigHandler:
    """
    Handles menu item configuration with DB-driven attributes.

    Reads item type attributes from the database to determine:
    - Which questions to ask (ask_in_conversation=True for mandatory)
    - What the question text should be (question_text field)
    - What options are valid (attribute_options or item_type_ingredients)
    """

    # Item types that use this handler for configuration
    SUPPORTED_ITEM_TYPES = {"deli_sandwich", "egg_sandwich", "fish_sandwich", "spread_sandwich", "espresso"}

    # Page size for options pagination (matches other handlers)
    OPTIONS_PAGE_SIZE = 5

    def __init__(self, config: "HandlerConfig | None" = None, **kwargs):
        """
        Initialize the menu item config handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.pricing = config.pricing
            self.menu_lookup = config.menu_lookup
            self._get_next_question = config.get_next_question
        else:
            self.pricing = kwargs.get("pricing")
            self.menu_lookup = kwargs.get("menu_lookup")
            self._get_next_question = kwargs.get("get_next_question")

        # Cache for item type attributes (keyed by item_type_slug)
        self._attributes_cache: dict[str, dict] = {}

    def supports_item_type(self, item_type_slug: str | None) -> bool:
        """Check if this handler supports the given item type."""
        return item_type_slug in self.SUPPORTED_ITEM_TYPES

    def _get_item_type_attributes(self, item_type_slug: str) -> dict:
        """
        Load item type attributes from database.

        Returns dict with structure:
        {
            "bread": {
                "slug": "bread",
                "display_name": "Bread",
                "question_text": "What kind of bread?",
                "ask_in_conversation": True,
                "input_type": "single_select",
                "display_order": 1,
                "options": [{"slug": "plain", "display_name": "Plain", "price": 0}, ...]
            },
            ...
        }
        """
        if item_type_slug in self._attributes_cache:
            return self._attributes_cache[item_type_slug]

        from ..db import SessionLocal
        from ..models import (
            ItemType, ItemTypeAttribute, AttributeOption,
            ItemTypeIngredient, Ingredient,
            ItemTypeGlobalAttribute, GlobalAttribute,
        )

        db = SessionLocal()
        try:
            item_type = db.query(ItemType).filter(ItemType.slug == item_type_slug).first()
            if not item_type:
                logger.warning("Item type '%s' not found in database", item_type_slug)
                self._attributes_cache[item_type_slug] = {}
                return {}

            attrs = db.query(ItemTypeAttribute).filter(
                ItemTypeAttribute.item_type_id == item_type.id
            ).order_by(ItemTypeAttribute.display_order).all()

            result = {}
            for attr in attrs:
                opts_data = []

                # Check if options should come from ingredients
                if attr.loads_from_ingredients and attr.ingredient_group:
                    ingredient_links = (
                        db.query(ItemTypeIngredient)
                        .join(Ingredient, ItemTypeIngredient.ingredient_id == Ingredient.id)
                        .filter(
                            ItemTypeIngredient.item_type_id == item_type.id,
                            ItemTypeIngredient.ingredient_group == attr.ingredient_group,
                            ItemTypeIngredient.is_available == True,
                        )
                        .order_by(ItemTypeIngredient.display_order)
                        .all()
                    )

                    for link in ingredient_links:
                        ingredient = link.ingredient
                        opt_data = {
                            "slug": ingredient.slug or ingredient.name.lower().replace(" ", "_"),
                            "display_name": link.display_name_override or ingredient.name,
                            "price": float(link.price_modifier or 0),
                            "is_default": link.is_default,
                        }
                        if ingredient.aliases:
                            opt_data["aliases"] = ingredient.aliases
                        if ingredient.must_match:
                            opt_data["must_match"] = ingredient.must_match
                        opts_data.append(opt_data)
                else:
                    # Load options from attribute_options table
                    options = db.query(AttributeOption).filter(
                        AttributeOption.item_type_attribute_id == attr.id,
                        AttributeOption.is_available == True,
                    ).order_by(AttributeOption.display_order).all()

                    for opt in options:
                        opt_data = {
                            "slug": opt.slug,
                            "display_name": opt.display_name,
                            "price": float(opt.price_modifier or 0),
                            "is_default": opt.is_default,
                        }
                        opts_data.append(opt_data)

                result[attr.slug] = {
                    "slug": attr.slug,
                    "display_name": attr.display_name,
                    "question_text": attr.question_text,
                    "ask_in_conversation": attr.ask_in_conversation,
                    "input_type": attr.input_type,
                    "display_order": attr.display_order,
                    "allow_none": attr.allow_none,
                    "options": opts_data,
                }

            # Also load global attributes linked to this item type
            global_attr_links = (
                db.query(ItemTypeGlobalAttribute)
                .filter(ItemTypeGlobalAttribute.item_type_id == item_type.id)
                .order_by(ItemTypeGlobalAttribute.display_order)
                .all()
            )

            for link in global_attr_links:
                global_attr = db.query(GlobalAttribute).filter(
                    GlobalAttribute.id == link.global_attribute_id
                ).first()
                if not global_attr:
                    continue

                # Load options from cache instead of direct DB query
                # This ensures we always have consistent field mappings (must_match, aliases, etc.)
                cached_opts = menu_cache.get_global_attribute_options(global_attr.slug)

                opts_data = []
                for opt in cached_opts:
                    # Skip unavailable options
                    if not opt.get("is_available", True):
                        continue
                    opt_data = {
                        "slug": opt["slug"],
                        "display_name": opt["display_name"],
                        "price": float(opt.get("price_modifier") or 0),
                        "is_default": opt.get("is_default", False),
                    }
                    # Include aliases for option matching (pipe-separated)
                    if opt.get("aliases"):
                        opt_data["aliases"] = opt["aliases"]
                    # Include must_match for filtering (e.g., "oat milk" only matches "oat milk")
                    if opt.get("must_match"):
                        opt_data["must_match"] = opt["must_match"]
                    opts_data.append(opt_data)

                # Use link's question_text if provided, else generate based on input_type
                if link.question_text:
                    question_text = link.question_text
                elif global_attr.input_type == "boolean":
                    question_text = f"Would you like it {global_attr.display_name.lower()}?"
                else:
                    question_text = f"What {global_attr.display_name.lower()} would you like?"

                result[global_attr.slug] = {
                    "slug": global_attr.slug,
                    "display_name": global_attr.display_name,
                    "question_text": question_text,
                    "ask_in_conversation": link.ask_in_conversation,
                    "input_type": global_attr.input_type or "single_select",
                    "display_order": link.display_order,
                    "allow_none": link.allow_none,
                    "options": opts_data,
                    "is_global_attribute": True,  # Flag to identify global attrs
                }

            self._attributes_cache[item_type_slug] = result
            logger.info(
                "Loaded %d attributes for %s: %s",
                len(result), item_type_slug, list(result.keys())
            )
            return result

        finally:
            db.close()

    def _get_mandatory_attributes(self, item_type_slug: str) -> list[dict]:
        """Get mandatory attributes (ask_in_conversation=True) in display order."""
        attrs = self._get_item_type_attributes(item_type_slug)
        mandatory = [
            attr for attr in attrs.values()
            if attr.get("ask_in_conversation", False)
        ]
        return sorted(mandatory, key=lambda x: x.get("display_order", 999))

    def _get_optional_attributes(self, item_type_slug: str) -> list[dict]:
        """Get optional attributes (ask_in_conversation=False) in display order."""
        attrs = self._get_item_type_attributes(item_type_slug)
        optional = [
            attr for attr in attrs.values()
            if not attr.get("ask_in_conversation", True)
        ]
        return sorted(optional, key=lambda x: x.get("display_order", 999))

    def _get_unanswered_mandatory(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get mandatory attributes that haven't been answered yet."""
        mandatory = self._get_mandatory_attributes(item_type_slug)
        unanswered = []
        for attr in mandatory:
            slug = attr["slug"]
            if slug not in item.attribute_values:
                unanswered.append(attr)
        return unanswered

    def _get_unanswered_optional(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get optional attributes that haven't been answered yet."""
        optional = self._get_optional_attributes(item_type_slug)
        unanswered = []
        for attr in optional:
            slug = attr["slug"]
            if slug not in item.attribute_values:
                unanswered.append(attr)
        return unanswered

    def _extract_quantity_from_input(self, user_input: str) -> tuple[int, str]:
        """
        Extract quantity from user input.

        Returns (quantity, remaining_text) tuple.
        E.g., "2 scrambled eggs" → (2, "scrambled eggs")
              "two fried eggs" → (2, "fried eggs")
              "scrambled egg" → (1, "scrambled egg")
        """
        text = user_input.strip()
        quantity = 1

        # Check for leading numeric quantity (e.g., "2", "2x", "10")
        match = re.match(r'^(\d+)x?\s+', text, re.IGNORECASE)
        if match:
            quantity = int(match.group(1))
            text = text[match.end():]
            return (quantity, text)

        # Check for word quantities
        word_quantities = {
            'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
            'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        }
        for word, num in word_quantities.items():
            pattern = rf'^{word}\s+'
            match = re.match(pattern, text, re.IGNORECASE)
            if match:
                quantity = num
                text = text[match.end():]
                return (quantity, text)

        return (quantity, text)

    def _normalize_for_matching(self, text: str) -> str:
        """
        Normalize user input for option matching.

        Handles common patterns users type when ordering:
        - Leading quantities: "2 scrambled eggs" → "scrambled eggs"
        - Plural forms: "scrambled eggs" → "scrambled egg"
        """
        text = text.lower().strip()

        # Strip leading quantity patterns (numbers like "2", "2x", words like "two")
        text = re.sub(r'^(\d+x?\s+)', '', text)  # "2 ", "2x ", "10 "
        text = re.sub(r'^(one|two|three|four|five|six|seven|eight|nine|ten)\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^(a|an)\s+', '', text)  # "a scrambled egg", "an egg"

        # Normalize common food plurals to singular for matching
        # "eggs" → "egg", "bagels" → "bagel", "syrups" → "syrup"
        text = re.sub(r'\beggs\b', 'egg', text)
        text = re.sub(r'\bbagels\b', 'bagel', text)
        text = re.sub(r'\bsyrups\b', 'syrup', text)

        # Normalize numeric shot quantities to words
        # "1" → "single", "2" → "double", etc.
        SHOT_NORMALIZATIONS = {
            "1": "single", "one": "single",
            "2": "double", "two": "double",
            "3": "triple", "three": "triple",
            "4": "quad", "four": "quad",
        }
        if text in SHOT_NORMALIZATIONS:
            text = SHOT_NORMALIZATIONS[text]

        return text.strip()

    def _match_option_from_input(
        self, user_input: str, options: list[dict]
    ) -> tuple[dict | None, list[dict]]:
        """
        Try to match user input to an option with smart partial matching.

        Returns:
            (matched_option, partial_matches) tuple:
            - (option, []) = exact or unique partial match found
            - (None, [opt1, opt2, ...]) = multiple partial matches, need disambiguation
            - (None, []) = no matches at all

        Matching priority:
        1. Exact match on display_name, slug, or alias
        2. Partial match: user input is contained in option name (e.g., "plain" → "Plain Bagel")
        3. Partial match: option name is contained in user input (e.g., "plain bagel please" → "Plain Bagel")

        Note: Options with must_match are only matched if user input contains at least
        one of the must_match strings.
        """
        # Normalize input to handle quantities and plurals
        # e.g., "2 scrambled eggs" → "scrambled egg"
        user_lower = self._normalize_for_matching(user_input)

        def get_aliases(opt: dict) -> list[str]:
            aliases_raw = opt.get("aliases", [])
            if isinstance(aliases_raw, str):
                # Support both pipe-separated (DB format) and comma-separated aliases
                if "|" in aliases_raw:
                    return [a.strip() for a in aliases_raw.split("|") if a.strip()]
                return [a.strip() for a in aliases_raw.split(",") if a.strip()]
            return aliases_raw or []

        # Phase 1: Exact matches (highest priority)
        for opt in options:
            if not self._passes_must_match(user_input, opt):
                continue  # Skip options that don't pass must_match
            display_lower = opt["display_name"].lower()
            if display_lower == user_lower:
                return (opt, [])
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable == user_lower:
                return (opt, [])
            for alias in get_aliases(opt):
                if alias.lower() == user_lower:
                    return (opt, [])

        # Phase 2: User input is contained in option name (partial match)
        # e.g., "plain" matches "Plain Bagel", "gluten free" matches "Gluten Free Plain Bagel"
        partial_matches = []
        for opt in options:
            if not self._passes_must_match(user_input, opt):
                continue  # Skip options that don't pass must_match
            display_lower = opt["display_name"].lower()
            if self._is_whole_word_match(user_lower, display_lower):
                partial_matches.append(opt)
                continue
            slug_readable = opt["slug"].replace("_", " ")
            if self._is_whole_word_match(user_lower, slug_readable):
                if opt not in partial_matches:
                    partial_matches.append(opt)
                continue
            for alias in get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and self._is_whole_word_match(user_lower, alias_lower):
                    if opt not in partial_matches:
                        partial_matches.append(opt)
                    break

        if len(partial_matches) == 1:
            return (partial_matches[0], [])
        elif len(partial_matches) > 1:
            return (None, partial_matches)

        # Phase 3: Option name is contained in user input (original behavior)
        # e.g., "plain bagel please" matches "Plain Bagel"
        for opt in options:
            if not self._passes_must_match(user_input, opt):
                continue  # Skip options that don't pass must_match
            display_lower = opt["display_name"].lower()
            if display_lower in user_lower and self._is_whole_word_match(display_lower, user_lower):
                return (opt, [])
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable in user_lower and self._is_whole_word_match(slug_readable, user_lower):
                return (opt, [])
            for alias in get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and alias_lower in user_lower:
                    if self._is_whole_word_match(alias_lower, user_lower):
                        return (opt, [])

        return (None, [])

    def _match_multiple_options_from_input(
        self, user_input: str, options: list[dict]
    ) -> list[dict]:
        """
        Match ALL options mentioned in user input (for multi_select attributes).

        Returns list of matched options (may be empty if none found).
        Unlike _match_option_from_input, this finds ALL matches, not just one.

        E.g., "mayo mustard" -> [mayo_option, mustard_option]

        Note: Options with must_match are only matched if user input contains at least
        one of the must_match strings.
        """
        # Normalize input to handle quantities and plurals
        user_lower = self._normalize_for_matching(user_input)
        matched = []

        def get_aliases(opt: dict) -> list[str]:
            aliases_raw = opt.get("aliases", [])
            if isinstance(aliases_raw, str):
                # Support both pipe-separated (DB format) and comma-separated aliases
                if "|" in aliases_raw:
                    return [a.strip() for a in aliases_raw.split("|") if a.strip()]
                return [a.strip() for a in aliases_raw.split(",") if a.strip()]
            return aliases_raw or []

        for opt in options:
            if not self._passes_must_match(user_input, opt):
                continue  # Skip options that don't pass must_match

            display_lower = opt["display_name"].lower()
            slug_readable = opt["slug"].replace("_", " ")

            # Check exact word match in user input
            if self._is_whole_word_match(display_lower, user_lower):
                matched.append(opt)
                continue
            if self._is_whole_word_match(slug_readable, user_lower):
                matched.append(opt)
                continue

            # Check aliases
            for alias in get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 2 and self._is_whole_word_match(alias_lower, user_lower):
                    matched.append(opt)
                    break

        return matched

    def _is_whole_word_match(self, needle: str, haystack: str) -> bool:
        """Check if needle appears as a whole word/phrase in haystack."""
        import re
        # Use word boundaries to ensure we match whole words
        pattern = r'\b' + re.escape(needle) + r'\b'
        return bool(re.search(pattern, haystack))

    def _passes_must_match(self, user_input: str, opt: dict) -> bool:
        """
        Check if option passes must_match requirement.

        If opt has must_match strings, at least one must be present in user_input.
        If no must_match is set, returns True (no restriction).
        """
        must_match_raw = opt.get("must_match")
        if not must_match_raw:
            return True  # No must_match requirement

        user_lower = user_input.lower()
        # Parse comma-separated must_match strings
        if isinstance(must_match_raw, str):
            must_match_list = [m.strip().lower() for m in must_match_raw.split(",") if m.strip()]
        else:
            must_match_list = [str(m).lower() for m in must_match_raw]

        # At least one must_match string must be present
        for must_str in must_match_list:
            if self._is_whole_word_match(must_str, user_lower):
                return True

        return False

    def _extract_qualifier_for_option(self, user_input: str, option_name: str) -> str | None:
        """
        Extract qualifier (extra, light, lots of, on the side, etc.) for a specific option.

        Scans user input for qualifier patterns adjacent to the option name.

        Args:
            user_input: The full user input text (e.g., "lots of lettuce and extra mayo")
            option_name: The option to find qualifier for (e.g., "Lettuce")

        Returns:
            Normalized qualifier like "extra" or "on the side", or None if no qualifier found.
        """
        qualifier_patterns = menu_cache.get_qualifier_patterns()
        if not qualifier_patterns:
            return None

        user_lower = user_input.lower()
        option_lower = option_name.lower()

        # Find position of the option in user input
        opt_match = re.search(rf'\b{re.escape(option_lower)}\b', user_lower)
        if not opt_match:
            return None

        opt_start, opt_end = opt_match.start(), opt_match.end()

        # Check for qualifiers adjacent to this option
        for pattern in qualifier_patterns:
            pattern_re = re.compile(rf'\b{re.escape(pattern)}\b', re.IGNORECASE)
            for match in pattern_re.finditer(user_lower):
                qual_start, qual_end = match.start(), match.end()

                # Qualifier before option: "extra lettuce", "lots of lettuce"
                is_before = qual_end <= opt_start and opt_start - qual_end <= 15
                # Qualifier after option: "lettuce on the side"
                is_after = qual_start >= opt_end and qual_start - opt_end <= 15

                if is_before or is_after:
                    info = menu_cache.get_qualifier_info(pattern)
                    if info:
                        return info["normalized_form"]

        return None

    def _match_attribute_from_input(
        self, user_input: str, attributes: list[dict]
    ) -> list[dict]:
        """
        Try to match user input to one or more attributes.

        Used when user says "add egg and spread" to match multiple.
        Supports partial matching: "cheese" matches "Extra Cheese", "egg" matches "Add Egg".
        """
        user_lower = user_input.lower().strip()
        matched = []

        for attr in attributes:
            display_lower = attr["display_name"].lower()
            slug_readable = attr["slug"].replace("_", " ")

            # Exact match: attribute name in user input
            if display_lower in user_lower:
                matched.append(attr)
                continue
            if slug_readable in user_lower:
                matched.append(attr)
                continue

            # Partial match: user input is a word in the attribute name
            # e.g., "cheese" matches "Extra Cheese", "egg" matches "Add Egg"
            if self._is_whole_word_match(user_lower, display_lower):
                matched.append(attr)
                continue
            if self._is_whole_word_match(user_lower, slug_readable):
                matched.append(attr)
                continue

        return matched

    def _format_options_list(self, options: list[dict]) -> str:
        """Format a list of options for display."""
        names = [opt["display_name"] for opt in options]
        if len(names) <= 2:
            return " or ".join(names)
        return ", ".join(names[:-1]) + f", or {names[-1]}"

    def _format_attributes_list(self, attributes: list[dict]) -> str:
        """Format a list of attributes for the customization menu."""
        names = [attr["display_name"] for attr in attributes]
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} or {names[1]}"
        return ", ".join(names[:-1]) + f", or {names[-1]}"

    # =========================================================================
    # Options Inquiry and Pagination
    # =========================================================================

    def _is_options_inquiry(self, user_input: str) -> bool:
        """Check if user is asking about available options."""
        input_lower = user_input.lower().strip()
        inquiry_phrases = [
            "what do you have",
            "what kind do you have",
            "what kinds do you have",
            "what type do you have",
            "what types do you have",
            "what are my options",
            "what are the options",
            "what options",
            "options",
            "list them",
            "what choices",
            "what can i choose",
            "what can i get",
            "show me",
        ]
        if any(phrase in input_lower for phrase in inquiry_phrases):
            return True

        # Also catch "what kind of X do you have?" pattern
        # e.g., "what kind of bread do you have?", "what kinds of toppings do you have?"
        flexible_pattern = r"what\s+kind(s)?\s+of\s+\w+\s+do\s+you\s+have"
        if re.search(flexible_pattern, input_lower):
            return True

        return False

    def _is_show_more_request(self, user_input: str) -> bool:
        """Check if user is asking to see more options."""
        input_lower = user_input.lower().strip()
        show_more_phrases = [
            "what else",
            "any other",
            "more options",
            "other options",
            "what other",
            "anything else",
            "show more",
            "more",
            "next",
            "keep going",
            "continue",
            "different",
        ]
        return any(phrase in input_lower for phrase in show_more_phrases)

    def _get_options_page(
        self, options: list[dict], page: int, page_size: int = 5
    ) -> tuple[list[dict], bool]:
        """
        Get a page of options.

        Returns (page_options, has_more).
        """
        start_idx = page * page_size
        end_idx = start_idx + page_size
        page_options = options[start_idx:end_idx]
        has_more = end_idx < len(options)
        return page_options, has_more

    def _format_options_page(
        self, options: list[dict], is_first_page: bool, has_more: bool
    ) -> str:
        """Format a page of options for display."""
        names = [opt["display_name"] for opt in options]
        if len(names) == 0:
            return "That's all the options."
        if len(names) == 1:
            options_str = names[0]
        else:
            options_str = ", ".join(names[:-1]) + f", or {names[-1]}"

        if is_first_page:
            if has_more:
                return f"We have {options_str}, and more."
            else:
                return f"We have {options_str}."
        else:
            if has_more:
                return f"We also have {options_str}, and more."
            else:
                return f"We also have {options_str}."

    def _handle_options_inquiry(
        self,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
        is_show_more: bool = False,
    ) -> StateMachineResult:
        """Handle user asking about available options with pagination."""
        if is_show_more:
            # Increment page
            order.config_options_page += 1
        else:
            # Start from first page
            order.config_options_page = 1

        page = order.config_options_page - 1  # 0-indexed for slicing
        page_options, has_more = self._get_options_page(
            options, page, self.OPTIONS_PAGE_SIZE
        )

        if not page_options:
            # No more options
            order.config_options_page = 0  # Reset
            return StateMachineResult(
                message="That's all the options. Which would you like?",
                order=order,
            )

        is_first_page = (page == 0)
        message = self._format_options_page(page_options, is_first_page, has_more)

        return StateMachineResult(message=message, order=order)

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    def get_first_question(
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """
        Get the first configuration question for a menu item.

        Called when a new menu item is added and needs configuration.
        """
        item_type = item.menu_item_type
        if not item_type or not self.supports_item_type(item_type):
            # Not a supported item type, mark complete
            item.mark_complete()
            return self._get_next_question(order)

        # Find first unanswered mandatory attribute
        unanswered = self._get_unanswered_mandatory(item, item_type)
        if not unanswered:
            # No mandatory questions, go to checkpoint
            return self._ask_customization_checkpoint(item, order)

        first_attr = unanswered[0]
        # Reset options page for first question
        order.config_options_page = 0
        return self._ask_attribute_question(item, order, first_attr, is_first_question=True)

    def _ask_attribute_question(
        self, item: MenuItemTask, order: OrderTask, attr: dict,
        is_first_question: bool = False
    ) -> StateMachineResult:
        """
        Ask the question for a specific attribute.

        Does NOT list options by default - user must ask "what options?" to see them.
        For boolean attributes (like toasted), uses simple yes/no question.
        Uses DB's question_text if configured, otherwise generates a natural question.
        """
        input_type = attr.get("input_type", "single_select")
        attr_name = attr["display_name"].lower()

        # Use DB's question_text if available, otherwise generate a natural question
        db_question = attr.get("question_text")
        if db_question:
            question = db_question
        elif input_type == "boolean":
            # Simple yes/no question
            question = f"Would you like it {attr_name}?"
        else:
            # For select types, ask naturally without listing options
            question = f"What kind of {attr_name} would you like?"

        # Add acknowledgment for first question
        if is_first_question:
            question = f"Got it, {item.menu_item_name}. {question}"

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_id = item.id
        order.pending_field = f"menu_item_attr_{attr['slug']}"
        # Reset options page when asking a new attribute question
        order.config_options_page = 0

        return StateMachineResult(message=question, order=order)

    def _ask_customization_checkpoint(
        self, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Ask if user wants to customize with optional attributes."""
        item_type = item.menu_item_type
        unanswered_optional = self._get_unanswered_optional(item, item_type)

        if not unanswered_optional:
            # No optional attributes available, item is complete
            item.customization_offered = True
            item.mark_complete()
            order.phase = OrderPhase.TAKING_ITEMS.value
            order.clear_pending()
            return StateMachineResult(
                message=f"Got it, {item.get_summary()}. Anything else?",
                order=order,
            )

        # Mark that we've reached the checkpoint
        item.customization_offered = True

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_id = item.id
        order.pending_field = "customization_checkpoint"

        # List available customization options
        options_list = self._format_attributes_list(unanswered_optional)

        return StateMachineResult(
            message=f"Any more changes to that? You can change {options_list}.",
            order=order,
        )

    # =========================================================================
    # Handle User Input for Different States
    # =========================================================================

    def handle_attribute_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr_slug: str
    ) -> StateMachineResult:
        """Handle user input for a specific attribute question."""
        item_type = item.menu_item_type
        attrs = self._get_item_type_attributes(item_type)
        attr = attrs.get(attr_slug)

        if not attr:
            logger.warning("Attribute '%s' not found for %s", attr_slug, item_type)
            order.clear_pending()
            return self._get_next_question(order)

        options = attr.get("options", [])
        input_type = attr.get("input_type", "single_select")

        # Check for options inquiry / show-more BEFORE trying to match an answer
        # (Only for select types with options)
        if options and input_type in ("single_select", "multi_select"):
            # Check if user is asking for more options (pagination)
            if order.config_options_page > 0 and self._is_show_more_request(user_input):
                return self._handle_options_inquiry(item, order, attr, options, is_show_more=True)

            # Check if user is asking about available options
            if self._is_options_inquiry(user_input):
                return self._handle_options_inquiry(item, order, attr, options, is_show_more=False)

        # Reset options page when user provides an actual answer
        order.config_options_page = 0

        # Handle boolean attributes
        if input_type == "boolean":
            return self._handle_boolean_input(user_input, item, order, attr)

        # Handle single/multi select
        if input_type in ("single_select", "multi_select"):
            return self._handle_select_input(user_input, item, order, attr, options)

        # Default: store raw input
        item.attribute_values[attr_slug] = user_input.strip()
        return self._advance_to_next_question(item, order, attr)

    def _handle_boolean_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        """Handle yes/no input for boolean attributes."""
        user_lower = user_input.lower().strip()
        attr_slug = attr["slug"]

        # Check for explicit yes/no
        yes_patterns = ["yes", "yeah", "yep", "sure", "please", "ok", "okay"]
        no_patterns = ["no", "nope", "not", "skip", "none"]

        # Also check for the attribute name with/without "not"
        attr_name = attr["display_name"].lower()
        if f"not {attr_name}" in user_lower or f"un{attr_name}" in user_lower:
            item.attribute_values[attr_slug] = False
        elif any(p in user_lower for p in yes_patterns) or attr_name in user_lower:
            item.attribute_values[attr_slug] = True
        elif any(p in user_lower for p in no_patterns):
            item.attribute_values[attr_slug] = False
        else:
            # Couldn't parse, ask again
            question = attr.get("question_text") or f"{attr['display_name']}?"
            return StateMachineResult(
                message=f"Sorry, I didn't catch that. {question} (yes or no)",
                order=order,
            )

        return self._advance_to_next_question(item, order, attr)

    def _handle_select_input(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
        attr: dict,
        options: list[dict],
    ) -> StateMachineResult:
        """Handle single/multi select input."""
        attr_slug = attr["slug"]
        user_lower = user_input.lower().strip()
        input_type = attr.get("input_type", "single_select")

        # Extract quantity from input (e.g., "2 scrambled eggs" → quantity=2)
        quantity, _ = self._extract_quantity_from_input(user_input)

        # Check for "none" / "no" / "skip"
        if attr.get("allow_none", False):
            skip_patterns = ["no", "none", "skip", "nothing", "no thanks", "nope"]
            if any(user_lower == p or user_lower.startswith(p + " ") for p in skip_patterns):
                item.attribute_values[attr_slug] = None
                return self._advance_to_next_question(item, order, attr)

        # For multi_select, try to match ALL options in the input
        if input_type == "multi_select":
            matched_options = self._match_multiple_options_from_input(user_input, options)
            if matched_options:
                # Store as list of slugs
                existing = item.attribute_values.get(attr_slug)
                if isinstance(existing, list):
                    # Append to existing selections
                    slugs = existing
                else:
                    slugs = []

                # Store list of {slug, display_name, price, quantity} for each matched option
                selections = item.attribute_values.get(f"{attr_slug}_selections", [])
                if not isinstance(selections, list):
                    selections = []

                user_lower = user_input.lower()
                for opt in matched_options:
                    if opt["slug"] not in slugs:
                        slugs.append(opt["slug"])
                        # Extract qualifier (extra, light, on the side, etc.)
                        qualifier = self._extract_qualifier_for_option(user_input, opt["display_name"])
                        # Extract quantity specific to this option (e.g., "2 vanilla syrups")
                        opt_quantity = _extract_quantity(user_lower, opt["display_name"].lower())
                        if opt_quantity == 1:
                            # Also try with slug pattern
                            opt_quantity = _extract_quantity(user_lower, opt["slug"].replace("_", " "))
                        selection = {
                            "slug": opt["slug"],
                            "display_name": opt["display_name"],
                            "price": opt.get("price", 0),
                            "quantity": opt_quantity,
                        }
                        if qualifier:
                            selection["qualifier"] = qualifier
                        selections.append(selection)

                item.attribute_values[attr_slug] = slugs
                item.attribute_values[f"{attr_slug}_selections"] = selections

                # Build acknowledgment text with quantity and qualifier
                display_names = []
                for sel in selections:
                    name = sel["display_name"]
                    qual = sel.get("qualifier")
                    qty = sel.get("quantity", 1)
                    if qual:
                        name = f"{name} ({qual})"
                    if qty > 1:
                        name = f"{qty} {name}"
                    display_names.append(name)

                if len(display_names) == 1:
                    ack_text = display_names[0]
                elif len(display_names) == 2:
                    ack_text = f"{display_names[0]} and {display_names[1]}"
                else:
                    ack_text = ", ".join(display_names[:-1]) + f", and {display_names[-1]}"

                return self._advance_to_next_question(item, order, attr, ack_text)

        # For single_select (or if multi_select found nothing), use single-match logic
        matched, partial_matches = self._match_option_from_input(user_input, options)

        if matched:
            # Extract qualifier for single match
            qualifier = self._extract_qualifier_for_option(user_input, matched["display_name"])
            selection = {
                "slug": matched["slug"],
                "display_name": matched["display_name"],
                "price": matched.get("price", 0),
                "quantity": quantity,
            }
            if qualifier:
                selection["qualifier"] = qualifier

            if input_type == "multi_select":
                # Store as list even for single match in multi_select
                item.attribute_values[attr_slug] = [matched["slug"]]
                item.attribute_values[f"{attr_slug}_selections"] = [selection]
            else:
                # Single select - store slug and use _selections format to support quantity
                item.attribute_values[attr_slug] = matched["slug"]
                # Store price if applicable and update unit_price
                if matched.get("price", 0) > 0:
                    price_key = f"{attr_slug}_price"
                    item.attribute_values[price_key] = matched["price"]
                    # Update unit_price to include this modifier price
                    if item.unit_price is not None:
                        item.unit_price = item.unit_price + matched["price"]
                        logger.info(
                            "Updated unit_price for %s: added %s price %.2f, new total %.2f",
                            item.id, attr_slug, matched["price"], item.unit_price
                        )
                # Always use _selections format to support quantity
                item.attribute_values[f"{attr_slug}_selections"] = [selection]

            # Acknowledgment with quantity and qualifier
            ack_name = matched["display_name"]
            if qualifier:
                ack_name = f"{ack_name} ({qualifier})"
            ack_text = f"{quantity} {ack_name}" if quantity > 1 else ack_name
            return self._advance_to_next_question(item, order, attr, ack_text)

        # Multiple partial matches - ask for disambiguation with just those options
        if partial_matches:
            options_text = self._format_options_list(partial_matches)
            return StateMachineResult(
                message=f"I found a few options matching that. Did you mean {options_text}?",
                order=order,
            )

        # Check for category words (e.g., "milk", "sweetener", "syrup")
        # that indicate user wants a specific category but needs to specify which one
        category_result = self._check_category_match(user_lower, options, item, order, attr_slug)
        if category_result:
            return category_result

        # No match at all - ask again WITHOUT listing options
        attr_name = attr["display_name"].lower()
        return StateMachineResult(
            message=f"Sorry, I didn't catch that. What kind of {attr_name} would you like? You can ask 'what options?' to see choices.",
            order=order,
        )

    def _check_category_match(
        self,
        user_input: str,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr_slug: str,
    ) -> StateMachineResult | None:
        """
        Check if user input is a category word that matches options via must_match.

        Uses must_match to filter options:
        - Options with must_match set only match if input contains that phrase
        - Options without must_match (None) match any input containing the category

        For example, if user says "milk":
        - "Oat Milk" (must_match="oat milk") - doesn't match
        - "Whole Milk" (must_match=None) - matches (default milk option)

        Returns:
        - None if no category match or if exactly one option matches (let normal flow handle it)
        - StateMachineResult with clarification question if multiple options match
        """
        # Common category words that might appear in option names
        category_keywords = {
            "milk": "milk",
            "milks": "milk",
            "sweetener": "sweetener",
            "sweetners": "sweetener",
            "syrup": "syrup",
            "syrups": "syrup",
        }

        user_lower = user_input.lower().strip()

        # Check if user input matches a category
        if user_lower not in category_keywords:
            return None

        category = category_keywords[user_lower]
        display_category = user_lower.rstrip("s")  # Remove plural 's' for display

        # Find options in this category that pass must_match check
        # Options with must_match=None will pass (they're default options for that category)
        # Options with must_match set will only pass if input contains the phrase
        matching_options = []
        for opt in options:
            display_lower = opt["display_name"].lower()
            slug_lower = opt["slug"].lower()

            # Only consider options that belong to this category
            if category not in display_lower and category not in slug_lower:
                continue

            # Check if option passes must_match requirement
            if self._passes_must_match(user_input, opt):
                matching_options.append(opt)

        if not matching_options:
            # No options match - return None to let other handlers deal with it
            return None

        if len(matching_options) == 1:
            # Exactly one option matches - return None to let normal matching select it
            # The single matching option (e.g., Whole Milk for "milk") will be picked up
            # by the normal _match_option_from_input flow
            logger.info(
                "Category '%s' matched single option: %s",
                user_input, matching_options[0]["display_name"]
            )
            return None

        # Multiple options match - ask for clarification
        options_text = self._format_options_list(matching_options)

        # Stay in same pending state to handle the follow-up answer
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_id = item.id
        order.pending_field = f"menu_item_attr_{attr_slug}"

        logger.info(
            "Category match: user said '%s', found %d matching %s options",
            user_input, len(matching_options), display_category
        )

        return StateMachineResult(
            message=f"What kind of {display_category}? We have {options_text}.",
            order=order,
        )

    def _advance_to_next_question(
        self, item: MenuItemTask, order: OrderTask, current_attr: dict,
        matched_choice: str | None = None
    ) -> StateMachineResult:
        """Advance to the next question after answering current attribute.

        Args:
            item: The menu item being configured
            order: The current order
            current_attr: The attribute that was just answered
            matched_choice: The display name of the choice the user made (for acknowledgment)
        """
        item_type = item.menu_item_type

        # Check if we're in mandatory phase or optional phase
        if current_attr.get("ask_in_conversation", True):
            # Just answered a mandatory question, check for more
            unanswered_mandatory = self._get_unanswered_mandatory(item, item_type)
            if unanswered_mandatory:
                next_attr = unanswered_mandatory[0]
                return self._ask_attribute_question(item, order, next_attr)
            else:
                # All mandatory done, go to checkpoint
                return self._ask_customization_checkpoint(item, order)
        else:
            # Just answered an optional question, ask for more customizations
            return self._ask_more_customizations(item, order, matched_choice)

    def _ask_more_customizations(
        self, item: MenuItemTask, order: OrderTask, matched_choice: str | None = None
    ) -> StateMachineResult:
        """Ask if user wants more customizations after completing one.

        Args:
            item: The menu item being configured
            order: The current order
            matched_choice: The display name of the choice just made (for acknowledgment)
        """
        item_type = item.menu_item_type
        unanswered = self._get_unanswered_optional(item, item_type)

        # Build acknowledgment prefix if we have a choice to acknowledge
        ack_prefix = f"Okay, {matched_choice}. " if matched_choice else ""

        if not unanswered:
            # No more options, complete the item
            item.mark_complete()
            order.phase = OrderPhase.TAKING_ITEMS.value
            order.clear_pending()
            return StateMachineResult(
                message=f"{ack_prefix}Got it, {item.get_summary()}. Anything else?",
                order=order,
            )

        # List remaining options
        options_list = self._format_attributes_list(unanswered)

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_id = item.id
        order.pending_field = "customization_checkpoint"

        return StateMachineResult(
            message=f"{ack_prefix}Any more changes to that? You can change {options_list}.",
            order=order,
        )

    def handle_customization_checkpoint(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle user response to customization checkpoint."""
        user_lower = user_input.lower().strip()
        item_type = item.menu_item_type

        # Check for "no" - user doesn't want to customize
        no_patterns = [
            "no", "nope", "no thanks", "that's it", "that's all",
            "i'm good", "im good", "all set", "done", "nothing"
        ]
        if any(user_lower == p or user_lower.startswith(p) for p in no_patterns):
            item.mark_complete()
            order.phase = OrderPhase.TAKING_ITEMS.value
            order.clear_pending()
            return StateMachineResult(
                message=f"Got it, {item.get_summary()}. Anything else?",
                order=order,
            )

        unanswered = self._get_unanswered_optional(item, item_type)

        # Check for "yes" - user wants to see the list
        yes_patterns = ["yes", "yeah", "yep", "sure", "ok", "okay", "please"]
        if any(user_lower == p or user_lower.startswith(p + " ") for p in yes_patterns):
            # If just "yes", list the options
            if user_lower in yes_patterns:
                options_list = self._format_attributes_list(unanswered)
                order.pending_field = "customization_selection"
                return StateMachineResult(
                    message=f"You can add: {options_list}. What would you like?",
                    order=order,
                )

        # Try to match specific attribute(s) from input
        matched_attrs = self._match_attribute_from_input(user_input, unanswered)

        if matched_attrs:
            # User specified one or more attributes
            if len(matched_attrs) == 1:
                # Single attribute, ask for its options
                attr = matched_attrs[0]
                return self._ask_optional_attribute(item, order, attr)
            else:
                # Multiple attributes mentioned - configure first one
                # Store the rest in a queue (or just handle first for now)
                attr = matched_attrs[0]
                return self._ask_optional_attribute(item, order, attr)

        # Try to match option values directly (e.g., "add a little mayo" -> mayo in condiments)
        # This allows users to specify options without naming the attribute
        result = self._try_direct_option_match(user_input, unanswered, item, order)
        if result:
            return result

        # Couldn't understand, list options again
        options_list = self._format_attributes_list(unanswered)
        return StateMachineResult(
            message=f"Sorry, I didn't catch that. You can add: {options_list}. What would you like?",
            order=order,
        )

    def handle_customization_selection(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle user selecting which attribute to customize from the list."""
        # This is essentially the same as checkpoint handling
        return self.handle_customization_checkpoint(user_input, item, order)

    def _ask_optional_attribute(
        self, item: MenuItemTask, order: OrderTask, attr: dict
    ) -> StateMachineResult:
        """Ask the question for a specific optional attribute."""
        options = attr.get("options", [])

        if attr.get("input_type") == "boolean":
            # For boolean, just confirm
            question = attr.get("question_text") or f"{attr['display_name']}?"
        elif options:
            options_text = self._format_options_list(options)
            question = f"What kind of {attr['display_name'].lower()}? ({options_text})"
        else:
            question = attr.get("question_text") or f"What {attr['display_name']}?"

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_id = item.id
        order.pending_field = f"menu_item_attr_{attr['slug']}"

        return StateMachineResult(message=question, order=order)

    def _try_direct_option_match(
        self,
        user_input: str,
        unanswered: list[dict],
        item: MenuItemTask,
        order: OrderTask,
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
            options = attr.get("options", [])
            if not options:
                continue

            input_type = attr.get("input_type", "single_select")
            attr_slug = attr["slug"]

            if input_type == "multi_select":
                # For multi_select, try to match multiple options
                matched = self._match_multiple_options_from_input(user_clean, options)
                if matched:
                    # Build list with qualifiers and quantities
                    added_values = []
                    display_parts = []
                    selections = item.attribute_values.get(f"{attr_slug}_selections", [])
                    if not isinstance(selections, list):
                        selections = []

                    user_lower = user_input.lower()
                    for opt in matched:
                        opt_name = opt["display_name"]
                        qualifier = self._extract_qualifier_for_option(user_input, opt_name)
                        # Extract quantity for this specific option
                        opt_quantity = _extract_quantity(user_lower, opt_name.lower())
                        if opt_quantity == 1:
                            opt_quantity = _extract_quantity(user_lower, opt["slug"].replace("_", " "))

                        if qualifier:
                            value = f"{opt['slug']}_{qualifier}"
                            display = f"{opt_name} ({qualifier})"
                        else:
                            value = opt["slug"]
                            display = opt_name

                        if opt_quantity > 1:
                            display = f"{opt_quantity} {display}"

                        display_parts.append(display)
                        added_values.append(value)

                        # Store selection metadata
                        selection = {
                            "slug": opt["slug"],
                            "display_name": opt_name,
                            "price": opt.get("price", 0),
                            "quantity": opt_quantity,
                        }
                        if qualifier:
                            selection["qualifier"] = qualifier
                        selections.append(selection)

                    # Add to existing values for this attribute
                    existing = item.attribute_values.get(attr_slug, [])
                    if isinstance(existing, list):
                        for val in added_values:
                            if val not in existing:
                                existing.append(val)
                        item.attribute_values[attr_slug] = existing
                    else:
                        item.attribute_values[attr_slug] = added_values

                    # Store selections metadata with quantities
                    item.attribute_values[f"{attr_slug}_selections"] = selections

                    logger.info(
                        "Direct option match: added %s to %s (item %s)",
                        added_values, attr_slug, item.id
                    )

                    # Confirm and stay at checkpoint for more customizations
                    display_text = ", ".join(display_parts)
                    order.pending_field = "customization_checkpoint"
                    return StateMachineResult(
                        message=f"Okay, {display_text} added. Anything else to customize?",
                        order=order,
                    )
            else:
                # For single_select, match one option
                matched_opt, _ = self._match_option_from_input(user_clean, options)
                if matched_opt:
                    opt_name = matched_opt["display_name"]
                    qualifier = self._extract_qualifier_for_option(user_input, opt_name)
                    if qualifier:
                        value = f"{matched_opt['slug']}_{qualifier}"
                        display = f"{opt_name} ({qualifier})"
                    else:
                        value = matched_opt["slug"]
                        display = opt_name

                    item.attribute_values[attr_slug] = value
                    logger.info(
                        "Direct option match: set %s = %s (item %s)",
                        attr_slug, value, item.id
                    )

                    order.pending_field = "customization_checkpoint"
                    return StateMachineResult(
                        message=f"Okay, {display} added. Anything else to customize?",
                        order=order,
                    )

        return None

    # =========================================================================
    # Proactive Attribute Capture
    # =========================================================================

    def capture_attributes_from_input(
        self, user_input: str, item: MenuItemTask
    ) -> None:
        """
        Capture any attributes mentioned in the initial order input.

        Called when item is first created to pre-fill attributes.
        e.g., "deli sandwich with scrambled egg on a plain bagel toasted"
        """
        item_type = item.menu_item_type
        if not item_type or not self.supports_item_type(item_type):
            return

        attrs = self._get_item_type_attributes(item_type)
        user_lower = user_input.lower()

        for attr_slug, attr in attrs.items():
            # Skip if already answered
            if attr_slug in item.attribute_values:
                continue

            options = attr.get("options", [])
            input_type = attr.get("input_type", "single_select")

            if input_type == "boolean":
                # Check for explicit mentions
                attr_name = attr["display_name"].lower()
                if f"not {attr_name}" in user_lower:
                    item.attribute_values[attr_slug] = False
                    logger.info("Captured %s=False from input", attr_slug)
                elif attr_name in user_lower:
                    item.attribute_values[attr_slug] = True
                    logger.info("Captured %s=True from input", attr_slug)

            elif input_type in ("single_select", "multi_select") and options:
                # For cheese-related attributes, mask out "cream cheese" patterns to prevent
                # "Strawberry Cream Cheese Sandwich" from matching American Cheese's
                # "cheese" alias. The word "cheese" in "cream cheese" is not sliced cheese.
                input_for_matching = user_input
                if attr_slug in ("cheese", "extra_cheese"):
                    # Mask common cream cheese patterns
                    input_for_matching = re.sub(
                        r'\b\w*\s*cream\s+cheese\b', '___SPREAD___', user_input, flags=re.IGNORECASE
                    )

                # Only capture if we get a unique match (ignore disambiguation cases)
                matched, _ = self._match_option_from_input(input_for_matching, options)
                if matched:
                    item.attribute_values[attr_slug] = matched["slug"]
                    if matched.get("price", 0) > 0:
                        item.attribute_values[f"{attr_slug}_price"] = matched["price"]
                    logger.info("Captured %s=%s from input", attr_slug, matched["slug"])
