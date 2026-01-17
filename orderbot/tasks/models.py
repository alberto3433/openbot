"""
Pydantic models for the hierarchical task system.

The task hierarchy represents the order capture process:
- OrderTask (root)
  - DeliveryMethodTask
  - ItemsTask (contains multiple ItemTasks)
  - CustomerInfoTask
  - CheckoutTask
  - PaymentTask
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field
import uuid


def get_modifier_name(entry: dict) -> str:
    """Extract the modifier name from a modifier entry dict.

    Standard format uses "slug" key:
        {"slug": "vanilla", "category": "syrup", "quantity": 1}

    Args:
        entry: Dict with modifier info

    Returns:
        The modifier slug, or empty string if not found
    """
    return entry.get("slug") or ""


def normalize_modifier_entry(entry: dict, category: str | None = None) -> dict:
    """Ensure a modifier entry has all standard fields.

    Adds display_name (derived from slug if missing) and ensures quantity is present.

    Args:
        entry: Dict with modifier info (must have "slug" key)
        category: Optional category to add (e.g., "syrup", "sweetener")

    Returns:
        Dict with "slug", "display_name", "quantity", and optionally "category"
    """
    name = get_modifier_name(entry)
    effective_category = category or entry.get("category")

    # Build display name, adding category suffix for syrups if not already present
    display_name = entry.get("display_name")
    if not display_name:
        display_name = name.replace("_", " ").title()
        # Add "Syrup" suffix for syrups if not already present
        if effective_category == "syrup" and not display_name.lower().endswith(" syrup"):
            display_name = f"{display_name} Syrup"

    result = {
        "slug": name,
        "display_name": display_name,
        "quantity": entry.get("quantity", 1),
    }
    if "price" in entry:
        result["price"] = entry["price"]
    if effective_category:
        result["category"] = effective_category
    return result


class TaskStatus(str, Enum):
    """Status of a task in the hierarchy."""
    PENDING = "pending"  # Not started, waiting for prerequisites
    IN_PROGRESS = "in_progress"  # Currently being worked on
    COMPLETE = "complete"  # All required fields filled
    SKIPPED = "skipped"  # Explicitly skipped or cancelled


class FieldConfig(BaseModel):
    """Configuration for a single field in a task."""
    name: str
    required: bool = True
    default: Any | None = None
    ask_if_empty: bool = True  # If True, ask user when field is empty
    question: str | None = None  # Question to ask (if ask_if_empty is True)

    def needs_asking(self, current_value: Any) -> bool:
        """Check if this field needs to be asked about."""
        # Check if current value is meaningful (not None, not empty collection)
        if self._has_meaningful_value(current_value):
            return False
        if not self.ask_if_empty:
            return False
        # Only skip asking if we have a meaningful (truthy) default value
        # Empty defaults like [] or "" still allow asking if ask_if_empty=True
        if self._has_meaningful_value(self.default):
            return False
        return self.required or self.ask_if_empty

    def _has_meaningful_value(self, value: Any) -> bool:
        """Check if a value is meaningful (not None, not empty collection/string)."""
        if value is None:
            return False
        # Empty collections and empty strings don't count as having a value
        if isinstance(value, (list, dict, set)) and not value:
            return False
        if value == "":
            return False
        return True


class BaseTask(BaseModel):
    """Base class for all tasks in the hierarchy."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    def mark_complete(self) -> None:
        """Mark this task as complete."""
        self.status = TaskStatus.COMPLETE
        self.completed_at = datetime.now(timezone.utc)

    def mark_in_progress(self) -> None:
        """Mark this task as in progress."""
        self.status = TaskStatus.IN_PROGRESS

    def mark_skipped(self) -> None:
        """Mark this task as skipped."""
        self.status = TaskStatus.SKIPPED

    def is_complete(self) -> bool:
        """Check if this task is complete."""
        return self.status == TaskStatus.COMPLETE

    def is_actionable(self) -> bool:
        """Check if this task can be worked on."""
        return self.status in (TaskStatus.PENDING, TaskStatus.IN_PROGRESS)

    def get_missing_required_fields(self, field_configs: dict[str, FieldConfig]) -> list[FieldConfig]:
        """Get list of required fields that are missing values."""
        missing = []
        for field_name, config in field_configs.items():
            if not config.required:
                continue
            current_value = getattr(self, field_name, None)
            if current_value is None and config.default is None:
                missing.append(config)
        return missing

    def get_fields_to_ask(self, field_configs: dict[str, FieldConfig]) -> list[FieldConfig]:
        """Get list of fields that need to be asked about."""
        to_ask = []
        for field_name, config in field_configs.items():
            current_value = getattr(self, field_name, None)
            if config.needs_asking(current_value):
                to_ask.append(config)
        return to_ask

    def get_progress(self, field_configs: dict[str, FieldConfig]) -> float:
        """Get completion progress as a percentage (0.0 to 1.0)."""
        if not field_configs:
            return 1.0 if self.is_complete() else 0.0

        required_fields = [f for f in field_configs.values() if f.required]
        if not required_fields:
            return 1.0 if self.is_complete() else 0.0

        filled = 0
        for config in required_fields:
            current_value = getattr(self, config.name, None)
            if current_value is not None or config.default is not None:
                filled += 1

        return filled / len(required_fields)


# =============================================================================
# Item Tasks
# =============================================================================

class ItemTask(BaseTask):
    """Base class for order items (bagels, coffee, etc.)."""

    item_type: str  # "bagel", "coffee", "sandwich", etc.
    quantity: int = 1
    unit_price: float = 0.0

    # Free-form special instructions that don't fit standard modifiers
    # e.g., "light on the cream cheese", "extra crispy", "splash of milk"
    special_instructions: str | None = None

    def get_display_name(self) -> str:
        """Get display name for this item."""
        raise NotImplementedError

    def get_summary(self) -> str:
        """Get a summary description of this item."""
        raise NotImplementedError


