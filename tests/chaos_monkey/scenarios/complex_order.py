"""Complex single-line order scenario for Chaos Monkey testing.

Tests the deterministic parser's ability to extract item names, attributes, and
modifiers from dense, detail-rich single sentences like:
- "large everything bagel toasted with lox and cream cheese"
- "I'd like a plain bagel scooped with a little butter please"
- "Can I get a small iced latte with oat milk and vanilla syrup"
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


class ComplexOrderScenario(BaseScenario):
    """Scenario that orders a single item with inline attributes and modifiers.

    Builds one complex natural-language sentence containing the item name plus
    1-3 attributes and 1-3 modifiers. After the initial turn, uses
    ReactiveAnswerGenerator to answer any remaining config questions.
    """

    scenario_type = "complex_order"

    # Sentence openers (empty string = no opener)
    _OPENERS = [
        "I'd like a",
        "Can I get a",
        "One",
        "I'll have a",
        "Give me a",
        "",
    ]

    # Random qualifier prefixes for modifiers
    _QUALIFIERS = ["a little", "extra", "light", ""]

    # Sentence suffixes
    _SUFFIXES = ["on the side", "please", "to go", ""]

    def __init__(
        self,
        item: dict[str, Any],
        attribute_options: dict[str, list[str]],
        boolean_attrs: list[str],
        modifiers: list[str],
        seed: int | None = None,
    ) -> None:
        """Initialize complex order scenario.

        Args:
            item: Menu item dict with 'name' and 'item_type'.
            attribute_options: Dict of attr_slug -> list of option display names.
            boolean_attrs: List of boolean attribute slugs.
            modifiers: List of valid modifier display names for this item type.
            seed: Random seed for reproducibility.
        """
        item_name = item.get("name", "Unknown")
        super().__init__(f"Complex order: {item_name}")

        self.item = item
        self.attribute_options = attribute_options
        self.boolean_attrs = boolean_attrs
        self.modifiers = modifiers
        self.rng = random.Random(seed)

        self._answer_gen = ReactiveAnswerGenerator(
            attribute_options=attribute_options,
            boolean_attrs=boolean_attrs,
            seed=seed,
        )

    def generate(self) -> None:
        """Generate a single complex ordering turn."""
        item_name = self.item.get("name", "Unknown")

        # Build inline parts
        prefix_parts = self._build_prefix_parts()
        modifier_phrase = self._build_modifier_phrase()

        # Assemble the sentence
        user_input = self._assemble_sentence(item_name, prefix_parts, modifier_phrase)

        self.turns.append(ConversationTurn(
            user_input=user_input,
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

    def generate_answer(self, bot_response: str) -> str | None:
        """Generate a natural answer to config questions.

        Delegates to ReactiveAnswerGenerator for any attributes the bot asks
        about that weren't specified in the one-liner.

        Args:
            bot_response: The bot's text response.

        Returns:
            User answer string, or None to stop the reactive loop.
        """
        return self._answer_gen.generate_answer(bot_response)

    def _build_prefix_parts(self) -> list[str]:
        """Build inline attribute parts that go before/around the item name.

        Picks 1-3 attributes from available attribute_options and boolean_attrs.
        Returns parts like ["large", "iced"] or ["everything", "toasted"].
        """
        parts: list[str] = []
        available_attrs: list[tuple[str, str | None]] = []

        # Collect select-type attributes (size, bread, etc.)
        for attr_slug, options in self.attribute_options.items():
            if options:
                available_attrs.append((attr_slug, "select"))

        # Collect boolean attributes (toasted, scooped, etc.)
        for attr_slug in self.boolean_attrs:
            available_attrs.append((attr_slug, "boolean"))

        if not available_attrs:
            return parts

        # Pick 1-3 attributes to include inline
        num_attrs = min(self.rng.randint(1, 3), len(available_attrs))
        chosen = self.rng.sample(available_attrs, num_attrs)

        for attr_slug, attr_type in chosen:
            if attr_type == "select":
                options = self.attribute_options[attr_slug]
                value = self.rng.choice(options)
                parts.append(value.lower())
            elif attr_type == "boolean":
                # Randomly negate: "toasted" vs "not toasted"
                if self.rng.random() < 0.7:
                    parts.append(attr_slug)
                else:
                    parts.append(f"not {attr_slug}")

        return parts

    def _build_modifier_phrase(self) -> str:
        """Build a modifier phrase like "with lox and cream cheese".

        Returns empty string if no modifiers available.
        """
        if not self.modifiers:
            return ""

        num_mods = min(self.rng.randint(1, 3), len(self.modifiers))
        chosen_mods = self.rng.sample(self.modifiers, num_mods)

        # Optionally add qualifiers to some modifiers
        qualified: list[str] = []
        for mod in chosen_mods:
            qualifier = self.rng.choice(self._QUALIFIERS)
            if qualifier:
                qualified.append(f"{qualifier} {mod.lower()}")
            else:
                qualified.append(mod.lower())

        # Join with "and" or commas
        if len(qualified) == 1:
            return f"with {qualified[0]}"
        elif len(qualified) == 2:
            return f"with {qualified[0]} and {qualified[1]}"
        else:
            return f"with {', '.join(qualified[:-1])}, and {qualified[-1]}"

    def _assemble_sentence(
        self,
        item_name: str,
        prefix_parts: list[str],
        modifier_phrase: str,
    ) -> str:
        """Assemble all parts into a natural sentence.

        Args:
            item_name: The menu item display name.
            prefix_parts: Inline attribute values (e.g., ["large", "iced"]).
            modifier_phrase: Modifier string (e.g., "with lox and cream cheese").
        """
        opener = self.rng.choice(self._OPENERS)
        suffix = self.rng.choice(self._SUFFIXES)

        # Build: {opener} {prefix_parts} {item_name} {modifier_phrase} {suffix}
        segments = []

        if opener:
            segments.append(opener)

        if prefix_parts:
            segments.append(" ".join(prefix_parts))

        segments.append(item_name.lower())

        if modifier_phrase:
            segments.append(modifier_phrase)

        if suffix:
            segments.append(suffix)

        # Join and clean up extra whitespace
        sentence = " ".join(segments)
        # Remove double spaces
        while "  " in sentence:
            sentence = sentence.replace("  ", " ")

        return sentence.strip()
