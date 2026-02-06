"""Cart operation scenarios (quantity, remove, cancel)."""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class CartOperationScenario(BaseScenario):
    """Scenario for cart operations like quantity changes, removal, and cancellation."""

    scenario_type = "cart_ops"

    def __init__(
        self,
        item: dict[str, Any],
        operation: str,
        quantity: int | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize cart operation scenario.

        Args:
            item: Item dict from menu cache.
            operation: "change_quantity", "remove", or "cancel".
            quantity: New quantity (for change_quantity).
            seed: Random seed.
        """
        item_name = item.get("name", "Unknown")
        if operation == "change_quantity":
            super().__init__(f"Change {item_name} quantity to {quantity}")
        elif operation == "remove":
            super().__init__(f"Remove {item_name} from cart")
        else:
            super().__init__("Cancel order")

        self.item = item
        self.operation = operation
        self.quantity = quantity
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the conversation."""
        if self.operation == "change_quantity":
            self._generate_change_quantity()
        elif self.operation == "remove":
            self._generate_remove()
        else:
            self._generate_cancel()

    def _generate_change_quantity(self) -> None:
        """Generate quantity change scenario."""
        item_name = self.item.get("name", "Unknown")

        # First, add the item
        self.turns.append(
            ConversationTurn(
                user_input=f"I'll have a {item_name}",
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name)
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )

        # Then change quantity
        qty = self.quantity or 2
        qty_words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        qty_str = qty_words.get(qty, str(qty))

        templates = [
            f"Actually, make that {qty_str}",
            f"Change that to {qty_str}",
            f"I'll take {qty_str} of those",
            f"Make it {qty_str} {item_name}s",
        ]

        template = self.rng.choice(templates)

        self.turns.append(
            ConversationTurn(
                user_input=template,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.UPDATE_QUANTITY,
                        item_name=item_name,
                        quantity=qty,
                    )
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )

    def _generate_remove(self) -> None:
        """Generate remove item scenario."""
        item_name = self.item.get("name", "Unknown")

        # First, add the item
        self.turns.append(
            ConversationTurn(
                user_input=f"I'll have a {item_name}",
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name)
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )

        # Then remove it
        templates = [
            f"Actually, remove the {item_name}",
            f"Take off the {item_name}",
            f"Cancel the {item_name}",
            f"Never mind on the {item_name}",
            f"I don't want the {item_name} anymore",
        ]

        template = self.rng.choice(templates)

        self.turns.append(
            ConversationTurn(
                user_input=template,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.REMOVE_ITEM,
                        item_name=item_name,
                    )
                ],
                expected_items_in_cart=[],  # Item should be removed
                allow_disambiguation=True,
            )
        )

    def _generate_cancel(self) -> None:
        """Generate order cancellation scenario."""
        item_name = self.item.get("name", "Unknown")

        # First, add an item
        self.turns.append(
            ConversationTurn(
                user_input=f"I'll have a {item_name}",
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name)
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )

        # Then cancel the whole order
        templates = [
            "Cancel my order",
            "Never mind, cancel everything",
            "I changed my mind, cancel",
            "Cancel the whole order",
            "Start over",
        ]

        template = self.rng.choice(templates)

        self.turns.append(
            ConversationTurn(
                user_input=template,
                expected_actions=[
                    ExpectedAction(action_type=ActionType.CANCEL_ORDER)
                ],
                expected_items_in_cart=[],  # Cart should be empty
                allow_disambiguation=True,
            )
        )


class AddAndRemoveScenario(BaseScenario):
    """Scenario for adding one item then removing another."""

    scenario_type = "add_and_remove"

    def __init__(
        self,
        item_to_add: dict[str, Any],
        item_to_remove: dict[str, Any],
        seed: int | None = None,
    ) -> None:
        """Initialize add and remove scenario.

        Args:
            item_to_add: Item to add.
            item_to_remove: Item to remove (should be added first).
            seed: Random seed.
        """
        add_name = item_to_add.get("name", "Unknown")
        remove_name = item_to_remove.get("name", "Unknown")
        super().__init__(f"Add {add_name}, remove {remove_name}")

        self.item_to_add = item_to_add
        self.item_to_remove = item_to_remove
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the conversation."""
        add_name = self.item_to_add.get("name", "Unknown")
        remove_name = self.item_to_remove.get("name", "Unknown")

        # Add item to remove first
        self.turns.append(
            ConversationTurn(
                user_input=f"I'll have a {remove_name}",
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=remove_name)
                ],
                expected_items_in_cart=[remove_name],
                allow_disambiguation=True,
            )
        )

        # Add second item
        self.turns.append(
            ConversationTurn(
                user_input=f"And a {add_name}",
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=add_name)
                ],
                expected_items_in_cart=[remove_name, add_name],
                allow_disambiguation=True,
            )
        )

        # Remove first item
        self.turns.append(
            ConversationTurn(
                user_input=f"Remove the {remove_name}",
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.REMOVE_ITEM,
                        item_name=remove_name,
                    )
                ],
                expected_items_in_cart=[add_name],  # Only second item remains
                allow_disambiguation=True,
            )
        )
