# Bug Fix: Unwanted Spreads Added Without User Input

## Status: IMPLEMENTED

## Problem Summary
When user says "two plain bagels toasted", the cart shows both bagels with "Plain Tofu Spread" and "Plain Cream Cheese" added automatically, even though the user never requested any spreads.

## Root Cause Analysis

The bug has two components:

### 1. Primary Issue: Plural Form Not Matched (extraction.py)

In `extract_attribute_values()` Phase 2, the bread option "Plain Bagel" doesn't match user input "plain bagels" because:
- The pattern `"plain bagel"` is searched in `"two plain bagels toasted"`
- The word boundary check fails: "bagel" vs "bagels"

**Evidence:**
```python
# Pattern: "plain bagel" (from bread option)
# Input: "two plain bagels toasted"
# Result: No match due to word boundary - "bagel" ≠ "bagels"
```

Since bread is NOT matched, the span for "plain" is not consumed.

### 2. Secondary Issue: Overly Aggressive Phase 5 Reverse Matching

Phase 5 performs "reverse matching" where any user token (word 3+ chars) that appears in an option's display_name gets matched.

With "plain" not consumed by bread matching:
- Token "plain" is extracted from user input
- Phase 5 checks all multi_select attributes (including `spread`)
- "plain" matches spread options "Plain Tofu Spread" and "Plain Cream Cheese"
- Both spreads are added to the item

## Implemented Solution

### Approach: `check_plural_boundary()` Helper Function

Added a new helper function `check_plural_boundary()` in Phase 2 that allows patterns to match input text with common plural suffixes (`-s`, `-es`).

**File:** `orderbot/tasks/parsers/deterministic/extraction.py`

**Changes:**

1. Added `check_plural_boundary()` function (lines 267-296):
```python
def check_plural_boundary(text: str, start: int, end: int) -> tuple[bool, int]:
    """Check if match is at word boundary, allowing for plural suffixes.

    Returns (is_valid, actual_end) where actual_end includes any plural suffix.
    Handles common English plural patterns: -s, -es.

    Examples:
        "bagel" in "bagels" -> (True, end+1)  # includes 's'
        "box" in "boxes" -> (True, end+2)     # includes 'es'
    """
    before_ok = start == 0 or not text[start - 1].isalnum()
    if not before_ok:
        return (False, end)

    # Check exact word boundary first
    if end >= len(text) or not text[end].isalnum():
        return (True, end)

    # Check for plural suffix
    remaining = text[end:]

    # Check 's' suffix (bagels, drinks)
    if remaining.startswith('s') and (len(remaining) == 1 or not remaining[1].isalnum()):
        return (True, end + 1)

    # Check 'es' suffix (boxes, dishes, tomatoes)
    if remaining.startswith('es') and (len(remaining) == 2 or not remaining[2].isalnum()):
        return (True, end + 2)

    return (False, end)
```

2. Modified Phase 2 pattern matching (lines 389-409) to use `check_plural_boundary`:
```python
is_valid, actual_end = check_plural_boundary(input_lower, pos, end)
if is_valid and check_must_match(opt, input_lower):
    candidates.append(CandidateMatch(
        ...
        end=actual_end,  # Include plural suffix in span
        length=actual_end - pos,  # Use actual matched length
    ))
```

## Verification Results

### Bug Case Fixed
```
Input: "two plain bagels toasted"
Result:
  bread: plain_bagel  ✓
  toasted: True       ✓
  spread: NOT FOUND   ✓ (no unwanted spreads)
```

### Other Cases Still Work
```
Input: "plain bagel toasted"     -> bread: plain_bagel, toasted: True
Input: "everything bagel with butter" -> bread: everything_bagel, spread: butter
Input: "two sesame bagels"       -> bread: sesame_bagel
```

### Test Suite Results
- **Before fix:** 48 failed, 463 passed
- **After fix:** 24 failed, 491 passed
- **Net improvement:** 24 previously failing tests now pass

The 24 remaining failures are pre-existing issues in other parts of the codebase (spread_sandwich detection, special instructions parsing, etc.) unrelated to this fix.

## Why This Approach

1. **Fixes root cause** - Bread correctly matches "plain bagels", consuming the "plain" span
2. **No database changes** - Pure code fix
3. **Improves accuracy** - All plural forms now match their singular patterns
4. **Low risk** - Only extends existing matches, doesn't remove any
5. **Span tracking preserved** - Plural suffix is included in the matched span, preventing Phase 5 from re-matching those characters
