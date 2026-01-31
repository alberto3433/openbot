"""
Selection Patterns.

Patterns for extracting user selections from numbered lists and ordinal references.
Used for disambiguation ("the first one", "number 2", "third", etc.).
"""

# =============================================================================
# Ordinal Words Mapping
# =============================================================================

# Maps ordinal words to 1-indexed positions
# Used for "the second bagel", "3rd coffee", "first one", etc.
ORDINAL_WORDS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
}

# Extended patterns for selection from numbered lists (maps to 0-indexed)
# Sorted by length descending so longer matches are checked first
# e.g., "the second one" should match "the second" not "one"
SELECTION_PATTERNS: list[tuple[str, int]] = sorted([
    ("the first", 0), ("number one", 0), ("number 1", 0), ("first", 0), ("one", 0), ("1", 0),
    ("the second", 1), ("number two", 1), ("number 2", 1), ("second", 1), ("two", 1), ("2", 1),
    ("the third", 2), ("number three", 2), ("number 3", 2), ("third", 2), ("three", 2), ("3", 2),
    ("the fourth", 3), ("number four", 3), ("number 4", 3), ("fourth", 3), ("four", 3), ("4", 3),
    ("the fifth", 4), ("number five", 4), ("number 5", 4), ("fifth", 4), ("five", 4), ("5", 4),
    ("the sixth", 5), ("number six", 5), ("number 6", 5), ("sixth", 5), ("six", 5), ("6", 5),
], key=lambda x: len(x[0]), reverse=True)

