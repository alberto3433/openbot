"""Base classes and dataclasses for Chaos Monkey scenarios."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(Enum):
    """Types of actions expected from the bot."""

    ADD_ITEM = "add_item"
    REMOVE_ITEM = "remove_item"
    UPDATE_QUANTITY = "update_quantity"
    ADD_MODIFIER = "add_modifier"
    REMOVE_MODIFIER = "remove_modifier"
    MODIFY_ITEM = "modify_item"  # General item modification (add/remove/change modifiers)
    ASK_QUESTION = "ask_question"
    CONFIRM_ORDER = "confirm_order"
    CANCEL_ORDER = "cancel_order"
    SHOW_CART = "show_cart"
    MENU_INQUIRY = "menu_inquiry"  # Menu information response
    NO_ACTION = "no_action"  # For error responses


class FailureCategory(Enum):
    """Categories of test failures for reporting."""

    ACTION_DETECTION = "Action Detection"
    ITEM_RECOGNITION = "Item Recognition"
    QUESTION_FLOW = "Question Flow"
    SYSTEM_ERROR = "System Error"
    MENU_ITEM_NOT_FOUND = "Menu Item Not Found"
    PRICING_ERROR = "Pricing Error"
    MODIFIER_HANDLING = "Modifier Handling"
    CART_OPERATION = "Cart Operation"
    OTHER = "Other"


@dataclass
class ExpectedAction:
    """An expected action from the bot response."""

    action_type: ActionType
    item_name: str | None = None
    modifier_name: str | None = None
    quantity: int | None = None
    attribute_name: str | None = None  # For ASK_QUESTION


@dataclass
class ConversationTurn:
    """A single turn in a conversation scenario."""

    user_input: str
    expected_actions: list[ExpectedAction] = field(default_factory=list)
    expected_items_in_cart: list[str] = field(default_factory=list)
    expected_question_about: str | None = None  # Attribute being asked about
    allow_disambiguation: bool = False  # Whether disambiguation is acceptable
    is_menu_inquiry: bool = False  # If True, "not found" responses are acceptable

    # Filled in after execution
    actual_response: str | None = None
    actual_actions: list[dict[str, Any]] | None = None
    actual_order_state: dict[str, Any] | None = None
    passed: bool | None = None
    failure_reason: str | None = None
    failure_category: FailureCategory | None = None


@dataclass
class ScenarioResult:
    """Result of executing a complete scenario."""

    scenario_name: str
    scenario_type: str
    turns: list[ConversationTurn]
    passed: bool
    failure_category: FailureCategory | None = None
    failure_summary: str | None = None
    session_id: str | None = None
    execution_time_ms: float = 0.0

    def get_first_failure(self) -> ConversationTurn | None:
        """Get the first turn that failed."""
        for turn in self.turns:
            if turn.passed is False:
                return turn
        return None


class BaseScenario(ABC):
    """Base class for all test scenarios."""

    scenario_type: str = "base"

    def __init__(self, name: str) -> None:
        """Initialize the scenario with a name."""
        self.name = name
        self.turns: list[ConversationTurn] = []

    @abstractmethod
    def generate(self) -> None:
        """Generate the conversation turns for this scenario.

        Subclasses must implement this to populate self.turns.
        """
        pass

    def get_turns(self) -> list[ConversationTurn]:
        """Get the conversation turns for this scenario."""
        if not self.turns:
            self.generate()
        return self.turns

    def to_result(self, session_id: str | None = None) -> ScenarioResult:
        """Convert executed scenario to a result object."""
        passed = all(turn.passed for turn in self.turns if turn.passed is not None)

        failure_category = None
        failure_summary = None
        first_failure = None

        for turn in self.turns:
            if turn.passed is False:
                first_failure = turn
                failure_category = turn.failure_category
                failure_summary = turn.failure_reason
                break

        return ScenarioResult(
            scenario_name=self.name,
            scenario_type=self.scenario_type,
            turns=self.turns,
            passed=passed,
            failure_category=failure_category,
            failure_summary=failure_summary,
            session_id=session_id,
        )
