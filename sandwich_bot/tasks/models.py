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


class BagelItemTask(ItemTask):
    """Task for capturing a bagel order."""

    item_type: Literal["bagel"] = "bagel"

    # Bagel-specific fields
    bagel_type: str | None = None  # plain, everything, sesame, etc.
    bagel_type_upcharge: float = 0.0  # Upcharge for specialty bagels (e.g., gluten free +$0.80)
    toasted: bool | None = None
    scooped: bool | None = None  # True if bagel should be scooped out
    spread: str | None = None  # cream cheese, butter, etc.
    spread_type: str | None = None  # plain, scallion, veggie, etc.
    extras: list[str] = Field(default_factory=list)
    sandwich_protein: str | None = None  # egg, bacon, lox, etc.
    needs_cheese_clarification: bool = False  # True if user said "cheese" without type

    def get_display_name(self) -> str:
        """Get display name for this bagel."""
        if self.bagel_type:
            return f"{self.bagel_type} bagel"
        return "bagel"

    def get_summary(self) -> str:
        """Get a summary description of this bagel."""
        parts = []

        if self.quantity > 1:
            parts.append(f"{self.quantity}x")

        if self.bagel_type:
            parts.append(f"{self.bagel_type} bagel")
        else:
            parts.append("bagel")

        if self.toasted:
            parts.append("toasted")

        # Build the "with X" part - combine spread, protein, and extras
        with_parts = []

        # Add spread if it's not "none"
        if self.spread and self.spread.lower() != "none":
            spread_desc = self.spread
            if self.spread_type and self.spread_type != "plain":
                spread_desc = f"{self.spread_type} {self.spread}"
            with_parts.append(spread_desc)

        # Add protein
        if self.sandwich_protein:
            with_parts.append(self.sandwich_protein)

        # Add extras
        if self.extras:
            with_parts.extend(self.extras)

        # Format the with clause
        if with_parts:
            parts.append(f"with {', '.join(with_parts)}")
        elif self.spread and self.spread.lower() == "none":
            # Only say "with nothing on it" if there's truly nothing
            parts.append("with nothing on it")

        # Add special instructions if present
        if self.special_instructions:
            parts.append(f"(Special Instructions: {self.special_instructions})")

        return " ".join(parts)


