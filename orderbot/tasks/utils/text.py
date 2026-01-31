"""
Text formatting utilities for human-readable output.
"""


def number_to_word(n: int) -> str:
    """Convert small integers (1-10) to words for natural language output.

    Args:
        n: Integer to convert (numbers > 10 return string representation)

    Returns:
        Word form for 1-10 ("one", "two", etc.), or str(n) for larger numbers.

    Examples:
        >>> number_to_word(1)
        'one'
        >>> number_to_word(5)
        'five'
        >>> number_to_word(15)
        '15'
    """
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    }
    return words.get(n, str(n))


def format_english_list(items: list[str], conjunction: str = "and") -> str:
    """Format a list of strings as an English list with Oxford comma.

    Args:
        items: List of strings to format.
        conjunction: Word to use before the last item ("and" or "or").

    Returns:
        Formatted string, e.g. "a, b, and c".

    Examples:
        >>> format_english_list([])
        ''
        >>> format_english_list(["apples"])
        'apples'
        >>> format_english_list(["apples", "bananas"])
        'apples and bananas'
        >>> format_english_list(["apples", "bananas", "cherries"])
        'apples, bananas, and cherries'
        >>> format_english_list(["a", "b"], conjunction="or")
        'a or b'
    """
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} {items[-1]}"


def format_display_list(
    items: list[dict],
    key: str = "display_name",
    conjunction: str = "or",
) -> str:
    """Format a list of dicts for display.

    Extracts a specific key from each dict and formats as English list.

    Args:
        items: List of dicts containing the display values
        key: Key to extract from each dict (default: "display_name")
        conjunction: Word to join items (default: "or")

    Returns:
        Formatted string like "A, B, or C"

    Examples:
        >>> format_display_list([{"display_name": "Apple"}, {"display_name": "Banana"}])
        'Apple or Banana'
    """
    names = [item.get(key, "") for item in items if item.get(key)]
    return format_english_list(names, conjunction=conjunction)


def format_numbered_list(
    items: list[dict] | list[str],
    name_key: str = "name",
    show_prices: bool = False,
    price_key: str = "base_price",
) -> str:
    """Format items as a numbered list.

    Args:
        items: List of dicts with name/price keys, or list of strings.
        name_key: Key for display name in dicts (ignored if items are strings).
        show_prices: Whether to show prices after names.
        price_key: Key for price field in dicts.

    Returns:
        Formatted string with numbered options, e.g.:
        "1. Apple
         2. Banana ($1.50)
         3. Cherry"

    Examples:
        >>> format_numbered_list(["Apple", "Banana"])
        '1. Apple\\n2. Banana'
        >>> format_numbered_list([{"name": "Apple"}, {"name": "Banana"}])
        '1. Apple\\n2. Banana'
        >>> format_numbered_list([{"name": "Latte", "base_price": 4.50}], show_prices=True)
        '1. Latte ($4.50)'
    """
    lines = []
    for i, item in enumerate(items, 1):
        # Handle both string lists and dict lists
        if isinstance(item, str):
            name = item
            price = 0
        else:
            name = item.get(name_key, "Unknown")
            price = item.get(price_key, 0) if show_prices else 0

        if show_prices and price > 0:
            lines.append(f"{i}. {name} (${price:.2f})")
        else:
            lines.append(f"{i}. {name}")
    return "\n".join(lines)
