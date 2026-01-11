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

from sandwich_bot.menu_data_cache import menu_cache
from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase, ExtractedModifiers, ExtractedCoffeeModifiers
from .parsers.constants import extract_quantity, DEFAULT_PAGINATION_SIZE
from .parsers import extract_modifiers_from_input, extract_coffee_modifiers_from_input
from .handler_config import BaseHandler
from .attribute_loader import load_item_type_attributes

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)


class MenuItemConfigHandler(BaseHandler):
    """
    Handles menu item configuration with DB-driven attributes.

    Reads item type attributes from the database to determine:
    - Which questions to ask (ask_in_conversation=True for mandatory)
    - What the question text should be (question_text field)
    - What options are valid (attribute_options or item_type_ingredients)
    """

    # Item types that use this handler for configuration
    SUPPORTED_ITEM_TYPES = {
        "deli_sandwich", "egg_sandwich", "fish_sandwich", "spread_sandwich", "espresso",
        "bagel", "sized_beverage",  # Added in Phase 6 migration
    }

    # Mapping from legacy pending_field names to DB attribute slugs
    # This allows routing legacy field handlers through the generic handler
    LEGACY_FIELD_TO_ATTR = {
        # Bagel fields
        "bagel_choice": "bread",
        "spread": "spread_type",
        "toasted": "toasted",
        "cheese_choice": "cheese",
        "spread_sandwich_toasted": "toasted",
        "menu_item_bagel_toasted": "toasted",
        # Coffee/beverage fields
        "coffee_size": "size",
        "coffee_style": "iced",  # Hot/iced maps to boolean iced attribute
        "coffee_modifiers": "milk_sweetener_syrup",
        "syrup_flavor": "syrup",
    }

    # Mapping from DB attribute slugs to legacy storage keys in attribute_values
    # This allows checking if an attribute is already answered when stored under legacy key
    LEGACY_ATTR_ALIASES = {
        "bread": ["bagel_type"],  # DB uses "bread", legacy code uses "bagel_type"
        "spread": ["spread_type"],  # DB uses "spread", legacy code uses "spread_type"
    }

    # Attributes that may be stored as direct model fields instead of in attribute_values
    # When checking if these are answered, we also check the direct field on MenuItemTask
    DIRECT_FIELD_ATTRS = {"toasted", "scooped", "decaf"}

    # Modifier extraction configuration per item type
    # Maps item type slugs to the type of modifier extraction to use
    MODIFIER_EXTRACTION_TYPE = {
        # Food items use bagel-style modifiers (proteins, cheeses, toppings, spreads)
        "deli_sandwich": "food",
        "egg_sandwich": "food",
        "fish_sandwich": "food",
        "spread_sandwich": "food",
        "bagel": "food",
        "omelette": "food",
        # Beverage items use coffee-style modifiers (milk, sweetener, syrup)
        "espresso": "beverage",
        "sized_beverage": "beverage",
    }

    def __init__(self, config: "HandlerConfig | None" = None, **kwargs):
        """
        Initialize the menu item config handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support.
        """
        super().__init__(config, **kwargs)

        # Cache for item type attributes (keyed by item_type_slug)
        self._attributes_cache: dict[str, dict] = {}

    def supports_item_type(self, item_type_slug: str | None) -> bool:
        """Check if this handler supports the given item type."""
        return item_type_slug in self.SUPPORTED_ITEM_TYPES

    def _get_item_type_attributes(self, item_type_slug: str) -> dict:
        """
        Load item type attributes from database.

        Uses the shared attribute_loader for core attributes and adds
        global attributes with custom question text handling.

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

        # Use shared loader for core item type attributes
        result = load_item_type_attributes(item_type_slug, include_global_attributes=False)

        if not result:
            self._attributes_cache[item_type_slug] = {}
            return {}

        # Load global attributes with custom question text handling
        from ..db import SessionLocal
        from ..models import (
            ItemType, ItemTypeGlobalAttribute, GlobalAttribute,
        )

        db = SessionLocal()
        try:
            item_type = db.query(ItemType).filter(ItemType.slug == item_type_slug).first()
            if not item_type:
                self._attributes_cache[item_type_slug] = result
                return result

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
        """Get mandatory attributes that haven't been answered yet.

        Checks both canonical attribute slugs and legacy aliases to handle
        backward compatibility with items created by legacy handlers.
        Also checks direct model fields for certain attributes.
        """
        mandatory = self._get_mandatory_attributes(item_type_slug)
        unanswered = []
        for attr in mandatory:
            slug = attr["slug"]
            # Check canonical slug in attribute_values
            if slug in item.attribute_values:
                continue
            # Check legacy aliases for this attribute
            legacy_aliases = self.LEGACY_ATTR_ALIASES.get(slug, [])
            found_via_alias = any(
                alias in item.attribute_values for alias in legacy_aliases
            )
            if found_via_alias:
                continue
            # Check direct model field for certain attributes (e.g., toasted, scooped)
            if slug in self.DIRECT_FIELD_ATTRS:
                direct_value = getattr(item, slug, None)
                if direct_value is not None:
                    continue
            unanswered.append(attr)
        return unanswered

    def _get_unanswered_optional(
        self, item: MenuItemTask, item_type_slug: str
    ) -> list[dict]:
        """Get optional attributes that haven't been answered yet.

        Checks both canonical attribute slugs, legacy aliases, and direct model fields.
        """
        optional = self._get_optional_attributes(item_type_slug)
        unanswered = []
        for attr in optional:
            slug = attr["slug"]
            # Check canonical slug in attribute_values
            if slug in item.attribute_values:
                continue
            # Check legacy aliases for this attribute
            legacy_aliases = self.LEGACY_ATTR_ALIASES.get(slug, [])
            found_via_alias = any(
                alias in item.attribute_values for alias in legacy_aliases
            )
            if found_via_alias:
                continue
            # Check direct model field for certain attributes
            if slug in self.DIRECT_FIELD_ATTRS:
                direct_value = getattr(item, slug, None)
                if direct_value is not None:
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

        # Normalize common food plurals to singular for matching
        # "eggs" → "egg", "bagels" → "bagel", "syrups" → "syrup"
        text = re.sub(r'\beggs\b', 'egg', text)
        text = re.sub(r'\bbagels\b', 'bagel', text)
        text = re.sub(r'\bsyrups\b', 'syrup', text)

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

        for opt in options:
            if not self._passes_must_match(user_input, opt):
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
    ) -> ExtractedModifiers | ExtractedCoffeeModifiers | None:
        """
        Extract modifiers from user input based on item type.

        Uses the appropriate extraction function for the item type:
        - Food items: extract_modifiers_from_input() -> ExtractedModifiers
        - Beverage items: extract_coffee_modifiers_from_input() -> ExtractedCoffeeModifiers

        Args:
            user_input: Raw user input string
            item_type: The item type slug (e.g., "deli_sandwich", "espresso")

        Returns:
            ExtractedModifiers or ExtractedCoffeeModifiers, or None if no extraction
            is configured for this item type
        """
        extraction_type = self.MODIFIER_EXTRACTION_TYPE.get(item_type)

        if extraction_type == "food":
            modifiers = extract_modifiers_from_input(user_input)
            if modifiers.has_modifiers() or modifiers.has_special_instructions():
                logger.debug("Extracted food modifiers from input: %s", modifiers)
                return modifiers
        elif extraction_type == "beverage":
            modifiers = extract_coffee_modifiers_from_input(user_input)
            if modifiers.milk or modifiers.sweetener or modifiers.flavor_syrup or modifiers.has_special_instructions():
                logger.debug("Extracted beverage modifiers from input: %s", modifiers)
                return modifiers

        return None

    def _apply_extracted_modifiers(
        self, item: MenuItemTask, modifiers: ExtractedModifiers | ExtractedCoffeeModifiers
    ) -> str | None:
        """
        Apply extracted modifiers to a menu item.

        Handles both food-style modifiers (proteins, cheeses, etc.) and
        beverage-style modifiers (milk, sweetener, syrup).

        Args:
            item: The menu item to apply modifiers to
            modifiers: Extracted modifiers from user input

        Returns:
            Acknowledgment string if modifiers were applied, None otherwise
        """
        added_items = []

        if isinstance(modifiers, ExtractedModifiers):
            # Apply food-style modifiers
            # Proteins: first one to sandwich_protein if not set, rest to extras
            if modifiers.proteins:
                if not item.sandwich_protein:
                    item.sandwich_protein = modifiers.proteins[0]
                    item.extras.extend(modifiers.proteins[1:])
                else:
                    item.extras.extend(modifiers.proteins)
                added_items.extend(modifiers.proteins)

            # Cheeses to extras
            if modifiers.needs_cheese_clarification:
                if "cheese" not in item.extras:
                    item.extras.append("cheese")
                item.needs_cheese_clarification = True
                added_items.append("cheese")
            elif modifiers.cheeses:
                item.extras.extend(modifiers.cheeses)
                added_items.extend(modifiers.cheeses)

            # Toppings to extras
            if modifiers.toppings:
                item.extras.extend(modifiers.toppings)
                added_items.extend(modifiers.toppings)

            # Spreads: set if not already set
            if modifiers.spreads and not item.spread:
                item.spread = modifiers.spreads[0]
                added_items.extend(modifiers.spreads)

            # Special instructions
            if modifiers.has_special_instructions():
                existing = item.special_instructions or ""
                new_instr = modifiers.get_special_instructions_string()
                item.special_instructions = f"{existing}, {new_instr}".strip(", ") if existing else new_instr

        elif isinstance(modifiers, ExtractedCoffeeModifiers):
            # Apply beverage-style modifiers using attribute_values
            if modifiers.milk and "milk" not in item.attribute_values:
                item.attribute_values["milk"] = modifiers.milk
                added_items.append(modifiers.milk)

            if modifiers.sweetener and "sweetener" not in item.attribute_values:
                item.attribute_values["sweetener"] = modifiers.sweetener
                if modifiers.sweetener_quantity > 1:
                    item.attribute_values["sweetener_quantity"] = modifiers.sweetener_quantity
                added_items.append(modifiers.sweetener)

            if modifiers.flavor_syrup and "flavor_syrup" not in item.attribute_values:
                item.attribute_values["flavor_syrup"] = modifiers.flavor_syrup
                if modifiers.syrup_quantity > 1:
                    item.attribute_values["syrup_quantity"] = modifiers.syrup_quantity
                added_items.append(f"{modifiers.flavor_syrup} syrup")

            if modifiers.cream_level and "cream_level" not in item.attribute_values:
                item.attribute_values["cream_level"] = modifiers.cream_level

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
        if item_type:
            target_types = {item_type} & self.SUPPORTED_ITEM_TYPES
        else:
            target_types = self.SUPPORTED_ITEM_TYPES

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
                order.pending_field = f"menu_item_attr_{first_attr['slug']}"
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
        Resolve user's selection from disambiguation options.

        Similar to bagel handler's _resolve_spread_disambiguation but works with
        dict options (having display_name and slug fields).

        Args:
            user_input: User's response (e.g., "honey walnut", "the first one", "maple")
            options: List of option dicts with display_name and slug fields

        Returns:
            Selected option dict if matched, None if no match found.
        """
        input_lower = user_input.lower().strip()

        # Remove common filler words
        input_lower = input_lower.replace("the ", "").strip()
        input_lower = input_lower.replace("please", "").strip()

        # Try exact match on display_name first
        for opt in options:
            if opt["display_name"].lower() == input_lower:
                return opt

        # Try exact match on slug (with underscores replaced by spaces)
        for opt in options:
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable == input_lower:
                return opt

        # Try if user said just the first word (e.g., "honey" for "honey walnut")
        for opt in options:
            display_lower = opt["display_name"].lower()
            first_word = display_lower.split()[0] if display_lower else ""
            if first_word and first_word == input_lower:
                return opt

        # Try substring match (e.g., "maple" matches "maple raisin walnut")
        for opt in options:
            display_lower = opt["display_name"].lower()
            if input_lower in display_lower:
                return opt

        # Try if option name is a substring of input (e.g., "honey walnut please")
        for opt in options:
            display_lower = opt["display_name"].lower()
            if display_lower in input_lower:
                return opt

        # Handle ordinal selections ("first one", "second one", "1", "2")
        ordinal_map = {
            "first": 0, "1": 0, "one": 0,
            "second": 1, "2": 1, "two": 1,
            "third": 2, "3": 2, "three": 2,
            "fourth": 3, "4": 3, "four": 3,
        }
        for word, index in ordinal_map.items():
            if word in input_lower and index < len(options):
                return options[index]

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

        selection = {
            "slug": selected["slug"],
            "display_name": selected["display_name"],
            "price": selected.get("price", 0),
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
            # Update price if applicable
            if selected.get("price", 0) > 0:
                price_key = f"{attr_slug}_price"
                item.attribute_values[price_key] = selected["price"]
                if item.unit_price is not None:
                    item.unit_price = item.unit_price + selected["price"]

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

        This handles modifiers that were extracted before disambiguation
        (e.g., "large iced oat milk latte" - oat milk is stored while
        disambiguating between latte types).

        Args:
            item: The item to apply modifiers to
            modifiers: Dict of modifier values to apply
        """
        # Handle common beverage modifiers
        if "milk" in modifiers:
            item.milk = modifiers["milk"]
        if "sweetener" in modifiers:
            # Sweeteners are stored as list of dicts
            if not item.sweeteners:
                item.sweeteners = []
            item.sweeteners.append({
                "type": modifiers["sweetener"],
                "quantity": modifiers.get("sweetener_quantity", 1),
            })
        if "syrup" in modifiers or "flavor_syrup" in modifiers:
            syrup = modifiers.get("syrup") or modifiers.get("flavor_syrup")
            if syrup:
                if not item.flavor_syrups:
                    item.flavor_syrups = []
                item.flavor_syrups.append({
                    "flavor": syrup,
                    "quantity": modifiers.get("syrup_quantity", 1),
                })
        if "size" in modifiers:
            item.size = modifiers["size"]
        if "iced" in modifiers:
            item.iced = modifiers["iced"]
        if "decaf" in modifiers:
            item.decaf = modifiers["decaf"]

        # Handle food modifiers (spreads, proteins, etc.)
        # These would come from _extract_modifiers_from_input
        if "spread" in modifiers:
            item.spread = modifiers["spread"]

    # =========================================================================
    # Handle User Input for Different States
    # =========================================================================

    def handle_legacy_field_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, legacy_field: str
    ) -> StateMachineResult:
        """
        Handle user input for legacy pending_field names (bagel_choice, coffee_size, etc.).

        This method maps legacy field names to DB attribute slugs and delegates to
        handle_attribute_input. It's used during the Phase 6 migration to route
        legacy handlers through the generic MenuItemConfigHandler.

        Args:
            user_input: The user's input text
            item: The menu item being configured
            order: The current order
            legacy_field: The legacy pending_field name (e.g., "bagel_choice", "coffee_size")

        Returns:
            StateMachineResult with next question or completion message
        """
        # Map legacy field to DB attribute slug
        attr_slug = self.LEGACY_FIELD_TO_ATTR.get(legacy_field)

        if not attr_slug:
            logger.warning(
                "Unknown legacy field '%s' for item type '%s'",
                legacy_field, item.menu_item_type
            )
            order.clear_pending()
            return self._get_next_question(order)

        # Special handling for coffee_style -> iced boolean
        # The coffee_style question asks "hot or iced?" but the DB attr is boolean "iced"
        if legacy_field == "coffee_style":
            return self._handle_coffee_style_input(user_input, item, order)

        # Delegate to generic attribute handler
        return self.handle_attribute_input(user_input, item, order, attr_slug)

    def _handle_coffee_style_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Handle coffee style (hot/iced) input - special case for boolean mapping."""
        user_lower = user_input.lower().strip()

        # Check for iced indicators
        iced_patterns = ["iced", "ice", "cold"]
        hot_patterns = ["hot", "warm"]

        if any(p in user_lower for p in iced_patterns):
            item.attribute_values["iced"] = True
            item.iced = True
        elif any(p in user_lower for p in hot_patterns):
            item.attribute_values["iced"] = False
            item.iced = False
        else:
            # Couldn't determine - ask again
            return StateMachineResult(
                message="Would you like that hot or iced?",
                order=order,
            )

        # Extract and apply any additional modifiers from the input
        self._extract_and_apply_modifiers(user_input, item)

        # Advance to next question using the multi-item flow for beverages
        return self._advance_to_next_question(
            item, order, {"slug": "iced"}, use_multi_item_orchestration=True
        )

    def handle_attribute_input(
        self, user_input: str, item: MenuItemTask, order: OrderTask, attr_slug: str
    ) -> StateMachineResult:
        """Handle user input for a specific attribute question."""
        # Check if we're resolving a disambiguation first
        disambiguation_result = self._handle_disambiguation_response(user_input, order)
        if disambiguation_result:
            return disambiguation_result

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
                        opt_quantity = extract_quantity(user_lower, opt["display_name"].lower())
                        if opt_quantity == 1:
                            # Also try with slug pattern
                            opt_quantity = extract_quantity(user_lower, opt["slug"].replace("_", " "))
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

                # Extract and apply any additional modifiers from the input
                self._extract_and_apply_modifiers(user_input, item)

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

            # Extract and apply any additional modifiers from the input
            self._extract_and_apply_modifiers(user_input, item)

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
                if hasattr(extracted_mods, "milk") and extracted_mods.milk:
                    stored_modifiers["milk"] = extracted_mods.milk
                if hasattr(extracted_mods, "sweetener") and extracted_mods.sweetener:
                    stored_modifiers["sweetener"] = extracted_mods.sweetener
                if hasattr(extracted_mods, "syrup") and extracted_mods.syrup:
                    stored_modifiers["syrup"] = extracted_mods.syrup
                if hasattr(extracted_mods, "size") and extracted_mods.size:
                    stored_modifiers["size"] = extracted_mods.size
                if hasattr(extracted_mods, "iced") and extracted_mods.iced is not None:
                    stored_modifiers["iced"] = extracted_mods.iced

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