class CoffeeItemTask(ItemTask):
    """Task for capturing a coffee/drink order.

    Note: This class is being deprecated in favor of MenuItemTask with
    menu_item_type="sized_beverage". The is_sized_beverage attribute is
    added for backward compatibility with code that checks this property.
    """

    item_type: Literal["coffee"] = "coffee"

    # Backward compatibility: new code checks is_sized_beverage on MenuItemTask,
    # but tests may still create CoffeeItemTask directly
    is_sized_beverage: bool = True

    # Coffee-specific fields
    drink_type: str | None = None  # drip, latte, espresso, etc.
    size: str | None = None  # small, medium, large
    iced: bool | None = None  # True=iced, False=hot, None=not specified
    decaf: bool | None = None  # True=decaf, None=regular (not specified)
    milk: str | None = None  # whole, skim, oat, almond, etc.
    cream_level: str | None = None  # dark, light, regular - refers to amount of cream/milk
    # Sweeteners - list of {"type": str, "quantity": int} e.g., [{"type": "sugar", "quantity": 2}]
    sweeteners: list[dict] = Field(default_factory=list)
    # Flavor syrups - list of {"flavor": str, "quantity": int} e.g., [{"flavor": "vanilla", "quantity": 1}]
    flavor_syrups: list[dict] = Field(default_factory=list)
    wants_syrup: bool = False  # True if user said "with syrup" without specifying flavor
    pending_syrup_quantity: int = 1  # Quantity from "2 syrups" before flavor is specified
    extra_shots: int = 0

    # Upcharge tracking (set by recalculate_coffee_price)
    size_upcharge: float = 0.0
    milk_upcharge: float = 0.0
    syrup_upcharge: float = 0.0  # Total upcharge for all syrups
    extra_shots_upcharge: float = 0.0  # Upcharge for double/triple espresso
    iced_upcharge: float = 0.0

    @property
    def is_espresso(self) -> bool:
        """Check if this is an espresso drink (no size, always hot)."""
        if not self.drink_type:
            return False
        return self.drink_type.lower() == "espresso"

    def get_display_name(self) -> str:
        """Get display name for this drink."""
        parts = []
        if self.size:
            parts.append(self.size)
        # Don't show hot/iced for espresso (always hot)
        if not self.is_espresso:
            if self.iced is True:
                parts.append("iced")
            elif self.iced is False:
                parts.append("hot")
        if self.decaf is True:
            parts.append("decaf")
        # Show double/triple for espresso drinks
        if self.extra_shots == 1:
            parts.append("double")
        elif self.extra_shots >= 2:
            parts.append("triple")
        if self.drink_type:
            parts.append(self.drink_type)
        else:
            parts.append("coffee")
        return " ".join(parts)

    def get_summary(self) -> str:
        """Get a summary description of this drink for bot responses.

        Note: Upcharges are tracked internally but not displayed in responses
        to sound more natural when read aloud.
        """
        parts = []

        if self.size:
            parts.append(self.size)

        # Don't show hot/iced for espresso (always hot)
        if not self.is_espresso:
            if self.iced is True:
                parts.append("iced")
            elif self.iced is False:
                parts.append("hot")

        if self.decaf is True:
            parts.append("decaf")

        # Show double/triple for espresso drinks
        if self.extra_shots == 1:
            parts.append("double")
        elif self.extra_shots >= 2:
            parts.append("triple")

        if self.drink_type:
            parts.append(self.drink_type)
        else:
            parts.append("coffee")

        # Add flavor syrups
        if self.flavor_syrups:
            syrup_parts = []
            for syrup in self.flavor_syrups:
                flavor = syrup.get("flavor", "")
                qty = syrup.get("quantity", 1)
                qty_prefix = f"{qty} " if qty > 1 else ""
                syrup_parts.append(f"{qty_prefix}{flavor} syrup")
            syrup_str = " and ".join(syrup_parts)
            parts.append(f"with {syrup_str}")

        if self.milk:
            # "none" or "black" means no milk - show as "black" for clarity
            if self.milk.lower() in ("none", "black"):
                parts.append("black")
            else:
                parts.append(f"with {self.milk} milk")

        # Add sweeteners with quantities
        if self.sweeteners:
            sweetener_parts = []
            for sweetener in self.sweeteners:
                s_type = sweetener.get("type", "")
                qty = sweetener.get("quantity", 1)
                if qty > 1:
                    sweetener_parts.append(f"{qty} {s_type}s")
                else:
                    sweetener_parts.append(s_type)
            parts.append(f"with {' and '.join(sweetener_parts)}")

        # Add special instructions if present
        if self.special_instructions:
            parts.append(f"(Special Instructions: {self.special_instructions})")

        return " ".join(parts)

    def get_spoken_summary(self) -> str:
        """Get a natural-sounding summary for bot responses.

        Uses special instructions phrase when it describes a modifier,
        e.g., 'with a splash of milk' instead of 'with whole milk'.

        Note: Upcharges are tracked internally but not displayed in responses
        to sound more natural when read aloud.
        """
        parts = []

        # Size (upcharges tracked internally, not displayed)
        if self.size:
            parts.append(self.size)

        # Hot/iced (skip for espresso, always hot)
        if not self.is_espresso:
            if self.iced is True:
                parts.append("iced")
            elif self.iced is False:
                parts.append("hot")

        # Show double/triple for espresso drinks
        if self.extra_shots == 1:
            parts.append("double")
        elif self.extra_shots >= 2:
            parts.append("triple")

        # Drink type
        if self.drink_type:
            parts.append(self.drink_type)
        else:
            parts.append("coffee")

        # Add flavor syrups (upcharges tracked internally, not displayed)
        if self.flavor_syrups:
            syrup_parts = []
            for syrup in self.flavor_syrups:
                flavor = syrup.get("flavor", "")
                qty = syrup.get("quantity", 1)
                qty_prefix = f"{qty} " if qty > 1 else ""
                syrup_parts.append(f"{qty_prefix}{flavor} syrup")
            syrup_str = " and ".join(syrup_parts)
            parts.append(f"with {syrup_str}")

        # Check if special instructions describe milk (e.g., "a splash of milk", "light cream")
        special_describes_milk = False
        special_used_for_milk = False
        if self.special_instructions:
            special_lower = self.special_instructions.lower()
            # Check for "milk" keyword or if the milk type is mentioned in special instructions
            if "milk" in special_lower or "cream" in special_lower:
                special_describes_milk = True
            # Also check if milk type itself is in special instructions (e.g., "light oat")
            if self.milk and self.milk.lower() in special_lower:
                special_describes_milk = True

        if self.milk:
            if self.milk.lower() in ("none", "black"):
                parts.append("black")
            elif special_describes_milk:
                # Use natural phrase from special_instructions instead of formal milk type
                parts.append(f"with {self.special_instructions}")
                special_used_for_milk = True
            else:
                parts.append(f"with {self.milk} milk")
        elif special_describes_milk:
            # Milk mentioned in special instructions but not set as a type
            parts.append(f"with {self.special_instructions}")
            special_used_for_milk = True

        # Check if special instructions describe sweetener
        special_describes_sweetener = False
        special_used_for_sweetener = False
        if self.special_instructions:
            sweetener_words = ["sugar", "sweet", "splenda", "stevia", "honey"]
            if any(word in self.special_instructions.lower() for word in sweetener_words):
                special_describes_sweetener = True

        # Add sweeteners or use special instructions if they describe sweetener
        if self.sweeteners and not special_describes_sweetener:
            sweetener_parts = []
            for sweetener in self.sweeteners:
                s_type = sweetener.get("type", "")
                qty = sweetener.get("quantity", 1)
                if qty > 1:
                    sweetener_parts.append(f"{qty} {s_type}s")
                else:
                    sweetener_parts.append(s_type)
            parts.append(f"with {' and '.join(sweetener_parts)}")
        elif special_describes_sweetener and not special_used_for_milk:
            # Use special instructions for sweetener (e.g., "a little sugar")
            parts.append(f"with {self.special_instructions}")
            special_used_for_sweetener = True

        # Only show special instructions if not already used for milk/sweetener description
        if self.special_instructions and not special_used_for_milk and not special_used_for_sweetener:
            parts.append(f"({self.special_instructions})")

        return " ".join(parts)


