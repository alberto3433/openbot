"""
Modification Parsing Functions for Deterministic Parsing.

This module contains functions for parsing modifications to existing items,
including adding modifiers, extracting modifications, and "add more" requests.
"""

import re
import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import (
    OpenInputResponse,
    QualifierConflict,
)

from ..constants import (
    get_known_menu_items,
    clean_extracted_text,
    SKIP_WORDS,
    SKIP_WORDS_BASIC,
    SKIP_WORDS_PREPOSITIONS,
)
from ..intent_patterns import ADD_MORE_PATTERN
from ..quantity_utils import extract_leading_quantity

from .extraction import extract_modifiers_with_qualifiers, extract_attribute_values

logger = logging.getLogger(__name__)


# Cache for dynamic terminator pattern
_ATTRIBUTE_TERMINATORS_PATTERN: str | None = None


def _get_attribute_terminators_pattern() -> str:
    """Build regex alternation of all attribute option words from database.

    These words act as terminators for 'with X' patterns, e.g.:
    - "with butter toasted" -> butter is the modifier, toasted terminates
    - "with cream cheese scooped" -> cream cheese is the modifier, scooped terminates

    Returns:
        Regex alternation string like "toasted|scooped|iced|hot|large|medium|..."
    """
    global _ATTRIBUTE_TERMINATORS_PATTERN
    if _ATTRIBUTE_TERMINATORS_PATTERN is not None:
        return _ATTRIBUTE_TERMINATORS_PATTERN

    # Get all attribute option words from database
    attr_words = menu_cache.get_all_attribute_option_words()

    # Filter to reasonable terminators (2+ chars, not common words)
    filter_words = SKIP_WORDS_BASIC | SKIP_WORDS_PREPOSITIONS | {'no', 'yes'}
    terminators = {word for word in attr_words.keys()
                   if len(word) >= 2 and word not in filter_words}

    # Sort by length descending (longer matches first)
    sorted_terminators = sorted(terminators, key=len, reverse=True)

    # Build alternation pattern
    _ATTRIBUTE_TERMINATORS_PATTERN = "|".join(re.escape(t) for t in sorted_terminators)
    return _ATTRIBUTE_TERMINATORS_PATTERN


# =============================================================================
# Menu Item Modifications Extraction
# =============================================================================

