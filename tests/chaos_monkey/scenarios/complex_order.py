"""Complex single-line order scenario for Chaos Monkey testing.

Tests the deterministic parser's ability to extract item names, attributes, and
modifiers from dense, detail-rich single sentences like:
- "large iced latte with oat milk and vanilla syrup"
- "everything bagel toasted with a little butter"
- "the tribeca toasted with extra cream cheese please"
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
    0-2 inline attributes and 1-2 modifiers. After the initial turn, uses
    ReactiveAnswerGenerator to answer any remaining config questions.

    Realism rules:
    - Only "size" and boolean attrs (toasted, scooped, iced) appear inline.
      Bread, cheese, and other select attrs are left for the bot to ask about.
    - Modifiers exclude bread-like words (bagel, wrap, flatz, etc.) since those
      are attribute choices, not toppings.
    - Max 2 modifiers with infrequent qualifiers for natural-sounding sentences.
    """

    scenario_type = "complex_order"

    _OPENERS = [
        "I'd like a",
        "Can I get a",
        "One",
        "I'll have a",
        "Give me a",
        "",
    ]

    _SUFFIXES = ["please", "to go", ""]

    # Words that indicate a bread/base option rather than a topping
    _BREAD_WORDS = frozenset({
        "bagel", "bread", "wrap", "flatz", "flagel", "bialy", "sourdough",
        "rye", "pumpernickel", "roll", "croissant", "artisan", "baguette",
        "pita", "tortilla", "ciabatta",
    })

    # Attributes that make sense as inline prefixes (before or after item name)
    _PREFIX_ATTR_SLUGS = frozenset({"size"})

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

        prefix_parts = self._build_prefix_parts()
        suffix_parts = self._build_suffix_parts()
        modifier_phrase = self._build_modifier_phrase()

        user_input = self._assemble_sentence(
            item_name, prefix_parts, suffix_parts, modifier_phrase,
        )

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

        Args:
            bot_response: The bot's text response.

        Returns:
            User answer string, or None to stop the reactive loop.
        """
        return self._answer_gen.generate_answer(bot_response)

    def _build_prefix_parts(self) -> list[str]:
        """Build parts that go BEFORE the item name.

        Only uses "size" attribute — e.g., "large", "small".
        Other select attrs (bread, cheese) are skipped to avoid unrealistic
        sentences like "poppy bagel the tribeca".
        """
        parts: list[str] = []

        for attr_slug in self._PREFIX_ATTR_SLUGS:
            if attr_slug in self.attribute_options and self.rng.random() < 0.6:
                options = self.attribute_options[attr_slug]
                if options:
                    parts.append(self.rng.choice(options).lower())

        return parts

    def _build_suffix_parts(self) -> list[str]:
        """Build parts that go AFTER the item name but before modifiers.

        Uses boolean attrs — e.g., "toasted", "not toasted", "scooped", "iced".
        These read naturally after the item name: "everything bagel toasted",
        "the tribeca toasted", "iced latte".
        """
        parts: list[str] = []

        if not self.boolean_attrs:
            return parts

        # Pick 0-1 boolean attrs (60% chance of including one)
        if self.rng.random() < 0.6:
            attr = self.rng.choice(self.boolean_attrs)
            if self.rng.random() < 0.75:
                parts.append(attr)
            else:
                parts.append(f"not {attr}")

        return parts

    def _is_bread_modifier(self, modifier: str) -> bool:
        """Check if a modifier is actually a bread/base option, not a topping."""
        words = modifier.lower().split()
        return any(w in self._BREAD_WORDS for w in words)

    def _get_filtered_modifiers(self) -> list[str]:
        """Get modifiers with bread-like options removed."""
        filtered = []
        for mod in self.modifiers:
            if self._is_bread_modifier(mod):
                continue
            # Skip very long modifier names (4+ words are usually not toppings)
            if len(mod.split()) > 3:
                continue
            filtered.append(mod)
        return filtered

    def _build_modifier_phrase(self) -> str:
        """Build a modifier phrase like "with lox and cream cheese".

        Uses max 2 modifiers with infrequent qualifiers for realism.
        """
        available = self._get_filtered_modifiers()
        if not available:
            return ""

        num_mods = min(self.rng.randint(1, 2), len(available))
        chosen_mods = self.rng.sample(available, num_mods)

        qualified: list[str] = []
        for mod in chosen_mods:
            # 25% chance of a qualifier — keeps most modifiers clean
            if self.rng.random() < 0.25:
                qualifier = self.rng.choice(["a little", "extra"])
                qualified.append(f"{qualifier} {mod.lower()}")
            else:
                qualified.append(mod.lower())

        if len(qualified) == 1:
            return f"with {qualified[0]}"
        else:
            return f"with {qualified[0]} and {qualified[1]}"

    def _assemble_sentence(
        self,
        item_name: str,
        prefix_parts: list[str],
        suffix_parts: list[str],
        modifier_phrase: str,
    ) -> str:
        """Assemble all parts into a natural sentence.

        Order: {opener} {size} {item_name} {toasted/scooped} {with mods} {please/to go}

        Args:
            item_name: The menu item display name.
            prefix_parts: Parts before item name (size).
            suffix_parts: Parts after item name (boolean attrs).
            modifier_phrase: Modifier string (e.g., "with lox and cream cheese").
        """
        opener = self.rng.choice(self._OPENERS)
        suffix = self.rng.choice(self._SUFFIXES)

        segments = []

        if opener:
            segments.append(opener)

        if prefix_parts:
            segments.append(" ".join(prefix_parts))

        segments.append(item_name.lower())

        if suffix_parts:
            segments.append(" ".join(suffix_parts))

        if modifier_phrase:
            segments.append(modifier_phrase)

        if suffix:
            segments.append(suffix)

        sentence = " ".join(segments)
        while "  " in sentence:
            sentence = sentence.replace("  ", " ")

        return sentence.strip()
