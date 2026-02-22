"""
Shared Constants for Orderbot.

This module contains application-wide constants that are used across multiple modules.
For parser-specific constants, see orderbot/tasks/parsers/constants.py.
For attribute metadata constants, see orderbot/tasks/utils/constants.py.
"""

# =============================================================================
# Item Configuration Thresholds
# =============================================================================

# When ordering configurable items with quantity > this threshold,
# create a single item with quantity=N instead of N separate items.
# E.g., "10 plain bagels" creates 1 item with qty=10 (configure once)
# vs "3 plain bagels" creates 3 items (configure each individually)
MULTI_CONFIG_THRESHOLD = 12

# =============================================================================
# Disambiguation & Matching Limits
# =============================================================================

# Maximum number of options to show in disambiguation prompts
MAX_DISAMBIGUATION_OPTIONS = 6

# Maximum number of fuzzy match suggestions to show for unrecognized items
MAX_FUZZY_MATCHES = 3

# Minimum similarity score (0-100) for fuzzy matching to suggest items
FUZZY_MATCH_THRESHOLD = 75

# =============================================================================
# Text Matching Thresholds
# =============================================================================

# Maximum character distance between a qualifier (e.g., "extra", "on the side")
# and an option name for them to be considered associated.
# Used in config handler to associate qualifiers with their target options.
QUALIFIER_PROXIMITY_THRESHOLD = 15

# =============================================================================
# Duplicate Handler Scoring
# =============================================================================
# Scoring constants for matching user input to cart items.
# Higher scores = better matches.

# Exact match (case-insensitive)
SCORE_EXACT_MATCH = 100

# Exact match after normalization (strip spaces, lowercase)
SCORE_NORMALIZED_EXACT = 90

# User input matches the full name as a substring
SCORE_FULL_NAME_MATCH = 85

# User input is a prefix of the item name
SCORE_PREFIX_MATCH = 70

# User input appears as a substring in the item name
SCORE_SUBSTRING_MATCH = 30

# Base score for matching individual words
SCORE_WORD_MATCH_BASE = 20

# Bonus points per additional matching word
SCORE_WORD_MATCH_BONUS = 5

# =============================================================================
# Cache Configuration
# =============================================================================

# Hour (0-23) for daily background cache refresh (local time)
CACHE_REFRESH_HOUR = 3

# Seconds to wait before retrying after a failed cache refresh
CACHE_RETRY_DELAY_SECONDS = 3600

# =============================================================================
# Search Index Thresholds
# =============================================================================

# Minimum word length for keyword indexing in recommendation search
MIN_KEYWORD_LENGTH = 3

# Minimum word length for general search index entries
MIN_INDEX_WORD_LENGTH = 2

# Minimum number of words in an item name for prefix indexing
MIN_PREFIX_WORDS = 2
