"""Modifier-related scenarios (add/remove/substitute)."""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class ModifierScenario(BaseScenario):
    """Scenario for adding or removing modifiers from items."""

    scenario_type = "modifier"

    def __init__(
        self,
        item: dict[str, Any],
        modifier: str,
        action: str = "add",
        seed: int | None = None,
    ) -> None:
        """Initialize modifier scenario.

        Args:
            item: Item dict from menu cache.
            modifier: Modifier to add/remove.
            action: "add" or "remove".
            seed: Random seed.
        """
        item_name = item.get("name", "Unknown")
        action_word = "with" if action == "add" else "without"
        super().__init__(f"Order {item_name} {action_word} {modifier}")

        self.item = item
        self.modifier = modifier
        self.action = action
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the conversation."""
        item_name = self.item.get("name", "Unknown")

        if self.action == "add":
            self._generate_add()
        else:
            self._generate_remove()

    def _generate_add(self) -> None:
        """Generate add modifier scenario."""
        item_name = self.item.get("name", "Unknown")

        templates = [
            "I'll have a {item} with {modifier}",
            "Can I get a {item} with {modifier}",
            "One {item} with {modifier} please",
            "{item} with {modifier}",
            "I'd like a {item} with extra {modifier}",
            "A {item}, add {modifier}",
            "Give me a {item} with {modifier}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(item=item_name, modifier=self.modifier)

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.ADD_ITEM,
                        item_name=item_name,
                    ),
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )

    def _generate_remove(self) -> None:
        """Generate remove modifier scenario."""
        item_name = self.item.get("name", "Unknown")

        templates = [
            "I'll have a {item} without {modifier}",
            "Can I get a {item} no {modifier}",
            "One {item} without {modifier} please",
            "{item} no {modifier}",
            "A {item}, hold the {modifier}",
            "Give me a {item} without the {modifier}",
            "I'd like a {item} minus {modifier}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(item=item_name, modifier=self.modifier)

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.ADD_ITEM,
                        item_name=item_name,
                    ),
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )


class SubstituteModifierScenario(BaseScenario):
    """Scenario for substituting one modifier for another."""

    scenario_type = "substitute_modifier"

    def __init__(
        self,
        item: dict[str, Any],
        original_modifier: str,
        replacement_modifier: str,
        seed: int | None = None,
    ) -> None:
        """Initialize substitute scenario.

        Args:
            item: Item dict from menu cache.
            original_modifier: Modifier to remove.
            replacement_modifier: Modifier to add instead.
            seed: Random seed.
        """
        item_name = item.get("name", "Unknown")
        super().__init__(
            f"Order {item_name} with {replacement_modifier} instead of {original_modifier}"
        )

        self.item = item
        self.original_modifier = original_modifier
        self.replacement_modifier = replacement_modifier
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the conversation."""
        item_name = self.item.get("name", "Unknown")

        templates = [
            "I'll have a {item} with {new} instead of {old}",
            "Can I get a {item} but with {new} instead of {old}",
            "{item} substitute {old} for {new}",
            "A {item}, swap {old} for {new}",
            "One {item} with {new} not {old}",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(
            item=item_name,
            old=self.original_modifier,
            new=self.replacement_modifier,
        )

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.ADD_ITEM,
                        item_name=item_name,
                    ),
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )


class MultipleModifiersScenario(BaseScenario):
    """Scenario for adding multiple modifiers to one item."""

    scenario_type = "multiple_modifiers"

    def __init__(
        self,
        item: dict[str, Any],
        modifiers: list[str],
        seed: int | None = None,
    ) -> None:
        """Initialize multiple modifiers scenario.

        Args:
            item: Item dict from menu cache.
            modifiers: List of modifiers to add.
            seed: Random seed.
        """
        item_name = item.get("name", "Unknown")
        mod_str = ", ".join(modifiers)
        super().__init__(f"Order {item_name} with {mod_str}")

        self.item = item
        self.modifiers = modifiers
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the conversation."""
        item_name = self.item.get("name", "Unknown")

        if len(self.modifiers) == 2:
            mod_str = f"{self.modifiers[0]} and {self.modifiers[1]}"
        else:
            mod_str = ", ".join(self.modifiers[:-1]) + f", and {self.modifiers[-1]}"

        templates = [
            "I'll have a {item} with {modifiers}",
            "Can I get a {item} with {modifiers}",
            "{item} with {modifiers} please",
        ]

        template = self.rng.choice(templates)
        user_input = template.format(item=item_name, modifiers=mod_str)

        self.turns.append(
            ConversationTurn(
                user_input=user_input,
                expected_actions=[
                    ExpectedAction(
                        action_type=ActionType.ADD_ITEM,
                        item_name=item_name,
                    ),
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            )
        )
