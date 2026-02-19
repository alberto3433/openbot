"""Corpus-based ordering scenario that uses realistic conversation patterns.

Fills slot placeholders from menu data and uses the shared ReactiveAnswerGenerator
to handle follow-up config questions from the bot.
"""

from typing import Any

from tests.chaos_monkey.scenarios.answer_generator import ReactiveAnswerGenerator
from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)
from tests.chaos_monkey.scenarios.corpus import ConversationPattern


class CorpusOrderScenario(BaseScenario):
    """Scenario that plays out a realistic conversation pattern.

    The generate() method fills pattern templates with actual menu data
    and creates conversation turns. After the scripted turns, the executor's
    reactive loop calls generate_answer() to handle config questions.
    """

    scenario_type = "corpus_order"

    def __init__(
        self,
        pattern: ConversationPattern,
        filled_slots: dict[str, str],
        attribute_options: dict[str, list[str]],
        boolean_attrs: list[str],
        expected_cart_items: list[str],
        seed: int | None = None,
    ) -> None:
        """Initialize corpus order scenario.

        Args:
            pattern: The conversation pattern to execute.
            filled_slots: Dict mapping slot names to filled values.
            attribute_options: Dict of attr_slug -> list of option display names
                (for the reactive answer generator).
            boolean_attrs: List of boolean attribute slugs.
            expected_cart_items: Item names expected in cart after scripted turns.
            seed: Random seed.
        """
        name = f"Corpus [{pattern.category.value}]: {pattern.description}"
        super().__init__(name)

        self.pattern = pattern
        self.filled_slots = filled_slots
        self.expected_cart_items = expected_cart_items

        self._answer_gen = ReactiveAnswerGenerator(
            attribute_options=attribute_options,
            boolean_attrs=boolean_attrs,
            seed=seed,
        )

    def generate(self) -> None:
        """Generate conversation turns from the pattern templates."""
        for turn_template in self.pattern.turns:
            # Fill slot placeholders in the template
            user_input = turn_template.template.format(**self.filled_slots)

            # Build expected actions for non-inquiry turns
            expected_actions: list[ExpectedAction] = []
            if not turn_template.is_menu_inquiry:
                # For each expected_item_slot, expect an ADD_ITEM action
                for slot_name in self.pattern.expected_item_slots:
                    if slot_name in self.filled_slots:
                        expected_actions.append(
                            ExpectedAction(
                                action_type=ActionType.ADD_ITEM,
                                item_name=self.filled_slots[slot_name],
                            )
                        )

            self.turns.append(ConversationTurn(
                user_input=user_input,
                expected_actions=expected_actions,
                expected_items_in_cart=list(self.expected_cart_items),
                allow_disambiguation=True,
                is_menu_inquiry=turn_template.is_menu_inquiry,
            ))

    def generate_answer(self, bot_response: str) -> str | None:
        """Generate a reactive answer to a bot config question.

        Delegates to the shared ReactiveAnswerGenerator.

        Args:
            bot_response: The bot's text response.

        Returns:
            User answer string, or None to stop the reactive loop.
        """
        return self._answer_gen.generate_answer(bot_response)
