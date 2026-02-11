"""
Context-Aware Handler - Base class for automatic context propagation.

Handlers that need context propagation to sub-handlers can inherit from
this class and define their sub_handlers property. Context will be
automatically propagated to all sub-handlers when set_context is called.
"""

from typing import TYPE_CHECKING

from ..mixins import ContextMixin

if TYPE_CHECKING:
    from ..context import OrderContext


class ContextAwareHandler(ContextMixin):
    """
    Base class for handlers that need automatic context propagation.

    Subclasses should implement the `sub_handlers` property to return
    a list of sub-handlers that need to receive context. The base
    `_propagate_context` method will automatically call `set_context`
    on each sub-handler.

    Example:
        class MyHandler(ContextAwareHandler):
            def __init__(self, child_handler):
                self._child = child_handler
                # Initialize ContextMixin attributes
                self._returning_customer = None
                self._is_repeat_order = False
                self._last_order_type = None
                self._store_info = None

            @property
            def sub_handlers(self) -> list:
                return [self._child]
    """

    @property
    def sub_handlers(self) -> list:
        """Return list of sub-handlers that need context propagation.

        Override this property to specify which sub-handlers should
        receive context when set_context is called on this handler.

        Returns:
            List of handler instances that have a set_context method.
        """
        return []

    def _propagate_context(self, ctx: "OrderContext") -> None:
        """Propagate context to all sub-handlers.

        This is called automatically by ContextMixin.set_context after
        setting local context attributes.

        Args:
            ctx: OrderContext to propagate to sub-handlers.
        """
        for handler in self.sub_handlers:
            if handler is not None and hasattr(handler, "set_context"):
                handler.set_context(ctx)
