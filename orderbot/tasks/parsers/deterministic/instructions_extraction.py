"""
Special Instructions Extraction.

Extracts special instructions (light, extra, no, on the side, leave room, etc.)
from user input text. All qualifier patterns are loaded from the database.
"""

import re
import logging

from orderbot.cache import menu_cache

from ..constants import SKIP_WORDS

logger = logging.getLogger(__name__)

# Regex to capture one or two adjacent words (stops at conjunctions/articles)
_ADJACENT_WORD_RE = r'(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)'


def extract_special_instructions_from_input(user_input: str) -> list[str]:
    """
    Extract special instructions from user input.

    Args:
        user_input: The raw user input string

    Returns:
        List of instruction strings like ["light cream cheese", "extra bacon", "leave room"]
    """
    instructions = []
    input_lower = user_input.lower()

    # Get qualifier patterns from database (sorted longest first)
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    for pattern_text in qualifier_patterns:
        info = menu_cache.get_qualifier_info(pattern_text)
        if not info:
            continue
        normalized = info["normalized_form"]
        category = info["category"]

        # "position" qualifiers (e.g. "on the side") appear after the item word
        if category == "position":
            # Pattern: <word> <qualifier>
            regex = rf'\b{_ADJACENT_WORD_RE}\s+{re.escape(pattern_text)}\b'
            for match in re.finditer(regex, input_lower):
                item = match.group(1).strip()
                if item.lower() in SKIP_WORDS:
                    continue
                instruction = f"{item} {normalized}"
                if instruction not in instructions:
                    instructions.append(instruction)
                    logger.debug("Extracted special instruction: '%s' from input", instruction)
        else:
            # Prefix qualifiers (amount, preparation, etc.): <qualifier> <word>
            regex = rf'\b{re.escape(pattern_text)}\s+{_ADJACENT_WORD_RE}'
            for match in re.finditer(regex, input_lower):
                item = match.group(1).strip()
                if item.lower() in SKIP_WORDS:
                    continue
                instruction = f"{normalized} {item}"
                if instruction not in instructions:
                    instructions.append(instruction)
                    logger.debug("Extracted special instruction: '%s' from input", instruction)

    # Check standalone patterns (e.g., "leave room", "cut in half", "melted")
    # Data-driven: patterns loaded from database via menu_cache
    for pattern in menu_cache.get_standalone_instruction_patterns():
        match = pattern.search(input_lower)  # Already compiled with IGNORECASE
        if match:
            instruction = match.group(0).strip()
            if instruction and instruction not in instructions:
                instructions.append(instruction)
                logger.debug("Extracted standalone instruction: '%s' from input", instruction)

    return instructions