def _extract_menu_item_modifications(
    text: str, item_type: str | None = None
) -> dict[str, list[dict[str, str]]]:
    """Extract modifications like 'with mayo and mustard' or 'no onions' from text.

    This is the data-driven version that only accepts ingredients explicitly
    linked to the item type in the database.

    Args:
        text: The user input text
        item_type: The item type slug (e.g., "sandwich", "salad"). If None,
            returns empty result.

    Returns:
        Dict with 'additions' and 'removals' lists. Each entry is a dict with:
        - slug: The ingredient slug (lowercase, normalized)
        - category: The ingredient category (e.g., "topping", "protein")

    Examples:
        >>> _extract_menu_item_modifications("with mayo and lettuce", "sandwich")
        {"additions": [{"slug": "mayo", "category": "condiment"}, {"slug": "lettuce", "category": "topping"}], "removals": []}

        >>> _extract_menu_item_modifications("no onions please", "sandwich")
        {"additions": [], "removals": [{"slug": "onion", "category": "topping"}]}
    """
    result: dict[str, list[dict[str, str]]] = {"additions": [], "removals": []}

    if not item_type:
        logger.debug("No item_type provided, returning empty modifications")
        return result

    text_lower = text.lower()

    # Get valid ingredients for this item type, organized by category
    # This is the data-driven lookup that replaces hardcoded known_additions
    ingredients_by_category = menu_cache.get_ingredients_by_category_for_item_type(item_type)
    if not ingredients_by_category:
        logger.debug("No ingredients defined for item type '%s'", item_type)
        return result

    # Build reverse lookup: ingredient name -> category
    ingredient_to_category: dict[str, str] = {}
    for category, ingredients in ingredients_by_category.items():
        for ingredient in ingredients:
            ingredient_to_category[ingredient.lower()] = category

    def match_ingredient(term: str) -> dict[str, str] | None:
        """Try to match a term against valid ingredients for the item type."""
        term = term.strip().lower()
        if not term:
            return None

        # Handle "extra X" by stripping the "extra" prefix
        if term.startswith("extra "):
            term = term[6:].strip()

        # Direct match
        if term in ingredient_to_category:
            return {"slug": term, "category": ingredient_to_category[term]}

        # Try singular form (remove trailing 's')
        if term.endswith("s") and len(term) > 2:
            singular = term[:-1]
            if singular in ingredient_to_category:
                return {"slug": singular, "category": ingredient_to_category[singular]}

        # Try with 's' added (in case user said singular but DB has plural)
        plural = term + "s"
        if plural in ingredient_to_category:
            return {"slug": plural, "category": ingredient_to_category[plural]}

        return None

    # Pattern for "with X and Y" or "with X, Y, and Z"
    # Build dynamic terminator pattern from attribute options
    attr_terminators = _get_attribute_terminators_pattern()
    with_pattern = re.search(
        rf'\bwith\s+(.+?)(?:\s*(?:please|thanks|{attr_terminators})|\s*$)',
        text_lower,
        re.IGNORECASE
    )

    if with_pattern:
        with_text = with_pattern.group(1).strip()
        # Remove trailing punctuation
        with_text = clean_extracted_text(with_text)

        # Split by "and" and commas
        parts = re.split(r'\s*(?:,\s*|\s+and\s+)\s*', with_text)
        for part in parts:
            part = part.strip()
            # Exclude common non-modifier words
            if part in SKIP_WORDS:
                continue

            matched = match_ingredient(part)
            if matched:
                result["additions"].append(matched)

    # Pattern for "no X" modifications
    no_pattern = re.findall(r'\bno\s+(\w+(?:\s+\w+)?)', text_lower)
    for item in no_pattern:
        item = item.strip()
        # Skip common false positives (language patterns, not food)
        skip_items = {'thanks', 'problem', 'worries', 'that', 'more', 'need'}
        if item in skip_items:
            continue

        matched = match_ingredient(item)
        if matched:
            result["removals"].append(matched)

    logger.debug("Extracted modifications from '%s' for item_type '%s': %s", text[:50], item_type, result)
    return result


# =============================================================================
# Modify Existing Item Parsing
# =============================================================================

