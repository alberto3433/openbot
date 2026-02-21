"""
Shared constants for the cache layer.

Skip-word sets used during keyword indexing and text processing.
These basic skip word sets are duplicated from orderbot/tasks/shared_constants.py.
Cannot import from shared_constants here because it triggers orderbot.tasks.__init__
which eventually imports back into orderbot.cache (circular import).
"""

SKIP_WORDS_BASIC = frozenset({'the', 'a', 'an'})
SKIP_WORDS_CONJUNCTIONS = frozenset({'and', 'or', 'with'})
SKIP_WORDS_PREPOSITIONS = frozenset({'on', 'in', 'to', 'of'})
