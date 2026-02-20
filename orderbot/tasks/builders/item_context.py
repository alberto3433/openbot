"""
Item Build Context.

Provides a dataclass encapsulating all parameters needed to build a menu item.
"""

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import OrderTask
    from ..schemas import Selection


@dataclass
class ItemBuildContext:
    """Context containing all parameters for building a menu item.

    This replaces the 10+ parameters of _create_configurable_item with
    a single context object, making the API cleaner and more maintainable.
    """

    # Required parameters
    menu_item: dict[str, Any]
    """Menu item dict from lookup (must have 'name', 'item_type', 'base_price')."""

    order: "OrderTask"
    """Current order task."""

    # Optional parameters with defaults
    quantity: int = 1
    """Number of items to create (default: 1)."""

    user_input: str | None = None
    """Original user input for attribute extraction (optional)."""

    pre_filled_attributes: dict[str, Any] | None = None
    """Dict of attribute values to pre-fill (optional)."""

    extracted_selections: "list[Selection] | None" = None
    """List of Selection objects to apply (optional)."""

    unavailable_selections: dict[str, Any] | None = None
    """Dict of attr_slug -> {attempted_slug, attempted_display}
    for options user tried that aren't available."""

    unmatched_selections: dict[str, Any] | None = None
    """Dict of attr_slug -> {tokens: list[str]}
    for tokens user mentioned that don't match any option."""

    ambiguous_selections: list[dict[str, Any]] | None = None
    """List of {attr_slug, token, matching_options} for ambiguous tokens
    that need disambiguation (e.g., 'syrup' matching multiple syrup options)."""

    special_instructions: list[str] | None = None
    """List of special instruction strings."""

    inapplicable_attributes: list[dict[str, Any]] | None = None
    """Attribute option words that don't apply to this item type."""

    skip_first_question: bool = False
    """If True, don't ask the first config question (for multi-item adds)."""

    # Derived properties (populated during build)
    canonical_name: str = field(init=False, default="")
    """Canonical name of the item."""

    price: float = field(init=False, default=0.0)
    """Base price of the item."""

    menu_item_id: int | None = field(init=False, default=None)
    """Database ID of the menu item."""

    item_type: str | None = field(init=False, default=None)
    """Item type slug from database."""

    skip_config: bool = field(init=False, default=False)
    """Whether to skip configuration for this item."""

    is_configurable: bool = field(init=False, default=False)
    """Whether this item type is configurable."""

    needs_configuration: bool = field(init=False, default=False)
    """Whether this item needs configuration flow."""

    size_category_slug: str | None = field(init=False, default=None)
    """Size category slug for variant pricing."""

    def __post_init__(self):
        """Extract derived properties from menu_item dict."""
        self.canonical_name = self.menu_item.get("name", "item")
        self.price = self.menu_item.get("base_price", 0.0)
        self.menu_item_id = self.menu_item.get("id")
        self.item_type = self.menu_item.get("item_type")
        self.skip_config = self.menu_item.get("skip_config", False)
        self.size_category_slug = self.menu_item.get("size_category_slug")
