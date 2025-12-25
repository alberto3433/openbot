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

from .flow import (
    ActionType,
    NextAction,
    update_order_state,
    get_next_action,
    process_message,
)

from .orchestrator import (
    TaskOrchestrator,
    TaskOrchestratorResult,
)

from .adapter import (
    is_task_orchestrator_enabled,
    dict_to_order_task,
    order_task_to_dict,
    get_task_orchestrator,
    process_message_with_tasks,
    process_message_with_tasks_async,
)

__all__ = [
    # Task models
    "TaskStatus",
    "FieldConfig",
    "BaseTask",
    "ItemTask",
    "BagelItemTask",
    "CoffeeItemTask",
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
    # Flow control
    "ActionType",
    "NextAction",
    "update_order_state",
    "get_next_action",
    "process_message",
    # Orchestrator
    "TaskOrchestrator",
    "TaskOrchestratorResult",
    # Adapter
    "is_task_orchestrator_enabled",
    "dict_to_order_task",
    "order_task_to_dict",
    "get_task_orchestrator",
    "process_message_with_tasks",
    "process_message_with_tasks_async",
]
