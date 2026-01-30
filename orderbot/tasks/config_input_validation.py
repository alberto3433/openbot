"""
Input Validation for Item Configuration.

Provides utilities for validating user input during item configuration,
including off-topic detection, modifier inquiry detection, and answer validation.

Extracted from configuring_item_handler.py for better separation of concerns.
"""

import logging
import re

from orderbot.menu_data_cache import menu_cache
from .models import parse_pending_field
from .pending_fields import PendingField
from .parsers.constants import OFF_TOPIC_PATTERNS
from .normalization import strip_ordering_prefix

logger = logging.getLogger(__name__)

__all__ = [
    "detect_modifier_inquiry",
    "is_valid_answer_for_pending_field",
    "is_off_topic_request",
    "get_cached_config_answers",
]

# Pattern to detect modifier inquiries like "what toppings do you have?"
# Captures the category (e.g., "toppings", "sweeteners", "spreads")
_MODIFIER_INQUIRY_PATTERN = re.compile(
    r"what (\w+(?:\s+\w+)?)\s+do\s+you\s+(?:have|offer|carry)",
    re.IGNORECASE
)


def detect_modifier_inquiry(user_input: str) -> str | None:
    """Detect modifier inquiry requests like 'what toppings do you have?'

    Args:
        user_input: The user's input text

    Returns:
        The extracted category (e.g., "toppings", "sweeteners") or None if not a modifier inquiry
    """
    match = _MODIFIER_INQUIRY_PATTERN.search(user_input)
    if match:
        category = match.group(1).strip().lower()
        logger.debug("Detected modifier inquiry for category: %s", category)
        return category
    return None


def is_valid_answer_for_pending_field(user_input: str, pending_field: str | None) -> bool:
    """Check if user input could be a valid answer to the current configuration question.

    This is used to prevent false positive change request detection. If the user says
    "I want avocado" when asked about toppings, we should treat it as an answer,
    not as a modifier change request.

    Args:
        user_input: The user's input text
        pending_field: The current configuration field in "item_type:attr_slug" format

    Returns:
        True if the input appears to be a valid answer for the pending field
    """
    if not pending_field:
        return False

    # Extract the potential answer value
    answer_value = strip_ordering_prefix(user_input).lower()
    if not answer_value:
        return False

    # Parse the pending_field to get item_type and attr_slug
    item_type_slug, attr_slug = parse_pending_field(pending_field)

    # Handle customization_checkpoint and customization_selection specially
    # These are open-ended fields where any valid ingredient is a valid answer
    if attr_slug in (PendingField.CUSTOMIZATION_CHECKPOINT, PendingField.CUSTOMIZATION_SELECTION):
        # Check if this is a known ingredient (toppings, proteins, cheeses, etc.)
        try:
            if menu_cache.is_known_modifier(answer_value):
                logger.debug("Found known modifier '%s' during customization", answer_value)
                return True
        except Exception as e:
            logger.debug("Error checking ingredient for customization: %s", e)
        return False

    # For standard "item_type:attr_slug" format, need both parts
    if not item_type_slug or not attr_slug:
        return False

    # Check if this value is valid for the current attribute
    try:
        # Get the valid options for this attribute
        attrs = menu_cache.get_item_type_attributes(item_type_slug)
        if attr_slug in attrs:
            attr_config = attrs[attr_slug]
            # Check if the value matches any option
            for opt in attr_config.get("options", []):
                opt_name = opt.get("display_name", "").lower()
                opt_slug = opt.get("slug", "").lower()
                if answer_value == opt_name or answer_value == opt_slug:
                    return True
                # Also check if answer_value is contained in option name
                if opt_name and answer_value in opt_name:
                    return True

            # For ingredient-based attributes, check against ingredients
            if attr_config.get("loads_from_ingredients"):
                # Check if this is a known ingredient
                if menu_cache.is_known_modifier(answer_value):
                    return True
    except Exception as e:
        logger.debug("Error checking valid answer for %s: %s", pending_field, e)

    return False


def _get_valid_config_answers() -> set[str]:
    """Get the set of valid configuration answers from the database.

    Combines affirmative/negative response patterns with all attribute options
    from the database. This is fully data-driven - no hardcoded values.

    Returns:
        Set of lowercase answer words that are valid responses to config questions

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded or configuration data is missing
    """
    # Start with affirmative/negative response patterns from database
    answers = menu_cache.get_response_patterns("affirmative")
    answers.update(menu_cache.get_response_patterns("negative"))

    # Get all attribute option words from database (includes negation variants)
    # This covers: size, temperature, toasted/not toasted, bagel types, side items, etc.
    db_answers = menu_cache.get_all_config_answer_words()
    answers.update(db_answers)

    return answers


