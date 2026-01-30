"""
Loader mixin for MenuDataCache.

This module re-exports LoaderMixin from the loaders package for backward compatibility.
The actual implementation is now split across focused modules in the loaders/ directory:

- loaders/core.py: Main load_from_db and bulk loading orchestration
- loaders/menu_items.py: Menu item, signature item, side item loaders
- loaders/ingredients.py: Ingredient and modifier loaders
- loaders/item_types.py: Item type and attribute loaders
- loaders/patterns.py: Response pattern and abbreviation loaders
"""

from .loaders import LoaderMixin

__all__ = ["LoaderMixin"]
