"""
Menu query mixin for MenuDataCache.

Thin composer that inherits from focused sub-query mixins.
"""

from .menu_core_queries import MenuCoreQueryMixin
from .menu_search_queries import MenuSearchQueryMixin
from .menu_metadata_queries import MenuMetadataQueryMixin
from .menu_dietary_queries import MenuDietaryQueryMixin


class MenuQueryMixin(
    MenuCoreQueryMixin,
    MenuSearchQueryMixin,
    MenuMetadataQueryMixin,
    MenuDietaryQueryMixin,
):
    """Combined menu query mixin — delegates to focused sub-mixins."""
    pass
