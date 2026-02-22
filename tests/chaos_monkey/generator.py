"""Scenario generation for Chaos Monkey tests."""

from __future__ import annotations

import logging
import random
from typing import Any

from tests.chaos_monkey.config import ChaosMonkeyConfig
from tests.chaos_monkey.mutator import TextMutator
from tests.chaos_monkey.scenarios.base import BaseScenario

logger = logging.getLogger(__name__)


class ScenarioGenerator:
    """Generates test scenarios from menu data."""

    def __init__(
        self,
        config: ChaosMonkeyConfig,
        menu_cache: Any,
        seed: int | None = None,
    ) -> None:
        """Initialize the generator.

        Args:
            config: Chaos Monkey configuration.
            menu_cache: The menu data cache instance.
            seed: Random seed for reproducibility.
        """
        self.config = config
        self.menu_cache = menu_cache
        self.rng = random.Random(seed)
        self.mutator = TextMutator(seed)

        # Cache menu data
        self._menu_items: list[dict[str, Any]] = []
        self._items_by_type: dict[str, list[dict[str, Any]]] = {}
        self._modifier_words: set[str] = set()
        self._loaded = False

    def load_menu_data(self) -> None:
        """Load menu data from the cache."""
        if self._loaded:
            return

        try:
            # Get all menu item names
            known_items = self.menu_cache.get_known_menu_items()
            logger.info("Loaded %d menu item names", len(known_items))

            # Get items by type
            item_types = self.menu_cache.get_all_item_type_slugs()
            for item_type in item_types:
                items = self.menu_cache.get_items_by_item_type(item_type)
                if items:
                    self._items_by_type[item_type] = items
                    self._menu_items.extend(items)

            logger.info(
                "Loaded %d menu items across %d types",
                len(self._menu_items),
                len(self._items_by_type),
            )

            # Get modifier words
            self._modifier_words = self.menu_cache.get_all_modifier_words()
            logger.info("Loaded %d modifier words", len(self._modifier_words))

            self._loaded = True

        except Exception as e:
            logger.error("Failed to load menu data: %s", e)
            raise

    def generate_batch(self, batch_size: int | None = None) -> list[BaseScenario]:
        """Generate a batch of test scenarios.

        Args:
            batch_size: Number of scenarios to generate. Uses config default if None.

        Returns:
            List of generated scenarios.
        """
        if not self._loaded:
            self.load_menu_data()

        batch_size = batch_size or self.config.batch_size
        scenarios: list[BaseScenario] = []

        for _ in range(batch_size):
            scenario = self._generate_weighted_scenario()
            if scenario:
                # Apply mutation if configured
                if self.rng.random() < self.config.mutation_probability:
                    self._apply_mutations(scenario)
                scenarios.append(scenario)

        return scenarios

    def _generate_weighted_scenario(self) -> BaseScenario | None:
        """Generate a scenario based on configured weights."""
        weights = self.config.scenario_weights
        scenario_types = list(weights.keys())
        type_weights = [weights[t] for t in scenario_types]

        # Weighted random selection
        chosen_type = self.rng.choices(scenario_types, weights=type_weights, k=1)[0]

        return self._generate_scenario_of_type(chosen_type)

    def _generate_scenario_of_type(self, scenario_type: str) -> BaseScenario | None:
        """Generate a scenario of a specific type."""
        if scenario_type == "single_item":
            return self._generate_single_item_scenario()
        elif scenario_type == "multi_item":
            return self._generate_multi_item_scenario()
        elif scenario_type == "modifier":
            return self._generate_modifier_scenario()
        elif scenario_type == "cart_ops":
            return self._generate_cart_ops_scenario()
        elif scenario_type == "modifier_flow":
            return self._generate_modifier_flow_scenario()
        elif scenario_type == "menu_inquiry":
            return self._generate_menu_inquiry_scenario()
        elif scenario_type == "tricky":
            return self._generate_tricky_scenario()
        elif scenario_type == "realistic_order":
            return self._generate_realistic_order_scenario()
        elif scenario_type == "corpus_order":
            return self._generate_corpus_order_scenario()
        else:
            logger.warning("Unknown scenario type: %s", scenario_type)
            return None

    def _generate_single_item_scenario(self) -> BaseScenario | None:
        """Generate a single item ordering scenario."""
        from tests.chaos_monkey.scenarios.single_item import SingleItemScenario

        if not self._menu_items:
            return None

        item = self.rng.choice(self._menu_items)
        item_name = item.get("name", "Unknown")
        item_type = item.get("item_type", "unknown")

        return SingleItemScenario(
            item_name=item_name,
            item_type=item_type,
            item_data=item,
            seed=self.rng.randint(0, 2**31),
        )

    def _generate_multi_item_scenario(self) -> BaseScenario | None:
        """Generate a multi-item ordering scenario."""
        from tests.chaos_monkey.scenarios.multi_item import MultiItemScenario

        if len(self._menu_items) < 2:
            return None

        # Pick 2 different items
        items = self.rng.sample(self._menu_items, min(2, len(self._menu_items)))

        return MultiItemScenario(
            items=items,
            seed=self.rng.randint(0, 2**31),
        )

    @staticmethod
    def _filter_display_names(modifiers: set[str] | list[str]) -> list[str]:
        """Filter modifier list to only display names, excluding slugs.

        The ingredient cache stores names, slugs, and aliases together.
        Slugs use underscores (e.g., 'vanilla_syrup') while display names
        and aliases use spaces or are single words (e.g., 'Vanilla Syrup', 'lox').
        """
        return [m for m in modifiers if "_" not in m]

    def _generate_modifier_scenario(self) -> BaseScenario | None:
        """Generate a modifier addition/removal scenario."""
        from tests.chaos_monkey.scenarios.modifier import ModifierScenario

        if not self._menu_items:
            return None

        # Filter to only configurable items
        configurable_items = [
            item for item in self._menu_items
            if self.menu_cache.is_item_type_configurable(item.get("item_type", ""))
        ]

        if not configurable_items:
            return None

        # Pick a configurable item
        item = self.rng.choice(configurable_items)
        item_type = item.get("item_type", "")

        # Get modifiers valid for this item type
        valid_ingredients = self.menu_cache.get_ingredients_by_category_for_item_type(
            item_type
        )

        # Flatten valid ingredient display names (exclude slugs with underscores)
        valid_modifiers: list[str] = []
        for category_ingredients in valid_ingredients.values():
            valid_modifiers.extend(self._filter_display_names(category_ingredients))

        if not valid_modifiers:
            return None

        modifier = self.rng.choice(valid_modifiers)

        return ModifierScenario(
            item=item,
            modifier=modifier,
            action=self.rng.choice(["add", "remove"]),
            seed=self.rng.randint(0, 2**31),
        )

    def _generate_cart_ops_scenario(self) -> BaseScenario | None:
        """Generate a cart operation scenario."""
        from tests.chaos_monkey.scenarios.cart_ops import CartOperationScenario

        if not self._menu_items:
            return None

        item = self.rng.choice(self._menu_items)
        operation = self.rng.choice(["change_quantity", "remove", "cancel"])

        return CartOperationScenario(
            item=item,
            operation=operation,
            quantity=self.rng.randint(1, 5) if operation == "change_quantity" else None,
            seed=self.rng.randint(0, 2**31),
        )

    def _generate_modifier_flow_scenario(self) -> BaseScenario | None:
        """Generate a modifier flow scenario (order then add/remove/change modifiers)."""
        from tests.chaos_monkey.scenarios.modifier_flow import ModifierFlowScenario

        if not self._menu_items:
            return None

        # Filter to only configurable items (those that accept modifiers)
        configurable_items = [
            item for item in self._menu_items
            if self.menu_cache.is_item_type_configurable(item.get("item_type", ""))
        ]

        if not configurable_items:
            return None

        # Pick 1 or 2 configurable items
        num_items = self.rng.choice([1, 2])
        items = self.rng.sample(
            configurable_items, min(num_items, len(configurable_items))
        )

        # Get modifiers that are valid for the first item's type
        first_item_type = items[0].get("item_type", "")
        valid_ingredients = self.menu_cache.get_ingredients_by_category_for_item_type(
            first_item_type
        )

        # Flatten valid ingredient display names (exclude slugs with underscores)
        valid_modifiers: list[str] = []
        for category_ingredients in valid_ingredients.values():
            valid_modifiers.extend(self._filter_display_names(category_ingredients))

        if not valid_modifiers:
            return None

        # Pick 3-5 modifiers from the valid list for this item type
        num_modifiers = min(5, len(valid_modifiers))
        modifiers = self.rng.sample(valid_modifiers, num_modifiers)

        return ModifierFlowScenario(
            items=items,
            modifiers=modifiers,
            seed=self.rng.randint(0, 2**31),
        )

    def _generate_menu_inquiry_scenario(self) -> BaseScenario | None:
        """Generate a menu inquiry scenario (ask about menu, categories, dietary options)."""
        from tests.chaos_monkey.scenarios.menu_inquiry import MenuInquiryScenario

        # Weighted random selection of inquiry type
        inquiry_types = ["general", "category", "dietary", "recommendation", "specific"]
        weights = [0.2, 0.35, 0.2, 0.15, 0.1]

        inquiry_type = self.rng.choices(inquiry_types, weights=weights, k=1)[0]

        if inquiry_type == "category":
            # Pick a category to ask about
            categories = [
                "bagels", "sandwiches", "coffee", "drinks", "spreads",
                "cream cheese", "breakfast", "salads", "soups", "sides",
                "omelettes", "pastries", "beverages",
            ]
            category = self.rng.choice(categories)
            return MenuInquiryScenario(
                inquiry_type="category",
                category=category,
                seed=self.rng.randint(0, 2**31),
            )
        elif inquiry_type == "specific" and self._menu_items:
            # Ask about a specific menu item
            item = self.rng.choice(self._menu_items)
            item_name = item.get("name", "Unknown")
            return MenuInquiryScenario(
                inquiry_type="specific",
                item_name=item_name,
                seed=self.rng.randint(0, 2**31),
            )
        else:
            return MenuInquiryScenario(
                inquiry_type=inquiry_type,
                seed=self.rng.randint(0, 2**31),
            )

    def _get_attribute_data_for_item_type(
        self, item_type_slug: str
    ) -> tuple[dict[str, list[str]], list[str]]:
        """Get attribute options and boolean attrs for an item type.

        Returns:
            Tuple of (attribute_options dict, boolean_attrs list).
            attribute_options maps attr_slug -> list of option display names.
            boolean_attrs is a list of boolean attribute slugs.
        """
        attribute_options: dict[str, list[str]] = {}
        boolean_attrs: list[str] = []

        try:
            attrs = self.menu_cache.get_item_type_attributes(item_type_slug)
            for attr_slug, attr_config in attrs.items():
                if not attr_config.get("ask_in_conversation", False):
                    continue

                input_type = attr_config.get("input_type", "")

                if input_type == "boolean":
                    boolean_attrs.append(attr_slug)
                elif input_type in ("single_select", "multi_select"):
                    options = self.menu_cache.get_global_attribute_options(attr_slug)
                    display_names = [
                        opt.get("display_name", opt.get("slug", ""))
                        for opt in options
                        if opt.get("display_name") or opt.get("slug")
                    ]
                    # Filter out long names (>3 words) to keep inputs natural
                    display_names = [n for n in display_names if len(n.split()) <= 3]
                    if display_names:
                        attribute_options[attr_slug] = display_names
        except Exception as e:
            logger.debug("Could not load attribute data for %s: %s", item_type_slug, e)

        return attribute_options, boolean_attrs

    def _generate_realistic_order_scenario(self) -> BaseScenario | None:
        """Generate a reactive realistic order scenario (1-2 items, answer config)."""
        from tests.chaos_monkey.scenarios.realistic_order import RealisticOrderScenario

        if not self._menu_items:
            return None

        # Pick 1-2 items (70% chance of 1 item, 30% chance of 2)
        num_items = 1 if self.rng.random() < 0.7 else 2
        items = self.rng.sample(
            self._menu_items, min(num_items, len(self._menu_items))
        )

        # Collect attribute options from all selected item types
        all_attribute_options: dict[str, list[str]] = {}
        all_boolean_attrs: list[str] = []

        seen_types: set[str] = set()
        for item in items:
            item_type = item.get("item_type", "")
            if item_type in seen_types:
                continue
            seen_types.add(item_type)

            attr_opts, bool_attrs = self._get_attribute_data_for_item_type(item_type)
            for slug, opts in attr_opts.items():
                if slug not in all_attribute_options:
                    all_attribute_options[slug] = []
                all_attribute_options[slug].extend(
                    o for o in opts if o not in all_attribute_options[slug]
                )
            all_boolean_attrs.extend(
                b for b in bool_attrs if b not in all_boolean_attrs
            )

        return RealisticOrderScenario(
            items=items,
            attribute_options=all_attribute_options,
            boolean_attrs=all_boolean_attrs,
            seed=self.rng.randint(0, 2**31),
        )

    def _generate_tricky_scenario(self) -> BaseScenario | None:
        """Generate a tricky scenario with out-of-place inputs (no filler words)."""
        from tests.chaos_monkey.scenarios.tricky import (
            MultiAttributeWithModifierScenario,
            TrickyScenario,
        )

        if not self._menu_items:
            return None

        # Filter to configurable items (those with config questions)
        configurable_items = [
            item for item in self._menu_items
            if self.menu_cache.is_item_type_configurable(item.get("item_type", ""))
        ]

        if not configurable_items:
            return None

        # Pick primary item
        primary_item = self.rng.choice(configurable_items)
        primary_type = primary_item.get("item_type", "")

        # Get attribute data for this item type
        attribute_options, boolean_attrs = self._get_attribute_data_for_item_type(
            primary_type
        )

        # Get valid modifiers for the primary item
        valid_ingredients = self.menu_cache.get_ingredients_by_category_for_item_type(
            primary_type
        )
        valid_modifiers: list[str] = []
        for category_ingredients in valid_ingredients.values():
            valid_modifiers.extend(self._filter_display_names(category_ingredients))

        # Pick secondary item (different from primary)
        other_items = [
            item for item in self._menu_items
            if item.get("name") != primary_item.get("name")
        ]
        secondary_item = self.rng.choice(other_items) if other_items else None

        # Choose trick type with weights
        trick_types = [
            "add_item_during_config",
            "multi_attribute",
            "context_switch",
            "early_answer",
            "change_config",
            "repeat_item",
        ]
        trick_weights = [0.20, 0.20, 0.15, 0.15, 0.15, 0.15]

        # Adjust weights based on available data
        if not boolean_attrs and not attribute_options:
            # No attribute data — skip multi_attribute, context_switch, change_config
            trick_weights[1] = 0.0  # multi_attribute
            trick_weights[2] = 0.0  # context_switch
            trick_weights[4] = 0.0  # change_config
        if not valid_modifiers:
            trick_weights[3] = 0.05  # early_answer less useful without modifiers

        # Normalize weights
        total = sum(trick_weights)
        if total == 0:
            return None
        trick_weights = [w / total for w in trick_weights]

        chosen_trick = self.rng.choices(trick_types, weights=trick_weights, k=1)[0]

        # 20% chance of the multi-attribute-with-modifier variant
        if (
            chosen_trick == "multi_attribute"
            and valid_modifiers
            and self.rng.random() < 0.5
        ):
            return MultiAttributeWithModifierScenario(
                primary_item=primary_item,
                secondary_item=secondary_item,
                attribute_options=attribute_options,
                boolean_attrs=boolean_attrs,
                modifiers=valid_modifiers,
                seed=self.rng.randint(0, 2**31),
            )

        return TrickyScenario(
            trick_type=chosen_trick,
            primary_item=primary_item,
            secondary_item=secondary_item,
            attribute_options=attribute_options,
            boolean_attrs=boolean_attrs,
            modifiers=valid_modifiers,
            seed=self.rng.randint(0, 2**31),
        )

    def _generate_corpus_order_scenario(self) -> BaseScenario | None:
        """Generate a scenario from the conversation pattern corpus."""
        from tests.chaos_monkey.scenarios.corpus import PATTERNS, SlotType
        from tests.chaos_monkey.scenarios.corpus_order import CorpusOrderScenario

        if not self._menu_items:
            return None

        # Try up to 10 patterns to find one whose slots we can fill
        candidates = self.rng.choices(
            PATTERNS,
            weights=[p.weight for p in PATTERNS],
            k=min(10, len(PATTERNS)),
        )

        for pattern in candidates:
            filled = self._fill_pattern_slots(pattern)
            if filled is None:
                continue

            # Collect attribute data for reactive answering from all items
            # referenced in the filled slots
            all_attr_options: dict[str, list[str]] = {}
            all_boolean_attrs: list[str] = []

            # Find item types from items we picked
            seen_types: set[str] = set()
            for slot_name, slot_def in pattern.slots.items():
                if slot_def.slot_type in (SlotType.ITEM, SlotType.CONFIGURABLE_ITEM):
                    # Look up item_type for the filled item name
                    item_name = filled.get(slot_name, "")
                    for mi in self._menu_items:
                        if mi.get("name") == item_name:
                            item_type = mi.get("item_type", "")
                            if item_type and item_type not in seen_types:
                                seen_types.add(item_type)
                                attr_opts, bool_attrs = (
                                    self._get_attribute_data_for_item_type(item_type)
                                )
                                for slug, opts in attr_opts.items():
                                    if slug not in all_attr_options:
                                        all_attr_options[slug] = []
                                    all_attr_options[slug].extend(
                                        o for o in opts
                                        if o not in all_attr_options[slug]
                                    )
                                all_boolean_attrs.extend(
                                    b for b in bool_attrs
                                    if b not in all_boolean_attrs
                                )
                            break

            # Build expected cart items from expected_item_slots
            expected_cart_items: list[str] = []
            for slot_name in pattern.expected_item_slots:
                if slot_name in filled:
                    expected_cart_items.append(filled[slot_name])

            return CorpusOrderScenario(
                pattern=pattern,
                filled_slots=filled,
                attribute_options=all_attr_options,
                boolean_attrs=all_boolean_attrs,
                expected_cart_items=expected_cart_items,
                seed=self.rng.randint(0, 2**31),
            )

        # All candidates failed slot filling
        logger.debug("Could not fill slots for any corpus pattern")
        return None

    def _fill_pattern_slots(
        self, pattern: "ConversationPattern"
    ) -> dict[str, str] | None:
        """Fill all slots in a pattern with menu data.

        Returns:
            Dict mapping slot names to filled values, or None if any slot
            can't be filled.
        """
        from tests.chaos_monkey.scenarios.corpus import SlotType

        filled: dict[str, str] = {}
        # Track which items we've picked so same_item_as constraints work
        item_type_for_slot: dict[str, str] = {}

        for slot_name, slot_def in pattern.slots.items():
            value = self._fill_single_slot(
                slot_def, filled, item_type_for_slot
            )
            if value is None:
                return None
            filled[slot_name] = value

            # Track item_type if this was an item slot
            if slot_def.slot_type in (SlotType.ITEM, SlotType.CONFIGURABLE_ITEM):
                for mi in self._menu_items:
                    if mi.get("name") == value:
                        item_type_for_slot[slot_name] = mi.get("item_type", "")
                        break

        return filled

    def _fill_single_slot(
        self,
        slot_def: "SlotDef",
        filled: dict[str, str],
        item_type_for_slot: dict[str, str],
    ) -> str | None:
        """Fill a single slot from menu data.

        Args:
            slot_def: The slot definition to fill.
            filled: Already-filled slots (for same_item_as constraints).
            item_type_for_slot: Maps slot names to their item_type slugs.

        Returns:
            Filled value string, or None if can't fill.
        """
        from tests.chaos_monkey.scenarios.corpus import SlotType

        st = slot_def.slot_type

        if st == SlotType.ITEM:
            if not self._menu_items:
                return None
            item = self.rng.choice(self._menu_items)
            return item.get("name")

        if st == SlotType.CONFIGURABLE_ITEM:
            configurable = [
                mi for mi in self._menu_items
                if self.menu_cache.is_item_type_configurable(
                    mi.get("item_type", "")
                )
            ]
            if not configurable:
                return None
            item = self.rng.choice(configurable)
            return item.get("name")

        if st == SlotType.BREAD_OPTION:
            options = self._get_options_for_attribute("bread")
            if options:
                return self.rng.choice(options)
            return self.rng.choice(["plain", "everything", "sesame"])

        if st == SlotType.SIZE_OPTION:
            options = self._get_options_for_attribute("size")
            if options:
                return self.rng.choice(options)
            return self.rng.choice(["large", "small"])

        if st == SlotType.MODIFIER:
            # If constrained to a specific item, use that item's valid modifiers
            if slot_def.same_item_as and slot_def.same_item_as in item_type_for_slot:
                item_type = item_type_for_slot[slot_def.same_item_as]
                valid_ingredients = (
                    self.menu_cache.get_ingredients_by_category_for_item_type(
                        item_type
                    )
                )
                valid_mods: list[str] = []
                for cat_ingredients in valid_ingredients.values():
                    valid_mods.extend(self._filter_display_names(cat_ingredients))
                if valid_mods:
                    return self.rng.choice(valid_mods)

            # Fallback: use any modifier word
            if self._modifier_words:
                display_mods = self._filter_display_names(self._modifier_words)
                if display_mods:
                    return self.rng.choice(display_mods)
            return None

        if st == SlotType.BOOLEAN_ATTR:
            return self.rng.choice(["toasted", "not toasted"])

        if st == SlotType.QUANTITY_WORD:
            return self.rng.choice(["two", "three", "2", "3"])

        if st == SlotType.CATEGORY_NAME:
            return self.rng.choice([
                "bagels", "sandwiches", "coffee", "drinks",
            ])

        return None

    def _get_options_for_attribute(self, attr_slug: str) -> list[str]:
        """Get display name options for a global attribute.

        Args:
            attr_slug: The attribute slug (e.g. "bread", "size").

        Returns:
            List of display name strings, possibly empty.
        """
        try:
            options = self.menu_cache.get_global_attribute_options(attr_slug)
            display_names = [
                opt.get("display_name", opt.get("slug", ""))
                for opt in options
                if opt.get("display_name") or opt.get("slug")
            ]
            # Filter out long names (>3 words) to keep inputs natural
            return [n for n in display_names if len(n.split()) <= 3]
        except Exception:
            return []

    def _apply_mutations(self, scenario: BaseScenario) -> None:
        """Apply text mutations to scenario turns."""
        is_voice = self.config.input_mode == "voice"
        gentle = self.config.gentle_mutations
        for turn in scenario.get_turns():
            if is_voice:
                # Voice mode: STT-specific mutations, 2 per turn
                result = self.mutator.mutate(
                    turn.user_input, mutation_count=2, stt=True,
                )
                if result.mutations_applied:
                    turn.stt_mutated = True
                    turn.original_input = result.original
            else:
                # Text mode: 1 gentle/aggressive mutation
                result = self.mutator.mutate(
                    turn.user_input, mutation_count=1, gentle=gentle,
                )
            turn.user_input = result.mutated

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about available menu data.

        Returns:
            Dict with menu data statistics.
        """
        return {
            "total_items": len(self._menu_items),
            "items_by_type": {k: len(v) for k, v in self._items_by_type.items()},
            "modifier_words": len(self._modifier_words),
            "loaded": self._loaded,
        }
