"""Single item ordering scenarios."""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class SingleItemScenario(BaseScenario):
    """Scenario for ordering a single menu item."""

    scenario_type = "single_item"

    def __init__(
        self,
        item_name: str,
        item_type: str,
        item_data: dict[str, Any],
        ordering_phrases: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize single item scenario.

        Args:
            item_name: The canonical menu item name.
            item_type: The item type slug (e.g., "bagel", "sized_beverage").
            item_data: Full item data from menu cache.
            ordering_phrases: Optional custom ordering phrases.
            seed: Random seed for reproducibility.
        """
        super().__init__(f"Order {item_name}")
        self.item_name = item_name
        self.item_type = item_type
        self.item_data = item_data
        self.ordering_phrases = ordering_phrases or self._default_ordering_phrases()
        self.rng = random.Random(seed)

    def _default_ordering_phrases(self) -> list[str]:
        """Get default ordering phrases."""
        return [
            "I'll have a {item}",
            "Can I get a {item}",
            "I'd like a {item}",
            "One {item} please",
            "I want a {item}",
            "Give me a {item}",
            "Let me get a {item}",
            "{item} please",
            "Just a {item}",
            "I'll take a {item}",
        ]

    def generate(self) -> None:
        """Generate conversation turns for ordering this item."""
        # Pick a random ordering phrase
        phrase_template = self.rng.choice(self.ordering_phrases)
        user_input = phrase_template.format(item=self.item_name)

        # Build expected action
        expected_action = ExpectedAction(
            action_type=ActionType.ADD_ITEM,
            item_name=self.item_name,
        )

        # First turn: order the item
        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[expected_action],
                expected_items_in_cart=[self.item_name],
                allow_disambiguation=True,  # Multiple matches acceptable
            )
        )


class SingleItemWithQuantityScenario(BaseScenario):
    """Scenario for ordering multiple of a single item."""

    scenario_type = "single_item_quantity"

    def __init__(
        self,
        item_name: str,
        item_type: str,
        quantity: int,
        seed: int | None = None,
    ) -> None:
        """Initialize quantity scenario.

        Args:
            item_name: The canonical menu item name.
            item_type: The item type slug.
            quantity: How many to order.
            seed: Random seed for reproducibility.
        """
        super().__init__(f"Order {quantity}x {item_name}")
        self.item_name = item_name
        self.item_type = item_type
        self.quantity = quantity
        self.rng = random.Random(seed)

    def _quantity_phrases(self) -> list[str]:
        """Get quantity ordering phrases."""
        qty_words = {
            2: ["two", "2", "a couple", "a pair of"],
            3: ["three", "3"],
            4: ["four", "4"],
            5: ["five", "5"],
        }
        qty_options = qty_words.get(self.quantity, [str(self.quantity)])
        qty = self.rng.choice(qty_options)

        return [
            f"I'll have {qty} {{item}}s",
            f"Can I get {qty} {{item}}s",
            f"{qty} {{item}}s please",
            f"I'd like {qty} {{item}}s",
        ]

    def generate(self) -> None:
        """Generate conversation turns."""
        phrase_template = self.rng.choice(self._quantity_phrases())
        user_input = phrase_template.format(item=self.item_name)

        expected_action = ExpectedAction(
            action_type=ActionType.ADD_ITEM,
            item_name=self.item_name,
            quantity=self.quantity,
        )

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[expected_action],
                expected_items_in_cart=[self.item_name],
                allow_disambiguation=True,
            )
        )
