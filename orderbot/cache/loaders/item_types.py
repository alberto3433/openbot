"""
Item Type Loaders for MenuDataCache.

Thin composer that inherits from focused sub-loader mixins.
"""

from .item_type_global_attrs import ItemTypeGlobalAttrsLoaderMixin
from .item_type_config import ItemTypeConfigLoaderMixin
from .item_type_components import ItemTypeComponentsLoaderMixin
from .item_type_suggestions import ItemTypeSuggestionsLoaderMixin


class ItemTypeLoaderMixin(
    ItemTypeGlobalAttrsLoaderMixin,
    ItemTypeConfigLoaderMixin,
    ItemTypeComponentsLoaderMixin,
    ItemTypeSuggestionsLoaderMixin,
):
    """Combined item type loader — delegates to focused sub-mixins."""
    pass
