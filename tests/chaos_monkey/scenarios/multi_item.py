"""Multi-item ordering scenarios."""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class MultiItemScenario(BaseScenario):
    """Scenario for ordering multiple items together."""

    scenario_type = "multi_item"

    def __init__(
        self,
        items: list[dict[str, Any]],
        ordering_style: str | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize multi-item scenario.

        Args:
            items: List of item dicts from menu cache.
            ordering_style: "together" or "sequential". Random if None.
            seed: Random seed for reproducibility.
        """
        item_names = [item.get("name", "Unknown") for item in items]
        super().__init__(f"Order {' and '.join(item_names)}")
        self.items = items
        self.rng = random.Random(seed)
        self.ordering_style = ordering_style or self.rng.choice(["together", "sequential"])

    def generate(self) -> None:
        """Generate conversation turns for multi-item ordering."""
        if self.ordering_style == "together":
            self._generate_together()
        else:
            self._generate_sequential()

    def _generate_together(self) -> None:
        """Generate a single message ordering multiple items."""
        item_names = [item.get("name", "Unknown") for item in self.items]

        # Various ways to combine items
        templates = [
            "I'll have a {item1} and a {item2}",
            "Can I get a {item1} and also a {item2}",
            "I'd like a {item1} plus a {item2}",
            "One {item1} and one {item2} please",
            "{item1} and {item2}",
            "I want a {item1}, and a {item2}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(
            item1=item_names[0],
            item2=item_names[1] if len(item_names) > 1 else item_names[0],
        )

        # Expect both items to be added
        expected_actions = [
            ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=name)
            for name in item_names
        ]

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=expected_actions,
                expected_items_in_cart=item_names,
                allow_disambiguation=True,
            )
        )

    def _generate_sequential(self) -> None:
        """Generate separate messages for each item."""
        item_names = [item.get("name", "Unknown") for item in self.items]

        phrases = [
            "I'll have a {item}",
            "Can I get a {item}",
            "And a {item}",
            "Also a {item}",
            "Add a {item}",
        ]

        items_so_far = []
        for i, name in enumerate(item_names):
            # Use different phrase for first vs subsequent items
            if i == 0:
                phrase = self.rng.choice(phrases[:2])
            else:
                phrase = self.rng.choice(phrases[2:])

            user_input = phrase.format(item=name)
            items_so_far.append(name)

            self.turns.append(
                ConversationTurn(
                    user_input=user_input,
                    expected_actions=[
                        ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=name)
                    ],
                    expected_items_in_cart=items_so_far.copy(),
                    allow_disambiguation=True,
                )
            )


class MultiItemWithModifiersScenario(BaseScenario):
    """Scenario for ordering multiple items with different modifiers."""

    scenario_type = "multi_item_modifiers"

    def __init__(
        self,
        item1: dict[str, Any],
        item1_modifier: str,
        item2: dict[str, Any],
        item2_modifier: str,
        seed: int | None = None,
    ) -> None:
        """Initialize scenario.

        Args:
            item1: First item dict.
            item1_modifier: Modifier for first item.
            item2: Second item dict.
            item2_modifier: Modifier for second item.
            seed: Random seed.
        """
        name1 = item1.get("name", "Unknown")
        name2 = item2.get("name", "Unknown")
        super().__init__(f"Order {name1} with {item1_modifier} and {name2} with {item2_modifier}")

        self.item1 = item1
        self.item1_modifier = item1_modifier
        self.item2 = item2
        self.item2_modifier = item2_modifier
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the conversation."""
        name1 = self.item1.get("name", "Unknown")
        name2 = self.item2.get("name", "Unknown")

        templates = [
            "I'll have a {item1} with {mod1} and a {item2} with {mod2}",
            "Can I get a {item1} {mod1} and a {item2} {mod2}",
            "One {item1} with {mod1}, and one {item2} with {mod2}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(
            item1=name1,
            mod1=self.item1_modifier,
            item2=name2,
            mod2=self.item2_modifier,
        )

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=name1),
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=name2),
                ],
                expected_items_in_cart=[name1, name2],
                allow_disambiguation=True,
            )
        )
