"""
Item task models for the hierarchical task system.
"""

import logging
from typing import Literal
import uuid

from pydantic import Field, PrivateAttr

from orderbot.cache import menu_cache

from .base import BaseTask
from .menuitem_selection import SelectionManagementMixin
from .menuitem_dict_access import DictAccessMixin
from .menuitem_display import DisplayFormattingMixin

logger = logging.getLogger(__name__)


class ItemTask(BaseTask):
    """Base class for order items."""

    item_type: str
    quantity: int = 1
    unit_price: float = 0.0

    def get_display_name(self) -> str:
        """Get display name for this item."""
        raise NotImplementedError

    def get_summary(self) -> str:
        """Get a summary description of this item."""
        raise NotImplementedError


class MenuItemTask(SelectionManagementMixin, DictAccessMixin, DisplayFormattingMixin, ItemTask):
    """Task for a menu item ordered by name (e.g., 'The Chipotle Egg Omelette').

    All customizations (attribute choices and add-ons) are stored in a unified
    `selections` list using the standard selection format.

    Access methods:
    - get_selection(category): Get first selection for a category
    - get_selections(category): Get all selections for a category
    - get_selection_value(category): Get slug of first selection
    - has_selection(category): Check if any selection exists
    - add_selection(...): Add a new selection
    - remove_selection(...): Remove selection(s)
    - duplicate(): Create a deep copy with a new UUID

    Examples:
        item.add_selection("everything", "bread", display_name="Everything")
        item.add_selection("yes", "toasted", display_name="Toasted")
        item.add_selection("bacon", "protein", quantity=2)  # price calculated later

        bread = item.get_selection_value("bread")  # "everything"
        is_toasted = item.get_selection_value("toasted") == "yes"

        # Duplicate an item
        new_item = item.duplicate()
    """

    item_type: Literal["menu_item"] = "menu_item"

    # Menu item fields
    menu_item_name: str  # The name of the menu item
    menu_item_id: int | None = None  # Database ID if matched
    menu_item_type: str | None = None  # Type slug (e.g., "omelette", "sandwich")
    modifications: list[str] = Field(default_factory=list)  # User modifications
    removed_ingredients: list[str] = Field(default_factory=list)  # Default ingredients that were removed

    # Track unavailable options user attempted to select
    # Map of attr_slug -> {attempted_slug, attempted_display}
    # Used to show helpful "We don't have X - we have Y or Z" messages
    unavailable_selections: dict[str, dict] = Field(default_factory=dict)

    # Track unmatched tokens user mentioned that don't match any option
    # Map of attr_slug -> {tokens: list[str]}
    # Used to show "We don't have X. We have A, B, C..." with pagination
    unmatched_selections: dict[str, dict] = Field(default_factory=dict)

    # Track ambiguous selections that need disambiguation
    # List of {attr_slug, token, matching_options: [{slug, display_name}]}
    # Used to ask "Which syrup? Vanilla, Hazelnut, Caramel, or Peppermint?"
    ambiguous_selections: list[dict] = Field(default_factory=list)

    # Unified selections list - all customizations (attribute choices and add-ons)
    # Renamed from "modifiers" to "selections" for clarity - everything is a selection
    selections: list[dict] = Field(default_factory=list)  # Stored as dict for serialization

    # Cached attribute_values dict — rebuilt from selections on demand, invalidated on mutation
    _attr_cache: dict | None = PrivateAttr(default=None)

    # Track if customization checkpoint has been offered
    customization_offered: bool = False

    # Track if user explicitly declined customization in their initial order
    # e.g., "plain bagel with cream cheese nothing else"
    customization_declined: bool = False

    # Item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions: list[str] = Field(default_factory=list)

    # Inapplicable attribute words from user input (e.g., "small" on non-sized item)
    # List of {word, attribute_slug} — consumed by question_builder to generate notes
    inapplicable_attributes: list[dict] = Field(default_factory=list)

    # Bundle fields - for items that include configurable sub-items (e.g., omelette + bagel)
    # bundle_id groups related items (parent + children share same bundle_id)
    bundle_id: str | None = None
    # bundle_parent_item_id points to the parent item's id (None for parent items)
    bundle_parent_item_id: str | None = None
    # bundle_slot identifies which slot this fills (e.g., "side")
    bundle_slot: str | None = None
    # bundle_price_rule determines pricing: "included" (base=0), "full_price", "fixed", etc.
    bundle_price_rule: str | None = None
    # bundle_included_price: dollar amount included in parent's price (for differential pricing)
    # None = entire base is free (e.g., bagel side), value = amount included (e.g., small fruit salad)
    bundle_included_price: float | None = None

    # -------------------------------------------------------------------------
    # Side item helpers
    # -------------------------------------------------------------------------

    def duplicate(self, mark_complete: bool = True) -> "MenuItemTask":
        """Create a deep copy of this item with a new UUID.

        Args:
            mark_complete: If True, mark the new item as complete (default True)

        Returns:
            A new MenuItemTask with the same data but a unique ID
        """
        new_item = self.model_copy(deep=True)
        new_item.id = str(uuid.uuid4())
        if mark_complete:
            new_item.mark_complete()
        return new_item

    # -------------------------------------------------------------------------
    # Bundle helpers
    # -------------------------------------------------------------------------

    def is_bundle_parent(self) -> bool:
        """Check if this item is a bundle parent (has bundle_id but no parent_item_id)."""
        return self.bundle_id is not None and self.bundle_parent_item_id is None

    def is_bundle_child(self) -> bool:
        """Check if this item is a bundle child (has both bundle_id and parent_item_id)."""
        return self.bundle_id is not None and self.bundle_parent_item_id is not None

    def is_included_in_bundle(self) -> bool:
        """Check if this item's base price is included in a parent's price."""
        return self.bundle_price_rule == "included"

    def start_bundle(self) -> str:
        """Initialize this item as a bundle parent.

        Returns:
            The generated bundle_id
        """
        self.bundle_id = str(uuid.uuid4())
        return self.bundle_id

    # -------------------------------------------------------------------------
    # Backward compatibility alias
    # -------------------------------------------------------------------------

    @property
    def modifiers(self) -> list[dict]:
        """DEPRECATED: Use `selections` instead. This alias exists for backward compatibility."""
        return self.selections

    @modifiers.setter
    def modifiers(self, value: list[dict]) -> None:
        """DEPRECATED: Use `selections` instead. This alias exists for backward compatibility."""
        self._attr_cache = None  # Invalidate cache
        self.selections = value

    # -------------------------------------------------------------------------
    # Attribute query method (data-driven)
    # -------------------------------------------------------------------------

    def has_attribute(self, attr_slug: str) -> bool:
        """Check if this item type has a specific attribute defined in the database.

        Args:
            attr_slug: The attribute slug to check for

        Returns:
            True if this item type has the specified attribute, False otherwise.
        """
        if not self.menu_item_type:
            return False
        attrs = menu_cache.get_item_type_attributes(self.menu_item_type)

        if attr_slug in attrs:
            return True

        # Check legacy aliases
        field_map = menu_cache.get_field_to_slug_map(self.menu_item_type) or {}
        db_slug = field_map.get(attr_slug)
        if db_slug and db_slug in attrs:
            return True

        return False
