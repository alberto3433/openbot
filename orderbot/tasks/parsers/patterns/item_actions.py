"""
Item Action Patterns.

Regex patterns for detecting item-level actions:
- Replace/change item (REPLACE_ITEM_PATTERN)
- Cancel/remove item (CANCEL_ITEM_PATTERN)
- Modifier change requests (CHANGE_REQUEST_PATTERNS)
"""

import re


# =============================================================================
# Replace Item Patterns
# =============================================================================

# Replace item patterns: "make it a X instead", "change it to X", "actually X instead", etc.
REPLACE_ITEM_PATTERN = re.compile(
    r"^(?:"
    # "make it X", "make that X", "make this X" - requires "make it/that/this"
    r"make\s+(?:it|that|this)\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "can you make it X?", "could you make it X?" - requires "can/could you make it/that/this"
    r"(?:can|could)\s+you\s+make\s+(?:it|that|this)\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "change it to X", "change to X" - requires "change"
    r"change\s+(?:it\s+)?(?:to\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "switch to X", "switch it to X" - requires "switch"
    r"switch\s+(?:it\s+)?(?:to\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "swap for X", "swap it for X" - requires "swap"
    r"swap\s+(?:it\s+)?(?:for\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "replace with X", "replace it with X" - requires "replace"
    r"replace\s+(?:it\s+)?(?:with\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "actually X", "no X", "nope X", "wait X" - requires one of these words
    r"(?:actually|nope|wait)[,]?\s+(?:make\s+(?:it\s+)?)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "no, make it X" / "no make it X" - requires "make it" to indicate replacement
    # Plain "no X" is handled by CANCEL_ITEM_PATTERN as removal
    r"no[,]?\s+make\s+(?:it\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "i meant X", "i said X", "no, i said X" - requires "i meant" or "i said"
    r"(?:no[,]?\s+)?i\s+(?:meant|said)\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "X instead" - requires "instead" at end
    r"(?:a\s+)?(.+?)\s+instead[\s!.,?]*$"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Cancel/Remove Item Patterns
# =============================================================================

CANCEL_ITEM_PATTERN = re.compile(
    r"^(?:"
    r"cancel\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"remove\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"skip\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"delete\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"clear\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"empty\s+(?:the\s+)?(?:my\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"take\s+(?:(?:off|out)(?:\s+of)?\s+)?(?:the\s+)?(.+?)(?:\s+off)?[\s!.,]*$"
    r"|"
    r"never\s*mind\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"forget\s+(?:about\s+)?(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"scratch\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"hold\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"without\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    # Handle "I don't want X", "don't want X", and "no I don't want X" (decline + remove)
    r"(?:no[,]?\s+)?(?:i\s+)?don'?t\s+want\s+(?:the\s+)?(.+?)(?:\s+anymore)?[\s!.,]*$"
    r"|"
    r"no\s+more\s+(?!changes?\b)(.+?)[\s!.,]*$"
    r"|"
    # "no X" / "no X please" - treat as removal (e.g., "no whole milk", "no sugar please")
    # Exclude common false positives: "no thanks", "no that's it", "no I'm good"
    # Also exclude "no make it X" which is a replacement pattern handled by REPLACE_ITEM_PATTERN
    # Also exclude "no I don't want..." which should be handled by the "I don't want X" pattern
    # Use negative lookahead to avoid matching these phrases
    r"no\s+(?!thanks\b|thank\s+you|more\b|but\b|changes?\b|nothing\b|none\b|that'?s?\s+(?:it|all|fine|good|ok|okay)|i'?m\s+(?:good|fine|ok|okay|done|all\s+set)|problem|worries|way|make\s+(?:it\s+)?|i\s+don|(?:can|could|may)\s+i\s+(?:have|get|do))(?:the\s+)?(.+?)(?:\s+please)?[\s!.,]*$"
    r"|"
    # "can you remove X?", "could you remove X?", "would you remove X?"
    r"(?:can|could|would)\s+you\s+(?:remove|delete|cancel|skip|take\s+(?:off|out))\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r"|"
    # "can I remove X?", "could we cancel X?"
    r"(?:can|could)\s+(?:i|we)\s+(?:remove|delete|cancel|skip|take\s+(?:off|out))\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r"|"
    # "please remove X", "please cancel X"
    r"please\s+(?:remove|delete|cancel|skip|take\s+(?:off|out))\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Modifier Change Request Patterns
# =============================================================================

# Change request patterns - detect when user wants to modify an item
# These patterns extract the target (what to change) and the new_value
# Returns (pattern, group_indices) where group_indices is (target_group, new_value_group)
# target_group can be None for "change it to X" patterns (refers to last item)
CHANGE_REQUEST_PATTERNS = [
    # "change it to X" / "make it X" - target is implicit (last item)
    (re.compile(r"(?:change|make|switch)\s+(?:it|that)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "change the bagel to X" / "make the spread X"
    (re.compile(r"(?:change|make|switch)\s+the\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "change X to Y" without "the" - e.g., "change corned beef to pastrami"
    # Note: This must come after "change it to X" pattern so "it" is matched as implicit target
    (re.compile(r"(?:change|switch)\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "can you change it to X" / "could you make it X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+(?:it|that)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "can you change the bagel to X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+the\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "make it with X" / "can you make it with X instead"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:make|have|do)\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "make it with X" (without "can you") - target is implicit (last item)
    (re.compile(r"make\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "make [quantity] [modifier]" - e.g., "make 2 vanilla syrups"
    (re.compile(r"make\s+(\d+\s+.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "actually X instead" / "actually make it X"
    # Negative lookahead excludes cancellation keywords so "actually cancel that" is NOT a change request
    (re.compile(r"actually\s+(?!cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off|no\s+)(?:make\s+it\s+)?(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I meant X" - clearly signals correction
    (re.compile(r"i\s+meant\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I want X instead" - requires "instead" to signal change (without "instead", treat as answer)
    (re.compile(r"i\s+want(?:ed)?\s+(.+?)\s+instead(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "no wait, X" / "wait, X instead"
    (re.compile(r"(?:no\s+)?wait[,.]?\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "make the bagel not toasted" - negate boolean attribute on specific item
    (re.compile(r"(?:make|have)\s+(?:the|my)\s+(\w+(?:\s+\w+)?)\s+(not\s+\w+)(?:\s+please)?(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "make it not toasted" - negate boolean attribute on implicit target
    (re.compile(r"(?:make|have)\s+(?:it|that)\s+(not\s+\w+)(?:\s+please)?(?:\?|$)", re.IGNORECASE), (None, 1)),
]
