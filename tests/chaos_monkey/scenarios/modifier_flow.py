"""Multi-turn modifier flow scenarios - order items then modify them."""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class ModifierFlowScenario(BaseScenario):
    """Multi-turn scenario: order items, then add/remove/change modifiers.

    This scenario tests realistic modifier operations:
    1. Order one or two items
    2. Add a modifier
    3. Remove the SAME modifier that was added (realistic flow)
    4. Add a different modifier

    All modifiers used must be valid for the item type being ordered.
    """

    scenario_type = "modifier_flow"

    def __init__(
        self,
        items: list[dict[str, Any]],
        modifiers: list[str],
        seed: int | None = None,
    ) -> None:
        """Initialize modifier flow scenario.

        Args:
            items: 1-2 items to order (must be configurable items).
            modifiers: Available modifiers to use (must be valid for items).
            seed: Random seed.
        """
        item_names = [item.get("name", "Unknown") for item in items]
        super().__init__(f"Order {', '.join(item_names)} then modify")

        self.items = items
        self.modifiers = modifiers
        self.rng = random.Random(seed)

        # Track state for realistic flow
        self._added_modifier: str | None = None

    def generate(self) -> None:
        """Generate the multi-turn conversation."""
        # Turn 1: Order the items (1 or 2)
        self._generate_order_turn()

        # Pick modifiers for subsequent turns
        if len(self.modifiers) >= 2:
            mod1, mod2 = self.rng.sample(self.modifiers, 2)
        elif len(self.modifiers) == 1:
            mod1 = self.modifiers[0]
            mod2 = None
        else:
            return  # No modifiers to test

        # Turn 2: Add first modifier
        self._generate_add_modifier_turn(mod1)
        self._added_modifier = mod1

        # Turn 3: Remove the SAME modifier that was added (realistic)
        self._generate_remove_modifier_turn(mod1)

        # Turn 4: Add a different modifier
        if mod2:
            self._generate_add_modifier_turn(mod2)

    def _generate_order_turn(self) -> None:
        """Generate the initial order turn."""
        if len(self.items) == 1:
            item_name = self.items[0].get("name", "Unknown")
            templates = [
                "I'll have a {item}",
                "Can I get a {item}",
                "One {item} please",
                "I'd like a {item}",
            ]
            template = self.rng.choice(templates)
            user_input = template.format(item=item_name)
            expected_items = [item_name]
        else:
            item1 = self.items[0].get("name", "Unknown")
            item2 = self.items[1].get("name", "Unknown")
            templates = [
                "I'll have a {item1} and a {item2}",
                "Can I get a {item1} and a {item2}",
                "{item1} and {item2} please",
                "I'd like a {item1} and also a {item2}",
            ]
            template = self.rng.choice(templates)
            user_input = template.format(item1=item1, item2=item2)
            expected_items = [item1, item2]

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.ADD_ITEM,
                        item_name=expected_items[0],
                    ),
                ],
                expected_items_in_cart=expected_items,
                allow_disambiguation=True,
            )
        )

    def _generate_add_modifier_turn(self, modifier: str) -> None:
        """Generate turn to add a specific modifier."""
        item_name = self.items[0].get("name", "Unknown")

        templates = [
            "Add {modifier} to that",
            "Can you add {modifier}",
            "With {modifier} please",
            "Also add {modifier}",
            "Put {modifier} on it",
            "I'd like {modifier} on that",
            "Add {modifier}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(modifier=modifier)

        # Expected items should still be in cart
        expected_items = [item.get("name", "Unknown") for item in self.items]

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.MODIFY_ITEM,
                        item_name=item_name,
                    ),
                ],
                expected_items_in_cart=expected_items,
                allow_disambiguation=True,
            )
        )

    def _generate_remove_modifier_turn(self, modifier: str) -> None:
        """Generate turn to remove a specific modifier."""
        item_name = self.items[0].get("name", "Unknown")

        templates = [
            "Actually no {modifier}",
            "Remove the {modifier}",
            "Hold the {modifier}",
            "No {modifier} please",
            "Take off the {modifier}",
            "Without {modifier}",
            "Skip the {modifier}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(modifier=modifier)

        expected_items = [item.get("name", "Unknown") for item in self.items]

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.MODIFY_ITEM,
                        item_name=item_name,
                    ),
                ],
                expected_items_in_cart=expected_items,
                allow_disambiguation=True,
            )
        )
