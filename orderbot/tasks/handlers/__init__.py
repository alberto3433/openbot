"""
Handler infrastructure for state machine.

This package contains base classes and utilities for handler management:
- HandlerCallbacks: Dataclass for state machine callbacks
- ContextAwareHandler: Base class for automatic context propagation
- HandlerFactory: Factory for building handlers in dependency order
"""

from .handler_callbacks import HandlerCallbacks
from .context_aware import ContextAwareHandler
from .handler_factory import HandlerFactory

__all__ = [
    "HandlerCallbacks",
    "ContextAwareHandler",
    "HandlerFactory",
]
