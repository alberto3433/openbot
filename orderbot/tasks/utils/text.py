"""
Text formatting utilities for human-readable output.
"""


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
