"""
LLM-based category inference for unrecognized menu items.

This module provides minimal LLM-based inference to determine what category
an unrecognized item might belong to. It uses the raw OpenAI client (not
instructor) for simplicity and speed.

Key differences from llm_parsers.py:
- No instructor dependency - uses raw OpenAI client
- Minimal tokens (max_tokens=20)
- Single word response (just category slug)
- Zero temperature for deterministic output
- Separate responsibility: category inference only
"""

import os
import logging

from ..utils.text import normalize_text

logger = logging.getLogger(__name__)


def infer_item_category(
    item_name: str,
    categories: list[dict],
    timeout: float = 5.0,
) -> str | None:
    """
    Use LLM to infer which menu category an unknown item likely belongs to.

    This is a fallback when curated suggestions and fuzzy matching both fail.
    The prompt is minimal and the response is just a category slug.

    Args:
        item_name: The unrecognized item name (e.g., "croissant", "pepsi")
        categories: List of category dicts with 'slug' and 'display_name' keys
        timeout: Request timeout in seconds

    Returns:
        Category slug if inference succeeds, None otherwise.

    Example:
        >>> categories = [
        ...     {"slug": "beverage", "display_name": "Beverages"},
        ...     {"slug": "pastry", "display_name": "Pastries"},
        ... ]
        >>> infer_item_category("croissant", categories)
        'pastry'
    """
    if not item_name or not categories:
        return None

    # Check for OpenAI API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.debug("LLM category inference skipped: OPENAI_API_KEY not set")
        return None

    # Build category list for prompt
    category_lines = []
    for cat in categories:
        slug = cat.get("slug", "")
        display = cat.get("display_name", slug)
        if slug:
            category_lines.append(f"- {slug}: {display}")

    if not category_lines:
        return None

    categories_text = "\n".join(category_lines)

    prompt = f"""What food/drink category best matches "{item_name}"?

Available categories:
{categories_text}

Reply with ONLY the category slug (lowercase, no quotes) or "none" if no match."""

    try:
        from .llm_parsers import _get_openai_client

        client = _get_openai_client(timeout=timeout)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0,
        )

        result = normalize_text(response.choices[0].message.content)

        # Validate result is a known category slug
        valid_slugs = {cat.get("slug", "").lower() for cat in categories}
        if result in valid_slugs:
            logger.info("LLM inferred category '%s' for item '%s'", result, item_name)
            return result
        elif result == "none":
            logger.debug("LLM returned 'none' for item '%s'", item_name)
            return None
        else:
            logger.warning(
                "LLM returned unexpected category '%s' for item '%s', valid: %s",
                result, item_name, valid_slugs
            )
            return None

    except (ImportError, ConnectionError, TimeoutError, OSError, ValueError, KeyError, AttributeError, RuntimeError) as e:  # noqa: E501
        logger.warning("LLM category inference failed for '%s': %s", item_name, e)
        return None
    except Exception as e:  # Catch-all for third-party SDK errors (openai.APIError, etc.)
        logger.warning("LLM category inference failed for '%s': %s", item_name, e)
        return None