class MenuItemTask(ItemTask):
    """Task for a menu item ordered by name (e.g., 'The Chipotle Egg Omelette')."""

    item_type: Literal["menu_item"] = "menu_item"

    # Menu item fields
    menu_item_name: str  # The name of the menu item
    menu_item_id: int | None = None  # Database ID if matched
    menu_item_type: str | None = None  # Type slug (e.g., "omelette", "sandwich")
    modifications: list[str] = Field(default_factory=list)  # User modifications
    removed_ingredients: list[str] = Field(default_factory=list)  # Default ingredients that were removed

    # NOTE: Customization fields (side_choice, bagel_choice, toasted, spread, etc.)
    # are now stored in attribute_values via property accessors for data-driven architecture.
    # See property definitions below.
    is_signature: bool = False  # Whether this is a signature/featured menu item

    # Dynamic attribute values from DB-driven configuration
    # Stores answers for attributes defined in item_type_attributes table
    # e.g., {"bread": "plain", "add_egg": "scrambled_egg", "scooped": True}
    attribute_values: dict[str, Any] = Field(default_factory=dict)

    # Unified modifier storage - all modifiers regardless of category
    # Each entry: {"slug": "vanilla", "category": "syrup", "quantity": 1, "price": 0.75, "display_name": "Vanilla Syrup"}
    modifiers: list[dict] = Field(default_factory=list)

    # Track if customization checkpoint has been offered
    customization_offered: bool = False

    # -------------------------------------------------------------------------
    # Generic helper properties
    # -------------------------------------------------------------------------

    @property
    def item_name(self) -> str | None:
        """Alias for menu_item_name (backward-compatible accessor)."""
        return self.menu_item_name

    @item_name.setter
    def item_name(self, value: str | None) -> None:
        """Set item name (updates menu_item_name)."""
        if value is not None:
            self.menu_item_name = value

    # -------------------------------------------------------------------------
    # Beverage helper properties (for sized_beverage items like coffee)
    # These provide a CoffeeItemTask-compatible interface using attribute_values
    # -------------------------------------------------------------------------

    @property
    def drink_type(self) -> str | None:
        """Get drink type (alias for menu_item_name for beverages with size attribute)."""
        return self.menu_item_name if self.has_attribute("size") else None

    @drink_type.setter
    def drink_type(self, value: str | None) -> None:
        """Set drink type (updates menu_item_name for beverages)."""
        if value is not None:
            self.menu_item_name = value

    @property
    def size(self) -> str | None:
        """Get beverage size from attribute_values."""
        return self.attribute_values.get("size")

    @size.setter
    def size(self, value: str | None) -> None:
        """Set beverage size in attribute_values."""
        if value is not None:
            self.attribute_values["size"] = value
        elif "size" in self.attribute_values:
            del self.attribute_values["size"]

    @property
    def decaf(self) -> bool | None:
        """Get decaf flag from attribute_values."""
        return self.attribute_values.get("decaf")

    @decaf.setter
    def decaf(self, value: bool | None) -> None:
        """Set decaf flag in attribute_values."""
        if value is not None:
            self.attribute_values["decaf"] = value
        elif "decaf" in self.attribute_values:
            del self.attribute_values["decaf"]

    @property
    def temperature(self) -> str | None:
        """Get temperature from attribute_values ('hot' or 'iced')."""
        return self.attribute_values.get("temperature")

    @temperature.setter
    def temperature(self, value: str | None) -> None:
        """Set temperature in attribute_values."""
        if value is not None:
            self.attribute_values["temperature"] = value
        elif "temperature" in self.attribute_values:
            del self.attribute_values["temperature"]

    @property
    def iced(self) -> bool | None:
        """Get iced flag from temperature attribute.

        Returns True if temperature is 'iced', False if 'hot', None if unset.
        """
        temp = self.attribute_values.get("temperature")
        if temp is None:
            return None
        return temp == "iced"

    @iced.setter
    def iced(self, value: bool | None) -> None:
        """Set iced flag by setting temperature attribute."""
        if value is True:
            self.attribute_values["temperature"] = "iced"
        elif value is False:
            self.attribute_values["temperature"] = "hot"
        elif "temperature" in self.attribute_values:
            del self.attribute_values["temperature"]

    @property
    def milk(self) -> str | None:
        """Get milk type from modifiers.

        Returns the slug of the first milk modifier.
        """
        for m in self.modifiers:
            if m.get("category") == "milk":
                return m.get("slug")
        return None

    @milk.setter
    def milk(self, value: str | None) -> None:
        """Set milk type in modifiers."""
        # Remove existing milk entries
        self.modifiers = [m for m in self.modifiers if m.get("category") != "milk"]

        if value is not None:
            self.modifiers.append({
                "slug": value,
                "display_name": value.replace("_", " ").title(),
                "quantity": 1,
                "category": "milk",
            })

    @property
    def cream_level(self) -> str | None:
        """Get cream level from attribute_values."""
        return self.attribute_values.get("cream_level")

    @cream_level.setter
    def cream_level(self, value: str | None) -> None:
        """Set cream level in attribute_values."""
        if value is not None:
            self.attribute_values["cream_level"] = value
        elif "cream_level" in self.attribute_values:
            del self.attribute_values["cream_level"]

    @property
    def sweeteners(self) -> list[dict]:
        """Get sweeteners list from modifiers.

        Returns entries with category="sweetener".
        """
        return [m for m in self.modifiers if m.get("category") == "sweetener"]

    @sweeteners.setter
    def sweeteners(self, value: list[dict]) -> None:
        """Set sweeteners list in modifiers."""
        # Remove existing sweetener entries
        self.modifiers = [m for m in self.modifiers if m.get("category") != "sweetener"]

        # Add new sweetener entries (normalize to canonical format)
        for entry in (value or []):
            normalized = normalize_modifier_entry(entry, category="sweetener")
            slug = normalized["slug"]
            # Check for duplicates
            if slug and not any(m.get("slug") == slug and m.get("category") == "sweetener" for m in self.modifiers):
                self.modifiers.append(normalized)

    @property
    def flavor_syrups(self) -> list[dict]:
        """Get flavor syrups list from modifiers.

        Returns entries with category="syrup".
        """
        return [m for m in self.modifiers if m.get("category") == "syrup"]

    @flavor_syrups.setter
    def flavor_syrups(self, value: list[dict]) -> None:
        """Set flavor syrups list in modifiers."""
        # Remove existing syrup entries
        self.modifiers = [m for m in self.modifiers if m.get("category") != "syrup"]

        # Add new syrup entries (normalize to canonical format)
        for entry in (value or []):
            normalized = normalize_modifier_entry(entry, category="syrup")
            slug = normalized["slug"]
            # Check for duplicates
            if slug and not any(m.get("slug") == slug and m.get("category") == "syrup" for m in self.modifiers):
                self.modifiers.append(normalized)

    def add_modifier(
        self,
        category: str,
        slug: str,
        quantity: int = 1,
        price: float = 0.0,
        display_name: str | None = None,
    ) -> None:
        """Add a modifier to the item.

        All modifiers are stored in a unified list regardless of category.

        Args:
            category: Modifier category (e.g., "syrup", "sweetener", "milk", "protein", "topping")
            slug: Modifier slug (e.g., "vanilla", "sugar", "oat", "bacon")
            quantity: Quantity (default 1)
            price: Price per unit (default 0.0)
            display_name: Display name (if not provided, derived from slug)
        """
        # Check if already present
        if any(m.get("slug") == slug and m.get("category") == category for m in self.modifiers):
            return

        # Build entry
        entry = {
            "slug": slug,
            "category": category,
            "quantity": quantity,
            "display_name": display_name or slug.replace("_", " ").title(),
        }
        if price > 0:
            entry["price"] = price

        self.modifiers.append(entry)

        # Update unit_price if modifier has a price
        if price > 0:
            self.unit_price = (self.unit_price or 0.0) + (price * quantity)

    def get_modifiers_by_category(self, category: str) -> list[dict]:
        """Get all modifiers of a specific category.

        Args:
            category: The category to filter by (e.g., "milk", "syrup", "protein")

        Returns:
            List of modifier dicts matching the category
        """
        return [m for m in self.modifiers if m.get("category") == category]

    def remove_modifier(self, slug: str, category: str | None = None) -> bool:
        """Remove a modifier by slug.

        Args:
            slug: The modifier slug to remove
            category: Optional category to match (if None, removes first match)

        Returns:
            True if a modifier was removed, False otherwise
        """
        for i, m in enumerate(self.modifiers):
            if m.get("slug") == slug:
                if category is None or m.get("category") == category:
                    removed = self.modifiers.pop(i)
                    # Subtract price from unit_price
                    if removed.get("price", 0) > 0:
                        self.unit_price -= removed["price"] * removed.get("quantity", 1)
                    return True
        return False

    @property
    def wants_syrup(self) -> bool:
        """Get wants_syrup flag from attribute_values."""
        return self.attribute_values.get("wants_syrup", False)

    @wants_syrup.setter
    def wants_syrup(self, value: bool) -> None:
        """Set wants_syrup flag in attribute_values."""
        self.attribute_values["wants_syrup"] = value

    @property
    def pending_syrup_quantity(self) -> int:
        """Get pending_syrup_quantity from attribute_values."""
        return self.attribute_values.get("pending_syrup_quantity", 1)

    @pending_syrup_quantity.setter
    def pending_syrup_quantity(self, value: int) -> None:
        """Set pending_syrup_quantity in attribute_values."""
        self.attribute_values["pending_syrup_quantity"] = value

    @property
    def extra_shots(self) -> int:
        """Get extra_shots from attribute_values."""
        return self.attribute_values.get("extra_shots", 0)

    @extra_shots.setter
    def extra_shots(self, value: int) -> None:
        """Set extra_shots in attribute_values."""
        self.attribute_values["extra_shots"] = value

    # Upcharge properties for beverages
    @property
    def size_upcharge(self) -> float:
        """Get size upcharge from attribute_values."""
        return self.attribute_values.get("size_upcharge", 0.0)

    @size_upcharge.setter
    def size_upcharge(self, value: float) -> None:
        """Set size upcharge in attribute_values."""
        self.attribute_values["size_upcharge"] = value

    @property
    def milk_upcharge(self) -> float:
        """Get milk upcharge from attribute_values."""
        return self.attribute_values.get("milk_upcharge", 0.0)

    @milk_upcharge.setter
    def milk_upcharge(self, value: float) -> None:
        """Set milk upcharge in attribute_values and update milk entry price."""
        self.attribute_values["milk_upcharge"] = value
        # Also update the price in the milk entry in modifiers
        for entry in self.modifiers:
            if entry.get("category") == "milk":
                entry["price"] = value
                break

    @property
    def syrup_upcharge(self) -> float:
        """Get syrup upcharge from attribute_values."""
        return self.attribute_values.get("syrup_upcharge", 0.0)

    @syrup_upcharge.setter
    def syrup_upcharge(self, value: float) -> None:
        """Set syrup upcharge in attribute_values."""
        self.attribute_values["syrup_upcharge"] = value

    @property
    def iced_upcharge(self) -> float:
        """Get iced upcharge from attribute_values."""
        return self.attribute_values.get("iced_upcharge", 0.0)

    @iced_upcharge.setter
    def iced_upcharge(self, value: float) -> None:
        """Set iced upcharge in attribute_values."""
        self.attribute_values["iced_upcharge"] = value

    @property
    def extra_shots_upcharge(self) -> float:
        """Get extra shots upcharge from attribute_values."""
        return self.attribute_values.get("extra_shots_upcharge", 0.0)

    @extra_shots_upcharge.setter
    def extra_shots_upcharge(self, value: float) -> None:
        """Set extra shots upcharge in attribute_values."""
        self.attribute_values["extra_shots_upcharge"] = value

    @property
    def is_espresso(self) -> bool:
        """Check if this is an espresso drink (has shots attribute).

        Data-driven: checks if item type has the 'shots' attribute,
        which identifies espresso-style items that can have extra shots.
        This is a capability check, not a name check.
        """
        # Espresso-style items have shots attribute
        # This covers both pure espresso (shots without size) and
        # espresso-based drinks that allow shot customization
        return self.has_attribute("shots")

    # -------------------------------------------------------------------------
    # Generic attribute query method (data-driven)
    # -------------------------------------------------------------------------

    def has_attribute(self, attr_slug: str) -> bool:
        """Check if this item type has a specific attribute defined in the database.

        This is the preferred way to check item capabilities instead of
        checking item type names directly. It queries the database to see
        what attributes are defined for this item's type.

        Also supports legacy alias lookup (e.g., "spread" -> "spread_type").

        Examples:
            item.has_attribute("size")        # True for sized_beverage
            item.has_attribute("bread")       # True for bagel
            item.has_attribute("spread")      # True for bagel, some sandwiches
            item.has_attribute("milk")        # True for sized_beverage

        Args:
            attr_slug: The attribute slug to check for (e.g., "size", "spread", "milk")

        Returns:
            True if this item type has the specified attribute, False otherwise.
        """
        if not self.menu_item_type:
            return False
        from orderbot.menu_data_cache import menu_cache
        attrs = menu_cache.get_item_type_attributes(self.menu_item_type)

        # Direct check first
        if attr_slug in attrs:
            return True

        # Check legacy aliases using the field-to-slug mapping from field_config
        # This mapping defines: code_field_name -> db_attribute_slug
        # Import inside method to avoid circular imports
        from orderbot.tasks.field_config import _FIELD_TO_SLUG_MAP
        field_map = _FIELD_TO_SLUG_MAP.get(self.menu_item_type, {})
        db_slug = field_map.get(attr_slug)
        if db_slug and db_slug in attrs:
            return True

        return False

    # -------------------------------------------------------------------------
    # Bagel helper properties (for bagel items)
    # These provide a BagelItemTask-compatible interface using attribute_values
    # -------------------------------------------------------------------------

    @property
    def bread(self) -> str | None:
        """Get bread type from attribute_values."""
        return self.attribute_values.get("bread")

    @bread.setter
    def bread(self, value: str | None) -> None:
        """Set bread type in attribute_values."""
        if value is not None:
            self.attribute_values["bread"] = value
        elif "bread" in self.attribute_values:
            del self.attribute_values["bread"]

    @property
    def bread_upcharge(self) -> float:
        """Get bread type upcharge from attribute_values."""
        return self.attribute_values.get("bread_upcharge", 0.0)

    @bread_upcharge.setter
    def bread_upcharge(self, value: float) -> None:
        """Set bread type upcharge in attribute_values."""
        self.attribute_values["bread_upcharge"] = value

    @property
    def toasted(self) -> bool | None:
        """Get toasted flag from attribute_values."""
        return self.attribute_values.get("toasted")

    @toasted.setter
    def toasted(self, value: bool | None) -> None:
        """Set toasted flag in attribute_values."""
        if value is not None:
            self.attribute_values["toasted"] = value
        elif "toasted" in self.attribute_values:
            del self.attribute_values["toasted"]

    @property
    def scooped(self) -> bool | None:
        """Get scooped flag from attribute_values."""
        return self.attribute_values.get("scooped")

    @scooped.setter
    def scooped(self, value: bool | None) -> None:
        """Set scooped flag in attribute_values."""
        if value is not None:
            self.attribute_values["scooped"] = value
        elif "scooped" in self.attribute_values:
            del self.attribute_values["scooped"]

    @property
    def spread_type(self) -> str | None:
        """Get spread type from attribute_values."""
        return self.attribute_values.get("spread_type")

    @spread_type.setter
    def spread_type(self, value: str | None) -> None:
        """Set spread type in attribute_values."""
        if value is not None:
            self.attribute_values["spread_type"] = value
        elif "spread_type" in self.attribute_values:
            del self.attribute_values["spread_type"]

    @property
    def spread(self) -> str | None:
        """Alias for spread_type (backward-compatible accessor)."""
        return self.spread_type

    @spread.setter
    def spread(self, value: str | None) -> None:
        """Set spread type (updates attribute_values["spread_type"])."""
        self.spread_type = value

    @property
    def toppings(self) -> list[str]:
        """Get toppings list from attribute_values.

        Creates the list if it doesn't exist, so .append() works correctly.
        """
        if "toppings" not in self.attribute_values:
            self.attribute_values["toppings"] = []
        return self.attribute_values["toppings"]

    @toppings.setter
    def toppings(self, value: list[str]) -> None:
        """Set toppings list in attribute_values."""
        self.attribute_values["toppings"] = value or []

    @property
    def extra_protein(self) -> str | None:
        """Get extra protein from attribute_values."""
        return self.attribute_values.get("extra_protein")

    @extra_protein.setter
    def extra_protein(self, value: str | None) -> None:
        """Set extra protein in attribute_values."""
        if value is not None:
            self.attribute_values["extra_protein"] = value
        elif "extra_protein" in self.attribute_values:
            del self.attribute_values["extra_protein"]

    @property
    def needs_cheese_clarification(self) -> bool:
        """Get needs_cheese_clarification flag from attribute_values."""
        return self.attribute_values.get("needs_cheese_clarification", False)

    @needs_cheese_clarification.setter
    def needs_cheese_clarification(self, value: bool) -> None:
        """Set needs_cheese_clarification flag in attribute_values."""
        self.attribute_values["needs_cheese_clarification"] = value

    # -------------------------------------------------------------------------
    # Side choice properties (for items with configurable sides like omelettes)
    # These are stored in attribute_values for data-driven architecture
    # -------------------------------------------------------------------------

    @property
    def side_choice(self) -> str | None:
        """Get side choice from attribute_values (e.g., 'bagel' or 'fruit_salad')."""
        return self.attribute_values.get("side_choice")

    @side_choice.setter
    def side_choice(self, value: str | None) -> None:
        """Set side choice in attribute_values."""
        if value is not None:
            self.attribute_values["side_choice"] = value
        elif "side_choice" in self.attribute_values:
            del self.attribute_values["side_choice"]

    @property
    def bagel_choice(self) -> str | None:
        """Get bagel choice from attribute_values (which bagel type for side)."""
        return self.attribute_values.get("bagel_choice")

    @bagel_choice.setter
    def bagel_choice(self, value: str | None) -> None:
        """Set bagel choice in attribute_values."""
        if value is not None:
            self.attribute_values["bagel_choice"] = value
        elif "bagel_choice" in self.attribute_values:
            del self.attribute_values["bagel_choice"]

    @property
    def bagel_choice_upcharge(self) -> float:
        """Get bagel choice upcharge from attribute_values."""
        return self.attribute_values.get("bagel_choice_upcharge", 0.0)

    @bagel_choice_upcharge.setter
    def bagel_choice_upcharge(self, value: float) -> None:
        """Set bagel choice upcharge in attribute_values."""
        self.attribute_values["bagel_choice_upcharge"] = value

    @property
    def spread_price(self) -> float | None:
        """Get spread price from attribute_values."""
        return self.attribute_values.get("spread_price")

    @spread_price.setter
    def spread_price(self, value: float | None) -> None:
        """Set spread price in attribute_values."""
        if value is not None:
            self.attribute_values["spread_price"] = value
        elif "spread_price" in self.attribute_values:
            del self.attribute_values["spread_price"]

    @property
    def requires_side_choice(self) -> bool:
        """Get requires_side_choice flag from attribute_values."""
        return self.attribute_values.get("requires_side_choice", False)

    @requires_side_choice.setter
    def requires_side_choice(self, value: bool) -> None:
        """Set requires_side_choice flag in attribute_values."""
        if value:
            self.attribute_values["requires_side_choice"] = value
        elif "requires_side_choice" in self.attribute_values:
            del self.attribute_values["requires_side_choice"]

    def _get_attribute_display_name(self, attr_slug: str, value_slug: str | None = None) -> str | None:
        """Get display name for an attribute value from stored selections.

        Looks up the display_name from {attr_slug}_selections which stores
        database-provided display names alongside slugs.

        Args:
            attr_slug: The attribute slug (e.g., "bread", "shots", "size")
            value_slug: Optional value slug to find in multi-select lists.
                        If None, returns the first selection's display name.

        Returns:
            The display name if found, None otherwise.
        """
        selections = self.attribute_values.get(f"{attr_slug}_selections", [])
        if not selections or not isinstance(selections, list):
            return None

        if value_slug:
            # Find specific value in selections list
            for sel in selections:
                if isinstance(sel, dict) and sel.get("slug") == value_slug:
                    return sel.get("display_name")
            return None

        # Return first selection's display name
        if len(selections) > 0 and isinstance(selections[0], dict):
            return selections[0].get("display_name")
        return None

    def _get_all_attribute_display_names(self, attr_slug: str) -> list[str]:
        """Get all display names for a multi-select attribute.

        Returns:
            List of display names from {attr_slug}_selections.
        """
        selections = self.attribute_values.get(f"{attr_slug}_selections", [])
        if not selections or not isinstance(selections, list):
            return []
        return [
            sel.get("display_name") for sel in selections
            if isinstance(sel, dict) and sel.get("display_name")
        ]

    def get_display_name(self) -> str:
        """Get display name for this menu item."""
        # Handle espresso-style items (have shots attribute but no size)
        if self.has_attribute("shots") and not self.has_attribute("size"):
            decaf = self.attribute_values.get("decaf", False)

            # Get shots display name from database (stored in shots_selections)
            shots_display = self._get_attribute_display_name("shots")
            if shots_display and shots_display.lower() != "single":
                # Use database display name as prefix (e.g., "Double", "Triple")
                display_name = f"{shots_display} {self.menu_item_name or 'Espresso'}"
            else:
                display_name = self.menu_item_name or "Espresso"

            if decaf:
                display_name = f"Decaf {display_name}"
            return display_name

        # Handle sized beverage display (items with size attribute)
        if self.has_attribute("size"):
            parts = []
            # Get size display name from database (stored in size_selections)
            size_display = self._get_attribute_display_name("size")
            if size_display:
                parts.append(size_display)
            elif self.size:
                parts.append(self.size)

            if self.decaf:
                parts.append("decaf")
            if self.extra_shots == 1:
                parts.append("double")
            elif self.extra_shots >= 2:
                parts.append("triple")
            # Use menu_item_name, or fall back to item type display name if available
            item_name = self.menu_item_name or getattr(self, 'menu_item_type', None) or "beverage"
            parts.append(item_name)
            return " ".join(parts)

        return self.menu_item_name

    def get_summary(self) -> str:
        """Get a summary description of this menu item."""
        parts = []

        if self.quantity > 1:
            parts.append(f"{self.quantity}x")

        # Use display name (handles espresso shots/decaf)
        parts.append(self.get_display_name())

        # Add DB-driven attribute values (for deli_sandwich, etc.)
        if self.attribute_values:
            # Handle bread selection
            bread = self.attribute_values.get("bread")
            if bread:
                # Get display name from database (stored in bread_selections)
                bread_display = self._get_attribute_display_name("bread") or bread
                parts.append(f"on {bread_display}")

            # Handle toasted - check both attribute_values and direct property
            # (supports both menu_item_config_handler which uses attribute_values,
            # and bagel_config_handler which uses direct property)
            toasted_from_attr = self.attribute_values.get("toasted")
            toasted_value = toasted_from_attr if toasted_from_attr is not None else self.toasted
            if toasted_value is True:
                parts.append("toasted")
            elif toasted_value is False and bread:
                parts.append("not toasted")

            # Handle other customizations (extra protein, toppings, etc.)
            extra_customizations = []
            for key, value in self.attribute_values.items():
                # Skip already handled fields and internal data fields
                if key in ("bread", "toasted", "scooped"):
                    continue  # Already handled above
                if key.endswith("_price") or key.endswith("_selections"):
                    continue  # Internal price/selection data, not for display
                # Skip espresso-style fields that are in the display name (items with shots but no size)
                if self.has_attribute("shots") and not self.has_attribute("size") and key in ("shots", "decaf"):
                    continue  # Already handled in get_display_name()
                if value is True:
                    # Boolean attribute - use attribute display name from database
                    display_name = self._get_attribute_display_name(key) or key
                    extra_customizations.append(display_name)
                elif value and value is not False:
                    # Handle list values (multi-select attributes like extra proteins)
                    if isinstance(value, list):
                        # Get display names from {key}_selections
                        display_names = self._get_all_attribute_display_names(key)
                        if display_names:
                            extra_customizations.extend(display_names)
                        else:
                            # Fallback: use raw values if no selections stored
                            for item in value:
                                if isinstance(item, str):
                                    extra_customizations.append(item)
                    else:
                        # Single-select: get display name from database
                        display_name = self._get_attribute_display_name(key, str(value))
                        extra_customizations.append(display_name or str(value))
            if extra_customizations:
                parts.append(f"with {', '.join(extra_customizations)}")

        # Add side choice info (data-driven approach)
        elif self.side_choice:
            # Check for {side_choice}_choice field dynamically
            choice_field = f"{self.side_choice}_choice"
            specific_choice = getattr(self, choice_field, None)
            if specific_choice:
                # Get display names from database
                choice_display = self._get_attribute_display_name(choice_field, specific_choice) or specific_choice
                side_display = self._get_attribute_display_name("side_choice", self.side_choice) or self.side_choice
                side_parts = [choice_display, side_display]
                if self.toasted:
                    side_parts.append("toasted")
                if self.spread:
                    spread_display = self._get_attribute_display_name("spread_type", self.spread) or self.spread
                    side_parts.append(f"with {spread_display}")
                parts.append(f"with {' '.join(side_parts)}")
            else:
                # Side has no sub-selection - get display name from database
                side_display = self._get_attribute_display_name("side_choice", self.side_choice) or self.side_choice
                parts.append(f"with {side_display}")

        if self.modifications:
            parts.append(f"({', '.join(self.modifications)})")

        # Add removed ingredients if present (e.g., "no bacon")
        if self.removed_ingredients:
            removed_parts = [f"no {ing}" for ing in self.removed_ingredients]
            parts.append(f"({', '.join(removed_parts)})")

        # Add special instructions if present
        if self.special_instructions:
            parts.append(f"(Special Instructions: {self.special_instructions})")

        return " ".join(parts)

    def get_missing_customizations(self) -> list[str]:
        """Get list of missing required customizations.

        Uses data-driven approach: check for {side_choice}_choice field dynamically.
        """
        missing = []
        if self.requires_side_choice and not self.side_choice:
            missing.append("side_choice")
        # Check if side_choice type needs a specific choice (e.g., bagel_choice for bagel)
        if self.side_choice:
            choice_field = f"{self.side_choice}_choice"
            if hasattr(self, choice_field) and getattr(self, choice_field, None) is None:
                missing.append(choice_field)
        return missing

    def is_fully_customized(self) -> bool:
        """Check if all required customizations are complete."""
        return len(self.get_missing_customizations()) == 0