# Cache the config answers to avoid repeated database calls
_cached_config_answers: set[str] | None = None


def get_cached_config_answers() -> set[str]:
    """Get cached valid config answers, loading from database if needed."""
    global _cached_config_answers
    if _cached_config_answers is None:
        _cached_config_answers = _get_valid_config_answers()
    return _cached_config_answers


def is_off_topic_request(user_input: str, pending_field: str | None = None) -> bool:
    """Check if user input is an off-topic request during configuration.

    This function determines if the user is asking about something unrelated to
    the current configuration question. It's data-driven - keywords are loaded
    from the database based on the attribute being configured.

    Args:
        user_input: The user's input text
        pending_field: The current configuration field in "item_type:attr_slug" format
                      (e.g., "bagel:spread", "sized_beverage:size")

    Returns:
        True if the request is off-topic and should trigger a redirect
    """
    input_lower = user_input.lower().strip()

    # Get valid config answers from database (cached)
    valid_config_answers = get_cached_config_answers()

    # First check if this looks like a valid config answer
    # Simple answers like "small", "large", "hot", "iced", etc.
    if input_lower in valid_config_answers:
        return False

    # Check for valid answers with minor variations
    for answer in valid_config_answers:
        if input_lower == answer or input_lower == f"{answer} please":
            return False

    # Check if the question is RELEVANT to the current config question
    if pending_field:
        # Parse the pending_field to get item_type and attr_slug
        item_type_slug, attr_slug = parse_pending_field(pending_field)

        # Generic "what do you have?" / "what kind do you have?" / "what are my options?"
        # These are always relevant when asked during configuration (truly universal patterns)
        generic_option_patterns = [
            "what do you have",
            "what kind do you have",
            "what kinds do you have",
            "what type do you have",
            "what types do you have",
            "what are my options",
            "what are the options",
            "what options do you have",
            "what choices",
        ]
        if any(pattern in input_lower for pattern in generic_option_patterns):
            return False  # Let them ask about options

        # Allow "what X do you have?" for any ingredient category (e.g., "what toppings do you have?")
        # This allows users to inquire about menu options even during item configuration
        if re.search(r"what \w+ do you have", input_lower):
            return False  # Let them ask about any category

        # Data-driven keyword matching: if this is an attribute config field,
        # get relevant keywords from the database
        if item_type_slug and attr_slug:
            try:
                relevant_keywords = menu_cache.get_relevant_keywords_for_attribute(
                    item_type_slug, attr_slug
                )
                if any(kw in input_lower for kw in relevant_keywords):
                    return False  # Question is relevant to the current attribute
            except Exception as e:
                logger.debug("Keyword lookup failed for %s.%s: %s", item_type_slug, attr_slug, e)

            # Also allow templatized questions: "what {attr} do you have?"
            # e.g., "what spreads do you have?" when configuring spread
            attr_display = attr_slug.replace("_", " ")
            if attr_display in input_lower:
                return False
            # Check for plural form
            if f"{attr_display}s" in input_lower:
                return False

        # During customization_checkpoint or customization_selection, "add X" commands are valid
        # The bot is specifically offering options like "Add Egg, Extra Cheese, Toppings"
        if attr_slug in (PendingField.CUSTOMIZATION_CHECKPOINT, PendingField.CUSTOMIZATION_SELECTION):
            # Allow "what X do you have?" questions - user is asking about offered options
            if re.search(r"what \w+ do you have", input_lower):
                return False
            # Allow "add X" commands since the bot offered these as valid choices
            if input_lower.startswith("add "):
                return False
            # Get customization keywords from database (available modifier categories)
            try:
                # Load customization options from the item type's modifiable attributes
                if item_type_slug:
                    attrs = menu_cache.get_item_type_attributes(item_type_slug)
                    for attr_config in attrs.values():
                        for opt in attr_config.get("options", []):
                            opt_name = opt.get("display_name", "").lower()
                            if opt_name and opt_name in input_lower:
                                return False
            except Exception as e:
                logger.debug("Customization options lookup failed for %s: %s", item_type_slug, e)
            # Allow ingredient category names (data-driven from database)
            try:
                category_names = menu_cache.get_all_ingredient_categories()
                if any(cat in input_lower for cat in category_names):
                    return False
            except Exception as e:
                logger.debug("Ingredient category lookup failed: %s", e)

    # Check if it matches any off-topic pattern
    for pattern in OFF_TOPIC_PATTERNS:
        if pattern.search(user_input):
            # Special case: "make it X" where X is a valid config answer
            if pattern.pattern.startswith("^make"):
                # Check against all valid config answers (database-driven)
                for answer in valid_config_answers:
                    if answer in input_lower:
                        return False
            return True

    return False
