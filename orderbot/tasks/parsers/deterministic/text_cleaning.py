"""
Text Cleaning Utilities for Deterministic Parser.

Functions for cleaning and normalizing user input text before parsing,
including noise phrase stripping, duplicate modification filtering,
and replacement item extraction.
"""

from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from ...utils.text import normalize_text

if TYPE_CHECKING:
    from .result_types import AttributeExtractionResult

logger = logging.getLogger(__name__)


def _collapse_repeated_words(text: str) -> str:
    """Collapse consecutive repeated words (stutters).

    In chat and speech, people don't intentionally repeat words for meaning.
    Repeated words are stutters, not double negatives or emphasis.

    Examples:
        "no no changes" → "no changes"
        "yes yes" → "yes"
        "the the classic" → "the classic"

    Args:
        text: User input text.

    Returns:
        Text with consecutive duplicate words collapsed.
    """
    lines = text.split('\n')
    collapsed_lines = []
    for line in lines:
        words = line.split()
        if len(words) <= 1:
            collapsed_lines.append(line)
            continue
        result = [words[0]]
        for word in words[1:]:
            if word.lower() != result[-1].lower():
                result.append(word)
        collapsed_lines.append(" ".join(result))
    return "\n".join(collapsed_lines)


def _extract_replacement_item(match: re.Match) -> str | None:
    """Extract the replacement item text from a REPLACE_ITEM_PATTERN match.

    Iterates over capture groups and strips leading articles.
    """
    for i in range(1, 11):  # 10 capture groups in REPLACE_ITEM_PATTERN
        if match.group(i):
            item = match.group(i).strip()
            item = re.sub(r"^(?:a|an)\s+", "", item, flags=re.IGNORECASE)
            return item
    return None


def _filter_duplicate_modifications(
    additions: list[dict[str, str]],
    attr_result: "AttributeExtractionResult",
    item_type: str | None,
) -> list[dict[str, str]]:
    """Remove modifier additions that duplicate already-extracted attribute options.

    When both attribute extraction and modification extraction match the same
    ingredient (e.g., "jalapeño cream" matches both as a spread attribute option
    and as an ingredient modifier), remove the modifier to avoid duplicates.

    Resolves modifier slugs to canonical ingredient slugs via ingredient details
    and checks against the set of attribute option slugs already extracted.
    """
    if not item_type or not additions:
        return additions

    # Collect canonical slugs of attribute options that were extracted
    extracted_option_slugs: set[str] = set()
    for value in attr_result.values.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    slug = item.get("slug", "")
                    if slug:
                        extracted_option_slugs.add(slug.lower())
        elif isinstance(value, str):
            extracted_option_slugs.add(value.lower())

    if not extracted_option_slugs:
        return additions

    # Build pattern -> ingredient slug mapping to resolve modifier aliases
    pattern_to_slug: dict[str, str] = {}
    ingredients_by_cat = menu_cache.get_ingredients_by_category_for_item_type(item_type)
    for cat in ingredients_by_cat:
        for detail in menu_cache.get_ingredient_details(cat):
            detail_slug = detail.get("slug", "").lower()
            for pattern in detail.get("patterns", []):
                pattern_to_slug[pattern.lower()] = detail_slug

    filtered = []
    for add in additions:
        mod_slug = add.get("slug", "").lower()
        # Check 1: Resolve to canonical ingredient slug for exact match
        canonical_slug = pattern_to_slug.get(mod_slug, mod_slug)
        if canonical_slug in extracted_option_slugs:
            logger.debug(
                "Filtered duplicate modification '%s' (canonical: %s) - already an attribute option",
                mod_slug, canonical_slug,
            )
            continue
        # Check 2: Component-word subset match
        # e.g. "nova" words are a subset of "tofu_nova_cream_cheese" → filter out
        mod_words = set(mod_slug.replace("-", "_").split("_"))
        is_subset = False
        for opt_slug in extracted_option_slugs:
            opt_words = set(opt_slug.replace("-", "_").split("_"))
            if mod_words and mod_words < opt_words:  # proper subset
                logger.debug(
                    "Filtered modification '%s' - words %s are a subset of attribute option '%s'",
                    mod_slug, mod_words, opt_slug,
                )
                is_subset = True
                break
        if is_subset:
            continue
        filtered.append(add)

    return filtered


