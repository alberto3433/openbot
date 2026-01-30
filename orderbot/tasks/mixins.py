"""
Shared mixins for task handlers.

These mixins provide common functionality across multiple handlers,
reducing boilerplate code.
"""


class MenuDataMixin:
    """Mixin providing menu_data property for handlers.

    Handlers using this mixin must initialize `_menu_data` in their `__init__`.

    Usage:
        class MyHandler(MenuDataMixin):
            def __init__(self):
                self._menu_data: dict = {}
    """

    _menu_data: dict

    @property
    def menu_data(self) -> dict:
        """Get the current menu data."""
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict | None) -> None:
        """Set menu data, converting None to empty dict."""
        self._menu_data = value or {}

    @property
    def _modifier_category_keywords(self) -> dict[str, str]:
        """Get modifier category keyword mapping from menu data.

        Returns:
            Dict mapping keywords to category slugs,
            e.g., {"bacon": "meat", "swiss": "cheese"}
        """
        modifier_cats = self._menu_data.get("modifier_categories", {})
        return modifier_cats.get("keyword_to_category", {})

    @property
    def _modifier_item_keywords(self) -> dict[str, str]:
        """Get item keyword to item type slug mapping from menu data.

        Returns:
            Dict mapping keywords to item type slugs,
            e.g., {"coffee": "sized_beverage", "bagel": "bagel"}
        """
        return self._menu_data.get("item_keywords", {})
