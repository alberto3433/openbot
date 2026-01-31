"""
Special Instructions Extraction.

Extracts special instructions (light, extra, no, on the side, leave room, etc.)
from user input text.
"""

import re
import logging

from orderbot.cache import menu_cache

from ..constants import QUALIFIER_PATTERNS, SKIP_WORDS

logger = logging.getLogger(__name__)


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

    # Check qualifier patterns (e.g., "light X", "extra X", "no X")
    for pattern, qualifier in QUALIFIER_PATTERNS:
        for match in re.finditer(pattern, input_lower, re.IGNORECASE):
            item = match.group(1).strip()
            if item.lower() in SKIP_WORDS:
                continue
            if qualifier == 'no':
                instruction = f"no {item}"
            elif qualifier == 'on the side':
                instruction = f"{item} on the side"
            else:
                instruction = f"{qualifier} {item}"
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