class MenuItemTask(ItemTask):
    """Task for a menu item ordered by name (e.g., 'The Chipotle Egg Omelette')."""

    item_type: Literal["menu_item"] = "menu_item"

    # Menu item fields
    menu_item_name: str  # The name of the menu item
    menu_item_id: int | None = None  # Database ID if matched
    menu_item_type: str | None = None  # Type slug (e.g., "omelette", "sandwich")
    modifications: list[str] = Field(default_factory=list)  # User modifications
    removed_ingredients: list[str] = Field(default_factory=list)  # Default ingredients that were removed

    # Customization fields for configurable items (e.g., omelettes, sandwiches)
    side_choice: str | None = None  # "bagel" or "fruit_salad" for omelettes
    bagel_choice: str | None = None  # Which bagel if side is bagel, or bagel for sandwiches
    bagel_choice_upcharge: float = 0.0  # Upcharge for specialty bagel choice (e.g., gluten free +$0.80)
    toasted: bool | None = None  # Whether sandwich/bagel should be toasted
    spread: str | None = None  # Spread for side bagel (butter, cream cheese, etc.)
    spread_price: float | None = None  # Price of spread for itemized display
    requires_side_choice: bool = False  # Whether this item needs side selection
    is_signature: bool = False  # Whether this is a signature/featured menu item

    # Dynamic attribute values from DB-driven configuration
    # Stores answers for attributes defined in item_type_attributes table
    # e.g., {"bread": "plain", "add_egg": "scrambled_egg", "scooped": True}
    attribute_values: dict[str, Any] = Field(default_factory=dict)

    # Track if customization checkpoint has been offered
    customization_offered: bool = False

    # -------------------------------------------------------------------------
    # Beverage helper properties (for sized_beverage items like coffee)
    # These provide a CoffeeItemTask-compatible interface using attribute_values
    # -------------------------------------------------------------------------

    @property
    def drink_type(self) -> str | None:
        """Get drink type (alias for menu_item_name for beverages)."""
        return self.menu_item_name if self.menu_item_type == "sized_beverage" else None

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
    def iced(self) -> bool | None:
        """Get iced flag from attribute_values."""
        return self.attribute_values.get("iced")

    @iced.setter
    def iced(self, value: bool | None) -> None:
        """Set iced flag in attribute_values."""
        if value is not None:
            self.attribute_values["iced"] = value
        elif "iced" in self.attribute_values:
            del self.attribute_values["iced"]

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
    def milk(self) -> str | None:
        """Get milk type from attribute_values."""
        return self.attribute_values.get("milk")

    @milk.setter
    def milk(self, value: str | None) -> None:
        """Set milk type in attribute_values."""
        if value is not None:
            self.attribute_values["milk"] = value
        elif "milk" in self.attribute_values:
            del self.attribute_values["milk"]

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
        """Get sweeteners list from attribute_values.

        Creates the list if it doesn't exist, so .append() works correctly.
        """
        if "sweetener_selections" not in self.attribute_values:
            self.attribute_values["sweetener_selections"] = []
        return self.attribute_values["sweetener_selections"]

    @sweeteners.setter
    def sweeteners(self, value: list[dict]) -> None:
        """Set sweeteners list in attribute_values."""
        self.attribute_values["sweetener_selections"] = value or []

    @property
    def flavor_syrups(self) -> list[dict]:
        """Get flavor syrups list from attribute_values.

        Creates the list if it doesn't exist, so .append() works correctly.
        """
        if "syrup_selections" not in self.attribute_values:
            self.attribute_values["syrup_selections"] = []
        return self.attribute_values["syrup_selections"]

    @flavor_syrups.setter
    def flavor_syrups(self, value: list[dict]) -> None:
        """Set flavor syrups list in attribute_values."""
        self.attribute_values["syrup_selections"] = value or []

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
        """Set milk upcharge in attribute_values."""
        self.attribute_values["milk_upcharge"] = value

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
        """Check if this is an espresso drink (no size, always hot)."""
        if self.menu_item_type == "espresso":
            return True
        if self.menu_item_type == "sized_beverage":
            drink_type = self.menu_item_name.lower() if self.menu_item_name else ""
            return drink_type == "espresso"
        return False

    @property
    def is_sized_beverage(self) -> bool:
        """Check if this is a sized beverage (coffee, latte, etc.)."""
        return self.menu_item_type == "sized_beverage"

    def get_display_name(self) -> str:
        """Get display name for this menu item."""
        # Handle espresso display name (shots and decaf info)
        if self.menu_item_type == "espresso":
            shots_slug = self.attribute_values.get("shots", "single_shot")
            decaf = self.attribute_values.get("decaf", False)

            shots_display_map = {
                "single_shot": "",
                "double_shot_espresso": "Double ",
                "triple_shot_espresso": "Triple ",
                "quad_shot": "Quad ",
            }
            shots_prefix = shots_display_map.get(shots_slug, "")
            display_name = f"{shots_prefix}Espresso"
            if decaf:
                display_name = f"Decaf {display_name}"
            return display_name

        # Handle sized_beverage display name (coffee, latte, etc.)
        if self.menu_item_type == "sized_beverage":
            parts = []
            if self.size:
                parts.append(self.size)
            if self.iced is True:
                parts.append("iced")
            elif self.iced is False:
                parts.append("hot")
            if self.decaf:
                parts.append("decaf")
            if self.extra_shots == 1:
                parts.append("double")
            elif self.extra_shots >= 2:
                parts.append("triple")
            parts.append(self.menu_item_name or "coffee")
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
                # Convert slug to display name (e.g., "plain_bagel" -> "Plain Bagel")
                bread_display = bread.replace("_", " ").title()
                parts.append(f"on {bread_display}")

            # Handle toasted
            toasted = self.attribute_values.get("toasted")
            if toasted is True:
                parts.append("toasted")
            elif toasted is False and bread:
                parts.append("not toasted")

            # Handle other customizations (extra protein, toppings, etc.)
            extra_customizations = []
            for key, value in self.attribute_values.items():
                # Skip already handled fields and internal data fields
                if key in ("bread", "toasted", "scooped"):
                    continue  # Already handled above
                if key.endswith("_price") or key.endswith("_selections"):
                    continue  # Internal price/selection data, not for display
                # Skip espresso-specific fields that are in the display name
                if self.menu_item_type == "espresso" and key in ("shots", "decaf"):
                    continue  # Already handled in get_display_name()
                if value is True:
                    extra_customizations.append(key.replace("_", " ").title())
                elif value and value is not False:
                    # Handle list values (multi-select attributes like extra proteins)
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                display_value = item.replace("_", " ").title()
                                extra_customizations.append(display_value)
                            # Skip dict items (they're selection metadata)
                    else:
                        # Convert slug to display name
                        display_value = str(value).replace("_", " ").title()
                        extra_customizations.append(display_value)
            if extra_customizations:
                parts.append(f"with {', '.join(extra_customizations)}")

        # Add side choice info for omelettes
        elif self.side_choice == "bagel" and self.bagel_choice:
            bagel_parts = [self.bagel_choice, "bagel"]
            if self.toasted:
                bagel_parts.append("toasted")
            if self.spread:
                bagel_parts.append(f"with {self.spread}")
            parts.append(f"with {' '.join(bagel_parts)}")
        elif self.side_choice == "fruit_salad":
            parts.append("with fruit salad")

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
        """Get list of missing required customizations."""
        missing = []
        if self.requires_side_choice and not self.side_choice:
            missing.append("side_choice")
        if self.side_choice == "bagel" and not self.bagel_choice:
            missing.append("bagel_choice")
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

    # Multiple matching menu items for disambiguation
    # Used when user says "orange juice" and there are 3 types
    # Each entry is a dict with: name, base_price, id, etc.
    pending_drink_options: list[dict] = Field(default_factory=list)

    # Coffee modifiers stored during drink disambiguation
    # When user says "large iced oat milk latte" and we ask "Latte or Seasonal Matcha Latte?",
    # we store the modifiers here so they can be applied when user clarifies the drink type
    pending_coffee_modifiers: dict = Field(default_factory=dict)

    # Unknown drink request - stores the drink name user asked for that doesn't exist
    # Used to show "Sorry, we don't have X" message
    unknown_drink_request: str | None = Field(default=None)

    # Generic menu item options for disambiguation (cookies, muffins, etc.)
    # Used when user says "cookies" and there are multiple cookie types
    pending_item_options: list[dict] = Field(default_factory=list)

    # Quantity stored during item disambiguation
    pending_item_quantity: int = Field(default=1)

    # Spread type options for disambiguation (e.g., "walnut" matches multiple types)
    # Used when user says "walnut cream cheese" and there are honey walnut, maple raisin walnut
    # Each entry is a spread type string like "honey walnut"
    pending_spread_options: list[str] = Field(default_factory=list)

    # Pending modifier change clarification
    # Used when user says "change it to blueberry" and we need to clarify bagel vs spread
    # Dict with: new_value, possible_categories (as strings), item_id
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

    # Transient error storage for _add_parsed_item -> _process_multi_item_order communication
    # This is a transient field that should not be serialized
    last_add_error: Any | None = Field(default=None, exclude=True)

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
        self.pending_coffee_modifiers = {}

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
            pending_field: The field to configure (toasted, bagel_type, etc.)
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