def _parse_modify_existing_item(text: str) -> OpenInputResponse | None:
    """Detect requests to modify an existing cart item with a modifier.

    Catches patterns like:
    - "can I have cream cheese on the cinnamon raisin bagel"
    - "put butter on the plain bagel"
    - "add mayo to the sandwich"
    - "make the bagel with scallion cream cheese"
    - "make it with butter"

    Item type names are loaded dynamically from the database, so this function
    works with any item types.

    This must be called BEFORE menu item matching to prevent modifiers like
    "scallion cream cheese" from being matched to menu items.

    Returns OpenInputResponse with modify_existing_item=True if detected, None otherwise.
    """
    text_lower = text.lower().strip()

    # Build dynamic item type pattern from database
    item_type_names = menu_cache.get_item_type_names_for_regex()
    if not item_type_names:
        return None

    # Build regex alternation:
    # Names are sorted by length (longest first) so "deli sandwich" matches before "sandwich"
    item_type_pattern = "(?:" + "|".join(re.escape(name) for name in item_type_names) + ")"

    modifier_part = None
    target_description = None

    # === Pattern Group 1: MODIFIER preposition TARGET item_type ===
    # These patterns have modifier BEFORE the target item type
    # Group 1: modifier, Group 2: item description (e.g., "plain", "cinnamon raisin")
    modifier_before_target_patterns = [
        # "can I have X on the Y {item_type}"
        rf"(?:can\s+i\s+(?:have|get)|i(?:'d|\s+would)\s+like)\s+(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}",
        # "put X on the Y {item_type}"
        rf"(?:put|add)\s+(.+?)\s+(?:on|to)\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}",
        # "X on the Y {item_type}" (simple form)
        rf"^(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}$",
        # "i want X on the Y {item_type}"
        rf"i\s+want\s+(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}",
    ]

    for pattern in modifier_before_target_patterns:
        match = re.search(pattern, text_lower)
        if match:
            modifier_part = match.group(1).strip()
            target_description = match.group(2).strip()
            break

    # === Pattern Group 2: TARGET item_type with MODIFIER ===
    # These patterns have target BEFORE the modifier (reversed order)
    # "make the plain {item_type} with X" - Group 1: item description, Group 2: modifier
    if not modifier_part:
        pattern = rf"make\s+(?:the|my)\s+(.+?)\s+{item_type_pattern}\s+with\s+(.+?)(?:\s+(?:please|thanks))?$"
        match = re.search(pattern, text_lower)
        if match:
            target_description = match.group(1).strip()
            modifier_part = match.group(2).strip()

    # === Pattern Group 3: Implicit target (IT or generic item type) ===
    # "make it with X", "make the bagel with X", "put X on it"
    # target_description stays None to indicate "find any/last item"
    if not modifier_part:
        # First try patterns with generic item type (no specific description)
        generic_patterns = [
            # "make the {item_type} with X" - no specific description
            rf"make\s+(?:the|my)\s+{item_type_pattern}\s+with\s+(.+?)(?:\s+(?:please|thanks))?$",
        ]
        for pattern in generic_patterns:
            match = re.search(pattern, text_lower)
            if match:
                modifier_part = match.group(1).strip()
                target_description = None
                break

        # Then try implicit "it" patterns
        if not modifier_part:
            implicit_target_patterns = [
                # "make it with X"
                r"make\s+it\s+with\s+(.+?)(?:\s+(?:please|thanks))?$",
                # "can you make it with X" / "could you make it with X instead"
                r"(?:can|could|would)\s+you\s+(?:make|have|do)\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\s+(?:please|thanks))?$",
                # "put X on it"
                r"(?:put|add)\s+(.+?)\s+(?:on|to)\s+it\b",
                # "i want X on it"
                r"i\s+want\s+(.+?)\s+(?:on|to)\s+it\b",
                # "can I have X on it"
                r"(?:can\s+i\s+(?:have|get))\s+(.+?)\s+(?:on|to)\s+it\b",
            ]
            for pattern in implicit_target_patterns:
                match = re.search(pattern, text_lower)
                if match:
                    modifier_part = match.group(1).strip()
                    target_description = None
                    break

    # No pattern matched
    if not modifier_part:
        return None

    # Clean up modifier_part - remove trailing "please/thanks"
    modifier_part = re.sub(r"\s+(?:please|thanks)$", "", modifier_part).strip()

    # Skip if modifier_part is empty or too short
    if not modifier_part or len(modifier_part) < 2:
        return None

    logger.info(
        "MODIFY EXISTING ITEM: '%s' -> modifier=%s, target=%s",
        text[:50], modifier_part, target_description
    )

    return OpenInputResponse(
        modify_existing_item=True,
        modify_target_description=target_description,
        modify_add_modifiers=[modifier_part],
    )


# =============================================================================
# Add Modifier to Item Parsing
# =============================================================================

