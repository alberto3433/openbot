"""
Hierarchical Task System for Order Capture.

This module provides a task-based architecture for capturing orders with:
- Hierarchical task tree (OrderTask → ItemTasks → field-level tasks)
- Configurable field defaults from menu config
- LLM parsing with structured outputs
- Deterministic flow control
- Support for modifications and cancellations at any point
"""

from .models import (
    TaskStatus,
    FieldConfig,
    BaseTask,
    ItemTask,
    BagelItemTask,
    CoffeeItemTask,
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
    ItemTypeConfig,
    MenuFieldConfig,
    get_field_config,
    get_default_value,
)

from .parsing import (
    ParsedBagelItem,
    ParsedCoffeeItem,
    ItemModification,
    ParsedInput,
    parse_user_message,
    parse_user_message_async,
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
    "BagelItemTask",
    "CoffeeItemTask",
    "MenuItemTask",
    "DeliveryMethodTask",
    "AddressTask",
    "CustomerInfoTask",
    "CheckoutTask",
    "PaymentTask",
    "ItemsTask",
    "OrderTask",
    # Field config
    "ItemTypeConfig",
    "MenuFieldConfig",
    "get_field_config",
    "get_default_value",
    # Parsing
    "ParsedBagelItem",
    "ParsedCoffeeItem",
    "ItemModification",
    "ParsedInput",
    "parse_user_message",
    "parse_user_message_async",
    # Adapter
    "dict_to_order_task",
    "order_task_to_dict",
]
