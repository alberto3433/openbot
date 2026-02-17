"""
Pydantic models for the hierarchical task system.

The task hierarchy represents the order capture process:
- OrderTask (root)
  - DeliveryMethodTask
  - ItemsTask (contains multiple ItemTasks)
  - CustomerInfoTask
  - CheckoutTask
  - PaymentTask

This module re-exports all model classes for backwards compatibility.
"""

from .base import (
    TaskStatus,
    FieldConfig,
    BaseTask,
)

from .utilities import (
    parse_pending_field,
    format_slug_for_display,
    pluralize_display_name,
    is_name_forming_category,
    _get_is_price_metadata_key,
)

# Also expose as private names for backwards compatibility
_format_slug_for_display = format_slug_for_display
_pluralize_display_name = pluralize_display_name
_is_name_forming_category = is_name_forming_category

from .item_tasks import (
    ItemTask,
    MenuItemTask,
)

from .order_flow import (
    AddressTask,
    DeliveryMethodTask,
    CustomerInfoTask,
    CheckoutTask,
    PaymentTask,
)

from .container_tasks import (
    ItemsTask,
    OrderTask,
)

from .pending_states import (
    PendingSwitchItem,
    PendingAttrDisambiguation,
    PendingChangeClarification,
    PendingUnmatchedPagination,
    PendingIngredientSuggestion,
    PendingDuplicateSelection,
    PendingSameThingClarification,
    PendingIngredientSearch,
    PendingDietaryFollowup,
)

__all__ = [
    # Base
    "TaskStatus",
    "FieldConfig",
    "BaseTask",
    # Utilities
    "parse_pending_field",
    "format_slug_for_display",
    "pluralize_display_name",
    "is_name_forming_category",
    # Private utilities (backwards compat)
    "_format_slug_for_display",
    "_pluralize_display_name",
    "_is_name_forming_category",
    "_get_is_price_metadata_key",
    # Item tasks
    "ItemTask",
    "MenuItemTask",
    # Order flow
    "AddressTask",
    "DeliveryMethodTask",
    "CustomerInfoTask",
    "CheckoutTask",
    "PaymentTask",
    # Container tasks
    "ItemsTask",
    "OrderTask",
]