def _parse_add_modifier_to_item(text: str) -> OpenInputResponse | None:
    """Detect requests to add modifiers to an existing item.

    Catches patterns like:
    - "add X" - add single modifier to current/last item
    - "add X and Y" - add multiple modifiers
    - "add X to the Y" - add modifier to specific item
    - "extra X" / "more X" - alternative action words
    - "put X on it" - implicit target

    Does NOT catch patterns where the modifier text matches a known menu item
    (e.g., if "bacon egg and cheese" is a menu item alias, "add bacon egg and cheese"
    will be treated as a menu item order, not a modifier-add request).

    Returns OpenInputResponse with modify_existing_item=True if detected, None otherwise.
    """
    text_lower = text.lower().strip()

    # Get known modifiers from all ingredient categories (database-driven)
    # Include both food and beverage modifiers (milk, sugar, syrup, etc.)
    all_modifiers: set[str] = set()
    for category in menu_cache.get_all_ingredient_categories():
        ingredients = menu_cache.get_ingredients(category)
        all_modifiers.update(ingredients)

    # === Pattern Group 1: "add/put/extra/more MODIFIER to the TARGET" ===
    # Captures: modifier(s) and target item
    target_patterns = [
        # "add bacon to the bagel" / "add bacon to the plain bagel"
        r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:the|my)\s+(.+?)$",
        # "add milk to tea" - single-word target, no article required
        # Using (\w+)$ to capture only single-word targets, avoiding false positives
        # like "add milk to my order". Excludes "it" which is handled by implicit patterns.
        r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?!it\b)(\w+)$",
    ]

    modifier_text = None
    target_item = None

    for pattern in target_patterns:
        match = re.match(pattern, text_lower)
        if match:
            modifier_text = match.group(1).strip()
            target_item = match.group(2).strip()
            break

    # === Pattern Group 2: "add/extra/more/put MODIFIER" (no explicit target) ===
    if not modifier_text:
        no_target_patterns = [
            # "add bacon" / "add bacon and cheese"
            r"^(?:add|put)\s+(.+?)(?:\s+please)?$",
            # "extra bacon" / "extra cheese"
            r"^extra\s+(.+?)(?:\s+please)?$",
            # "more bacon" / "more cheese"
            r"^more\s+(.+?)(?:\s+please)?$",
        ]

        for pattern in no_target_patterns:
            match = re.match(pattern, text_lower)
            if match:
                modifier_text = match.group(1).strip()
                target_item = None  # Implicit - apply to last/current item
                break

    # === Pattern Group 3: "put MODIFIER on it" ===
    if not modifier_text:
        match = re.match(r"^put\s+(.+?)\s+on\s+it(?:\s+please)?$", text_lower)
        if match:
            modifier_text = match.group(1).strip()
            target_item = None  # "it" means last/current item

    # No pattern matched
    if not modifier_text:
        return None

    # Check if modifier_text matches a known menu item (e.g., "bacon egg and cheese")
    # If so, this is likely a menu item order, not a modifier-add request.
    # Only skip if the menu item match covers most of the modifier_text - we don't want
    # to skip "add bacon and cheese" just because "bacon" is also a menu item.
    if len(modifier_text.split()) > 1:
        menu_item, _, _ = _extract_menu_item_from_text(modifier_text)
        if menu_item:
            # Only skip if the menu item name covers most of the modifier text
            # This prevents "bacon and cheese" from being skipped because "bacon" matches
            menu_item_lower = menu_item.lower()
            modifier_text_lower = modifier_text.lower()
            # Check if menu item name is a significant portion of the modifier text
            if len(menu_item_lower) >= len(modifier_text_lower) * 0.7:
                logger.debug("ADD MODIFIER: '%s' matches menu item '%s', skipping", modifier_text, menu_item)
                return None

    # Check if modifier_text contains an item type trigger (e.g., "a latte with milk")
    # If so, this is a new item order, not a modifier-add request.
    # BUT: only skip if the trigger word is NOT also a known modifier (e.g., "bacon"
    # is both an omelette trigger and a valid modifier to add to items).
    # Import here to avoid circular imports
    from .item_parsing import _detect_item_type
    detected_item_type, detected_trigger = _detect_item_type(modifier_text)
    if detected_item_type and detected_trigger:
        # Only treat as new item if the trigger word is NOT a known modifier
        trigger_lower = detected_trigger.lower()
        if trigger_lower not in all_modifiers:
            logger.debug(
                "ADD MODIFIER: '%s' contains item type '%s' (trigger='%s'), treating as new item order",
                modifier_text, detected_item_type, detected_trigger
            )
            return None

    # === Parse modifier_text to extract individual modifiers with qualifiers ===
    # Handle "extra bacon and cheese on the side", "bacon, cheese, and tomato", etc.

    # Extract modifiers with qualifiers (e.g., "extra mayo" -> "mayo (extra)")
    modifiers_found, conflicts = extract_modifiers_with_qualifiers(
        modifier_text.lower(),
        all_modifiers
    )

    # Also check for category names (e.g., "cheese" in "add bacon and cheese")
    # This handles cases where "cheese" is a category name, not a specific ingredient
    # Include all categories (food + beverage) since "milk" is a beverage category
    all_categories = menu_cache.get_all_ingredient_categories()
    modifier_words = modifier_text.lower().split()
    for word in modifier_words:
        word_clean = word.strip(",;").strip()
        if word_clean in all_categories:
            # Found a category name - add it to modifiers if not already there
            category_title = word_clean.title()
            if category_title not in modifiers_found:
                modifiers_found.append(category_title)
                logger.debug("ADD MODIFIER: added category '%s' to modifiers", category_title)

    # If no known modifiers found (including categories), this isn't a modify request
    if not modifiers_found:
        return None

    # Clean up target_item if present (remove trailing "please", "thanks", etc.)
    if target_item:
        target_item = re.sub(r"\s*(please|thanks|thank you)$", "", target_item).strip()

    logger.info(
        "ADD MODIFIER TO ITEM: '%s' -> modifiers=%s, target=%s, conflicts=%s",
        text[:50], modifiers_found, target_item, conflicts
    )

    # Convert conflict tuples to QualifierConflict objects
    conflict_objects = None
    if conflicts:
        conflict_objects = [
            QualifierConflict(modifier=mod, qualifier1=q1, qualifier2=q2)
            for mod, q1, q2 in conflicts
        ]

    return OpenInputResponse(
        modify_existing_item=True,
        modify_target_description=target_item,
        modify_add_modifiers=modifiers_found,
        modify_qualifier_conflicts=conflict_objects,
    )


