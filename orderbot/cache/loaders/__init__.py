"""
Loader package for MenuDataCache.

This package contains the LoaderMixin which provides all database loading
methods for the menu cache. The loaders are split into focused modules:

- core.py: Main load_from_db and bulk loading orchestration
- menu_items.py: Menu item, signature item, side item loaders
- ingredients.py: Ingredient and modifier loaders
- item_types.py: Item type and attribute loaders
- patterns.py: Response pattern and abbreviation loaders
"""

from .core import LoaderMixin

__all__ = ["LoaderMixin"]
