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