# =============================================================================
# Order Flow Tasks
# =============================================================================

class AddressTask(BaseTask):
    """Task for capturing delivery address."""

    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    apt_unit: str | None = None
    delivery_instructions: str | None = None
    is_validated: bool = False

    def get_formatted_address(self) -> str | None:
        """Get formatted address string."""
        if not self.street:
            return None

        parts = [self.street]
        if self.apt_unit:
            parts.append(f"Apt {self.apt_unit}")

        city_state_zip = []
        if self.city:
            city_state_zip.append(self.city)
        if self.state:
            city_state_zip.append(self.state)
        if self.zip_code:
            city_state_zip.append(self.zip_code)

        if city_state_zip:
            parts.append(", ".join(city_state_zip))

        return ", ".join(parts)


class DeliveryMethodTask(BaseTask):
    """Task for capturing delivery method (pickup vs delivery)."""

    order_type: Literal["pickup", "delivery"] | None = None
    address: AddressTask = Field(default_factory=AddressTask)
    store_location_confirmed: bool = False

    def is_complete(self) -> bool:
        """Check if delivery method is complete."""
        if self.order_type is None:
            return False
        if self.order_type == "pickup":
            return True  # Pickup doesn't need address
        if self.order_type == "delivery":
            # Need at least street and zip for delivery
            return bool(self.address.street and self.address.zip_code)
        return False


