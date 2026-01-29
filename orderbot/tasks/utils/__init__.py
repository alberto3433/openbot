"""
Utility classes extracted from handler modules.

This package contains focused, reusable utilities:
- OptionMatcher: Unified option matching with multi-phase algorithm
- InputNormalizer: Text normalization for option matching
- format_english_list: Format lists as human-readable English
"""

from .option_matcher import OptionMatcher
from .input_normalizer import InputNormalizer
from .text import format_english_list

__all__ = ["OptionMatcher", "InputNormalizer", "format_english_list"]
