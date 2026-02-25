"""
Ingredient Fallback Handler.

Handles matching user input to ingredients as a fallback when attribute/option
matching fails. Supports:
- Space-separated multi-ingredient input (e.g., "salt pepper ketchup")
- Quantity modifiers (e.g., "more bacon", "extra cheese", "double egg")
- Attribute category matching (e.g., "more cheese" when cheese is an attribute)

Extracted from customization_checkpoint.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable

from orderbot.cache import menu_cache

from ...shared_constants import ARTICLES, ACTION_VERB_STOPWORDS
from ...schemas import StateMachineResult
from ...parsers.quantity_utils import (
    extract_leading_quantity,
    extract_additive_quantity,
    QUANTITY_MODIFIER_WORDS,
)
from ...utils.text import format_english_list, normalize_text

if TYPE_CHECKING:
    from ...models import OrderTask, MenuItemTask

logger = logging.getLogger(__name__)

__all__ = ["IngredientFallbackHandler"]


class IngredientFallbackHandler:
    """
    Handles ingredient fallback matching during customization.

    When attribute/option matching fails, this handler tries to match
    user input against the ingredients table, supporting:
    - Multi-word ingredient lists
    - Quantity modifiers
    - Attribute category matching
    """

    def __init__(
        self,
        recalculate_item_price: Callable[["MenuItemTask"], None],
        ask_customization_checkpoint: Callable[
            ["MenuItemTask", "OrderTask", str | None], StateMachineResult
        ],
    ):
        """Initialize the ingredient fallback handler.

        Args:
            recalculate_item_price: Callback to recalculate item price after changes.
            ask_customization_checkpoint: Callback to ask the customization checkpoint.
        """
        self._recalculate_item_price = recalculate_item_price
        self._ask_customization_checkpoint = ask_customization_checkpoint

    def try_match(
        self,
        user_input: str,
        item: "MenuItemTask",
        order: "OrderTask",
    ) -> StateMachineResult | None:
        """Try matching space-separated words against ingredients as fallback.

        This handles input like "salt pepper ketchup" by splitting on spaces
        and matching each word individually against the ingredients table.
        Also handles quantity modifier patterns like "more bacon", "extra cheese".
        Only called after attribute/option matching has failed.

        Args:
            user_input: User's input text
            item: Menu item being configured
            order: Current order

        Returns:
            StateMachineResult if any ingredients matched, None otherwise
        """
        user_clean = normalize_text(user_input)

        # Only try splitting if there are multiple words
        words = user_clean.split()
        if len(words) <= 1:
            return None  # Single word already tried via other matching

        added_names: list[str] = []
        unmatched: list[str] = []
        matched_slugs: set[str] = set()  # Track already matched ingredients

        # Phase 1: Try to match full phrases with quantity modifiers
        result = self._try_quantity_modifier_match(
            user_clean, item, order, added_names, matched_slugs
        )
        if result is not None:
            return result

        # Phase 1b: Check if term matches an attribute category
        result = self._try_attribute_category_match(
            user_clean, words, item, order, added_names, matched_slugs
        )
        if result is not None:
            return result

        # Phase 2: Word-by-word matching for multi-ingredient input
        self._try_word_by_word_match(words, item, added_names, unmatched)

        if not added_names:
            return None  # No matches at all, let caller show "Sorry" message

        # Recalculate price
        self._recalculate_item_price(item)

        # Build message
        added_text = format_english_list(added_names)

        if unmatched:
            unmatched_text = format_english_list(unmatched)
            msg = f"{added_text} added. Couldn't find: {unmatched_text}."
        else:
            msg = f"{added_text} added."

        return self._ask_customization_checkpoint(item, order, msg)

    def _try_quantity_modifier_match(
        self,
        user_clean: str,
        item: "MenuItemTask",
        order: "OrderTask",
        added_names: list[str],
        matched_slugs: set[str],
    ) -> StateMachineResult | None:
        """Try to match full phrases with quantity modifiers.

        Handles patterns like "more bacon", "extra cheese", "double egg".

        Args:
            user_clean: Lowercase user input
            item: Menu item being configured
            order: Current order
            added_names: List to append matched ingredient names to
            matched_slugs: Set to track matched ingredient slugs

        Returns:
            StateMachineResult if matches found, None otherwise
        """
        for match in menu_cache.find_matching_ingredients(user_clean):
            pattern = match["name"].lower()
            if pattern not in user_clean:
                continue

            quantity, is_additive = extract_additive_quantity(user_clean, pattern)
            slug = match["slug"]

            # Check for "extra X" which should be additive when ingredient exists
            is_extra_prefix = user_clean.startswith(f"extra {pattern}")

            existing = item.find_modifier_by_slug(slug)

            if is_additive or (is_extra_prefix and existing):
                # Additive pattern: increment existing quantity or add new
                if existing:
                    existing["quantity"] = existing.get("quantity", 1) + quantity
                    display_qty = existing["quantity"]
                    display_name = f"{match['name']} x{display_qty}"
                    added_names.append(display_name)
                    logger.info(
                        "QUANTITY_MODIFIER: Incremented '%s' by %d to qty=%d",
                        slug, quantity, display_qty
                    )
                else:
                    # Additive but doesn't exist yet - add normally
                    item.add_selection(
                        slug=slug,
                        category=match["category"],
                        display_name=match["name"],
                        quantity=quantity,
                        price=match.get("base_price", 0.0),
                    )
                    added_names.append(match["name"])
                    logger.info(
                        "QUANTITY_MODIFIER: Added new '%s' with qty=%d (additive pattern)",
                        slug, quantity
                    )
            else:
                # Absolute pattern (e.g., "double bacon" = 2)
                if existing:
                    # Update existing quantity to absolute value
                    existing["quantity"] = quantity
                    display_name = f"{match['name']} x{quantity}" if quantity > 1 else match["name"]
                    added_names.append(display_name)
                else:
                    item.add_selection(
                        slug=slug,
                        category=match["category"],
                        display_name=match["name"],
                        quantity=quantity,
                        price=match.get("base_price", 0.0),
                    )
                    display_name = f"{quantity} {match['name']}" if quantity > 1 else match["name"]
                    added_names.append(display_name)
                logger.info(
                    "QUANTITY_MODIFIER: Set '%s' to qty=%d (absolute)",
                    slug, quantity
                )

            matched_slugs.add(slug)

        # If we matched via quantity modifier patterns, we're done
        if matched_slugs:
            self._recalculate_item_price(item)
            added_text = format_english_list(added_names)
            return self._ask_customization_checkpoint(item, order, f"{added_text} added")

        return None

    def _try_attribute_category_match(
        self,
        user_clean: str,
        words: list[str],
        item: "MenuItemTask",
        order: "OrderTask",
        added_names: list[str],
        matched_slugs: set[str],
    ) -> StateMachineResult | None:
        """Check if term matches an attribute category.

        Handles "more cheese" when user has already selected provolone
        (cheese is attribute category).

        Args:
            user_clean: Lowercase user input
            words: Split words from input
            item: Menu item being configured
            order: Current order
            added_names: List to append matched names to
            matched_slugs: Set to track matched slugs

        Returns:
            StateMachineResult if matches found, None otherwise
        """
        item_type_attrs = menu_cache.get_item_type_attributes(item.menu_item_type)

        for word in words:
            if word in QUANTITY_MODIFIER_WORDS or word in ARTICLES or word in ACTION_VERB_STOPWORDS:
                continue

            # Check if word matches an attribute category slug
            if word in item_type_attrs:
                existing = item.get_selection(word)  # e.g., get_selection("cheese")
                attr_config = item_type_attrs[word]

                if existing:
                    # Case A: Attribute already has a selection - modify quantity
                    quantity, is_additive = extract_additive_quantity(user_clean, word)
                    is_extra = user_clean.startswith(f"extra {word}")

                    if is_additive:
                        # "more cheese" - add the extracted quantity
                        existing["quantity"] = existing.get("quantity", 1) + quantity
                    elif is_extra:
                        # "extra cheese" - add 1 more
                        existing["quantity"] = existing.get("quantity", 1) + 1
                    else:
                        # "double cheese", "triple cheese" - set absolute quantity
                        existing["quantity"] = quantity

                    display_name = existing.get("display_name", word.title())
                    display_qty = existing["quantity"]
                    added_names.append(f"{display_name} x{display_qty}")
                    matched_slugs.add(word)
                    logger.info("ATTRIBUTE_QUANTITY: Set '%s' to qty=%d", word, display_qty)

                else:
                    # Case B: No existing selection - check options count
                    options = attr_config.get("options", [])
                    if len(options) == 1:
                        # Single option: add it directly
                        opt = options[0]
                        quantity, _ = extract_additive_quantity(user_clean, word)
                        opt_price = opt.get("price") or opt.get("price_modifier") or 0
                        item.add_selection(
                            slug=opt["slug"],
                            category=word,
                            quantity=quantity,
                            display_name=opt.get("display_name", opt["slug"]),
                            price=opt_price,
                        )
                        display_name = opt.get("display_name", opt["slug"])
                        added_names.append(display_name)
                        matched_slugs.add(word)
                        logger.info(
                            "ATTRIBUTE_SINGLE_OPTION: Added '%s' for category '%s'",
                            opt["slug"], word
                        )
                    elif len(options) > 1:
                        # Multiple options: ask which one
                        order.pending_field = f"{item.menu_item_type}:{word}"
                        question = attr_config.get("question_text", f"What kind of {word}?")
                        return StateMachineResult(message=question, order=order)

        # If we matched via attribute category patterns, we're done
        if matched_slugs:
            self._recalculate_item_price(item)
            added_text = format_english_list(added_names)
            return self._ask_customization_checkpoint(item, order, f"{added_text} added")

        return None

    def _try_word_by_word_match(
        self,
        words: list[str],
        item: "MenuItemTask",
        added_names: list[str],
        unmatched: list[str],
    ) -> None:
        """Word-by-word matching for multi-ingredient input.

        Handles "salt pepper ketchup" by matching each word individually.

        Args:
            words: Split words from input
            item: Menu item being configured
            added_names: List to append matched ingredient names to
            unmatched: List to append unmatched words to
        """
        for word in words:
            # Skip quantity modifier words and stopwords - don't report them as "not found"
            if word in QUANTITY_MODIFIER_WORDS or word in ARTICLES or word in ACTION_VERB_STOPWORDS:
                continue

            quantity, search_term = extract_leading_quantity(word)
            quantity = quantity or 1
            if not search_term:
                search_term = word

            matches = menu_cache.find_matching_ingredients(search_term)

            if len(matches) == 1:
                match = matches[0]
                item.add_selection(
                    slug=match["slug"],
                    category=match["category"],
                    display_name=match["name"],
                    quantity=quantity,
                    price=match.get("base_price", 0.0),
                    increment_if_exists=True,
                )
                added_names.append(match["name"])
                logger.info(
                    "INGREDIENT_FALLBACK: Added '%s' (category=%s) from word '%s'",
                    match["name"], match["category"], word
                )
            elif len(matches) > 1:
                # Multiple matches - ambiguous, skip for now
                logger.debug(
                    "INGREDIENT_FALLBACK: Multiple matches for '%s', skipping", word
                )
                unmatched.append(word)
            else:
                # No match
                unmatched.append(word)
