"""
Shared mixins for task handlers.

These mixins provide common functionality across multiple handlers,
reducing boilerplate code.
"""

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .models import OrderTask
    from .schemas import StateMachineResult
    from .context import OrderContext
    from .pricing import PricingEngine


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
    """Mixin providing transition and configuration callbacks.

    Handlers using this mixin can invoke callbacks to transition order
    state or trigger configuration of incomplete items.

    Usage:
        class MyHandler(CallbackMixin):
            def __init__(self, transition_callback=None, configure_callback=None):
                self._transition_to_next_slot = transition_callback
                self._configure_next_incomplete_item = configure_callback
    """

    _transition_to_next_slot: Callable[["OrderTask"], None] | None
    _configure_next_incomplete_item: Callable[["OrderTask"], "StateMachineResult"] | None

    def transition_if_available(self, order: "OrderTask") -> None:
        """Invoke transition callback if available.

        Args:
            order: The order to transition.
        """
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

    def configure_next_if_available(
        self, order: "OrderTask"
    ) -> "StateMachineResult | None":
        """Invoke configure callback if available.

        Args:
            order: The order to get next configuration question for.

        Returns:
            StateMachineResult with next config question, or None if no callback.
        """
        if self._configure_next_incomplete_item:
            return self._configure_next_incomplete_item(order)
        return None


class PricingMixin:
    """Mixin providing price recalculation helpers.

    Handlers using this mixin can safely recalculate item prices
    after modifications.

    Usage:
        class MyHandler(PricingMixin):
            def __init__(self, pricing=None):
                self.pricing = pricing
    """

    pricing: "PricingEngine | None"

    def recalculate_price_safe(self, item) -> None:
        """Recalculate item price if pricing engine is available.

        Safely handles missing pricing engine or price lookup failures.

        Args:
            item: The item to recalculate price for.
        """
        if self.pricing:
            try:
                self.pricing.recalculate_item_price(item)
            except ValueError:
                pass  # Price lookup failed - item may not have pricing data


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
