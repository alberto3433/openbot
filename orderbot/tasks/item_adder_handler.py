"""
Item Adder Handler for Order State Machine.

This module handles adding new items to orders, including menu items,
side items, and bagels with their configurations.

Extracted from state_machine.py for better separation of concerns.
Delegates to ItemCreationHandler and MenuItemAdder for specific flows.
"""

import logging
from typing import TYPE_CHECKING

from .models import (
    OrderTask,
    MenuItemTask,
    TaskStatus,
)
from .pending_fields import PendingField
from .schemas import OrderPhase, StateMachineResult, Selection
from .handler_config import HandlerConfig
from .disambiguation_handler import DisambiguationHandler
from .item_lookup_handler import ItemLookupHandler
from .mixins import MenuDataMixin
from .checkout_messages import got_it_anything_else
from .attribute_inference import (
    infer_attributes_from_item_name,
    extract_pre_filled_attributes,
)
from .unrecognized_item_handler import UnrecognizedItemHandler
from .order_item_builder import OrderItemBuilder
from orderbot.cache import menu_cache
from orderbot.cache.base import singularize
from orderbot.constants import MULTI_CONFIG_THRESHOLD
from .config_side_choice_handler import SIDE_SLOT_NAME
from .default_ingredients import (
    populate_default_ingredients,
    filter_redundant_default_selections,
)
from .builders import ItemBuilder, ItemBuildContext
from .utils.text import normalize_text
from .item_creation_handler import ItemCreationHandler
from .menu_item_adder import MenuItemAdder

if TYPE_CHECKING:
    from .context import OrderContext

logger = logging.getLogger(__name__)


