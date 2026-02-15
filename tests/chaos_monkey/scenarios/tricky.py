"""Out-of-place / tricky scenarios that try to confuse the bot.

These scenarios don't use filler words. Instead they try to trick the bot by:
- Giving config answers before they're asked
- Adding items while another is being configured
- Providing multiple attributes in a single message
- Switching context to a different item mid-configuration
- Changing already-answered configuration
- Repeating the same item during configuration
"""

import random
from typing import Any

from tests.chaos_monkey.scenarios.base import (
    ActionType,
    BaseScenario,
    ConversationTurn,
    ExpectedAction,
)


class TrickyScenario(BaseScenario):
    """Scenario that uses out-of-place inputs to try to trick the bot.

    Trick types:
    - add_item_during_config: Add a new item while another is being configured
    - multi_attribute: Order with multiple attributes in one message
    - context_switch: Mention a different item mid-configuration
    - early_answer: Answer a config question with a modifier/attribute for a later step
    - change_config: Change an already-answered config attribute
    - repeat_item: Order the same item again during config
    """

    scenario_type = "tricky"

    def __init__(
        self,
        trick_type: str,
        primary_item: dict[str, Any],
        secondary_item: dict[str, Any] | None,
        attribute_options: dict[str, list[str]],
        boolean_attrs: list[str],
        modifiers: list[str],
        seed: int | None = None,
    ) -> None:
        """Initialize tricky scenario.

        Args:
            trick_type: Type of trick to apply.
            primary_item: Main item being ordered (dict with name, item_type).
            secondary_item: Second item for multi-item tricks.
            attribute_options: Dict of attr_slug -> list of option display names
                for single_select attributes.
            boolean_attrs: List of boolean attribute slugs (e.g., ["toasted", "scooped"]).
            modifiers: Valid modifier display names for the primary item.
            seed: Random seed.
        """
        item_name = primary_item.get("name", "Unknown")
        name = f"Tricky ({trick_type}): {item_name}"
        super().__init__(name)

        self.trick_type = trick_type
        self.primary_item = primary_item
        self.secondary_item = secondary_item
        self.attribute_options = attribute_options
        self.boolean_attrs = boolean_attrs
        self.modifiers = modifiers
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate turns based on trick type."""
        generators = {
            "add_item_during_config": self._gen_add_item_during_config,
            "multi_attribute": self._gen_multi_attribute,
            "context_switch": self._gen_context_switch,
            "early_answer": self._gen_early_answer,
            "change_config": self._gen_change_config,
            "repeat_item": self._gen_repeat_item,
        }
        gen = generators.get(self.trick_type)
        if gen:
            gen()

    def _gen_add_item_during_config(self) -> None:
        """Add a new item while another item is being configured.

        Example:
          User: "Can I get a Plain Bagel"
          Bot: "What kind of bread?"
          User: "And a Joe's Lemonade"
        """
        item1 = self.primary_item.get("name", "Unknown")
        item2 = (self.secondary_item or {}).get("name", item1)

        # Turn 1: Order first item
        templates = [
            "Can I get a {item}",
            "I'll have a {item}",
            "One {item}",
            "I'd like a {item}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(templates).format(item=item1),
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item1),
            ],
            expected_items_in_cart=[item1],
            allow_disambiguation=True,
        ))

        # Turn 2: While being asked a config question, add second item
        add_templates = [
            "And a {item}",
            "Also a {item}",
            "Add a {item}",
            "I also want a {item}",
            "Can I also get a {item}",
            "And also a {item}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(add_templates).format(item=item2),
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item2),
            ],
            expected_items_in_cart=[item1, item2],
            allow_disambiguation=True,
        ))

    def _gen_multi_attribute(self) -> None:
        """Order with multiple attributes in one message.

        Example:
          User: "scooped toasted plain bagel"
          (provides bread=plain, toasted=yes, scooped=yes all at once)
        """
        item_name = self.primary_item.get("name", "Unknown")

        # Collect words to prepend: boolean attrs and one single-select option
        prefix_words = []

        # Add 1-2 boolean attributes as prefix words (e.g., "toasted", "scooped")
        if self.boolean_attrs:
            num_bools = min(len(self.boolean_attrs), self.rng.randint(1, 2))
            chosen_bools = self.rng.sample(self.boolean_attrs, num_bools)
            prefix_words.extend(chosen_bools)

        # Add one single-select option (e.g., "everything" for bread)
        single_select_options = []
        for attr_slug, options in self.attribute_options.items():
            if options:
                single_select_options.append(self.rng.choice(options))
        if single_select_options:
            prefix_words.append(self.rng.choice(single_select_options))

        if not prefix_words:
            # Fallback: just order normally
            self.turns.append(ConversationTurn(
                user_input=f"Can I get a {item_name}",
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            ))
            return

        # Shuffle the prefix words for variety
        self.rng.shuffle(prefix_words)
        attrs_str = " ".join(prefix_words)

        # Build the order
        templates = [
            "{attrs} {item}",
            "I'll have a {attrs} {item}",
            "Can I get a {attrs} {item}",
            "One {attrs} {item}",
            "Give me a {attrs} {item}",
        ]
        user_input = self.rng.choice(templates).format(attrs=attrs_str, item=item_name)

        self.turns.append(ConversationTurn(
            user_input=user_input,
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

    def _gen_context_switch(self) -> None:
        """Order 2 items, then during config of item 1, mention item 2 with attributes.

        Example:
          User: "Plain Bagel and The Health Nut"
          Bot: "For the Plain Bagel, what kind of bread?"
          User: "onion bagel toasted and scooped"
        """
        item1 = self.primary_item.get("name", "Unknown")
        item2 = (self.secondary_item or {}).get("name", item1)

        # Turn 1: Order both items
        templates = [
            "{item1} and {item2}",
            "I'll have a {item1} and a {item2}",
            "Can I get a {item1} and a {item2}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(templates).format(item1=item1, item2=item2),
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item1),
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item2),
            ],
            expected_items_in_cart=[item1, item2],
            allow_disambiguation=True,
        ))

        # Turn 2: Mention item 2 with some attributes while item 1 is being configured
        attr_words = []
        if self.boolean_attrs:
            attr_words.extend(
                self.rng.sample(self.boolean_attrs, min(2, len(self.boolean_attrs)))
            )
        if self.attribute_options:
            # Pick one single-select option
            all_opts = [
                opt for opts in self.attribute_options.values() for opt in opts
            ]
            if all_opts:
                attr_words.append(self.rng.choice(all_opts))

        if attr_words:
            attrs_str = " and ".join(attr_words)
            switch_templates = [
                "{item} {attrs}",
                "make the {item} {attrs}",
                "for the {item} I want {attrs}",
                "{attrs} for the {item}",
            ]
            user_input = self.rng.choice(switch_templates).format(
                item=item2, attrs=attrs_str
            )
        else:
            user_input = f"what about the {item2}"

        self.turns.append(ConversationTurn(
            user_input=user_input,
            expected_actions=[],
            expected_items_in_cart=[item1, item2],
            allow_disambiguation=True,
        ))

    def _gen_early_answer(self) -> None:
        """Answer a config question with a modifier/attribute that hasn't been asked yet.

        Example:
          User: "Can I get a Plain Bagel"
          Bot: "What kind of bread?"
          User: "cream cheese" (answering the spread question, not bread)
        """
        item_name = self.primary_item.get("name", "Unknown")

        # Turn 1: Order item
        templates = [
            "Can I get a {item}",
            "I'll have a {item}",
            "One {item}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(templates).format(item=item_name),
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

        # Turn 2: Instead of answering the first question, give a modifier or later attr
        if self.modifiers:
            modifier = self.rng.choice(self.modifiers)
            early_templates = [
                "{mod}",
                "with {mod}",
                "I want {mod} on that",
                "put {mod} on it",
                "add {mod}",
            ]
            user_input = self.rng.choice(early_templates).format(mod=modifier)
        elif self.attribute_options:
            # Pick an option from a non-first attribute
            attr_slugs = list(self.attribute_options.keys())
            if len(attr_slugs) > 1:
                # Pick from second or later attribute
                later_attr = self.rng.choice(attr_slugs[1:])
                options = self.attribute_options[later_attr]
                if options:
                    user_input = self.rng.choice(options)
                else:
                    user_input = "yes"
            else:
                user_input = "yes"
        else:
            user_input = "yes"

        self.turns.append(ConversationTurn(
            user_input=user_input,
            expected_actions=[],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

    def _gen_change_config(self) -> None:
        """Order with a pre-filled attribute, then change it.

        Example:
          User: "toasted everything bagel"
          Bot: "Any spread?"
          User: "actually make it not toasted"
        """
        item_name = self.primary_item.get("name", "Unknown")

        # Try to use a boolean attribute for the pre-fill and change
        if self.boolean_attrs:
            bool_attr = self.rng.choice(self.boolean_attrs)

            # Turn 1: Order with boolean pre-filled
            templates = [
                "{attr} {item}",
                "I'll have a {attr} {item}",
                "Can I get a {attr} {item}",
            ]
            self.turns.append(ConversationTurn(
                user_input=self.rng.choice(templates).format(
                    attr=bool_attr, item=item_name
                ),
                expected_actions=[
                    ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
                ],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            ))

            # Turn 2: Change the boolean attribute
            change_templates = [
                "actually make it not {attr}",
                "actually not {attr}",
                "wait, don't {attr} it",
                "no wait, un{attr}",
                "scratch that, no {attr}",
            ]
            self.turns.append(ConversationTurn(
                user_input=self.rng.choice(change_templates).format(attr=bool_attr),
                expected_actions=[],
                expected_items_in_cart=[item_name],
                allow_disambiguation=True,
            ))

        elif self.attribute_options:
            # Use a single-select attribute
            changeable = [
                (slug, opts)
                for slug, opts in self.attribute_options.items()
                if len(opts) >= 2
            ]
            if changeable:
                attr_slug, options = self.rng.choice(changeable)
                first_opt, second_opt = self.rng.sample(options, 2)

                # Turn 1: Order with pre-filled option
                self.turns.append(ConversationTurn(
                    user_input=f"I'll have a {first_opt} {item_name}",
                    expected_actions=[
                        ExpectedAction(
                            action_type=ActionType.ADD_ITEM, item_name=item_name
                        ),
                    ],
                    expected_items_in_cart=[item_name],
                    allow_disambiguation=True,
                ))

                # Turn 2: Change to different option
                change_templates = [
                    "actually make it {opt}",
                    "switch to {opt}",
                    "change it to {opt}",
                    "no wait, {opt} instead",
                    "actually {opt}",
                ]
                self.turns.append(ConversationTurn(
                    user_input=self.rng.choice(change_templates).format(opt=second_opt),
                    expected_actions=[],
                    expected_items_in_cart=[item_name],
                    allow_disambiguation=True,
                ))
            else:
                # Fallback
                self._gen_add_item_during_config()
        else:
            self._gen_add_item_during_config()

    def _gen_repeat_item(self) -> None:
        """Order the same item again while it's being configured.

        Example:
          User: "Can I get a Plain Bagel"
          Bot: "What kind of bread?"
          User: "another Plain Bagel"
        """
        item_name = self.primary_item.get("name", "Unknown")

        # Turn 1: Order item
        templates = [
            "Can I get a {item}",
            "I'll have a {item}",
            "One {item}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(templates).format(item=item_name),
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

        # Turn 2: Order same item again during config
        repeat_templates = [
            "another {item}",
            "one more {item}",
            "and another {item}",
            "add another {item}",
            "I'll also have a {item}",
            "also one {item}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(repeat_templates).format(item=item_name),
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))


class MultiAttributeWithModifierScenario(BaseScenario):
    """Order with attributes AND modifiers in one shot, then add more mid-config.

    Example:
      User: "scooped toasted plain bagel with cream cheese"
      Bot: "Any more changes?"
      User: "onion bagel toasted and scooped"  (switch to new item mid-config)
    """

    scenario_type = "tricky"

    def __init__(
        self,
        primary_item: dict[str, Any],
        secondary_item: dict[str, Any] | None,
        attribute_options: dict[str, list[str]],
        boolean_attrs: list[str],
        modifiers: list[str],
        seed: int | None = None,
    ) -> None:
        item_name = primary_item.get("name", "Unknown")
        super().__init__(f"Tricky (multi_attr_modifier): {item_name}")

        self.primary_item = primary_item
        self.secondary_item = secondary_item
        self.attribute_options = attribute_options
        self.boolean_attrs = boolean_attrs
        self.modifiers = modifiers
        self.rng = random.Random(seed)

    def generate(self) -> None:
        """Generate the multi-attribute + modifier flow."""
        item1 = self.primary_item.get("name", "Unknown")
        item2 = (self.secondary_item or {}).get("name", item1)

        # Build prefix: boolean attrs + single-select option
        prefix_words = []
        if self.boolean_attrs:
            num = min(len(self.boolean_attrs), self.rng.randint(1, 2))
            prefix_words.extend(self.rng.sample(self.boolean_attrs, num))
        if self.attribute_options:
            all_opts = [
                opt for opts in self.attribute_options.values() for opt in opts
            ]
            if all_opts:
                prefix_words.append(self.rng.choice(all_opts))

        self.rng.shuffle(prefix_words)
        prefix = " ".join(prefix_words) if prefix_words else ""

        # Build modifier suffix
        modifier = self.rng.choice(self.modifiers) if self.modifiers else None
        mod_suffix = f" with {modifier}" if modifier else ""

        # Turn 1: Order with everything packed in
        if prefix:
            user_input = f"{prefix} {item1}{mod_suffix}"
        else:
            user_input = f"{item1}{mod_suffix}"

        self.turns.append(ConversationTurn(
            user_input=user_input,
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item1),
            ],
            expected_items_in_cart=[item1],
            allow_disambiguation=True,
        ))

        # Turn 2: Answer a config question normally (if one is asked)
        if self.modifiers and modifier:
            # Pick a different modifier
            other_mods = [m for m in self.modifiers if m != modifier]
            if other_mods:
                mod2 = self.rng.choice(other_mods)
                self.turns.append(ConversationTurn(
                    user_input=mod2,
                    expected_actions=[],
                    expected_items_in_cart=[item1],
                    allow_disambiguation=True,
                ))

        # Turn 3: Context switch - mention a different item with attributes
        if item2 != item1:
            switch_words = []
            if self.boolean_attrs:
                switch_words.extend(
                    self.rng.sample(
                        self.boolean_attrs, min(2, len(self.boolean_attrs))
                    )
                )
            if self.attribute_options:
                all_opts = [
                    opt for opts in self.attribute_options.values() for opt in opts
                ]
                if all_opts:
                    switch_words.append(self.rng.choice(all_opts))

            if switch_words:
                self.rng.shuffle(switch_words)
                attrs_str = " and ".join(switch_words)
                switch_templates = [
                    "{item} {attrs}",
                    "{attrs} {item}",
                    "make the {item} {attrs}",
                ]
                user_input = self.rng.choice(switch_templates).format(
                    item=item2, attrs=attrs_str
                )
            else:
                user_input = f"what about the {item2}"

            self.turns.append(ConversationTurn(
                user_input=user_input,
                expected_actions=[],
                expected_items_in_cart=[item1],
                allow_disambiguation=True,
            ))
