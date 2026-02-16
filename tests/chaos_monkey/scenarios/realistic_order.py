"""Reactive realistic order scenario that answers config questions naturally.

Unlike pre-scripted scenarios, this scenario reacts to bot responses:
- Orders 1-2 items in the initial turn
- Answers config questions (bread, size, toasted, etc.) based on bot response keywords
- Stops when the bot asks "anything else?" or config is done
"""

import random
import re
from typing import Any

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
        self.attribute_options = attribute_options
        self.boolean_attrs = boolean_attrs
        self.rng = random.Random(seed)

        # Flatten all valid option values for answering select questions
        self._all_options: list[str] = []
        for opts in attribute_options.values():
            self._all_options.extend(opts)

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

        Called by the executor after each bot response. Returns None when
        config is done (bot asks "anything else?" or similar end-of-config).

        Args:
            bot_response: The bot's text response to react to.

        Returns:
            User answer string, or None to stop the reactive loop.
        """
        resp = bot_response.lower()

        # End-of-config detection — stop the reactive loop
        if self._is_end_of_config(resp):
            return None

        # Numbered list (disambiguation) — pick "1"
        if re.search(r"^\s*1\.\s+", bot_response, re.MULTILINE):
            return "1"

        # Bread/bagel type question
        if self._matches_any(resp, ["what kind of bread", "what kind of bagel",
                                     "what type of bagel", "which bagel"]):
            bread_options = self.attribute_options.get("bread", [])
            if bread_options:
                return self.rng.choice(bread_options)
            return self.rng.choice(["plain", "everything", "sesame"])

        # Size question
        if self._matches_any(resp, ["what size", "small or large", "which size",
                                     "small, medium, or large"]):
            size_options = self.attribute_options.get("size", [])
            if size_options:
                return self.rng.choice(size_options)
            return self.rng.choice(["large", "small"])

        # Toasted question
        if "toasted" in resp or "toast" in resp:
            return self.rng.choice(["yes", "no"])

        # Hot or iced question
        if self._matches_any(resp, ["hot or iced", "iced or hot",
                                     "would you like it hot", "would you like it iced"]):
            return self.rng.choice(["hot", "iced"])

        # Scooped question
        if "scooped" in resp or "scoop" in resp:
            return self.rng.choice(["yes", "no"])

        # Optional add-on questions (spread, milk, sweetener, syrup, extras)
        if self._matches_any(resp, ["any spread", "any milk", "any sweetener",
                                     "any syrup", "would you like any",
                                     "any extras", "anything on"]):
            # 80% decline, 20% pick a valid option
            if self.rng.random() < 0.8 or not self._all_options:
                return self.rng.choice(["no thanks", "no", "nope", "I'm good"])
            return self.rng.choice(self._all_options)

        # Quantity / "how many" question
        if self._matches_any(resp, ["how many", "quantity"]):
            return "no"

        # Side choice question — "Would you like a bagel or fruit salad with it?"
        if self._matches_any(resp, ["side choice", "for side", "which side",
                                     "choose a side", "bagel or fruit salad",
                                     "fruit salad or bagel"]):
            # Pick a specific side or decline (never answer "yes" to an either/or)
            return self.rng.choice(["no thanks", "bagel", "fruit salad"])

        # Either/or question — extract the options and pick one
        or_match = re.search(
            r"would you like (?:a |an )?(.+?) or (?:a |an )?(.+?)(?:\?|with)",
            resp,
        )
        if or_match:
            option_a = or_match.group(1).strip().rstrip("?")
            option_b = or_match.group(2).strip().rstrip("?")
            return self.rng.choice([option_a, option_b, "no thanks"])

        # Generic yes/no question fallback (only for actual yes/no questions)
        if "?" in resp:
            return self.rng.choice(["no thanks", "no"])

        # No question detected — stop
        return None

    def _is_end_of_config(self, resp: str) -> bool:
        """Check if bot is done configuring and asking if we want anything else."""
        end_patterns = [
            "anything else",
            "would you like anything else",
            "can i get you anything else",
            "is that everything",
            "will that be all",
            "that all for you",
            "is that all",
            "ready to checkout",
            "ready to check out",
            "would you like to checkout",
            "would you like to check out",
            "for pickup or delivery",
            "pickup or delivery",
        ]
        return self._matches_any(resp, end_patterns)

    @staticmethod
    def _matches_any(text: str, patterns: list[str]) -> bool:
        """Check if text contains any of the given patterns."""
        return any(p in text for p in patterns)
