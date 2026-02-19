"""Reactive realistic order scenario that answers config questions naturally.

Unlike pre-scripted scenarios, this scenario reacts to bot responses:
- Orders 1-2 items in the initial turn
- Answers config questions (bread, size, toasted, etc.) based on bot response keywords
- Stops when the bot asks "anything else?" or config is done
"""

import random
from typing import Any

from tests.chaos_monkey.scenarios.answer_generator import ReactiveAnswerGenerator
from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class RealisticOrderScenario(BaseScenario):
    """Scenario that orders items and reactively answers config questions.

    The generate() method creates only the initial ordering turn.
    After each bot response, the executor calls generate_answer() to get
    the next user reply based on what the bot asked.
    """

    scenario_type = "realistic_order"

    def __init__(
        self,
        items: list[dict[str, Any]],
        attribute_options: dict[str, list[str]],
        boolean_attrs: list[str],
        seed: int | None = None,
    ) -> None:
        """Initialize realistic order scenario.

        Args:
            items: 1-2 menu items to order (dicts with name, item_type).
            attribute_options: Dict of attr_slug -> list of option display names.
            boolean_attrs: List of boolean attribute slugs.
            seed: Random seed.
        """
        names = [item.get("name", "Unknown") for item in items]
        name = f"Realistic order: {', '.join(names)}"
        super().__init__(name)

        self.items = items
        self.rng = random.Random(seed)

        self._answer_gen = ReactiveAnswerGenerator(
            attribute_options=attribute_options,
            boolean_attrs=boolean_attrs,
            seed=seed,
        )

    def generate(self) -> None:
        """Generate only the initial ordering turn."""
        names = [item.get("name", "Unknown") for item in self.items]

        if len(names) == 1:
            templates = [
                "Can I get a {item}",
                "I'll have a {item}",
                "One {item} please",
                "I'd like a {item}",
            ]
            user_input = self.rng.choice(templates).format(item=names[0])
        else:
            templates = [
                "I'll have a {item1} and a {item2}",
                "Can I get a {item1} and a {item2}",
                "{item1} and {item2} please",
                "I'd like a {item1} and also a {item2}",
            ]
            user_input = self.rng.choice(templates).format(
                item1=names[0], item2=names[1]
            )

        expected_actions = [
            ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=n)
            for n in names
        ]

        self.turns.append(ConversationTurn(
            user_input=user_input,
            expected_actions=expected_actions,
            expected_items_in_cart=list(names),
            allow_disambiguation=True,
        ))

    def generate_answer(self, bot_response: str) -> str | None:
        """Generate a natural answer based on the bot's response.

        Delegates to the shared ReactiveAnswerGenerator.

        Args:
            bot_response: The bot's text response to react to.

        Returns:
            User answer string, or None to stop the reactive loop.
        """
        return self._answer_gen.generate_answer(bot_response)