# =============================================================================
# Menu Item Extraction from Text
# =============================================================================

def _extract_menu_item_from_text(text: str) -> tuple[str | None, int, str | None]:
    """Try to extract a known menu item from text.

    Returns:
        Tuple of (canonical_name, quantity, matched_alias) where:
        - canonical_name: The canonical menu item name or None if not found
        - quantity: Number of items (default 1)
        - matched_alias: The alias text that was found in the input, or None.
            This is useful for finding the span of the match in the original text
            to exclude from attribute/modifier extraction.
    """
    text_lower = text.lower().strip()

    # Strip ordering phrases like "I want", "add", "can I get", etc.
    text_lower = re.sub(
        r'^(i\s+want\s+|i\'?d\s+like\s+|can\s+i\s+(get|have)\s+|give\s+me\s+|'
        r'let\s+me\s+(get|have)\s+|add\s+)', '', text_lower
    )
    text_lower = re.sub(r'^(a|an|the)\s+', '', text_lower)

    # Extract quantity using extract_leading_quantity which handles all quantity phrases
    # (a few, couple, dozen, etc.)
    extracted_qty, remaining = extract_leading_quantity(text_lower)
    if extracted_qty is not None:
        quantity = extracted_qty
        text_lower = remaining
        # Strip trailing filler words before singularizing to handle cases like
        # "chocolate babkas please" -> "chocolate babkas" -> "chocolate babka"
        # Without this, "please" at the end confuses the singularization
        trailing_fillers = {"please", "thanks", "thank", "you"}
        words = text_lower.split()
        while words and words[-1] in trailing_fillers:
            words.pop()
        text_lower = " ".join(words)
        # Singularize after extracting quantity: "two cookies" -> "cookie"
        text_lower = singularize(text_lower)
    else:
        quantity = 1

    for item in sorted(get_known_menu_items(), key=len, reverse=True):
        # Use word boundary check to prevent partial matches (e.g., "ham" matching "hamburger")
        # The item should appear as complete words in the text
        pattern = rf'\b{re.escape(item)}\b'
        if re.search(pattern, text_lower):
            # Check if user input is longer than matched item - if so, there might be
            # more specific items that match the full user phrase
            # Example: "orange juice" should NOT match the generic "Juice" item
            # if there are items like "Fresh Squeezed Orange Juice" that match better
            if len(text_lower) > len(item) + 3:  # Allow for minor variations
                # Check if the full user input word-matches any menu items
                more_specific_matches = menu_cache.find_items_by_word_match(text_lower)
                if more_specific_matches:
                    # Found more specific matches - skip this generic match
                    # and let the disambiguation flow handle it
                    logger.debug(
                        "Skipping generic match '%s' for '%s' - found %d more specific matches",
                        item, text_lower, len(more_specific_matches)
                    )
                    continue

            # Use database lookup to get canonical name
            canonical = menu_cache.resolve_menu_item_alias(item)
            if canonical is None:
                # Item not found in database - skip this match and try next
                continue
            return canonical, quantity, item

    return None, 0, None


