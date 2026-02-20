"""
Item Builder.

Provides a builder for constructing menu items with all their configuration,
selections, and attributes. Breaks down the complex item creation process
into clear, testable steps.

Extracted from item_adder_handler._create_configurable_item for better
separation of concerns and testability.
"""

import logging
import re
from typing import TYPE_CHECKING, Callable

from orderbot.cache import menu_cache
from orderbot.constants import MULTI_CONFIG_THRESHOLD

from ..models import MenuItemTask
from ..default_ingredients import (
    populate_default_ingredients,
    filter_redundant_default_selections,
)
from .item_context import ItemBuildContext

if TYPE_CHECKING:
    from ..pricing import PricingEngine
    from ..config import MenuItemConfigHandler

logger = logging.getLogger(__name__)

__all__ = ["ItemBuilder"]


class ItemBuilder:
    """
    Builder for constructing menu items.

    Provides a step-by-step process for creating and configuring menu items,
    breaking down the complex creation logic into manageable pieces.
    """

    def __init__(
        self,
        pricing: "PricingEngine | None",
        config_handler: "MenuItemConfigHandler | None" = None,
        infer_attributes_callback: Callable[["MenuItemTask"], None] | None = None,
        apply_pending_ingredient_callback: Callable | None = None,
    ):
        """Initialize the item builder.

        Args:
            pricing: PricingEngine for price calculations.
            config_handler: MenuItemConfigHandler for applying selections.
            infer_attributes_callback: Callback to infer attributes from item name.
            apply_pending_ingredient_callback: Callback to apply pending ingredient.
        """
        self._pricing = pricing
        self._config_handler = config_handler
        self._infer_attributes = infer_attributes_callback
        self._apply_pending_ingredient = apply_pending_ingredient_callback

    def prepare_context(self, ctx: ItemBuildContext) -> None:
        """Prepare the build context by determining configuration requirements.

        Args:
            ctx: The build context to prepare.
        """
        # Check if this item type is configurable
        configurable_types = menu_cache.get_configurable_item_types()
        ctx.is_configurable = ctx.item_type in configurable_types if ctx.item_type else False

        # If skip_config is set (from DB), don't configure
        ctx.needs_configuration = ctx.is_configurable and not ctx.skip_config

        logger.info(
            "Creating item: name='%s', type='%s', price=$%.2f, qty=%d, configurable=%s, skip_config=%s, needs_config=%s",
            ctx.canonical_name, ctx.item_type, ctx.price, ctx.quantity,
            ctx.is_configurable, ctx.skip_config, ctx.needs_configuration
        )

    def calculate_item_count(
        self,
        ctx: ItemBuildContext,
        check_config_complete: Callable[[str | None, dict | None], bool] | None = None,
    ) -> tuple[int, int]:
        """Calculate how many items to create and with what quantity.

        Quantity threshold logic:
        - Non-configurable items: single item with quantity=N
        - Configurable items with qty > threshold: single item with quantity=N
        - Configurable items with all mandatory attrs filled: single item with quantity=N
        - Otherwise: N separate items (configure each individually)

        Args:
            ctx: The build context.
            check_config_complete: Callback to check if config is already complete.

        Returns:
            Tuple of (item_count, item_quantity)
        """
        config_already_complete = False
        if check_config_complete:
            config_already_complete = check_config_complete(
                ctx.item_type, ctx.pre_filled_attributes
            )

        if not ctx.needs_configuration or ctx.quantity > MULTI_CONFIG_THRESHOLD or config_already_complete:
            # Create single item with quantity=N
            return 1, ctx.quantity
        else:
            # Create N separate items (configure each individually)
            return ctx.quantity, 1

    def create_item(
        self,
        ctx: ItemBuildContext,
        item_quantity: int,
    ) -> MenuItemTask:
        """Create a single menu item task.

        Args:
            ctx: The build context.
            item_quantity: Quantity for this item.

        Returns:
            The created MenuItemTask.
        """
        return MenuItemTask(
            menu_item_name=ctx.canonical_name,
            menu_item_id=ctx.menu_item_id,
            unit_price=ctx.price,
            menu_item_type=ctx.item_type,
            quantity=item_quantity,
        )

    def populate_defaults(
        self,
        item: MenuItemTask,
        ctx: ItemBuildContext,
        exclude_slugs: set[str] | None = None,
    ) -> None:
        """Populate default ingredients for the item.

        This must happen before applying user selections so user selections
        can replace defaults (e.g., "BEC with swiss" replaces cheddar).

        Args:
            item: The menu item to populate.
            ctx: The build context.
            exclude_slugs: Optional set of ingredient slugs to skip.
        """
        if ctx.menu_item_id:
            populate_default_ingredients(item, exclude_slugs=exclude_slugs)

    def apply_variant_defaults(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Auto-populate variant selection for items with weight-based pricing.

        Only auto-populate for "weight" category (spreads, fish), NOT for:
        - "size" (coffee drinks - user should choose small/medium/large)
        - "quantity" (bagel packages - user should choose 6/dozen)

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.size_category_slug == "weight" and self._pricing:
            default_variant = self._pricing.get_default_variant_for_item(ctx.canonical_name)
            if default_variant:
                item.add_selection(
                    slug=default_variant["slug"],
                    category=ctx.size_category_slug,
                    display_name=default_variant["display_name"],
                    is_default=True,
                )

    def apply_pre_filled_attributes(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Apply pre-filled attributes to the item.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.pre_filled_attributes:
            for attr_name, attr_value in ctx.pre_filled_attributes.items():
                item[attr_name] = attr_value

    def apply_extracted_selections(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Apply extracted selections to the item.

        These replace/add to defaults, filtering out redundant selections.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.extracted_selections and self._config_handler:
            filtered_selections = filter_redundant_default_selections(
                item, ctx.extracted_selections
            )
            self._config_handler._apply_selections(item, filtered_selections)

    def apply_pending_ingredient(
        self,
        item: MenuItemTask,
        ctx: ItemBuildContext,
        is_first_item: bool,
    ) -> None:
        """Apply pending ingredient from ingredient suggestion flow.

        Only apply to the first item.

        Args:
            item: The menu item to configure.
            ctx: The build context.
            is_first_item: Whether this is the first item being created.
        """
        if is_first_item and self._apply_pending_ingredient:
            self._apply_pending_ingredient(
                item, ctx.order, ctx.item_type, ctx.canonical_name
            )

    def set_unavailable_selections(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Set unavailable selections for messaging.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.unavailable_selections:
            item.unavailable_selections = ctx.unavailable_selections.copy()

    def set_unmatched_selections(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Set unmatched selections for messaging.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.unmatched_selections:
            item.unmatched_selections = ctx.unmatched_selections.copy()

    def set_ambiguous_selections(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Set ambiguous selections for disambiguation.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.ambiguous_selections:
            item.ambiguous_selections = list(ctx.ambiguous_selections)

    def set_special_instructions(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Set special instructions for the item.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.special_instructions:
            item.special_instructions = list(ctx.special_instructions)

    def set_unrecognized_ingredients(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Set unrecognized ingredient suggestions for the item.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.unrecognized_ingredients:
            item.unrecognized_ingredients = list(ctx.unrecognized_ingredients)

    def clean_item_name(self, item: MenuItemTask) -> None:
        """Strip 'with {unrecognized_ingredient}' from item name.

        Prevents infer_attributes from re-inferring removed ingredients
        from the item name (e.g., "The Pizza BEC with Pepperoni" -> "The Pizza BEC").

        Args:
            item: The menu item whose name to clean.
        """
        if not item.unrecognized_ingredients:
            return
        name = item.menu_item_name
        for entry in item.unrecognized_ingredients:
            token = entry.get("token", "")
            display = entry.get("display_name", "")
            for term in (token, display):
                if not term:
                    continue
                # Strip "with <term>" (case-insensitive)
                pattern = rf'\s+with\s+{re.escape(term)}'
                name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        cleaned = name.strip()
        if cleaned != item.menu_item_name:
            logger.info(
                "Cleaned item name: '%s' -> '%s'",
                item.menu_item_name, cleaned,
            )
            item.menu_item_name = cleaned

    def set_inapplicable_attributes(self, item: MenuItemTask, ctx: ItemBuildContext) -> None:
        """Set inapplicable attribute words for the item.

        Args:
            item: The menu item to configure.
            ctx: The build context.
        """
        if ctx.inapplicable_attributes:
            item.inapplicable_attributes = list(ctx.inapplicable_attributes)

    def infer_attributes(self, item: MenuItemTask) -> None:
        """Infer attributes from item name.

        Data-driven inference (e.g., "Hot Coffee" -> temperature=hot)
        prevents asking questions already answered by the item name.

        Args:
            item: The menu item to configure.
        """
        if self._infer_attributes:
            self._infer_attributes(item)

    def recalculate_price(self, item: MenuItemTask) -> bool:
        """Recalculate the item price with modifiers.

        Args:
            item: The menu item to price.

        Returns:
            True if successful, False if pricing failed.
        """
        if self._pricing:
            try:
                self._pricing.recalculate_item_price(item)
                return True
            except ValueError as e:
                logger.warning(
                    "Price lookup failed for '%s': %s",
                    item.menu_item_name, str(e)
                )
                return False
        return True

    def set_status(self, item: MenuItemTask, needs_configuration: bool) -> None:
        """Set the item status based on configuration requirements.

        Args:
            item: The menu item to update.
            needs_configuration: Whether the item needs configuration.
        """
        if needs_configuration:
            item.mark_in_progress()
        else:
            item.mark_complete()

    @staticmethod
    def _get_unrecognized_slugs(item: MenuItemTask) -> set[str] | None:
        """Build a set of slugs from unrecognized ingredients for exclusion.

        Args:
            item: The menu item with unrecognized ingredients set.

        Returns:
            Set of lowercase token strings, or None if no unrecognized ingredients.
        """
        if not item.unrecognized_ingredients:
            return None
        slugs = set()
        for entry in item.unrecognized_ingredients:
            token = entry.get("token", "")
            if token:
                slugs.add(token.lower())
            display = entry.get("display_name", "")
            if display:
                slugs.add(display.lower())
        return slugs or None

    def build_single_item(
        self,
        ctx: ItemBuildContext,
        item_quantity: int,
        is_first_item: bool,
    ) -> MenuItemTask:
        """Build a single menu item with all steps applied.

        Args:
            ctx: The build context.
            item_quantity: Quantity for this item.
            is_first_item: Whether this is the first item being created.

        Returns:
            The fully configured MenuItemTask.
        """
        # Step 1: Create the item
        item = self.create_item(ctx, item_quantity)

        # Step 2: Set unrecognized ingredients (before defaults so we can exclude them)
        self.set_unrecognized_ingredients(item, ctx)

        # Step 3: Clean item name (strip "with {unrecognized}" to prevent re-inference)
        self.clean_item_name(item)

        # Step 4: Populate defaults (skip unrecognized ingredients)
        exclude_slugs = self._get_unrecognized_slugs(item)
        self.populate_defaults(item, ctx, exclude_slugs=exclude_slugs)

        # Step 5: Apply variant defaults (weight-based pricing)
        self.apply_variant_defaults(item, ctx)

        # Step 6: Apply pre-filled attributes
        self.apply_pre_filled_attributes(item, ctx)

        # Step 7: Apply extracted selections
        self.apply_extracted_selections(item, ctx)

        # Step 8: Apply pending ingredient (first item only)
        self.apply_pending_ingredient(item, ctx, is_first_item)

        # Step 9: Set unavailable selections
        self.set_unavailable_selections(item, ctx)

        # Step 10: Set unmatched selections
        self.set_unmatched_selections(item, ctx)

        # Step 11: Set ambiguous selections
        self.set_ambiguous_selections(item, ctx)

        # Step 12: Set special instructions
        self.set_special_instructions(item, ctx)

        # Step 13: Set inapplicable attributes
        self.set_inapplicable_attributes(item, ctx)

        # Step 14: Infer attributes from item name
        self.infer_attributes(item)

        # Step 15: Recalculate price
        self.recalculate_price(item)

        # Step 16: Set status
        self.set_status(item, ctx.needs_configuration)

        return item
