"""Response verification for Chaos Monkey tests."""

import re
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    ConversationTurn,
    ExpectedAction,
    FailureCategory,
)


class ResponseVerifier:
    """Verifies bot responses against expected outcomes."""

    # Error patterns in bot responses
    ERROR_PATTERNS = [
        r"i'm sorry.*trouble",
        r"error occurred",
        r"something went wrong",
        r"please try again",
        r"internal error",
        r"couldn't process",
        r"failed to",
    ]

    # Patterns indicating item not found
    NOT_FOUND_PATTERNS = [
        r"(i )?don't (have|see|recognize|know)",
        r"not on (the|our) menu",
        r"couldn't find",
        r"not available",
        r"we don't (carry|offer|have)",
        r"sorry.*(don't|can't) find",
    ]

    # Disambiguation patterns
    DISAMBIGUATION_PATTERNS = [
        r"which (one|.*) (did you mean|would you like)",
        r"do you mean",
        r"could you clarify",
        r"\d+\.\s+",  # Numbered list
        r"did you want",
        r"choose from",
    ]

    def __init__(self) -> None:
        """Initialize the verifier."""
        self._error_re = [re.compile(p, re.IGNORECASE) for p in self.ERROR_PATTERNS]
        self._not_found_re = [
            re.compile(p, re.IGNORECASE) for p in self.NOT_FOUND_PATTERNS
        ]
        self._disambig_re = [
            re.compile(p, re.IGNORECASE) for p in self.DISAMBIGUATION_PATTERNS
        ]

    def verify_turn(
        self,
        turn: ConversationTurn,
        response: str,
        actions: list[dict[str, Any]],
        order_state: dict[str, Any],
    ) -> None:
        """Verify a single conversation turn.

        Updates the turn object with verification results.

        Args:
            turn: The conversation turn to verify.
            response: Bot's text response.
            actions: List of action dicts from the API.
            order_state: Current order state from the API.
        """
        turn.actual_response = response
        turn.actual_actions = actions
        turn.actual_order_state = order_state

        # Check for system errors first
        if self._is_system_error(response):
            turn.passed = False
            turn.failure_category = FailureCategory.SYSTEM_ERROR
            turn.failure_reason = f"System error in response: {response[:100]}"
            return

        # Check for disambiguation (may be acceptable)
        if self._is_disambiguation(response) and turn.allow_disambiguation:
            turn.passed = True
            return

        # Check for item not found (skip for menu inquiry turns)
        # The bot often warns about an unrecognized modifier
        # (e.g. "Sorry, we don't carry Pepperoni") but still adds the
        # item successfully. Check the actual cart to distinguish real
        # failures (nothing added) from spurious warnings.
        if self._is_not_found(response) and not turn.is_menu_inquiry:
            cart_items = order_state.get("items", [])
            if not cart_items:
                turn.passed = False
                # If this turn was STT-mutated, categorize as STT-induced
                if turn.stt_mutated:
                    turn.failure_category = FailureCategory.STT_INDUCED
                    turn.failure_reason = (
                        f"STT-induced not found (original: "
                        f"'{turn.original_input}'): {response[:100]}"
                    )
                else:
                    turn.failure_category = FailureCategory.MENU_ITEM_NOT_FOUND
                    turn.failure_reason = f"Item not found: {response[:100]}"
                return

        # Verify cart contents (primary verification for add_item scenarios)
        # This is more reliable than action intents since the API uses generic
        # action types like "conversation" for all interactions
        cart_result = self._verify_cart(turn.expected_items_in_cart, order_state)
        if not cart_result["passed"]:
            turn.passed = False
            turn.failure_category = cart_result["category"]
            turn.failure_reason = cart_result["reason"]
            return

        # Verify question asked if expected
        if turn.expected_question_about:
            question_result = self._verify_question(
                turn.expected_question_about, response
            )
            if not question_result["passed"]:
                turn.passed = False
                turn.failure_category = question_result["category"]
                turn.failure_reason = question_result["reason"]
                return

        # Deep verification: order type
        if turn.expected_order_type:
            actual_order_type = order_state.get("order_type")
            if actual_order_type != turn.expected_order_type:
                turn.passed = False
                turn.failure_category = FailureCategory.ORDER_TYPE
                turn.failure_reason = (
                    f"Expected order_type='{turn.expected_order_type}', "
                    f"got '{actual_order_type}'"
                )
                return

        # Deep verification: attribute values on items
        if turn.expected_attribute_values:
            items = order_state.get("items", [])
            for item in items:
                attrs = item.get("attribute_values", {})
                for key, expected_val in turn.expected_attribute_values.items():
                    actual_val = attrs.get(key)
                    if actual_val is not None and actual_val != expected_val:
                        turn.passed = False
                        turn.failure_category = FailureCategory.ATTRIBUTE_VALUE
                        turn.failure_reason = (
                            f"Expected {key}='{expected_val}', got '{actual_val}'"
                        )
                        return

        # Deep verification: total quantity
        if turn.expected_quantity is not None:
            items = order_state.get("items", [])
            total_qty = sum(item.get("quantity", 1) for item in items)
            if total_qty != turn.expected_quantity:
                turn.passed = False
                turn.failure_category = FailureCategory.CART_OPERATION
                turn.failure_reason = (
                    f"Expected total quantity {turn.expected_quantity}, "
                    f"got {total_qty}"
                )
                return

        # Deep verification: item count
        if turn.expect_item_count is not None:
            items = order_state.get("items", [])
            if len(items) != turn.expect_item_count:
                turn.passed = False
                turn.failure_category = FailureCategory.CART_OPERATION
                turn.failure_reason = (
                    f"Expected {turn.expect_item_count} items in cart, "
                    f"got {len(items)}"
                )
                return

        # Deep verification: no instruction leak
        if turn.expect_no_special_instruction_contains:
            items = order_state.get("items", [])
            needle = turn.expect_no_special_instruction_contains.lower()
            for item in items:
                for instr in item.get("special_instructions", []):
                    if needle in instr.lower():
                        turn.passed = False
                        turn.failure_category = FailureCategory.OTHER
                        turn.failure_reason = (
                            f"Special instruction '{instr}' contains "
                            f"'{turn.expect_no_special_instruction_contains}'"
                        )
                        return

        turn.passed = True

    def _is_system_error(self, response: str) -> bool:
        """Check if response indicates a system error."""
        return any(pattern.search(response) for pattern in self._error_re)

    def _is_not_found(self, response: str) -> bool:
        """Check if response indicates item not found."""
        return any(pattern.search(response) for pattern in self._not_found_re)

    def _is_disambiguation(self, response: str) -> bool:
        """Check if response is asking for disambiguation."""
        return any(pattern.search(response) for pattern in self._disambig_re)

    def _verify_actions(
        self, expected: list[ExpectedAction], actual: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Verify expected actions are in actual actions."""
        if not expected:
            return {"passed": True}

        actual_intents = {a.get("intent", "").lower() for a in actual}

        for exp_action in expected:
            expected_intent = self._action_type_to_intent(exp_action.action_type)

            if expected_intent not in actual_intents:
                # Determine failure category based on action type
                category = self._get_action_failure_category(exp_action.action_type)
                return {
                    "passed": False,
                    "category": category,
                    "reason": (
                        f"Expected action '{expected_intent}' not in {list(actual_intents)}"
                    ),
                }

        return {"passed": True}

    def _verify_cart(
        self, expected_items: list[str], order_state: dict[str, Any]
    ) -> dict[str, Any]:
        """Verify expected items are in the cart."""
        if not expected_items:
            return {"passed": True}

        items = order_state.get("items", [])
        cart_item_names = {
            (item.get("menu_item_name") or item.get("name") or "").lower()
            for item in items
        }

        for expected_item in expected_items:
            expected_lower = expected_item.lower()
            # Allow partial matching for cart verification
            if not any(expected_lower in name or name in expected_lower
                       for name in cart_item_names):
                return {
                    "passed": False,
                    "category": FailureCategory.ITEM_RECOGNITION,
                    "reason": (
                        f"Expected item '{expected_item}' not in cart. "
                        f"Cart contains: {list(cart_item_names)}"
                    ),
                }

        return {"passed": True}

    def _verify_question(
        self, expected_attribute: str, response: str
    ) -> dict[str, Any]:
        """Verify the bot is asking about the expected attribute."""
        # Simple heuristic: check if attribute keyword is in response
        attr_lower = expected_attribute.lower()
        response_lower = response.lower()

        # Map common attributes to question keywords
        attribute_keywords = {
            "size": ["size", "small", "medium", "large", "what size"],
            "toasted": ["toasted", "toast"],
            "bread": ["bagel", "bread", "what kind"],
            "iced": ["iced", "hot", "cold"],
            "spread": ["spread", "cream cheese"],
        }

        keywords = attribute_keywords.get(attr_lower, [attr_lower])

        if not any(kw in response_lower for kw in keywords):
            return {
                "passed": False,
                "category": FailureCategory.QUESTION_FLOW,
                "reason": (
                    f"Expected question about '{expected_attribute}' "
                    f"but got: {response[:100]}"
                ),
            }

        return {"passed": True}

    def _action_type_to_intent(self, action_type: ActionType) -> str:
        """Convert ActionType to expected intent string."""
        intent_map = {
            ActionType.ADD_ITEM: "add_item",
            ActionType.REMOVE_ITEM: "remove_item",
            ActionType.UPDATE_QUANTITY: "update_quantity",
            ActionType.ADD_MODIFIER: "add_modifier",
            ActionType.REMOVE_MODIFIER: "remove_modifier",
            ActionType.ASK_QUESTION: "ask_question",
            ActionType.CONFIRM_ORDER: "confirm",
            ActionType.CANCEL_ORDER: "cancel",
            ActionType.SHOW_CART: "show_cart",
            ActionType.NO_ACTION: "no_action",
        }
        return intent_map.get(action_type, action_type.value)

    def _get_action_failure_category(self, action_type: ActionType) -> FailureCategory:
        """Get failure category for a missing action."""
        category_map = {
            ActionType.ADD_ITEM: FailureCategory.ACTION_DETECTION,
            ActionType.REMOVE_ITEM: FailureCategory.CART_OPERATION,
            ActionType.UPDATE_QUANTITY: FailureCategory.CART_OPERATION,
            ActionType.ADD_MODIFIER: FailureCategory.MODIFIER_HANDLING,
            ActionType.REMOVE_MODIFIER: FailureCategory.MODIFIER_HANDLING,
            ActionType.ASK_QUESTION: FailureCategory.QUESTION_FLOW,
            ActionType.CONFIRM_ORDER: FailureCategory.ACTION_DETECTION,
            ActionType.CANCEL_ORDER: FailureCategory.ACTION_DETECTION,
        }
        return category_map.get(action_type, FailureCategory.OTHER)
