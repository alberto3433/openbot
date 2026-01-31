"""
Item type query mixin for MenuDataCache.

This module provides the combined ItemTypeQueryMixin by inheriting from
focused sub-mixins. Each sub-mixin handles a specific domain of queries.

New code should consider importing from the specific sub-mixins for clarity:
- item_type_core_queries.ItemTypeCoreQueryMixin - Core item type queries
- attribute_queries.AttributeQueryMixin - Attribute configuration queries
- option_queries.OptionQueryMixin - Option resolution queries
- keyword_queries.KeywordQueryMixin - Keyword extraction for matching
"""

import logging

from .item_type_core_queries import ItemTypeCoreQueryMixin
from .attribute_queries import AttributeQueryMixin
from .option_queries import OptionQueryMixin
from .keyword_queries import KeywordQueryMixin

logger = logging.getLogger(__name__)


class ItemTypeQueryMixin(
    ItemTypeCoreQueryMixin,
    AttributeQueryMixin,
    OptionQueryMixin,
    KeywordQueryMixin,
):
    """Mixin containing all item type, attribute, and option query methods.

    This class composes functionality from focused sub-mixins:
    - ItemTypeCoreQueryMixin: Core item type queries
    - AttributeQueryMixin: Attribute configuration queries
    - OptionQueryMixin: Option resolution queries
    - KeywordQueryMixin: Keyword extraction for matching

    All methods from the sub-mixins are available on this class for
    backward compatibility.
    """

    pass