# =============================================================================
# Add More Request Parsing
# =============================================================================

def _parse_add_more_request(text: str) -> OpenInputResponse | None:
    """
    Parse "add more" requests like "add a third orange juice", "add another coffee".

    These phrases mean "add 1 more" - ordinals like "third" mean "one more to make 3 total",
    NOT "add 3 items".

    Returns OpenInputResponse with quantity=1 for the item, or None if no match.
    """
    match = ADD_MORE_PATTERN.match(text.strip())
    if not match:
        return None

    item_text = match.group(1)
    if item_text:
        item_text = item_text.strip()
        # Clean up trailing punctuation
        item_text = clean_extracted_text(item_text)

    logger.info("ADD MORE REQUEST: detected in '%s', item_text='%s'", text[:50], item_text)

    # If no item specified, we can't parse deterministically - need context
    # The state machine will need to infer from the last item type
    if not item_text:
        # Return a special marker that indicates "add 1 more of whatever was last ordered"
        # For now, return None and let it fall through to LLM or state machine handling
        logger.debug("ADD MORE: no item specified, needs context")
        return None

    # Import here to avoid circular imports
    from .item_parsing import (
        _parse_configurable_item,
        _detect_configurable_item_type,
        build_parsed_item,
    )
    from .simple_item_parsing import _parse_simple_item_deterministic

    # Try simple (non-configurable) items first - they have more specific names
    # and don't require additional configuration questions
    simple_result = _parse_simple_item_deterministic(item_text)
    if simple_result and simple_result.parsed_items:
        # Set quantity to 1 for "add another"
        for item in simple_result.parsed_items:
            item.quantity = 1
        item_name = simple_result.parsed_items[0].item_name if hasattr(simple_result.parsed_items[0], 'item_name') else "item"
        logger.info("ADD MORE: parsed as simple item '%s' (qty=1)", item_name)
        return simple_result

    # Try configurable item types using data-driven parser
    configurable_result = _parse_configurable_item(item_text)
    if configurable_result and configurable_result.parsed_items:
        # Set quantity to 1 for "add another"
        for item in configurable_result.parsed_items:
            item.quantity = 1
        item_type = configurable_result.parsed_items[0].item_type if hasattr(configurable_result.parsed_items[0], 'item_type') else "item"
        logger.info("ADD MORE: parsed as configurable item '%s' (qty=1)", item_type)
        return configurable_result

    # Try menu item (includes signature items)
    menu_item, _, _ = _extract_menu_item_from_text(item_text)
    if menu_item:
        logger.info("ADD MORE: parsed as menu item '%s' (qty=1)", menu_item)
        return OpenInputResponse(
            parsed_items=[build_parsed_item(item_type="menu_item", item_name=menu_item, quantity=1)],
        )

    # Try to detect any configurable item type using data-driven triggers
    # This replaces hardcoded bagel detection
    detected_type, _ = _detect_configurable_item_type(item_text)
    if detected_type:
        # Extract attributes using data-driven extraction
        attr_values, _ = extract_attribute_values(item_text, detected_type)
        logger.info("ADD MORE: parsed as %s (qty=1), attrs=%s", detected_type, list(attr_values.keys()))
        return OpenInputResponse(
            parsed_items=[build_parsed_item(
                item_type=detected_type,
                attribute_values=attr_values,
            )],
        )

    # Try to resolve item via menu alias lookup (data-driven, replaces hardcoded drink_shorthands)
    resolved_item = menu_cache.resolve_menu_item_alias(item_text)
    if resolved_item:
        # Look up item type for the resolved item
        resolved_item_type = menu_cache.get_item_type_for_menu_item(resolved_item)
        logger.info("ADD MORE: resolved alias '%s' -> '%s' (type=%s, qty=1)", item_text[:30], resolved_item, resolved_item_type)
        return OpenInputResponse(
            parsed_items=[build_parsed_item(
                item_type=resolved_item_type or "menu_item",
                item_name=resolved_item,
                quantity=1,
            )],
        )

    # Couldn't parse the item - fall back to LLM
    logger.debug("ADD MORE: couldn't parse item '%s', falling back", item_text)
    return None
