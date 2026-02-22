"""Regression scenarios that test patterns from past bug fixes.

Each scenario class corresponds to a specific bug pattern that was found in
production and fixed. These scenarios ensure those bugs don't regress.

Bug patterns tested:
1. "make it pickup" emptied cart (order type confused as item replacement)
2. "no black please" = cancellation (attribute decline treated as item removal)
3. Qualifier lost in disambiguation ("extra" dropped after disambig)
4. Self-referential instruction leak (item name leaked into special instructions)
5. "change it to delivery" misrouted (treated as modifier change)
6. Phase lost after customer edit (editing info then continuing order)
7. Item vs category query routing (specific item routed to category browser)
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


class OrderTypeConfusionScenario(BaseScenario):
    """Tests that 'make it pickup/delivery' doesn't destroy the cart.

    Bug pattern #1: "make it pickup" after adding items emptied the cart
    because the order type change was confused as an item replacement.

    This is a reactive scenario: it answers config questions first (since the
    bot may defer order type during config), then checks that both the item
    and order type are correctly set.
    """

    scenario_type = "regression"

    # States for reactive answer generation
    _STATE_ORDERING = "ordering"
    _STATE_CONFIGURING = "configuring"
    _STATE_SET_ORDER_TYPE = "set_order_type"
    _STATE_DONE = "done"

    def __init__(
        self,
        item: dict[str, Any],
        attribute_options: dict[str, list[str]] | None = None,
        boolean_attrs: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        item_name = item.get("name", "Unknown")
        super().__init__(f"Regression: order type confusion ({item_name})")
        self.item = item
        self.rng = random.Random(seed)

        self._answer_gen = ReactiveAnswerGenerator(
            attribute_options=attribute_options or {},
            boolean_attrs=boolean_attrs or [],
            seed=seed,
        )

        self._order_type = self.rng.choice(["pickup", "delivery"])
        phrases = {
            "pickup": [
                "make it pickup",
                "make it for pickup",
                "this is for pickup",
                "I'll pick it up",
                "pickup please",
            ],
            "delivery": [
                "make it delivery",
                "make it for delivery",
                "this is for delivery",
                "I need it delivered",
                "delivery please",
            ],
        }
        self._order_type_phrase = self.rng.choice(phrases[self._order_type])
        self._state = self._STATE_ORDERING
        self._config_turns = 0

    def generate(self) -> None:
        item_name = self.item.get("name", "Unknown")

        # Turn 1: Add an item
        self.turns.append(ConversationTurn(
            user_input=f"I'd like a {item_name}",
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))
        self._state = self._STATE_CONFIGURING

    def generate_answer(self, bot_response: str) -> str | None:
        """React to bot responses: answer config, then set order type."""
        response_lower = bot_response.lower()

        if self._state == self._STATE_CONFIGURING:
            # Answer config questions until bot asks "anything else?"
            done_phrases = [
                "anything else", "will that be all", "what else",
                "ready to", "would you like anything", "can i get you anything",
            ]
            if any(p in response_lower for p in done_phrases):
                # Config done — now set order type
                self._state = self._STATE_SET_ORDER_TYPE
                return self._order_type_phrase

            # Safety: don't loop forever
            self._config_turns += 1
            if self._config_turns > 8:
                self._state = self._STATE_SET_ORDER_TYPE
                return self._order_type_phrase

            # Try reactive answer for config questions
            answer = self._answer_gen.generate_answer(bot_response)
            if answer is not None:
                return answer

            # No config question detected — set order type now
            self._state = self._STATE_SET_ORDER_TYPE
            return self._order_type_phrase

        if self._state == self._STATE_SET_ORDER_TYPE:
            # We just sent the order type phrase — done
            self._state = self._STATE_DONE
            return None

        return None


class AttributeDeclineScenario(BaseScenario):
    """Tests that declining an attribute option doesn't remove the item.

    Bug pattern #2: "no black please" during coffee config was treated as
    item removal instead of declining the attribute option.
    """

    scenario_type = "regression"

    def __init__(
        self,
        item: dict[str, Any],
        attribute_options: dict[str, list[str]],
        seed: int | None = None,
    ) -> None:
        item_name = item.get("name", "Unknown")
        super().__init__(f"Regression: attribute decline ({item_name})")
        self.item = item
        self.attribute_options = attribute_options
        self.rng = random.Random(seed)

    def generate(self) -> None:
        item_name = self.item.get("name", "Unknown")

        # Turn 1: Order the item
        self.turns.append(ConversationTurn(
            user_input=f"I'd like a {item_name}",
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

        # Turn 2: Decline an attribute option — item must stay
        # Find an option to decline from any attribute
        decline_option = None
        for options in self.attribute_options.values():
            if options:
                decline_option = self.rng.choice(options)
                break

        if decline_option is None:
            decline_option = "that"

        decline_phrases = [
            f"no {decline_option} please",
            f"not {decline_option}",
            f"skip the {decline_option}",
            "none",
            "no thanks",
        ]
        phrase = self.rng.choice(decline_phrases)

        self.turns.append(ConversationTurn(
            user_input=phrase,
            expected_items_in_cart=[item_name],
            expect_item_count=1,
            allow_disambiguation=True,
        ))


class QualifierPersistenceScenario(BaseScenario):
    """Tests that qualifiers survive disambiguation.

    Bug pattern #3: "extra large iced latte" led to disambiguation, and
    after selecting an option, the "extra" qualifier was dropped.
    """

    scenario_type = "regression"

    def __init__(
        self,
        item: dict[str, Any],
        qualifier: str,
        seed: int | None = None,
    ) -> None:
        item_name = item.get("name", "Unknown")
        super().__init__(f"Regression: qualifier persistence ({qualifier} {item_name})")
        self.item = item
        self.qualifier = qualifier
        self.rng = random.Random(seed)

    def generate(self) -> None:
        item_name = self.item.get("name", "Unknown")

        # Turn 1: Order with qualifier — may trigger disambiguation
        templates = [
            f"{self.qualifier} {item_name}",
            f"I'd like a {self.qualifier} {item_name}",
            f"Can I get a {self.qualifier} {item_name}",
        ]
        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(templates),
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

        # Turn 2: If disambiguation, pick first option
        self.turns.append(ConversationTurn(
            user_input="1",
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))


class OrderTypeMidOrderScenario(BaseScenario):
    """Tests that 'change it to delivery/pickup' mid-order sets order type.

    Bug pattern #5: "change it to delivery" mid-order was treated as a
    modifier change instead of setting the order type.

    This is reactive: answers config questions first, then changes order type.
    """

    scenario_type = "regression"

    _STATE_CONFIGURING = "configuring"
    _STATE_SET_ORDER_TYPE = "set_order_type"
    _STATE_DONE = "done"

    def __init__(
        self,
        item: dict[str, Any],
        attribute_options: dict[str, list[str]] | None = None,
        boolean_attrs: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        item_name = item.get("name", "Unknown")
        super().__init__(f"Regression: order type mid-order ({item_name})")
        self.item = item
        self.rng = random.Random(seed)

        self._answer_gen = ReactiveAnswerGenerator(
            attribute_options=attribute_options or {},
            boolean_attrs=boolean_attrs or [],
            seed=seed,
        )

        self._order_type = self.rng.choice(["pickup", "delivery"])
        phrases = {
            "pickup": [
                "change it to pickup",
                "actually make it pickup",
                "switch to pickup",
                "let's do pickup instead",
            ],
            "delivery": [
                "change it to delivery",
                "actually make it delivery",
                "switch to delivery",
                "let's do delivery instead",
            ],
        }
        self._order_type_phrase = self.rng.choice(phrases[self._order_type])
        self._state = self._STATE_CONFIGURING
        self._config_turns = 0

    def generate(self) -> None:
        item_name = self.item.get("name", "Unknown")

        # Turn 1: Add item
        self.turns.append(ConversationTurn(
            user_input=f"I'd like a {item_name}",
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=item_name),
            ],
            expected_items_in_cart=[item_name],
            allow_disambiguation=True,
        ))

    def generate_answer(self, bot_response: str) -> str | None:
        """React to bot responses: answer config, then change order type."""
        response_lower = bot_response.lower()

        if self._state == self._STATE_CONFIGURING:
            done_phrases = [
                "anything else", "will that be all", "what else",
                "ready to", "would you like anything", "can i get you anything",
            ]
            if any(p in response_lower for p in done_phrases):
                self._state = self._STATE_SET_ORDER_TYPE
                return self._order_type_phrase

            self._config_turns += 1
            if self._config_turns > 8:
                self._state = self._STATE_SET_ORDER_TYPE
                return self._order_type_phrase

            answer = self._answer_gen.generate_answer(bot_response)
            if answer is not None:
                return answer

            self._state = self._STATE_SET_ORDER_TYPE
            return self._order_type_phrase

        if self._state == self._STATE_SET_ORDER_TYPE:
            self._state = self._STATE_DONE
            return None

        return None


class InstructionLeakScenario(BaseScenario):
    """Tests that ordering 'X on the side' doesn't leak item name into instructions.

    Bug pattern #4: "Hot Coffee on the side" caused "coffee on the side" to
    appear as a special instruction on the item.
    """

    scenario_type = "regression"

    def __init__(
        self,
        item: dict[str, Any],
        seed: int | None = None,
    ) -> None:
        item_name = item.get("name", "Unknown")
        super().__init__(f"Regression: instruction leak ({item_name})")
        self.item = item
        self.rng = random.Random(seed)

    def generate(self) -> None:
        item_name = self.item.get("name", "Unknown")

        phrases = [
            f"{item_name} on the side",
            f"I'd like a {item_name} on the side",
            f"Can I get a {item_name} on the side",
        ]

        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(phrases),
            expected_items_in_cart=[item_name],
            expect_no_special_instruction_contains=item_name.lower(),
            allow_disambiguation=True,
        ))


class PhaseRestorationScenario(BaseScenario):
    """Tests that editing customer info mid-order returns to the right phase.

    Bug pattern #6: After providing a name mid-order, the system lost track
    of the current phase and couldn't continue adding items.

    This is reactive: answers config questions for item 1, provides name,
    then adds item 2.
    """

    scenario_type = "regression"

    _STATE_CONFIGURING = "configuring"
    _STATE_GIVE_NAME = "give_name"
    _STATE_ADD_ITEM2 = "add_item2"
    _STATE_DONE = "done"

    def __init__(
        self,
        item1: dict[str, Any],
        item2: dict[str, Any],
        attribute_options: dict[str, list[str]] | None = None,
        boolean_attrs: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        name1 = item1.get("name", "Unknown")
        name2 = item2.get("name", "Unknown")
        super().__init__(f"Regression: phase restoration ({name1}, {name2})")
        self.item1 = item1
        self.item2 = item2
        self.rng = random.Random(seed)

        self._answer_gen = ReactiveAnswerGenerator(
            attribute_options=attribute_options or {},
            boolean_attrs=boolean_attrs or [],
            seed=seed,
        )

        self._state = self._STATE_CONFIGURING
        self._config_turns = 0
        test_names = ["Test", "Alex", "Jordan", "Sam", "Pat"]
        self._test_name = self.rng.choice(test_names)

    def generate(self) -> None:
        name1 = self.item1.get("name", "Unknown")

        # Turn 1: Add first item
        self.turns.append(ConversationTurn(
            user_input=f"I'd like a {name1}",
            expected_actions=[
                ExpectedAction(action_type=ActionType.ADD_ITEM, item_name=name1),
            ],
            expected_items_in_cart=[name1],
            allow_disambiguation=True,
        ))

    def generate_answer(self, bot_response: str) -> str | None:
        """React to bot: config item 1, give name, add item 2."""
        response_lower = bot_response.lower()

        if self._state == self._STATE_CONFIGURING:
            done_phrases = [
                "anything else", "will that be all", "what else",
                "ready to", "would you like anything", "can i get you anything",
            ]
            if any(p in response_lower for p in done_phrases):
                self._state = self._STATE_GIVE_NAME
                return f"my name is {self._test_name}"

            self._config_turns += 1
            if self._config_turns > 8:
                self._state = self._STATE_GIVE_NAME
                return f"my name is {self._test_name}"

            answer = self._answer_gen.generate_answer(bot_response)
            if answer is not None:
                return answer

            self._state = self._STATE_GIVE_NAME
            return f"my name is {self._test_name}"

        if self._state == self._STATE_GIVE_NAME:
            name2 = self.item2.get("name", "Unknown")
            self._state = self._STATE_ADD_ITEM2
            return f"actually, I also want a {name2}"

        if self._state == self._STATE_ADD_ITEM2:
            self._state = self._STATE_DONE
            return None

        return None


class AvailabilityInquiryScenario(BaseScenario):
    """Tests that asking about a specific item gets a direct answer.

    Bug pattern #7: "is the iced tea available?" was routed to the category
    browser instead of giving a direct answer about the specific item.
    """

    scenario_type = "regression"

    def __init__(
        self,
        item: dict[str, Any],
        seed: int | None = None,
    ) -> None:
        item_name = item.get("name", "Unknown")
        super().__init__(f"Regression: availability inquiry ({item_name})")
        self.item = item
        self.rng = random.Random(seed)

    def generate(self) -> None:
        item_name = self.item.get("name", "Unknown")

        phrases = [
            f"do you have {item_name}?",
            f"is the {item_name} available?",
            f"do you carry {item_name}?",
            f"can I get a {item_name}?",
        ]

        self.turns.append(ConversationTurn(
            user_input=self.rng.choice(phrases),
            is_menu_inquiry=True,
            allow_disambiguation=True,
        ))
