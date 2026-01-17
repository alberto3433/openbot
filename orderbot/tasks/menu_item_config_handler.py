"""
Menu Item Configuration Handler for Order State Machine.

This module handles the configuration of menu items (like deli sandwiches)
with DB-driven attributes. It supports:
- Mandatory attributes (ask_in_conversation=True) asked in sequence
- Customization checkpoint after mandatory attributes
- Optional attributes (ask_in_conversation=False) offered in a loop
- Modifier extraction during configuration (proteins, cheeses, toppings, etc.)

Designed to be generic and work with any item type that has DB-defined attributes.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache, singularize
from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase, ExtractedModifiers
from .parsers.constants import extract_quantity, DEFAULT_PAGINATION_SIZE
from .parsers import extract_attribute_values
from .handler_config import BaseHandler

logger = logging.getLogger(__name__)


class MenuItemConfigHandler(BaseHandler):
    """
    Handles menu item configuration with DB-driven attributes.

    Reads item type attributes from the database to determine:
    - Which questions to ask (ask_in_conversation=True for mandatory)
    - What the question text should be (question_text field)
    - What options are valid (attribute_options or item_type_ingredients)
    """

    # Note: SUPPORTED_ITEM_TYPES is now queried from the database via menu_cache.
    # Item types are configurable if they have linked attributes in the DB.
    #
    # NOTE: All legacy attribute aliases have been eliminated:
    # - Parsers now use canonical keys (bread, spread_type, etc.)
    # - Properties (toasted, scooped, decaf, spread) now use attribute_values as backing store
    # - milk_sweetener_syrup uses unified storage with milk_sweetener_syrup_selections

    # Note: MODIFIER_EXTRACTION_TYPE is now stored in the item_type_categories table
    # and queried via menu_cache.get_modifier_category(item_type_slug).
    # Values: "food" (proteins, cheeses, toppings) or "beverage" (milk, sweetener, syrup)

    def __init__(self, config: "HandlerConfig"):
        """
        Initialize the menu item config handler.

        Args:
            config: HandlerConfig with shared dependencies.
        """
        super().__init__(config)
        # Note: Item type attributes are cached in menu_cache (single source of truth)

    def supports_item_type(self, item_type_slug: str | None) -> bool:
        """Check if this handler supports the given item type.

        An item type is supported if it has linked attributes in the database.
        """
        if not item_type_slug:
            return False
        return item_type_slug in menu_cache.get_configurable_item_types()

    def _set_legacy_field_if_applicable(
        self,
        item: "MenuItemTask",
        attr_slug: str,
        display_value: str | None,
        slug_value: str | None = None,
    ) -> None:
        """No-op - legacy field syncing is no longer needed.

        All properties (bread, spread, toasted, scooped, decaf) now use
        attribute_values as their backing store, so setting attribute_values
        automatically makes the properties return the correct values.
        """
        # No-op: Properties now use attribute_values as backing store
        pass

    def _get_item_type_attributes(self, item_type_slug: str) -> dict:
        """
        Get item type attributes from centralized cache.

        Uses menu_cache as the single source of truth for all item type
        attributes (both item-type-specific and global attributes).

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
        return menu_cache.get_item_type_attributes(item_type_slug)

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
        """Get mandatory attributes that haven't been answered yet.

        Checks both canonical attribute slugs and legacy aliases to handle
        backward compatibility with items created by legacy handlers.
        Also checks direct model fields for certain attributes.
        """
        mandatory = self._get_mandatory_attributes(item_type_slug)
        unanswered = []
        logger.info(
            "GET_UNANSWERED_MANDATORY: item_type=%s, attribute_values=%s",
            item_type_slug, item.attribute_values
        )
        for attr in mandatory:
            slug = attr["slug"]
            # Check canonical slug in attribute_values
            # All properties (bread, toasted, etc.) now use attribute_values as backing store
            if slug in item.attribute_values:
                logger.debug("  %s: FOUND in attribute_values", slug)
                continue
            logger.debug("  %s: NOT FOUND - adding to unanswered", slug)
            unanswered.append(attr)
        logger.info(
            "GET_UNANSWERED_MANDATORY result: %s",
            [a["slug"] for a in unanswered]
        )
        return unanswered

    def _get_unanswered_optional(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get optional attributes that haven't been answered yet.

        Checks canonical attribute slugs in attribute_values.
        All properties (bread, toasted, etc.) now use attribute_values as backing store.
        """
        optional = self._get_optional_attributes(item_type_slug)
        unanswered = []
        for attr in optional:
            slug = attr["slug"]
            # Check canonical slug in attribute_values
            if slug in item.attribute_values:
                continue
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
        - Shot quantities: "two shots" → "double", "3 shots" → "triple"
        - Leading quantities: "2 scrambled eggs" → "scrambled eggs"
        - Plural forms: "scrambled eggs" → "scrambled egg"
        """
        text = text.lower().strip()

        # Normalize numeric shot quantities to words
        # "1" → "single", "2" → "double", etc.
        SHOT_NORMALIZATIONS = {
            "1": "single", "one": "single",
            "2": "double", "two": "double",
            "3": "triple", "three": "triple",
            "4": "quad", "four": "quad",
        }

        # Handle "X shot(s)" pattern FIRST before stripping quantities:
        # "two shots" → "double", "3 shots" → "triple", "one shot" → "single"
        shot_pattern = re.match(r'^(\w+)\s+shots?$', text)
        if shot_pattern:
            num_word = shot_pattern.group(1)
            if num_word in SHOT_NORMALIZATIONS:
                return SHOT_NORMALIZATIONS[num_word]

        # Strip leading quantity patterns (numbers like "2", "2x", words like "two")
        text = re.sub(r'^(\d+x?\s+)', '', text)  # "2 ", "2x ", "10 "
        text = re.sub(r'^(one|two|three|four|five|six|seven|eight|nine|ten)\s+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^(a|an)\s+', '', text)  # "a scrambled egg", "an egg"

        # Normalize plurals to singular for matching using generic singularize function
        # "eggs" → "egg", "bagels" → "bagel", "syrups" → "syrup", etc.
        words = text.split()
        text = " ".join(singularize(word) for word in words)

        # Also handle exact matches: "two" → "double", "3" → "triple"
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

    def _tokenize_multi_input(self, user_input: str) -> list[str]:
        """
        Tokenize compound input into individual items.

        E.g., "milk and sugar" -> ["milk", "sugar"]
              "bacon, cheese, tomato" -> ["bacon", "cheese", "tomato"]
              "oat milk and vanilla syrup" -> ["oat milk", "vanilla syrup"]
        """
        import re
        # Split on common separators, preserving multi-word items
        # Order matters: check longer patterns first
        separators = [
            r'\s+and\s+',      # " and "
            r'\s*,\s*',        # ", " or ","
            r'\s+&\s+',        # " & "
            r'\s+with\s+',     # " with "
            r'\s+plus\s+',     # " plus "
        ]
        pattern = '|'.join(separators)
        tokens = re.split(pattern, user_input, flags=re.IGNORECASE)
        # Clean up tokens
        return [t.strip() for t in tokens if t.strip()]

    def _match_multiple_options_from_input(
        self, user_input: str, options: list[dict]
    ) -> list[dict]:
        """
        Match ALL options mentioned in user input (for multi_select attributes).

        Returns list of matched options (may be empty if none found).
        Unlike _match_option_from_input, this finds ALL matches, not just one.

        E.g., "milk and sugar" -> [whole_milk_option, sugar_option]
              "mayo mustard" -> [mayo_option, mustard_option]

        Supports tokenized input: splits on "and", ",", "&", etc. to match
        multiple items like "milk and sugar" -> ["milk", "sugar"].

        Matching is bidirectional:
        1. Option name in user input (e.g., "sugar" in "milk and sugar")
        2. User token in option name (e.g., "milk" in "whole milk")

        Note: Options with must_match are only matched if user input contains at least
        one of the must_match strings.
        """
        # Normalize input to handle quantities and plurals
        user_lower = self._normalize_for_matching(user_input)
        matched = []
        matched_slugs = set()  # Track slugs to avoid duplicates

        def get_aliases(opt: dict) -> list[str]:
            aliases_raw = opt.get("aliases", [])
            if isinstance(aliases_raw, str):
                # Support both pipe-separated (DB format) and comma-separated aliases
                if "|" in aliases_raw:
                    return [a.strip() for a in aliases_raw.split("|") if a.strip()]
                return [a.strip() for a in aliases_raw.split(",") if a.strip()]
            return aliases_raw or []

        def add_match(opt: dict) -> bool:
            """Add option to matches if not already present. Returns True if added."""
            if opt["slug"] not in matched_slugs:
                matched_slugs.add(opt["slug"])
                matched.append(opt)
                return True
            return False

        # Tokenize input for compound inputs like "milk and sugar"
        tokens = self._tokenize_multi_input(user_input)
        # Also include the full input for single-item matching
        all_inputs = [user_lower] + [self._normalize_for_matching(t) for t in tokens if t.lower() != user_lower]

        # Log which options have must_match for debugging
        opts_with_must_match = [
            (o.get("display_name"), o.get("must_match"))
            for o in options if o.get("must_match")
        ]
        if opts_with_must_match:
            logger.info(
                "MULTI_SELECT OPTIONS with must_match: %s",
                opts_with_must_match
            )
        else:
            logger.info(
                "MULTI_SELECT OPTIONS: none have must_match (total %d options)",
                len(options)
            )

        for opt in options:
            if not self._passes_must_match(user_input, opt):
                logger.debug(
                    "MULTI_SELECT SKIP: '%s' filtered by must_match=%s for option '%s'",
                    user_input, opt.get("must_match"), opt.get("display_name")
                )
                continue  # Skip options that don't pass must_match

            display_lower = opt["display_name"].lower()
            slug_readable = opt["slug"].replace("_", " ")

            # === Direction 1: Option name/alias appears in user input ===
            # E.g., "sugar" (option) in "milk and sugar" (input)
            if self._is_whole_word_match(display_lower, user_lower):
                add_match(opt)
                continue
            if self._is_whole_word_match(slug_readable, user_lower):
                add_match(opt)
                continue

            # Check aliases in user input
            alias_matched = False
            for alias in get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 2 and self._is_whole_word_match(alias_lower, user_lower):
                    add_match(opt)
                    alias_matched = True
                    break
            if alias_matched:
                continue

            # === Direction 2: User token appears in option name ===
            # E.g., "milk" (token) in "whole milk" (option)
            # This handles cases like "milk" matching "Whole Milk"
            for token in all_inputs:
                if not token or len(token) < 2:
                    continue
                # Check if token is in display name
                if self._is_whole_word_match(token, display_lower):
                    add_match(opt)
                    break
                # Check if token is in slug
                if self._is_whole_word_match(token, slug_readable):
                    add_match(opt)
                    break
                # Check if token matches an alias
                for alias in get_aliases(opt):
                    alias_lower = alias.lower()
                    if len(alias_lower) >= 2 and self._is_whole_word_match(token, alias_lower):
                        add_match(opt)
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
                logger.debug(
                    "MUST_MATCH PASSED: '%s' contains '%s' for option '%s'",
                    user_input, must_str, opt.get("display_name")
                )
                return True

        logger.debug(
            "MUST_MATCH FAILED: '%s' does not contain any of %s for option '%s'",
            user_input, must_match_list, opt.get("display_name")
        )
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

    def _is_options_inquiry(self, user_input: str, topic: str | None = None) -> bool:
        """Check if user is asking about available options.

        Args:
            user_input: The user's input text
            topic: Optional topic word (e.g., "bread", "cheese") to check for
                   context-specific patterns like "what bread do you have"
        """
        input_lower = user_input.lower().strip()

        # Generic option inquiry phrases (always match)
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

        # Context-aware patterns: check if user is asking about the specific topic
        # e.g., "what bread do you have" when we're asking about bread
        if topic:
            topic_lower = topic.lower().strip()
            # Handle plural forms (bread -> breads)
            topic_plural = topic_lower + "s" if not topic_lower.endswith("s") else topic_lower

            # Build patterns for this specific topic
            # "what bread do you have", "what breads do you have"
            # "what bread options", "what breads are there"
            # "what types of bread", "what kinds of bread"
            # "which bread", "which breads"
            topic_patterns = [
                # "what bread do you have" / "what breads do you have"
                rf"what\s+{re.escape(topic_lower)}s?\s+do\s+you\s+have",
                rf"what\s+{re.escape(topic_lower)}s?\s+(?:are\s+there|have\s+you\s+got|you\s+got)",
                # "what types/kinds of bread"
                rf"what\s+(?:types?|kinds?)\s+of\s+{re.escape(topic_lower)}",
                # "what bread options" / "bread options"
                rf"(?:what\s+)?{re.escape(topic_lower)}s?\s+(?:options?|choices?)",
                # "which bread" / "which breads"
                rf"which\s+{re.escape(topic_lower)}s?",
                # "any bread options" / "any breads"
                rf"(?:any|some)\s+{re.escape(topic_lower)}s?(?:\s+options?)?",
            ]

            for pattern in topic_patterns:
                if re.search(pattern, input_lower):
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
            options, page, DEFAULT_PAGINATION_SIZE
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
            # Not a supported item type, recalculate price and mark complete
            self._recalculate_item_price(item)
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
        order.pending_field = f"{item.menu_item_type}:{attr['slug']}"
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
            # No optional attributes available, recalculate price and complete
            item.customization_offered = True
            self._recalculate_item_price(item)
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
    # Modifier Extraction During Configuration
    # =========================================================================

    def _extract_modifiers_from_input(
        self, user_input: str, item_type: str
    ) -> ExtractedModifiers | None:
        """
        Extract modifiers from user input based on item type.

        Uses the generic data-driven extract_attribute_values() function which
        queries the database for what attributes the item type accepts and
        extracts matching values from the input.

        Args:
            user_input: Raw user input string
            item_type: The item type slug (e.g., "deli_sandwich", "espresso")

        Returns:
            ExtractedModifiers with category-based storage, or None if no modifiers found
        """
        # Use generic data-driven extraction
        attr_values = extract_attribute_values(user_input, item_type)

        if not attr_values:
            return None

        # Convert flat dict to ExtractedModifiers for backward compatibility
        modifiers = ExtractedModifiers()

        for attr_slug, value in attr_values.items():
            if attr_slug == "special_instructions":
                # Special instructions are a list of strings
                if isinstance(value, list):
                    modifiers.special_instructions = value
                continue

            if isinstance(value, list):
                # Multi-select attribute: list of {slug, quantity, display_name, ...}
                for item in value:
                    if isinstance(item, dict):
                        slug = item.get("slug", "")
                        quantity = item.get("quantity", 1)
                        category = item.get("category") or attr_slug
                        if slug:
                            modifiers.add(category, slug, quantity)
            elif isinstance(value, bool):
                # Boolean attribute - store as single-value category
                if value:
                    modifiers.add(attr_slug, "yes", 1)
            elif isinstance(value, str):
                # Single-select attribute: just the slug
                modifiers.add(attr_slug, value, 1)

        if modifiers.has_modifiers() or modifiers.has_special_instructions():
            logger.debug("Extracted modifiers from input: %s", modifiers)
            return modifiers

        return None

    def _apply_extracted_modifiers(
        self, item: MenuItemTask, modifiers: ExtractedModifiers
    ) -> str | None:
        """
        Apply extracted modifiers to a menu item in a data-driven way.

        Iterates through all categories in the extracted modifiers and applies
        them generically using the item's add_modifier() method. Prices are
        looked up from the pricing engine.

        Args:
            item: The menu item to apply modifiers to
            modifiers: Extracted modifiers from user input

        Returns:
            Acknowledgment string if modifiers were applied, None otherwise
        """
        added_items = []
        item_type = item.menu_item_type

        # Get all categories that have modifiers
        for category in modifiers.get_categories():
            category_modifiers = modifiers.get_all(category)

            for mod in category_modifiers:
                # Look up price from pricing engine
                price = 0.0
                if self.pricing and item_type:
                    price = self.pricing.lookup_generic_modifier_price(
                        mod.slug, item_type, category
                    ) or 0.0

                # Use generic add_modifier for unified storage
                item.add_modifier(category, mod.slug, mod.quantity, price)

                # Build display name for acknowledgment
                if category == "syrup":
                    added_items.append(f"{mod.slug} syrup")
                else:
                    added_items.append(mod.slug)

        # Handle categories needing clarification (e.g., "cheese" without type)
        for category, needs_clarification in modifiers.needs_clarification.items():
            if needs_clarification:
                item.attribute_values[f"needs_{category}_clarification"] = True

        # Special instructions
        if modifiers.has_special_instructions():
            existing = item.special_instructions or ""
            new_instr = modifiers.get_special_instructions_string()
            item.special_instructions = f"{existing}, {new_instr}".strip(", ") if existing else new_instr

        # Build acknowledgment string
        if not added_items:
            return None

        if len(added_items) == 1:
            return f"I've added {added_items[0]}. "
        else:
            items_str = ", ".join(added_items[:-1]) + f" and {added_items[-1]}"
            return f"I've added {items_str}. "

    def _extract_and_apply_modifiers(
        self, user_input: str, item: MenuItemTask
    ) -> str | None:
        """
        Extract modifiers from user input and apply them to the item.

        This is a convenience method that combines extraction and application.
        Call this after successfully handling an attribute input to capture
        any additional modifiers mentioned with the answer.

        Args:
            user_input: Raw user input string
            item: The menu item to apply modifiers to

        Returns:
            Acknowledgment string if modifiers were applied, None otherwise
        """
        item_type = item.menu_item_type
        if not item_type:
            return None

        modifiers = self._extract_modifiers_from_input(user_input, item_type)
        if modifiers:
            logger.info("Applying extracted modifiers to %s: %s", item.menu_item_name, modifiers)
            return self._apply_extracted_modifiers(item, modifiers)

        return None

    # =========================================================================
    # Pricing Abstraction
    # =========================================================================

    def _recalculate_item_price(self, item: MenuItemTask) -> float:
        """
        Recalculate and update an item's price based on its current state.

        This method provides a generic price recalculation that works with any
        item type. It delegates to PricingEngine.recalculate_item_price when
        available (which routes to specialized methods for bagels/beverages).
        Falls back to local calculation for items without specialized pricing.

        Args:
            item: The menu item to recalculate price for

        Returns:
            The new calculated price
        """
        # Use unified pricing method when available
        if self.pricing:
            return self.pricing.recalculate_item_price(item)

        # Fallback: generic pricing for DB-driven item types
        return self._calculate_generic_item_price(item)

    def _calculate_generic_item_price(self, item: MenuItemTask) -> float:
        """
        Calculate price for a generic DB-driven item type.

        Sums the base price (from menu item) plus all attribute selection prices
        stored in attribute_values[*_selections].

        Args:
            item: The menu item to calculate price for

        Returns:
            The calculated total price
        """
        # Get base price from menu item data
        base_price = self._get_item_base_price(item)
        total = base_price

        # Sum up prices from attribute selections
        for key, value in item.attribute_values.items():
            if key.endswith("_selections") and isinstance(value, list):
                for sel in value:
                    if isinstance(sel, dict):
                        price = sel.get("price", 0) or 0
                        qty = sel.get("quantity", 1) or 1
                        total += price * qty

        # Round and update
        new_price = round(total, 2)
        item.unit_price = new_price

        logger.info(
            "Recalculated generic item price for %s (%s): base=$%.2f + selections -> total=$%.2f",
            item.menu_item_name, item.menu_item_type, base_price, new_price
        )

        return new_price

    def _get_item_base_price(self, item: MenuItemTask) -> float:
        """
        Get the base price for an item from menu data.

        Looks up the menu item by ID or name to find its base price.
        Falls back to calculating from current price minus known selections.

        Args:
            item: The menu item to get base price for

        Returns:
            The base price (before any modifier upcharges)
        """
        # Try to look up from menu item data
        if hasattr(item, 'menu_item_id') and item.menu_item_id:
            menu_index = menu_cache.get_menu_index()
            if menu_index:
                # Search through all categories for the menu item
                for category_data in menu_index.get("categories", {}).values():
                    for mi in category_data.get("items", []):
                        if mi.get("id") == item.menu_item_id:
                            return float(mi.get("base_price", 0))

        # Try by name lookup
        if hasattr(item, 'menu_item_name') and item.menu_item_name:
            menu_index = menu_cache.get_menu_index()
            if menu_index:
                for category_data in menu_index.get("categories", {}).values():
                    for mi in category_data.get("items", []):
                        if mi.get("name", "").lower() == item.menu_item_name.lower():
                            return float(mi.get("base_price", 0))

        # Fallback: calculate from current price minus selections
        if item.unit_price:
            selections_total = 0.0
            for key, value in item.attribute_values.items():
                if key.endswith("_selections") and isinstance(value, list):
                    for sel in value:
                        if isinstance(sel, dict):
                            price = sel.get("price", 0) or 0
                            qty = sel.get("quantity", 1) or 1
                            selections_total += price * qty
            return max(0.0, item.unit_price - selections_total)

        return 0.0

    # =========================================================================
    # Multi-Item Orchestration
    # =========================================================================

    def configure_next_incomplete_item(
        self, order: OrderTask, item_type: str | None = None
    ) -> StateMachineResult:
        """
        Find and configure the next incomplete menu item of supported types.

        This method provides multi-item orchestration similar to bagel/coffee handlers.
        It iterates through items, asks required questions, and tracks progress.

        Args:
            order: The order task containing all items
            item_type: Optional specific item type to configure. If None,
                      configures all supported item types.

        Returns:
            StateMachineResult with next question or completion message
        """
        from .models import TaskStatus
        from .message_builder import MessageBuilder

        # Determine which item types to process
        # Get configurable item types from database (item types with linked attributes)
        configurable_types = menu_cache.get_configurable_item_types()
        if item_type:
            target_types = {item_type} & configurable_types
        else:
            target_types = configurable_types

        if not target_types:
            # No supported types to configure
            return self._get_next_question(order)

        # Collect all items of the target types
        target_items = [
            item for item in order.items.items
            if isinstance(item, MenuItemTask)
            and item.menu_item_type in target_types
        ]

        if not target_items:
            return self._get_next_question(order)

        # Group items by type for ordinal messaging
        items_by_type: dict[str, list[MenuItemTask]] = {}
        for item in target_items:
            t = item.menu_item_type
            if t not in items_by_type:
                items_by_type[t] = []
            items_by_type[t].append(item)

        # Process each incomplete item
        for item in target_items:
            if item.status != TaskStatus.IN_PROGRESS:
                continue

            item_type_slug = item.menu_item_type
            same_type_items = items_by_type.get(item_type_slug, [item])
            same_type_count = len(same_type_items)

            # Build ordinal descriptor if multiple items of same type
            if same_type_count > 1:
                item_num = next(
                    (i + 1 for i, it in enumerate(same_type_items) if it.id == item.id),
                    1
                )
                ordinal = MessageBuilder.get_ordinal(item_num)
                item_desc = f"the {ordinal} {item.menu_item_name}"
            else:
                item_desc = f"your {item.menu_item_name}"

            # Get unanswered mandatory attributes
            unanswered = self._get_unanswered_mandatory(item, item_type_slug)

            if unanswered:
                # Ask the first unanswered mandatory question
                first_attr = unanswered[0]
                order.phase = OrderPhase.CONFIGURING_ITEM.value
                order.pending_item_id = item.id
                order.pending_field = f"{item_type_slug}:{first_attr['slug']}"
                order.config_options_page = 0

                # Get question text
                db_question = first_attr.get("question_text")
                attr_name = first_attr["display_name"].lower()
                if db_question:
                    question = db_question
                elif first_attr.get("input_type") == "boolean":
                    question = f"Would you like it {attr_name}?"
                else:
                    question = f"What kind of {attr_name} would you like?"

                # Add ordinal prefix for multi-item
                if same_type_count > 1:
                    message = f"For {item_desc}, {question.lower()}"
                else:
                    message = question

                return StateMachineResult(message=message, order=order)

            # No mandatory questions left - check if customization was offered
            if not item.customization_offered:
                return self._ask_customization_checkpoint(item, order)

            # Item is complete - recalculate price and mark complete
            self._recalculate_item_price(item)
            item.mark_complete()

        # All target items are complete - summarize and return
        completed_items = [
            item for item in target_items
            if item.status == TaskStatus.COMPLETE
        ]

        if completed_items:
            last_item = completed_items[-1]
            summary = last_item.get_summary()

            # Count identical items at the end for pluralization
            count = 0
            for item in reversed(completed_items):
                if item.get_summary() == summary:
                    count += 1
                else:
                    break

            if count > 1:
                summary = f"{count} {summary}s" if not summary.endswith("s") else f"{count} {summary}"

            order.clear_pending()
            order.phase = OrderPhase.TAKING_ITEMS.value

            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                order=order,
            )

        # Fallback to generic next question
        return self._get_next_question(order)

    # =========================================================================
    # Disambiguation Resolution
    # =========================================================================

    def _resolve_disambiguation(
        self,
        user_input: str,
        options: list[dict],
    ) -> dict | None:
        """
        Resolve user's selection from disambiguation options using STRICT matching.

        This is used when we've asked "Did you mean X or Y?" and need to match
        the user's response to one of the specific options. We use exact matching
        to avoid "ham" matching "Black Forest Ham".

        Args:
            user_input: User's response (e.g., "ham", "black forest ham", "first", "1")
            options: List of option dicts with display_name and slug fields

        Returns:
            Selected option dict if matched, None if no match found.
        """
        input_lower = user_input.lower().strip()

        # Remove common filler words
        input_lower = input_lower.replace("the ", "").strip()
        input_lower = input_lower.replace("please", "").strip()
        input_lower = input_lower.replace("i want ", "").strip()
        input_lower = input_lower.replace("i'll take ", "").strip()
        input_lower = input_lower.replace("just ", "").strip()

        # Handle ordinal selections FIRST ("first one", "second one", "1", "2")
        # This allows quick selection by position
        ordinal_map = {
            "first": 0, "1": 0,
            "second": 1, "2": 1,
            "third": 2, "3": 2,
            "fourth": 3, "4": 3,
        }
        for word, index in ordinal_map.items():
            if input_lower == word or input_lower == f"{word} one":
                if index < len(options):
                    return options[index]

        # Try EXACT match on display_name (case-insensitive)
        # "ham" matches "Ham" but NOT "Black Forest Ham"
        for opt in options:
            if opt["display_name"].lower() == input_lower:
                return opt

        # Try EXACT match on slug (with underscores replaced by spaces)
        for opt in options:
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable == input_lower:
                return opt

        # Helper to parse aliases from option dict
        def get_aliases(opt: dict) -> list[str]:
            aliases_raw = opt.get("aliases", [])
            if isinstance(aliases_raw, str):
                if "|" in aliases_raw:
                    return [a.strip() for a in aliases_raw.split("|") if a.strip()]
                return [a.strip() for a in aliases_raw.split(",") if a.strip()]
            return aliases_raw or []

        # Try EXACT match on alias
        for opt in options:
            for alias in get_aliases(opt):
                if alias.lower() == input_lower:
                    return opt

        # Try if the FULL option name is in the user input
        # This handles "black forest ham please" → "Black Forest Ham"
        # But NOT "ham" → "Black Forest Ham" (substring of option name)
        for opt in options:
            display_lower = opt["display_name"].lower()
            if display_lower in input_lower:
                return opt

        # Try if the FULL alias is in the user input
        # This handles "sesame sourdough please" → option with alias "sesame sourdough"
        for opt in options:
            for alias in get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and alias_lower in input_lower:
                    return opt

        # NO substring matching in the other direction!
        # We deliberately don't check if input_lower is in display_name
        # because that would make "ham" match "Black Forest Ham"

        return None

    def _handle_disambiguation_response(
        self, user_input: str, order: OrderTask
    ) -> StateMachineResult | None:
        """
        Handle user response to an attribute disambiguation question.

        Checks if there's a pending disambiguation, attempts to resolve
        the user's selection, applies any stored modifiers, and returns
        the next question.

        Args:
            user_input: User's response to disambiguation question
            order: Current order state

        Returns:
            StateMachineResult if disambiguation was handled, None if no disambiguation pending
        """
        disambiguation = order.pending_attr_disambiguation
        if not disambiguation:
            return None

        options = disambiguation.get("options", [])
        attr_slug = disambiguation.get("attr_slug")
        stored_modifiers = disambiguation.get("modifiers", {})
        item_id = disambiguation.get("item_id")

        # Find the item being configured
        item = order.items.get_item_by_id(item_id) if item_id else None
        if not item or not isinstance(item, MenuItemTask):
            logger.warning("Disambiguation item not found: %s", item_id)
            order.pending_attr_disambiguation = None
            return self._get_next_question(order)

        # Try to resolve the selection
        selected = self._resolve_disambiguation(user_input, options)

        if not selected:
            # Couldn't match - ask again
            options_text = self._format_options_list(options)
            return StateMachineResult(
                message=f"Sorry, I didn't catch that. Did you mean {options_text}?",
                order=order,
            )

        # Clear disambiguation state
        order.pending_attr_disambiguation = None

        # Get the attribute info
        item_type = item.menu_item_type
        attrs = self._get_item_type_attributes(item_type)
        attr = attrs.get(attr_slug, {})

        # Store the selected value
        quantity = stored_modifiers.pop("_quantity", 1)
        qualifier = self._extract_qualifier_for_option(user_input, selected["display_name"])

        opt_price = selected.get("price") or selected.get("price_modifier") or 0
        selection = {
            "slug": selected["slug"],
            "display_name": selected["display_name"],
            "price": opt_price,
            "quantity": quantity,
        }
        if qualifier:
            selection["qualifier"] = qualifier

        input_type = attr.get("input_type", "single_select")
        if input_type == "multi_select":
            item.attribute_values[attr_slug] = [selected["slug"]]
            item.attribute_values[f"{attr_slug}_selections"] = [selection]
        else:
            item.attribute_values[attr_slug] = selected["slug"]
            item.attribute_values[f"{attr_slug}_selections"] = [selection]
            # Also set legacy direct fields for backward compatibility
            self._set_legacy_field_if_applicable(
                item, attr_slug, selected["display_name"], slug_value=selected["slug"]
            )
            # Update price if applicable
            if opt_price > 0:
                price_key = f"{attr_slug}_price"
                item.attribute_values[price_key] = opt_price
                if item.unit_price is not None:
                    item.unit_price = item.unit_price + opt_price

        # Apply any stored modifiers (e.g., milk type, sweetener extracted before disambiguation)
        if stored_modifiers:
            self._apply_stored_modifiers(item, stored_modifiers)

        # Build acknowledgment
        ack_name = selected["display_name"]
        if qualifier:
            ack_name = f"{ack_name} ({qualifier})"
        ack_text = f"{quantity} {ack_name}" if quantity > 1 else ack_name

        logger.info(
            "DISAMBIGUATION RESOLVED: %s -> %s for attr=%s, stored_mods=%s",
            user_input, selected["display_name"], attr_slug, stored_modifiers
        )

        return self._advance_to_next_question(item, order, attr, ack_text)

    def _apply_stored_modifiers(self, item: MenuItemTask, modifiers: dict) -> None:
        """
        Apply stored modifiers from disambiguation to the item.

        Uses data-driven approach: gets is_multi_select from ingredient_categories
        table to determine whether to use add_modifier() vs property setter.

        Args:
            item: The item to apply modifiers to
            modifiers: Dict of modifier values to apply
        """
        if not modifiers:
            return

        from .menu_data_cache import menu_cache

        # Keys that are special metadata, not actual modifier fields
        skip_keys = {"_quantity"}
        # Suffix for quantity keys (e.g., "sweetener_quantity")
        quantity_suffix = "_quantity"
        # Alias mappings for normalized field names
        key_aliases = {"flavor_syrup": "syrup"}

        # Track processed keys to avoid double-processing
        processed: set[str] = set()

        for key, value in modifiers.items():
            # Skip special keys, quantity suffixes, and already-processed keys
            if key in skip_keys or key.endswith(quantity_suffix) or key in processed:
                continue

            # Normalize key (e.g., flavor_syrup -> syrup)
            normalized_key = key_aliases.get(key, key)

            # Get field config to determine if this is a multi-select field
            field_config = menu_cache.get_ingredient_category_field_config(normalized_key)
            is_multi_select = field_config.get("is_multi_select", False) if field_config else False

            if is_multi_select:
                # Multi-select: use add_modifier with quantity
                quantity = modifiers.get(f"{key}{quantity_suffix}", 1)
                item.add_modifier(normalized_key, value, quantity, 0.0)
            else:
                # Single-select or boolean: use property setter if available
                if hasattr(item, normalized_key):
                    setattr(item, normalized_key, value)
                else:
                    # No property - set directly in attribute_values
                    item.attribute_values[normalized_key] = value

            processed.add(key)

    # =========================================================================
    # Handle User Input for Different States
    # =========================================================================

    def _handle_coffee_modifiers_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle beverage modifiers input in a data-driven way.

        Uses the generic extract_attribute_values() function to parse user input like
        "oat milk with 2 sugars and vanilla" and applies modifiers generically
        with pricing from the database.
        """
        user_lower = user_input.lower().strip()

        # Check for "no thanks" / "nothing" / "that's it" to skip modifiers
        skip_patterns = ["no", "nothing", "none", "that's it", "thats it", "i'm good", "im good", "nope"]
        if any(p in user_lower for p in skip_patterns) and len(user_lower) < 20:
            # Mark item as complete and advance
            item.mark_complete()
            order.clear_pending()
            return self._get_next_question(order)

        # Use the generic modifier extractor (data-driven, queries DB for item type attributes)
        item_type = item.menu_item_type
        modifiers = self._extract_modifiers_from_input(user_input, item_type)

        if not modifiers or not modifiers.has_modifiers():
            return StateMachineResult(
                message="Sorry, I didn't catch that. What kind of milk, sweetener, or syrup would you like? You can ask 'what options?' to see choices.",
                order=order,
            )

        # Apply extracted modifiers using data-driven approach with pricing
        applied = []
        for category in modifiers.get_categories():
            for mod in modifiers.get_all(category):
                # Look up price from pricing engine
                price = 0.0
                if self.pricing and item_type:
                    price = self.pricing.lookup_generic_modifier_price(
                        mod.slug, item_type, category
                    ) or 0.0

                # Use generic add_modifier for unified storage
                item.add_modifier(category, mod.slug, mod.quantity, price)

                # Build display name - use display_name from modifier if available
                display_name = getattr(mod, 'display_name', None) or mod.slug
                if mod.quantity > 1:
                    applied.append(f"{mod.quantity} {display_name}")
                else:
                    applied.append(display_name)

        # Mark item as complete since we got modifier info
        item.mark_complete()
        order.clear_pending()
        return self._get_next_question(order)

    def handle_attribute_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr_slug: str
    ) -> StateMachineResult:
        """Handle user input for a specific attribute question."""
        # Check if we're resolving a disambiguation first
        disambiguation_result = self._handle_disambiguation_response(user_input, order)
        if disambiguation_result:
            return disambiguation_result

        # NOTE: milk_sweetener_syrup now uses the standard multi_select flow
        # which includes partial matching (e.g., "syrup" lists all syrup options)

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
            # Pass the attribute display name as topic for context-aware detection
            # e.g., "what bread do you have" when asking about bread
            topic = attr.get("display_name", "")
            if self._is_options_inquiry(user_input, topic=topic):
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
        bool_value: bool | None = None
        if f"not {attr_name}" in user_lower or f"un{attr_name}" in user_lower:
            bool_value = False
        elif any(p in user_lower for p in yes_patterns) or attr_name in user_lower:
            bool_value = True
        elif any(p in user_lower for p in no_patterns):
            bool_value = False
        else:
            # Couldn't parse, ask again
            question = attr.get("question_text") or f"{attr['display_name']}?"
            return StateMachineResult(
                message=f"Sorry, I didn't catch that. {question} (yes or no)",
                order=order,
            )

        # Store in attribute_values
        item.attribute_values[attr_slug] = bool_value

        # Extract and apply any additional modifiers from the input
        # (e.g., "yes with bacon" -> captures the boolean AND the bacon modifier)
        self._extract_and_apply_modifiers(user_input, item)

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
            logger.info(
                "MULTI_SELECT MATCH for %s: input='%s', found %d matches: %s",
                attr_slug, user_input, len(matched_options),
                [o["slug"] for o in matched_options]
            )

            # DISAMBIGUATION: If multiple options matched but user input was a single token
            # (not compound like "ham and bacon"), ask for clarification
            if len(matched_options) > 1:
                tokens = self._tokenize_multi_input(user_input)
                is_single_token = len(tokens) <= 1
                if is_single_token:
                    logger.info(
                        "MULTI_SELECT DISAMBIGUATION: single token '%s' matched %d options: %s",
                        user_input, len(matched_options), [o["display_name"] for o in matched_options]
                    )
                    # Store disambiguation state and ask user to clarify
                    order.pending_attr_disambiguation = {
                        "options": matched_options,
                        "attr_slug": attr_slug,
                        "modifiers": {"_quantity": quantity},
                        "item_id": item.id,
                    }
                    options_text = self._format_options_list(matched_options)
                    return StateMachineResult(
                        message=f"Did you mean {options_text}?",
                        order=order,
                    )

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

                # Track count before adding new selections (for price update below)
                existing_count = len(selections)

                user_lower = user_input.lower()
                for opt in matched_options:
                    if opt["slug"] not in slugs:
                        slugs.append(opt["slug"])
                        # Extract qualifier (extra, light, on the side, etc.)
                        qualifier = self._extract_qualifier_for_option(user_input, opt["display_name"])
                        # Extract quantity specific to this option (e.g., "2 vanilla syrups")
                        opt_quantity = extract_quantity(user_lower, opt["display_name"].lower())
                        if opt_quantity == 1:
                            # Also try with slug pattern
                            opt_quantity = extract_quantity(user_lower, opt["slug"].replace("_", " "))
                        selection = {
                            "slug": opt["slug"],
                            "display_name": opt["display_name"],
                            "price": opt.get("price") or opt.get("price_modifier") or 0,
                            "quantity": opt_quantity,
                        }
                        if qualifier:
                            selection["qualifier"] = qualifier
                        selections.append(selection)

                item.attribute_values[attr_slug] = slugs
                item.attribute_values[f"{attr_slug}_selections"] = selections
                logger.info(
                    "STORED multi_select: %s = %s, attribute_values keys: %s",
                    attr_slug, slugs, list(item.attribute_values.keys())
                )

                # Update unit_price for NEWLY added selections only (skip previously existing ones)
                for sel in selections[existing_count:]:
                    sel_price = sel.get("price", 0) or 0.0
                    sel_qty = sel.get("quantity", 1) or 1
                    sel_slug = sel.get("slug", "")

                    # Look up price from pricing engine if not in option
                    # Pass actual item type - pricing engine returns 0 for non-applicable types
                    if sel_price == 0 and self.pricing:
                        # Try syrup price first, then milk
                        sel_price = self.pricing.lookup_generic_modifier_price(sel_slug, item.menu_item_type, "syrup") or 0.0
                        if sel_price == 0:
                            sel_price = self.pricing.lookup_generic_modifier_price(sel_slug, item.menu_item_type, "milk") or 0.0
                        # Update the selection with the looked-up price
                        if sel_price > 0:
                            sel["price"] = sel_price

                    # Update unit_price
                    total_sel_price = sel_price * sel_qty
                    if total_sel_price > 0 and item.unit_price is not None:
                        item.unit_price = item.unit_price + total_sel_price
                        logger.info(
                            "Updated unit_price for %s: added %s price %.2f (qty=%d), new total %.2f",
                            item.id, sel_slug, sel_price, sel_qty, item.unit_price
                        )

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

                # NOTE: Do NOT call _extract_and_apply_modifiers here.
                # Multi-select input has been fully handled above. Extracting
                # modifiers would cause duplicates (e.g., "2 scrambled eggs"
                # would add scrambled_egg to both add_egg_selections AND extras).

                return self._advance_to_next_question(item, order, attr, ack_text)

        # For single_select (or if multi_select found nothing), use single-match logic
        matched, partial_matches = self._match_option_from_input(user_input, options)

        if matched:
            # Extract qualifier for single match
            qualifier = self._extract_qualifier_for_option(user_input, matched["display_name"])
            sel_price = matched.get("price") or matched.get("price_modifier") or 0
            selection = {
                "slug": matched["slug"],
                "display_name": matched["display_name"],
                "price": sel_price,
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

                # Also set legacy direct fields for backward compatibility
                # (e.g., item.spread = value when spread_type is set)
                self._set_legacy_field_if_applicable(
                    item, attr_slug, matched["display_name"], slug_value=matched["slug"]
                )

                # Determine the price for this option
                option_price = sel_price or 0.0

                # Look up price from pricing engine if not set
                # First check for variant pricing (menu_item_size_prices), then fall back to upcharges
                variant_price_applied = False
                if option_price == 0 and self.pricing:
                    # Check if this item has variant pricing for this attribute
                    # Variant pricing: full price per option (from menu_item_size_prices)
                    # Upcharge pricing: base price + modifier (from attribute_options)
                    variant_price, _ = self.pricing.lookup_size_price(
                        item.menu_item_name, matched["slug"]
                    )
                    if variant_price is not None:
                        # Variant pricing found - set unit_price to the looked-up price
                        item.unit_price = variant_price
                        variant_price_applied = True
                        logger.info(
                            "Set unit_price for %s from variant pricing: %s=%s, price=%.2f",
                            item.id, attr_slug, matched["slug"], variant_price
                        )
                    else:
                        # No variant pricing - try upcharge from attribute_options
                        option_price = self.pricing.lookup_attribute_option_upcharge(
                            item.menu_item_type, attr_slug, matched["slug"]
                        ) or 0.0

                # Store price if applicable and update unit_price (for upcharge-based pricing)
                if not variant_price_applied and option_price > 0:
                    price_key = f"{attr_slug}_price"
                    item.attribute_values[price_key] = option_price
                    # Update unit_price to include this modifier price (multiplied by quantity)
                    total_price = option_price * quantity
                    if item.unit_price is not None:
                        item.unit_price = item.unit_price + total_price
                        logger.info(
                            "Updated unit_price for %s: added %s price %.2f (qty=%d), new total %.2f",
                            item.id, attr_slug, option_price, quantity, item.unit_price
                        )

                # Always use _selections format to support quantity
                item.attribute_values[f"{attr_slug}_selections"] = [selection]

            # NOTE: Generally do NOT call _extract_and_apply_modifiers here.
            # The user's input was a direct answer to the attribute question.
            # Extracting modifiers would cause duplicates (e.g., "2 scrambled eggs"
            # would add scrambled_egg to both add_egg_selections AND extras/extra_protein).

            # Acknowledgment with quantity and qualifier
            ack_name = matched["display_name"]
            if qualifier:
                ack_name = f"{ack_name} ({qualifier})"
            ack_text = f"{quantity} {ack_name}" if quantity > 1 else ack_name
            return self._advance_to_next_question(item, order, attr, ack_text)

        # Multiple partial matches - store disambiguation state and ask
        if partial_matches:
            # Extract any modifiers that should be remembered during disambiguation
            # (e.g., "walnut with bacon" -> remember bacon while disambiguating walnut type)
            extracted_mods = self._extract_modifiers_from_input(user_input, item.menu_item_type)
            stored_modifiers = {"_quantity": quantity}
            if extracted_mods:
                # Convert extracted modifiers to dict for storage
                milk = extracted_mods.get_first("milk")
                if milk:
                    stored_modifiers["milk"] = milk.name
                sweetener = extracted_mods.get_first("sweetener")
                if sweetener:
                    stored_modifiers["sweetener"] = sweetener.name
                    stored_modifiers["sweetener_quantity"] = sweetener.quantity
                syrup = extracted_mods.get_first("syrup")
                if syrup:
                    stored_modifiers["syrup"] = syrup.name
                    stored_modifiers["syrup_quantity"] = syrup.quantity

            # Store disambiguation state
            order.pending_attr_disambiguation = {
                "options": partial_matches,
                "attr_slug": attr_slug,
                "modifiers": stored_modifiers,
                "item_id": item.id,
            }

            logger.info(
                "DISAMBIGUATION STARTED: attr=%s, options=%s, stored_mods=%s",
                attr_slug, [o["display_name"] for o in partial_matches], stored_modifiers
            )

            options_text = self._format_options_list(partial_matches)
            return StateMachineResult(
                message=f"I found a few options matching that. Did you mean {options_text}?",
                order=order,
            )

        # Check for partial matches on option display names
        # e.g., "syrup" matches "vanilla syrup", "caramel syrup", etc.
        partial_result = self._check_partial_match(user_lower, options, item, order, attr_slug)
        if partial_result:
            return partial_result

        # No match at all - ask again WITHOUT listing options
        attr_name = attr["display_name"].lower()
        return StateMachineResult(
            message=f"Sorry, I didn't catch that. What kind of {attr_name} would you like? You can ask 'what options?' to see choices.",
            order=order,
        )

    def _check_partial_match(
        self,
        user_input: str,
        options: list[dict],
        item: MenuItemTask,
        order: OrderTask,
        attr_slug: str,
    ) -> StateMachineResult | None:
        """
        Check if user input partially matches option display names.

        This is a data-driven approach that searches for options where the
        display_name contains any significant word from the user input.

        For example:
        - "syrup" → matches "vanilla syrup", "caramel syrup", "hazelnut syrup"
        - "what syrup do you have" → extracts "syrup", matches same options
        - "caramel" → matches "caramel syrup", "caramel sauce", etc.

        Returns:
        - None if no partial matches found
        - StateMachineResult listing matching options if multiple found
        """
        # Stop words to skip when extracting search terms
        stop_words = {
            "what", "which", "do", "you", "have", "are", "the", "a", "an",
            "is", "there", "any", "some", "can", "i", "get", "want", "like",
            "options", "option", "choices", "choice", "available", "kind",
            "kinds", "type", "types", "of", "for", "with", "please", "thanks",
        }

        user_lower = user_input.lower().strip()

        # Extract meaningful words (at least 3 chars, not stop words)
        words = [
            word.strip("?.,!") for word in user_lower.split()
            if len(word.strip("?.,!")) >= 3 and word.strip("?.,!") not in stop_words
        ]

        if not words:
            return None

        # Search for options where display_name contains any of the search words
        matching_options = []
        matched_term = None

        for word in words:
            # Singularize the word for matching (e.g., "syrups" -> "syrup")
            singular_word = singularize(word)

            for opt in options:
                display_lower = opt["display_name"].lower()

                # Check if word is contained in display_name
                if singular_word in display_lower or word in display_lower:
                    if opt not in matching_options:
                        matching_options.append(opt)
                        if not matched_term:
                            matched_term = singular_word

        if not matching_options:
            return None

        if len(matching_options) == 1:
            # Exactly one option matches - return None to let normal matching select it
            logger.info(
                "Partial match '%s' matched single option: %s",
                user_input, matching_options[0]["display_name"]
            )
            return None

        # Multiple options match - list them for user
        options_text = self._format_options_list(matching_options)

        # Stay in same pending state to handle the follow-up answer
        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_item_id = item.id
        order.pending_field = f"{item.menu_item_type}:{attr_slug}"

        logger.info(
            "Partial match: user said '%s', term '%s' matched %d options",
            user_input, matched_term, len(matching_options)
        )

        return StateMachineResult(
            message=f"We have {options_text}. Which would you like?",
            order=order,
        )

    def _advance_to_next_question(
        self, item: MenuItemTask, order: OrderTask, current_attr: dict,
        matched_choice: str | None = None,
        use_multi_item_orchestration: bool = False
    ) -> StateMachineResult:
        """Advance to the next question after answering current attribute.

        Args:
            item: The menu item being configured
            order: The current order
            current_attr: The attribute that was just answered
            matched_choice: The display name of the choice the user made (for acknowledgment)
            use_multi_item_orchestration: If True, use configure_next_incomplete_item()
                to handle multiple items of the same type
        """
        item_type = item.menu_item_type
        logger.info(
            "ADVANCE_TO_NEXT: after attr=%s, item_type=%s, attribute_values=%s",
            current_attr.get("slug"), item_type, item.attribute_values
        )

        # Check if we're in mandatory phase or optional phase
        if current_attr.get("ask_in_conversation", True):
            # Just answered a mandatory question, check for more
            unanswered_mandatory = self._get_unanswered_mandatory(item, item_type)
            if unanswered_mandatory:
                next_attr = unanswered_mandatory[0]
                return self._ask_attribute_question(item, order, next_attr)
            else:
                # All mandatory done for this item
                if use_multi_item_orchestration:
                    # Use multi-item orchestration to check for more items
                    return self.configure_next_incomplete_item(order, item_type)
                else:
                    # Single-item flow - go to checkpoint
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
            # No more options, recalculate price and complete
            self._recalculate_item_price(item)
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
            # Recalculate price and complete
            self._recalculate_item_price(item)
            item.mark_complete()
            order.clear_pending()

            # Check if there are more items to configure (e.g., coffee added with bagel)
            if self._get_next_question:
                next_result = self._get_next_question(order)
                # If there's another item to configure, return that
                if next_result and next_result.order.pending_field:
                    return next_result

            # No more items to configure - go back to taking items
            order.phase = OrderPhase.TAKING_ITEMS.value
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
        order.pending_field = f"{item.menu_item_type}:{attr['slug']}"

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
                        opt_quantity = extract_quantity(user_lower, opt_name.lower())
                        if opt_quantity == 1:
                            opt_quantity = extract_quantity(user_lower, opt["slug"].replace("_", " "))

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
                            "price": opt.get("price") or opt.get("price_modifier") or 0,
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
                    opt_price = matched.get("price") or matched.get("price_modifier") or 0
                    if opt_price > 0:
                        item.attribute_values[f"{attr_slug}_price"] = opt_price
                    logger.info("Captured %s=%s from input", attr_slug, matched["slug"])