def _strip_noise_phrases(text: str) -> str:
    """Strip container words, indifference phrases, and conditional phrases.

    Removes patterns like:
    - "a bottle of orange juice" -> "orange juice"
    - "coffee or whatever" -> "coffee"
    - "bagel if you have it" -> "bagel"
    """
    # Strip container/packaging words that don't affect item identification
    # e.g., "a bottle of orange juice" -> "a  orange juice" -> parsers match "orange juice"
    # Only strips "container of" patterns (requires "of" to avoid false positives)
    text = re.sub(
        r'\b(?:bottles?|glasses?|cups?|cans?|boxes?|cartons?|bags?|packs?|jars?|jugs?)\s+of\s+',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Strip trailing indifference/flexibility phrases that don't affect item identification
    # e.g., "orange juice or whatever they have" -> "orange juice"
    # e.g., "a coffee or something" -> "a coffee"
    text = re.sub(
        r'\s+or\s+(?:whatever(?:\s+(?:you|they|you guys)\s+(?:have|got|recommend))?'
        r'|something(?:\s+like\s+that)?'
        r'|anything(?:\s+(?:like\s+that|similar|really|works?))?'
        r')\s*$',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Also strip "if you have it/that", "if that's available", "if possible", etc.
    text = re.sub(
        r'\s+if\s+(?:you\s+have\s+(?:it|that|any|some)'
        r'|that(?:\'s|\s+is)\s+(?:available|okay|ok|fine|possible|alright|all\s+right|cool)'
        r'|that\s+works'
        r'|it(?:\'s|\s+is)\s+not\s+too\s+much\s+trouble'
        r'|that(?:\'s|\s+is)\s+not\s+too\s+much\s+trouble'
        r'|possible'
        r'|you\s+don(?:\'t|\s+not)\s+mind(?:\s+me\s+asking)?'
        r'|you\s+wouldn(?:\'t|\s+not)\s+mind'
        r'|you\s+could'
        r'|you\s+would'
        r'|you\s+can'
        r')\s*$',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Strip trailing pleasantries that don't affect item identification
    text = re.sub(
        r',?\s+(?:when(?:ever)?\s+you(?:\s+get\s+a\s+chance|(?:\'re|\s+are)\s+ready)'
        r'|no\s+rush'
        r'|that\s+would\s+be\s+(?:great|nice)'
        r'|that(?:\'d|\s+would)\s+be\s+(?:great|nice)'
        r'|i(?:\'d|\s+would)\s+appreciate\s+it'
        r'|much\s+appreciated'
        r')\s*$',
        '', text, flags=re.IGNORECASE
    ).strip()

    return text


def _strip_one_leading_attribute_word(text: str) -> tuple[str | None, str | None]:
    """Strip the FIRST leading attribute option word only.

    Unlike _strip_leading_attribute_words which strips ALL leading attribute words
    in a while loop, this strips exactly one word and returns immediately. Used for
    iterative retry where each stripped word is tested individually.

    Returns:
        (stripped_text, stripped_word) if a word was removed, (None, None) otherwise.
    """
    attr_option_words = menu_cache.get_all_attribute_option_words()
    text_lower = normalize_text(text)

    # Try longest options first (e.g., "extra large" before "extra")
    for option_word in sorted(attr_option_words.keys(), key=len, reverse=True):
        if re.match(rf'^{re.escape(option_word)}\s+', text_lower):
            stripped = text_lower[len(option_word):].strip()
            if stripped:
                return stripped, option_word
    return None, None


def _strip_leading_attribute_words(text: str) -> str | None:
    """Strip leading attribute option words from text for retry parsing.

    When all parsers fail, the user may have prepended attribute words
    (like "large", "iced") to a non-configurable item. Strip them and
    allow re-parsing.

    Returns stripped text if any words were removed, None otherwise.
    """
    attr_option_words = menu_cache.get_all_attribute_option_words()
    text_lower = normalize_text(text)
    original = text_lower

    while text_lower:
        matched = False
        # Try longest options first (e.g., "extra large" before "extra")
        for option_word in sorted(attr_option_words.keys(), key=len, reverse=True):
            if re.match(rf'^{re.escape(option_word)}\s+', text_lower):
                text_lower = text_lower[len(option_word):].strip()
                matched = True
                break
        if not matched:
            break

    if not text_lower or text_lower == original:
        return None
    return text_lower