class ItemAdderHandler(MenuDataMixin):
    """
    Handles adding items to orders.

    Manages menu item lookup, price calculation, and item creation
    for menu items, side items, and bagels.

    Delegates to:
    - ItemCreationHandler: configurable item creation pipeline
    - MenuItemAdder: menu-item-name-based addition flow
    """

    def __init__(
        self,
        config: HandlerConfig,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
        item_lookup_handler: ItemLookupHandler | None = None,
        db_session=None,
    ):
        """
        Initialize the item adder handler.

        Args:
            config: HandlerConfig with shared dependencies.
            menu_item_handler: Unified handler for all item configuration.
            item_lookup_handler: Handler for menu item lookup with disambiguation.
            db_session: Optional SQLAlchemy session for database operations.
        """
        self.menu_lookup = config.menu_lookup
        self.pricing = config.pricing
        self._get_next_question = config.get_next_question
        self._db_session = db_session

        # Unified configuration handler for all item types
        self.menu_item_handler = menu_item_handler
        self._menu_data: dict = {}

        # Generic disambiguation handler
        self.disambiguation_handler = DisambiguationHandler()

        # Item lookup handler (with disambiguation)
        self.item_lookup_handler = item_lookup_handler or ItemLookupHandler(
            menu_lookup=self.menu_lookup,
            disambiguation_handler=self.disambiguation_handler,
        )

        # Order item builder for creating menu item dicts
        self._item_builder = OrderItemBuilder(
            menu_lookup_func=self.menu_lookup.lookup_menu_item if self.menu_lookup else None,
            pricing=self.pricing,
        )

        # Unrecognized item handler with fallback chain
        self._unrecognized_handler = UnrecognizedItemHandler(
            menu_lookup=self.menu_lookup,
            db_session=db_session,
        )

        # Sub-handlers for delegated flows
        self._creation_handler = ItemCreationHandler(parent=self)
        self._menu_item_adder = MenuItemAdder(parent=self)

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context including db_session.

        Args:
            ctx: OrderContext with db_session and other request-scoped data.
        """
        logger.debug(
            "ItemAdderHandler.set_context: ctx.db_session=%s",
            "set" if ctx.db_session else "None"
        )
        if ctx.db_session is not None:
            self._db_session = ctx.db_session
            # Update the unrecognized handler's db_session
            if self._unrecognized_handler:
                self._unrecognized_handler._db_session = ctx.db_session
                logger.debug("Updated _unrecognized_handler._db_session")

    def _infer_attributes_from_item_name(self, item: MenuItemTask) -> None:
        """Infer attribute values from the menu item name.

        Delegates to attribute_inference.infer_attributes_from_item_name().
        See that function for full documentation.
        """
        infer_attributes_from_item_name(item)

    def add_item(
        self,
        item_type: str,
        order: OrderTask,
        quantity: int = 1,
        skip_first_question: bool = False,
        **kwargs,
    ) -> StateMachineResult:
        """
        Unified item adder using data-driven configuration.

        All item types flow through _create_configurable_item() which handles
        DB-driven configuration. Items that need disambiguation (matching multiple
        menu items) use _lookup_menu_item_with_disambiguation().

        Args:
            item_type: The item type slug (e.g., "bagel", "sized_beverage", "deli_sandwich")
            order: The current order
            skip_first_question: If True, don't ask the first config question immediately.
                Used when adding multiple items - questions are asked after all items are added.
            quantity: Number of items to add (default 1)
            **kwargs: Item-specific parameters:
                - item_name: Menu item name (e.g., "Iced Latte", "Turkey Club")
                - Any attribute values to pre-fill (bread, toasted, size, milk, etc.)
                - modifications, bagel_choice (for menu items with bagel choice)
                - extracted_selections (list of Selection objects for any item)

        Returns:
            StateMachineResult with next question or confirmation
        """
        quantity = max(1, quantity)

        # Get item name from kwargs - use standardized "item_name" parameter
        item_name = kwargs.get("item_name") or item_type

        # Step 1: Check if disambiguation is needed
        needs_disambiguation, disambiguation_state = self._check_needs_disambiguation(
            item_type, item_name, quantity, kwargs,
        )

        # Step 2: If disambiguation needed, resolve it (may update item_name/item_type or return early)
        if needs_disambiguation:
            early_result = self._resolve_disambiguation(
                disambiguation_state, item_name, item_type, order, kwargs,
            )
            if early_result is not None:
                return early_result
            # Disambiguation resolved to a specific item - pull updated values
            item_name = disambiguation_state.get("resolved_item_name", item_name)
            item_type = disambiguation_state.get("resolved_item_type", item_type)

        # Step 3: Build and dispatch to _create_configurable_item
        return self._dispatch_item_creation(
            item_type, item_name, order, quantity, skip_first_question, kwargs,
        )

    def _check_needs_disambiguation(
        self,
        item_type: str,
        item_name: str,
        quantity: int,
        kwargs: dict,
    ) -> tuple[bool, dict]:
        """Determine if disambiguation is needed and prepare disambiguation state.

        Returns:
            Tuple of (needs_disambiguation, state_dict). The state_dict contains:
                - item_name_lower: Lowered/stripped item name
                - category_ref: Category slug if item is a category reference, else None
                - is_category_reference: Whether item_name is a category reference
                - is_empty_name: Whether item_name is empty
                - has_multiple_word_matches: Whether multiple items match by word boundary
                - item_modifiers: Serialized kwargs for preservation during disambiguation
                - filter_type: Item type filter for disambiguation lookup
        """
        item_name_lower = normalize_text(item_name)
        category_ref = menu_cache.is_category_reference(item_name_lower) if item_name_lower else None
        is_category_reference = category_ref is not None
        is_empty_name = not item_name_lower

        # Skip word-match disambiguation for configurable item types requested generically
        # e.g., "plain bagel" has item_type="bagel" and item_name="bagel" (or item_name=None)
        # User wants a configurable bagel, not disambiguation among "6 Bagel Package", "Pizza Bagel", etc.
        # EXCEPTION: If the item type has NO generic item (only signature items like omelettes),
        # we should show disambiguation to let user pick which specific item they want.
        configurable_types = menu_cache.get_configurable_item_types()
        is_configurable_generic_request = (
            item_type in configurable_types and
            (item_name_lower == item_type.lower() or is_empty_name)
        )

        # Override: If item type has component slots (like omelette with side choice),
        # it's a signature-item-only type that requires user to pick a specific item.
        # Trigger disambiguation instead of treating as a generic configurable request.
        needs_item_selection = False
        if is_configurable_generic_request and item_type:
            has_component_slots = menu_cache.item_type_has_component_slots(item_type)
            if has_component_slots:
                items_of_type = menu_cache.get_items_by_item_type(item_type)
                if len(items_of_type) > 1:
                    # Item type with component slots (e.g., omelette) - need disambiguation
                    is_configurable_generic_request = False

        # Override: If caller didn't specify an item name and type has multiple items,
        # the user provided only attributes (e.g., "large iced") — need disambiguation
        # to ask which specific item they want
        if is_configurable_generic_request and not kwargs.get("item_name"):
            items_of_type = menu_cache.get_items_by_item_type(item_type)
            if len(items_of_type) > 1:
                is_configurable_generic_request = False
                needs_item_selection = True

        # Check for multiple word-boundary matches (e.g., "tea" matches Hot Tea, Iced Tea, etc.)
        # This triggers disambiguation even when the term isn't a registered category reference
        # Skip this check for configurable item types requested generically
        has_multiple_word_matches = False
        if not is_configurable_generic_request:
            word_matches = menu_cache.find_items_by_word_match(item_name_lower) if item_name_lower else []
            has_multiple_word_matches = len(word_matches) > 1

        # Generic modifier storage for disambiguation (stores ALL non-None kwargs)
        # This preserves modifiers like size, milk, sweetener during disambiguation
        item_modifiers = {k: v for k, v in kwargs.items() if v is not None}
        item_modifiers["quantity"] = quantity

        # Convert Selection objects to dicts for JSON serialization
        # (extracted_selections may contain Pydantic Selection objects)
        if "extracted_selections" in item_modifiers:
            selections = item_modifiers["extracted_selections"]
            if selections and hasattr(selections[0], "model_dump"):
                item_modifiers["extracted_selections"] = [s.model_dump() for s in selections]

        # Determine filter_type for disambiguation lookup
        if is_category_reference:
            filter_type = category_ref
        elif has_multiple_word_matches:
            filter_type = None  # Don't filter - show all word matches
        else:
            filter_type = item_type

        needs_disambiguation = (
            (is_category_reference or is_empty_name or has_multiple_word_matches
             or needs_item_selection)
            and not is_configurable_generic_request
        )

        state = {
            "item_name_lower": item_name_lower,
            "category_ref": category_ref,
            "is_category_reference": is_category_reference,
            "is_empty_name": is_empty_name,
            "has_multiple_word_matches": has_multiple_word_matches,
            "item_modifiers": item_modifiers,
            "filter_type": filter_type,
        }

        return needs_disambiguation, state

    def _resolve_disambiguation(
        self,
        state: dict,
        item_name: str,
        item_type: str,
        order: OrderTask,
        kwargs: dict,
    ) -> StateMachineResult | None:
        """Execute disambiguation lookup and handle the result.

        On success, updates state["resolved_item_name"] and state["resolved_item_type"]
        with the resolved values and returns None so the caller can continue.

        Returns:
            StateMachineResult if disambiguation requires user interaction or item is unknown,
            None if disambiguation resolved to a specific item (caller should continue).
        """
        item_name_lower = state["item_name_lower"]
        item_modifiers = state["item_modifiers"]
        filter_type = state["filter_type"]
        is_category_reference = state["is_category_reference"]
        quantity = item_modifiers.get("quantity", 1)

        menu_item, disambiguation_result = self.item_lookup_handler.lookup_menu_item_with_disambiguation(
            item_name=item_name_lower or "item",
            quantity=quantity,
            order=order,
            modifiers=item_modifiers,
            pending_field=PendingField.ITEM_SELECTION,
            item_type_filter=filter_type,
        )

        if disambiguation_result:
            return disambiguation_result

        if menu_item:
            canonical_name = menu_item.get("name", item_name)
            state["resolved_item_name"] = canonical_name
            state["resolved_item_type"] = menu_item.get("item_type") or item_type
            kwargs["item_name"] = canonical_name
            return None
        elif item_name_lower and not is_category_reference:
            # Unknown item - mark for error handling
            order.pending_field = PendingField.ITEM_SELECTION
            order.unknown_item_request = item_name
            order.set_phase(OrderPhase.CONFIGURING_ITEM)
            return StateMachineResult(message="", order=order)

        return None

    def _dispatch_item_creation(
        self,
        item_type: str,
        item_name: str,
        order: OrderTask,
        quantity: int,
        skip_first_question: bool,
        kwargs: dict,
    ) -> StateMachineResult:
        """Build the menu item dict and dispatch to _create_configurable_item."""
        # Build menu_item dict (unified lookup for all item types)
        menu_item = self._build_menu_item_dict(item_type, item_name, kwargs)

        # Build pre_filled_attributes from kwargs (data-driven, queries DB for item type attributes)
        pre_filled_attributes = self._extract_pre_filled_attributes(item_type, kwargs)

        # Get extracted_selections from kwargs if provided
        extracted_selections = kwargs.get("extracted_selections")

        # Get unavailable_selections from kwargs (for "We don't have X" messaging)
        unavailable_selections = kwargs.get("unavailable_selections")

        # Get unmatched_selections from kwargs (for unrecognized tokens messaging)
        unmatched_selections = kwargs.get("unmatched_selections")

        # Get ambiguous_selections from kwargs (for "Which syrup?" disambiguation)
        ambiguous_selections = kwargs.get("ambiguous_selections")

        # Get special_instructions from kwargs (e.g., "room for cream", "extra hot")
        special_instructions = kwargs.get("special_instructions")

        # Get inapplicable_attributes from kwargs (for "only comes in one size" messaging)
        inapplicable_attributes = kwargs.get("inapplicable_attributes")

        logger.info(
            "ADD ITEM: type=%s, name=%s, qty=%d, pre_filled=%s",
            item_type, item_name, quantity,
            {k: v for k, v in pre_filled_attributes.items() if v is not None}
        )

        # Create item through generic flow (delegated to ItemCreationHandler)
        return self._creation_handler._create_configurable_item(
            menu_item=menu_item,
            order=order,
            quantity=quantity,
            user_input=kwargs.get("original_input"),
            pre_filled_attributes=pre_filled_attributes if pre_filled_attributes else None,
            extracted_selections=extracted_selections,
            unavailable_selections=unavailable_selections,
            unmatched_selections=unmatched_selections,
            ambiguous_selections=ambiguous_selections,
            special_instructions=special_instructions,
            inapplicable_attributes=inapplicable_attributes,
            skip_first_question=skip_first_question,
        )

    def _build_menu_item_dict(
        self,
        item_type: str,
        item_name: str,
        kwargs: dict,
    ) -> dict:
        """Build menu_item dict for _create_configurable_item().

        Delegates to OrderItemBuilder.

        Args:
            item_type: The item type slug
            item_name: The item name (e.g., "Bagel", "Latte", "Turkey Club")
            kwargs: Original kwargs with item details

        Returns:
            Dict with name, item_type, base_price, id, skip_config
        """
        return self._item_builder.build_menu_item_dict(item_type, item_name, kwargs)

    def _extract_pre_filled_attributes(self, item_type: str, kwargs: dict) -> dict:
        """Extract pre-filled attributes from kwargs based on item type.

        Delegates to attribute_inference.extract_pre_filled_attributes().
        """
        return extract_pre_filled_attributes(item_type, kwargs)

    # =========================================================================
    # Delegation to MenuItemAdder
    # =========================================================================

    def add_menu_item(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        attributes: dict | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Add a menu item and determine next question.

        Delegates to MenuItemAdder.add_menu_item().
        """
        return self._menu_item_adder.add_menu_item(
            item_name=item_name,
            quantity=quantity,
            order=order,
            attributes=attributes,
            modifications=modifications,
        )

    def add_side_item(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> tuple[str | None, str | None]:
        """Add a side item to the order without returning a response.

        Delegates to MenuItemAdder.add_side_item().
        """
        return self._menu_item_adder.add_side_item(
            side_item_name=side_item_name,
            quantity=quantity,
            order=order,
        )

    def _apply_pending_ingredient(
        self,
        item: MenuItemTask,
        order: OrderTask,
        item_type: str | None,
        canonical_name: str,
    ) -> None:
        """Apply pending ingredient from ingredient suggestion flow.

        Delegates to MenuItemAdder._apply_pending_ingredient().
        """
        self._menu_item_adder._apply_pending_ingredient(
            item=item,
            order=order,
            item_type=item_type,
            canonical_name=canonical_name,
        )

    # =========================================================================
    # Delegation to ItemCreationHandler
    # =========================================================================

    def _check_config_complete(
        self,
        item_type: str | None,
        pre_filled_attributes: dict | None,
    ) -> bool:
        """Check if all mandatory attributes for item_type are already filled.

        Delegates to ItemCreationHandler._check_config_complete().
        """
        return self._creation_handler._check_config_complete(
            item_type=item_type,
            pre_filled_attributes=pre_filled_attributes,
        )

    def _create_configurable_item(
        self,
        menu_item: dict,
        order: OrderTask,
        quantity: int = 1,
        user_input: str | None = None,
        pre_filled_attributes: dict | None = None,
        extracted_selections: list[Selection] | None = None,
        unavailable_selections: dict | None = None,
        unmatched_selections: dict | None = None,
        ambiguous_selections: list[dict] | None = None,
        special_instructions: list[str] | None = None,
        inapplicable_attributes: list[dict] | None = None,
        skip_first_question: bool = False,
    ) -> StateMachineResult:
        """Create an item and start its configuration flow if needed.

        Delegates to ItemCreationHandler._create_configurable_item().
        """
        return self._creation_handler._create_configurable_item(
            menu_item=menu_item,
            order=order,
            quantity=quantity,
            user_input=user_input,
            pre_filled_attributes=pre_filled_attributes,
            extracted_selections=extracted_selections,
            unavailable_selections=unavailable_selections,
            unmatched_selections=unmatched_selections,
            ambiguous_selections=ambiguous_selections,
            special_instructions=special_instructions,
            inapplicable_attributes=inapplicable_attributes,
            skip_first_question=skip_first_question,
        )

    def _build_items_for_order(
        self,
        ctx: ItemBuildContext,
        builder: ItemBuilder,
    ) -> MenuItemTask | None:
        """Build menu items and add them to the order.

        Delegates to ItemCreationHandler._build_items_for_order().
        """
        return self._creation_handler._build_items_for_order(ctx=ctx, builder=builder)

    def _start_configuration_flow(
        self,
        ctx: ItemBuildContext,
        first_item: MenuItemTask,
    ) -> StateMachineResult:
        """Start the configuration flow for a configurable item.

        Delegates to ItemCreationHandler._start_configuration_flow().
        """
        return self._creation_handler._start_configuration_flow(ctx=ctx, first_item=first_item)

    def _complete_non_configurable_item(
        self,
        ctx: ItemBuildContext,
        first_item: MenuItemTask,
    ) -> StateMachineResult:
        """Complete a non-configurable item and return confirmation.

        Delegates to ItemCreationHandler._complete_non_configurable_item().
        """
        return self._creation_handler._complete_non_configurable_item(ctx=ctx, first_item=first_item)

    def _create_menu_item_from_lookup(
        self,
        menu_item: dict,
        item_name: str,
        quantity: int,
        order: OrderTask,
        attributes: dict | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Create a menu item from lookup result.

        Delegates to MenuItemAdder._create_menu_item_from_lookup().
        """
        return self._menu_item_adder._create_menu_item_from_lookup(
            menu_item=menu_item,
            item_name=item_name,
            quantity=quantity,
            order=order,
            attributes=attributes,
            modifications=modifications,
        )

    # =========================================================================
    # Backward Compatibility
    # =========================================================================

    def _lookup_menu_item_with_disambiguation(
        self,
        item_name: str,
        quantity: int,
        order: OrderTask,
        modifiers: dict | None = None,
        pending_field: str = PendingField.ITEM_SELECTION,
        item_type_filter: str | None = None,
    ) -> tuple[dict | None, StateMachineResult | None]:
        """Delegate to item_lookup_handler for menu item lookup with disambiguation.

        This method is kept for backward compatibility.
        """
        return self.item_lookup_handler.lookup_menu_item_with_disambiguation(
            item_name=item_name,
            quantity=quantity,
            order=order,
            modifiers=modifiers,
            pending_field=pending_field,
            item_type_filter=item_type_filter,
        )