class CustomerInfoTask(BaseTask):
    """Task for capturing customer information."""

    name: str | None = None
    phone: str | None = None
    email: str | None = None

    def has_contact(self) -> bool:
        """Check if we have at least one contact method."""
        return bool(self.phone or self.email)


class CheckoutTask(BaseTask):
    """Task for order review and confirmation."""

    order_reviewed: bool = False
    subtotal: float = 0.0
    city_tax: float = 0.0
    state_tax: float = 0.0
    tax: float = 0.0  # Total tax
    delivery_fee: float = 0.0
    tip: float = 0.0
    total: float = 0.0
    confirmed: bool = False
    order_number: str | None = None

    def calculate_total(
        self,
        subtotal: float,
        is_delivery: bool = False,
        city_tax_rate: float = 0.0,
        state_tax_rate: float = 0.0,
        delivery_fee: float = 0.0,
    ) -> None:
        """Calculate order totals."""
        self.subtotal = subtotal
        self.city_tax = round(subtotal * city_tax_rate, 2)
        self.state_tax = round(subtotal * state_tax_rate, 2)
        self.tax = self.city_tax + self.state_tax
        self.delivery_fee = delivery_fee if is_delivery else 0.0
        self.total = round(self.subtotal + self.tax + self.delivery_fee + self.tip, 2)

    def generate_order_number(self) -> str:
        """Generate a unique order number."""
        import random
        hex_part = uuid.uuid4().hex[:6].upper()
        digit_suffix = f"{random.randint(0, 99):02d}"
        self.order_number = f"ORD-{hex_part}-{digit_suffix}"
        return self.order_number

    @property
    def short_order_number(self) -> str:
        """Get just the last 2 digits of the order number for easy verbal reference."""
        if self.order_number and "-" in self.order_number:
            return self.order_number.split("-")[-1]
        return self.order_number or ""


