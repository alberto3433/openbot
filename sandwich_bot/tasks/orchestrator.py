"""
Task Orchestrator - Main entry point for the hierarchical task system.

This orchestrator uses:
1. LLM parsing with structured outputs (ParsedInput)
2. Deterministic state updates (OrderTask)
3. Deterministic flow control (NextAction)

This replaces the pattern-matching based orchestrator with a more
reliable hierarchical task approach.
"""

from typing import Any
import logging

from .models import OrderTask, TaskStatus
from .parsing import ParsedInput, parse_user_message, parse_user_message_async
from .flow import (
    ActionType,
    NextAction,
    update_order_state,
    get_next_action,
    process_message,
)
from .field_config import MenuFieldConfig

logger = logging.getLogger(__name__)


class TaskOrchestratorResult:
    """Result from TaskOrchestrator processing."""

    def __init__(
        self,
        message: str,
        order: OrderTask,
        action_type: ActionType,
        is_complete: bool = False,
        suggested_responses: list[str] | None = None,
    ):
        self.message = message
        self.order = order
        self.action_type = action_type
        self.is_complete = is_complete
        self.suggested_responses = suggested_responses or []


class TaskOrchestrator:
    """
    Main orchestrator for the hierarchical task system.

    This orchestrator:
    1. Parses user input using LLM with structured outputs
    2. Updates order state deterministically
    3. Determines next action deterministically
    4. Generates response messages

    It provides a simple interface: process(user_input, order) -> result
    """

    def __init__(
        self,
        menu_config: MenuFieldConfig | None = None,
        menu_data: dict | None = None,
        llm_model: str = "gpt-4o-mini",
    ):
        """
        Initialize the TaskOrchestrator.

        Args:
            menu_config: Optional menu field configuration
            menu_data: Optional menu data dict
            llm_model: Model to use for parsing
        """
        self.menu_config = menu_config or MenuFieldConfig.from_menu_data(menu_data)
        self.menu_data = menu_data or {}
        self.llm_model = llm_model
        self._instructor_client = None

    def process(
        self,
        user_input: str,
        order: OrderTask | None = None,
        pending_question: str | None = None,
    ) -> TaskOrchestratorResult:
        """
        Process user input and return response.

        This is the main synchronous entry point.

        Args:
            user_input: User's message text
            order: Current order state (None for new conversation)
            pending_question: The question we just asked (helps interpret answers)

        Returns:
            TaskOrchestratorResult with response and updated order
        """
        # Initialize order if needed
        if order is None:
            order = OrderTask()

        # Add user message to conversation history
        order.add_message("user", user_input)

        try:
            # 1. Parse user input with LLM
            context = self._build_parsing_context(order)
            # Auto-get pending question from conversation history if not provided
            if pending_question is None:
                pending_question = self.get_pending_question(order)
            parsed = parse_user_message(
                message=user_input,
                context=context,
                pending_question=pending_question,
                model=self.llm_model,
            )

            logger.debug(f"Parsed input: {parsed}")

            # 2. Process message (update state + get next action)
            order, next_action = process_message(order, parsed, self.menu_config, self.menu_data)

            # 3. Generate response
            response = self._generate_response(next_action, order)

            # 4. Add assistant message to history
            order.add_message("assistant", response)

            return TaskOrchestratorResult(
                message=response,
                order=order,
                action_type=next_action.action_type,
                is_complete=next_action.action_type == ActionType.COMPLETE_ORDER,
                suggested_responses=self._get_suggested_responses(next_action, order),
            )

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            error_response = "I'm sorry, I didn't quite catch that. Could you try again?"
            order.add_message("assistant", error_response)
            return TaskOrchestratorResult(
                message=error_response,
                order=order,
                action_type=ActionType.CLARIFY,
                is_complete=False,
            )

    async def process_async(
        self,
        user_input: str,
        order: OrderTask | None = None,
        pending_question: str | None = None,
    ) -> TaskOrchestratorResult:
        """
        Process user input asynchronously.

        This is the main async entry point for better performance.

        Args:
            user_input: User's message text
            order: Current order state (None for new conversation)
            pending_question: The question we just asked (helps interpret answers)

        Returns:
            TaskOrchestratorResult with response and updated order
        """
        # Initialize order if needed
        if order is None:
            order = OrderTask()

        # Add user message to conversation history
        order.add_message("user", user_input)

        try:
            # 1. Parse user input with LLM (async)
            context = self._build_parsing_context(order)
            # Auto-get pending question from conversation history if not provided
            if pending_question is None:
                pending_question = self.get_pending_question(order)
            parsed = await parse_user_message_async(
                message=user_input,
                context=context,
                pending_question=pending_question,
                model=self.llm_model,
            )

            logger.debug(f"Parsed input: {parsed}")

            # 2. Process message (update state + get next action)
            order, next_action = process_message(order, parsed, self.menu_config, self.menu_data)

            # 3. Generate response
            response = self._generate_response(next_action, order)

            # 4. Add assistant message to history
            order.add_message("assistant", response)

            return TaskOrchestratorResult(
                message=response,
                order=order,
                action_type=next_action.action_type,
                is_complete=next_action.action_type == ActionType.COMPLETE_ORDER,
                suggested_responses=self._get_suggested_responses(next_action, order),
            )

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            error_response = "I'm sorry, I didn't quite catch that. Could you try again?"
            order.add_message("assistant", error_response)
            return TaskOrchestratorResult(
                message=error_response,
                order=order,
                action_type=ActionType.CLARIFY,
                is_complete=False,
            )

    def _build_parsing_context(self, order: OrderTask) -> dict:
        """Build context dict for LLM parsing."""
        from .models import MenuItemTask  # Import here to avoid circular import

        context = {}

        # Current items
        items = order.items.get_active_items()
        if items:
            context["items_count"] = len(items)
            context["items"] = [item.get_summary() for item in items]

        # Current item being worked on
        current = order.items.get_current_item()
        if current:
            context["current_item"] = current.get_summary()
            context["current_item_type"] = current.item_type

            # Add specific context for menu items (like omelettes)
            if isinstance(current, MenuItemTask):
                context["current_menu_item_name"] = current.menu_item_name
                if current.menu_item_type:
                    context["current_menu_item_type"] = current.menu_item_type
                # Tell parser what customizations are pending
                missing = current.get_missing_customizations()
                if missing:
                    context["pending_customization"] = missing[0]
                    if "omelette" in current.menu_item_name.lower():
                        context["omelette_pending"] = True

        # Order type
        if order.delivery_method.order_type:
            context["order_type"] = order.delivery_method.order_type

        # Delivery address (if delivery)
        if order.delivery_method.order_type == "delivery":
            if order.delivery_method.address.street:
                context["delivery_address"] = order.delivery_method.address.street
            if order.delivery_method.address.zip_code:
                context["delivery_zip_code"] = order.delivery_method.address.zip_code

        # Customer info
        if order.customer_info.name:
            context["customer_name"] = order.customer_info.name

        return context

    def _generate_response(self, action: NextAction, order: OrderTask) -> str:
        """Generate the response message for an action."""
        if action.message:
            return action.message

        if action.question:
            # Only add confirmation when asking "Anything else?" (just finished an item)
            # Don't repeat confirmation for subsequent questions like pickup/delivery, name, etc.
            should_confirm = action.context and action.context.get("asking_for_more")
            if should_confirm:
                confirmation = self._get_confirmation_prefix(order)
                if confirmation:
                    return f"{confirmation} {action.question}"
            return action.question

        # Default responses by action type
        defaults = {
            ActionType.GREETING: "Hi! Welcome to Zucker's Bagels. What can I get for you today?",
            ActionType.CLARIFY: "I didn't quite catch that. Could you repeat?",
            ActionType.ASK_CHECKOUT: "Would you like to proceed to checkout?",
            ActionType.ASK_PAYMENT: "How would you like to pay?",
            ActionType.COMPLETE_ORDER: "Thank you for your order!",
        }

        return defaults.get(action.action_type, "What else can I help you with?")

    def _get_confirmation_prefix(self, order: OrderTask) -> str | None:
        """Get confirmation text for recently added/modified items."""
        # Check if we just added items
        active_items = order.items.get_active_items()
        if not active_items:
            return None

        # Get the most recent complete item to confirm
        complete_items = [
            item for item in active_items
            if item.status == TaskStatus.COMPLETE
        ]

        if complete_items:
            last_item = complete_items[-1]
            return f"Got it, {last_item.get_summary()}."

        return None

    def _get_suggested_responses(
        self,
        action: NextAction,
        order: OrderTask,
    ) -> list[str]:
        """Get suggested quick responses for the current state."""
        if action.action_type == ActionType.GREETING:
            return ["I'd like a bagel", "Just a coffee", "Bagel and coffee"]

        if action.field_name == "toasted":
            return ["Yes, toasted", "No thanks"]

        if action.field_name == "iced":
            return ["Iced", "Hot"]

        if action.field_name == "spread":
            return ["Cream cheese", "Butter", "No spread"]

        if action.field_name == "order_type":
            return ["Pickup", "Delivery"]

        if action.context and action.context.get("asking_for_more"):
            return ["That's all", "Add a coffee", "Add a bagel"]

        if action.action_type == ActionType.SHOW_ORDER:
            return ["Looks good", "Make a change"]

        return []

    def get_order_summary(self, order: OrderTask) -> str:
        """Get human-readable order summary."""
        return order.get_order_summary()

    def get_pending_question(self, order: OrderTask) -> str | None:
        """Get the last question asked (for context in next parse)."""
        # Look at conversation history for last assistant message
        for msg in reversed(order.conversation_history):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                # Simple heuristic: if ends with ?, it's a question
                if content.strip().endswith("?"):
                    return content
                break
        return None
