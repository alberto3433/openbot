"""
Qualifier Extractor for Menu Item Configuration.

Extracts qualifier patterns (extra, light, lots of, on the side, etc.)
adjacent to option names in user input.

Extracted from MenuItemConfigHandler._extract_qualifier_for_option.
"""

import re

from orderbot.cache import menu_cache
from orderbot.constants import QUALIFIER_PROXIMITY_THRESHOLD

__all__ = ["QualifierExtractor"]


class QualifierExtractor:
    """Extracts qualifiers (extra, light, on the side, etc.) for matched options."""

    def extract_qualifier_for_option(
        self, user_input: str, option_name: str,
        other_option_positions: list[tuple[int, int]] | None = None,
    ) -> str | None:
        """
        Extract qualifier (extra, light, lots of, on the side, etc.) for a specific option.

        Scans user input for qualifier patterns adjacent to the option name.

        Args:
            user_input: The full user input text (e.g., "lots of lettuce and extra mayo")
            option_name: The option to find qualifier for (e.g., "Lettuce")
            other_option_positions: Positions of other matched options in the input.
                When provided, a qualifier is skipped if another option is closer to it.

        Returns:
            Normalized qualifier like "extra" or "on the side", or None if no qualifier found.
        """
        qualifier_patterns = menu_cache.get_qualifier_patterns()
        if not qualifier_patterns:
            return None

        user_lower = user_input.lower()
        option_lower = option_name.lower()

        # Find position of the option in user input
        # Try multiple variations: full name, individual words, slug-based patterns
        opt_match = None
        search_terms = [option_lower]

        # Also try individual words from the display name (e.g., "milk" from "Whole Milk")
        for word in option_lower.split():
            if len(word) >= 3:  # Skip short words like "a", "of", etc.
                search_terms.append(word)

        for term in search_terms:
            opt_match = re.search(rf'\b{re.escape(term)}\b', user_lower)
            if opt_match:
                break

        if not opt_match:
            return None

        opt_start, opt_end = opt_match.start(), opt_match.end()

        # Check for qualifiers adjacent to this option -- pick the closest one.
        # When distances tie, prefer a qualifier BEFORE the option over one AFTER,
        # since English qualifiers naturally precede their noun ("dash of milk").
        best_qualifier = None
        best_distance = float('inf')
        best_is_before = False

        for pattern in qualifier_patterns:
            pattern_re = re.compile(rf'\b{re.escape(pattern)}\b', re.IGNORECASE)
            for match in pattern_re.finditer(user_lower):
                qual_start, qual_end = match.start(), match.end()

                # Qualifier before option: "extra lettuce", "lots of lettuce"
                is_before = qual_end <= opt_start and opt_start - qual_end <= QUALIFIER_PROXIMITY_THRESHOLD
                # Qualifier after option: "lettuce on the side"
                is_after = qual_start >= opt_end and qual_start - opt_end <= QUALIFIER_PROXIMITY_THRESHOLD

                if is_before or is_after:
                    distance = (opt_start - qual_end) if is_before else (qual_start - opt_end)

                    # Skip this qualifier if another option is closer to it
                    if other_option_positions:
                        closer_to_other = False
                        for other_start, other_end in other_option_positions:
                            if qual_end <= other_start:
                                other_dist = other_start - qual_end
                            elif qual_start >= other_end:
                                other_dist = qual_start - other_end
                            else:
                                other_dist = 0  # Overlapping
                            if other_dist < distance:
                                closer_to_other = True
                                break
                        if closer_to_other:
                            continue

                    # Pick this qualifier if it's closer, or if tied prefer before
                    if distance < best_distance or (distance == best_distance and is_before and not best_is_before):
                        info = menu_cache.get_qualifier_info(pattern)
                        if info:
                            best_qualifier = info["normalized_form"]
                            best_distance = distance
                            best_is_before = is_before

        return best_qualifier