class PaymentTask(BaseTask):
    """Task for capturing payment method."""

    method: Literal["in_store", "cash_delivery", "card_link"] | None = None
    payment_link_sent: bool = False
    payment_link_destination: str | None = None  # email or phone
    payment_received: bool = False


# =============================================================================
# Container Tasks
# =============================================================================

class ItemsTask(BaseTask):
    """Container task for all order items."""

    items: list[ItemTask] = Field(default_factory=list)

    def add_item(self, item: ItemTask) -> None:
        """Add an item to the order."""
        self.items.append(item)
        if self.status == TaskStatus.PENDING:
            self.status = TaskStatus.IN_PROGRESS

    def remove_item(self, index: int) -> ItemTask | None:
        """Remove and return item at index."""
        if 0 <= index < len(self.items):
            return self.items.pop(index)
        return None

    def skip_item(self, index: int) -> None:
        """Mark item at index as skipped."""
        if 0 <= index < len(self.items):
            self.items[index].mark_skipped()

    def get_active_items(self) -> list[ItemTask]:
        """Get items that are not skipped."""
        return [item for item in self.items if item.status != TaskStatus.SKIPPED]

    def get_current_item(self) -> ItemTask | None:
        """Get the item currently being worked on (first in_progress)."""
        for item in self.items:
            if item.status == TaskStatus.IN_PROGRESS:
                return item
        return None

    def get_next_pending_item(self) -> ItemTask | None:
        """Get the next pending item."""
        for item in self.items:
            if item.status == TaskStatus.PENDING:
                return item
        return None

    def all_items_complete(self) -> bool:
        """Check if all non-skipped items are complete."""
        active_items = self.get_active_items()
        if not active_items:
            return False
        return all(item.is_complete() for item in active_items)

    def is_complete(self) -> bool:
        """Check if all items are complete."""
        return self.all_items_complete()

    def get_subtotal(self) -> float:
        """Calculate subtotal for all active items."""
        return sum(
            item.unit_price * item.quantity
            for item in self.get_active_items()
        )

    def get_item_count(self) -> int:
        """Get total count of active items."""
        return sum(item.quantity for item in self.get_active_items())

    def get_item_by_id(self, item_id: str) -> ItemTask | None:
        """Get an item by its ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None


# =============================================================================
# Root Order Task
# =============================================================================

class OrderTask(BaseTask):
    """Root task representing the entire order."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    db_order_id: int | None = None  # Database order ID for persistence

    # Sub-tasks
    delivery_method: DeliveryMethodTask = Field(default_factory=DeliveryMethodTask)
    items: ItemsTask = Field(default_factory=ItemsTask)
    customer_info: CustomerInfoTask = Field(default_factory=CustomerInfoTask)
    checkout: CheckoutTask = Field(default_factory=CheckoutTask)
    payment: PaymentTask = Field(default_factory=PaymentTask)

    # Conversation tracking
    conversation_history: list[dict] = Field(default_factory=list)

    # Flow state (moved from FlowState in Phase 4)
    phase: str = "greeting"  # Current order phase (stored as string to avoid circular imports)
    pending_item_ids: list[str] = Field(default_factory=list)  # Items needing input
    pending_field: str | None = None  # Field we're asking about
    last_bot_message: str | None = None  # For context

    # Queue of items that need configuration after the current one is done
    # Each entry is a dict with: item_id, item_type (e.g., "coffee", "bagel")
    pending_config_queue: list[dict] = Field(default_factory=list)

    # Modifiers stored during item disambiguation
    # When user says "large iced oat milk latte" and we ask "Latte or Seasonal Matcha Latte?",
    # we store the modifiers here so they can be applied when user clarifies the item type
    # Works for any item type (coffee, bagels, etc.), not just beverages
    pending_item_modifiers: dict = Field(default_factory=dict)

    # Unknown item request - stores the item name user asked for that doesn't exist
    # Used to show "Sorry, we don't have X" message
    unknown_item_request: str | None = Field(default=None)

    # Generic menu item options for disambiguation (cookies, muffins, etc.)
    # Used when user says "cookies" and there are multiple cookie types
    pending_item_options: list[dict] = Field(default_factory=list)

    # Quantity stored during item disambiguation
    pending_item_quantity: int = Field(default=1)

    # Pending modifier change clarification
    # Used when user says "change it to blueberry" and we need to clarify bagel vs spread
    # Dict with: new_value, possible_attributes (list of attribute slugs), item_id
    pending_change_clarification: dict | None = None

    # Pending duplicate selection
    # Used when user says "another one" with multiple items in cart
    # Dict with: count (int - how many to duplicate), items (list of item summaries for question)
    pending_duplicate_selection: dict | None = None

    # Pending "same thing" disambiguation
    # Used when user says "same thing" and we have both a previous order AND items in cart
    # Dict with: has_previous_order (bool), cart_items (list of item summaries)
    pending_same_thing_clarification: dict | None = None

    # Pending suggested item from menu inquiry
    # Set when bot describes an item and asks "Would you like to order one?"
    # Stores the menu item name (e.g., "The Lexington") for confirmation
    pending_suggested_item: str | None = None

    # Menu query pagination state for "show more" functionality
    # Dict with: category (str), offset (int), total_items (int)
    # Used when user asks "what other X do you have?" or "more X"
    menu_query_pagination: dict | None = None

    # Ingredient search pagination state for "what else" follow-up
    # Dict with: ingredient (str), matches (list of item dicts), offset (int)
    # Used when user says "chicken" and we show items, then they say "what else"
    pending_ingredient_search: dict | None = None

    # Configuration options page for "what else" during field configuration
    # Tracks which page of options (e.g., bagel types) we're showing
    # 0 = first page (default), 1 = second page, etc.
    config_options_page: int = 0

    # Names of items in a multi-item order that need configuration
    # Used to build final summary like "Great, both toasted. Anything else?"
    multi_item_config_names: list[str] = Field(default_factory=list)

    # Transient error storage for _add_parsed_item -> _process_items communication
    # This is a transient field that should not be serialized
    last_add_error: Any | None = Field(default=None, exclude=True)

    # Generic attribute disambiguation state for MenuItemConfigHandler
    # Used when user input matches multiple options for an attribute (e.g., "walnut" matches
    # "honey walnut" and "maple raisin walnut" for cream cheese spread)
    # Dict with:
    #   - options: list[dict] - the options to choose from
    #   - attr_slug: str - the attribute being disambiguated
    #   - modifiers: dict - extracted modifiers to apply after resolution
    #   - item_id: str - the item being configured
    pending_attr_disambiguation: dict | None = None

    # Legacy single-item property for backwards compatibility
    @property
    def pending_item_id(self) -> str | None:
        """Get the first pending item ID (backwards compat)."""
        return self.pending_item_ids[0] if self.pending_item_ids else None

    @pending_item_id.setter
    def pending_item_id(self, value: str | None):
        """Set a single pending item ID (backwards compat)."""
        if value is None:
            self.pending_item_ids = []
        else:
            self.pending_item_ids = [value]

    def is_configuring_item(self) -> bool:
        """Check if we're waiting for input on a specific item or menu inquiry."""
        # Also handle by-pound category selection (no item, just pending_field)
        if self.pending_field == "by_pound_category":
            return True
        # Handle drink selection when multiple options were presented
        if self.pending_field == "drink_selection":
            return True
        # Handle drink type selection (disambiguation like "latte" matching multiple items)
        if self.pending_field == "drink_type":
            return True
        # Handle generic item selection (cookies, muffins, etc.) when multiple options presented
        if self.pending_field == "item_selection":
            return True
        # Handle category inquiry follow-up
        if self.pending_field == "category_inquiry":
            return True
        # Handle duplicate item selection when multiple items in cart
        if self.pending_field == "duplicate_selection":
            return True
        # Handle suggested item confirmation ("Would you like to order one?" -> "yes")
        if self.pending_field == "confirm_suggested_item":
            return True
        # Handle attribute disambiguation (e.g., "walnut" -> "honey walnut" or "maple raisin walnut")
        if self.pending_attr_disambiguation is not None:
            return True
        return len(self.pending_item_ids) > 0 and self.pending_field is not None

    def is_configuring_multiple(self) -> bool:
        """Check if we're configuring multiple items at once."""
        return len(self.pending_item_ids) > 1

    def clear_pending(self):
        """Clear pending item/field when done configuring."""
        self.pending_item_ids = []
        self.pending_field = None
        self.config_options_page = 0
        self.pending_suggested_item = None
        self.pending_item_modifiers = {}
        self.pending_attr_disambiguation = None

    def clear_menu_pagination(self):
        """Clear menu query pagination state."""
        self.menu_query_pagination = None

    def set_menu_pagination(self, category: str, offset: int, total_items: int):
        """Set menu query pagination state for 'show more' functionality."""
        self.menu_query_pagination = {
            "category": category,
            "offset": offset,
            "total_items": total_items,
        }

    def get_menu_pagination(self) -> dict | None:
        """Get current menu query pagination state."""
        return self.menu_query_pagination

    def queue_item_for_config(
        self,
        item_id: str,
        item_type: str,
        item_name: str | None = None,
        pending_field: str | None = None,
    ) -> None:
        """Add an item to the configuration queue.

        Args:
            item_id: The item's unique ID
            item_type: Type of item (bagel, coffee, signature_item, etc.)
            item_name: Display name for abbreviated follow-up questions
            pending_field: The field to configure (toasted, bread, etc.)
        """
        # Don't add duplicates - handle mixed types (strings from category inquiry, dicts from item config)
        for entry in self.pending_config_queue:
            if isinstance(entry, dict) and entry.get("item_id") == item_id:
                return
        self.pending_config_queue.append({
            "item_id": item_id,
            "item_type": item_type,
            "item_name": item_name,
            "pending_field": pending_field,
        })

    def pop_next_config_item(self) -> dict | None:
        """Pop the next config item (dict) from the queue, skipping category strings."""
        while self.pending_config_queue:
            entry = self.pending_config_queue.pop(0)
            if isinstance(entry, dict) and "item_id" in entry:
                return entry
            # Skip non-dict entries (category strings from by_pound inquiry)
        return None

    def has_queued_config_items(self) -> bool:
        """Check if there are item config dicts waiting in the queue."""
        return any(isinstance(e, dict) and "item_id" in e for e in self.pending_config_queue)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def is_complete(self) -> bool:
        """Check if the entire order is complete."""
        return (
            self.items.is_complete()
            and self.delivery_method.is_complete()
            and self.checkout.confirmed
        )

    def get_order_summary(self) -> str:
        """Generate human-readable order summary with consolidated identical items."""
        from collections import defaultdict

        # Group items by their summary string to consolidate identical items
        item_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_price": 0.0})
        for item in self.items.get_active_items():
            summary = item.get_summary()
            price = item.unit_price * item.quantity
            item_data[summary]["count"] += 1
            item_data[summary]["total_price"] += price

        if not item_data:
            return "No items in order yet."

        # Build consolidated lines
        lines = []
        for summary, data in item_data.items():
            count = data["count"]
            total_price = data["total_price"]
            if count > 1:
                lines.append(f"- {count}× {summary} — ${total_price:.2f}")
            else:
                lines.append(f"- {summary} — ${total_price:.2f}")

        return "\n".join(lines)

    def get_progress_summary(self) -> dict[str, str]:
        """Get progress summary for each sub-task."""
        def status_emoji(task: BaseTask) -> str:
            if task.status == TaskStatus.COMPLETE:
                return "✅"
            elif task.status == TaskStatus.IN_PROGRESS:
                return "🔄"
            elif task.status == TaskStatus.SKIPPED:
                return "⏭️"
            else:
                return "⏳"

        return {
            "items": f"{status_emoji(self.items)} Items ({len(self.items.get_active_items())})",
            "delivery_method": f"{status_emoji(self.delivery_method)} Delivery Method",
            "customer_info": f"{status_emoji(self.customer_info)} Customer Info",
            "checkout": f"{status_emoji(self.checkout)} Checkout",
            "payment": f"{status_emoji(self.payment)} Payment",
        }
