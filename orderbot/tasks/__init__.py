"""
Hierarchical Task System for Order Capture.

This module provides a task-based architecture for capturing orders with:
- Hierarchical task tree (OrderTask → ItemTasks → field-level tasks)
- Configurable field defaults from menu config
- Deterministic flow control
- Support for modifications and cancellations at any point
"""

from .models import (
    TaskStatus,
    FieldConfig,
    BaseTask,
    ItemTask,
    MenuItemTask,
    DeliveryMethodTask,
    AddressTask,
    CustomerInfoTask,
    CheckoutTask,
    PaymentTask,
    ItemsTask,
    OrderTask,
)

from .field_config import (
    MenuFieldConfig,
    get_field_config,
    get_default_value,
)

from .adapter import (
    dict_to_order_task,
    order_task_to_dict,
)

__all__ = [
    # Task models
    "TaskStatus",
    "FieldConfig",
    "BaseTask",
    "ItemTask",
    "MenuItemTask",
    "DeliveryMethodTask",
    "AddressTask",
    "CustomerInfoTask",
    "CheckoutTask",
    "PaymentTask",
    "ItemsTask",
    "OrderTask",
    # Field config
    "MenuFieldConfig",
    "get_field_config",
    "get_default_value",
    # Adapter
    "dict_to_order_task",
    "order_task_to_dict",
]
