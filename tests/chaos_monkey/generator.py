"""Scenario generation for Chaos Monkey tests."""

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

    def _generate_modifier_scenario(self) -> BaseScenario | None:
        """Generate a modifier addition/removal scenario."""
        from tests.chaos_monkey.scenarios.modifier import ModifierScenario

        if not self._menu_items or not self._modifier_words:
            return None

        # Pick an item and a modifier
        item = self.rng.choice(self._menu_items)
        modifier = self.rng.choice(list(self._modifier_words))

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

    def _apply_mutations(self, scenario: BaseScenario) -> None:
        """Apply text mutations to scenario turns."""
        for turn in scenario.get_turns():
            mutation_count = self.rng.randint(1, 3)
            result = self.mutator.mutate(turn.user_input, mutation_count)
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
