"""
Shared mixins for task handlers.

These mixins provide common functionality across multiple handlers,
reducing boilerplate code.
"""

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import OrderContext


class ContextMixin:
    """Mixin providing per-request context management.

    Handlers using this mixin can receive context from OrderContext
    containing returning customer data, repeat order info, and store info.

    Usage:
        class MyHandler(ContextMixin):
            def __init__(self):
                self._returning_customer: dict | None = None
                self._is_repeat_order: bool = False
                self._last_order_type: str | None = None
                self._store_info: dict | None = None
    """

    _returning_customer: dict | None
    _is_repeat_order: bool
    _last_order_type: str | None
    _store_info: dict | None

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context from unified OrderContext.

        Args:
            ctx: OrderContext with store info, returning customer data, etc.
        """
        self._store_info = ctx.store_info
        self._returning_customer = ctx.returning_customer
        self._is_repeat_order = ctx.is_repeat_order
        self._last_order_type = ctx.last_order_type
        self._propagate_context(ctx)

    def _propagate_context(self, ctx: "OrderContext") -> None:
        """Override to propagate context to sub-handlers.

        Subclasses can override this to pass context to any sub-handlers
        that also need request-scoped context.

        Args:
            ctx: OrderContext to propagate.
        """
        pass


class CallbackMixin:
    """Mixin providing callback attributes for state transitions.

    Handlers using this mixin can receive callbacks for transitioning to next
    slots and configuring incomplete items.

    Usage:
        class MyHandler(CallbackMixin):
            def __init__(self):
                self._transition_to_next_slot: Callable | None = None
                self._configure_next_incomplete_item: Callable | None = None
    """

    _transition_to_next_slot: "Callable | None"
    _configure_next_incomplete_item: "Callable | None"


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
