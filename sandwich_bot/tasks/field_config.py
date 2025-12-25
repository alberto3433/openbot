"""
Field configuration for task fields.

This module defines how fields are configured per item type,
allowing the menu to specify:
- Required vs optional fields
- Default values (if set, don't ask)
- Whether to ask if empty (for optional fields)
- The question to ask
"""

from typing import Any
from pydantic import BaseModel, Field

from .models import FieldConfig


class ItemTypeConfig(BaseModel):
    """Configuration for a specific item type (bagel, coffee, etc.)."""

    item_type: str
    display_name: str
    fields: dict[str, FieldConfig] = Field(default_factory=dict)


# =============================================================================
# Default Field Configurations
# =============================================================================

DEFAULT_BAGEL_FIELDS: dict[str, FieldConfig] = {
    # Bagel type defaults to "plain bagel" if not specified
    "bagel_type": FieldConfig(
        name="bagel_type",
        required=True,
        default="plain bagel",
        ask_if_empty=False,  # Don't ask - use default
        question="What kind of bagel would you like?",
    ),
    "quantity": FieldConfig(
        name="quantity",
        required=True,
        default=1,
        ask_if_empty=False,
        question=None,
    ),
    # Ask about spread FIRST (before toasted)
    "spread": FieldConfig(
        name="spread",
        required=False,
        default=None,
        ask_if_empty=True,
        question="Would you like cream cheese or butter on that?",
    ),
    # Then ask about toasted
    "toasted": FieldConfig(
        name="toasted",
        required=True,
        default=None,  # Must ask
        ask_if_empty=True,
        question="Would you like that toasted?",
    ),
    "extras": FieldConfig(
        name="extras",
        required=False,
        default=[],
        ask_if_empty=False,  # Don't ask about extras by default
        question="Anything else on it?",
    ),
    "sandwich_protein": FieldConfig(
        name="sandwich_protein",
        required=False,
        default=None,
        ask_if_empty=False,  # Only ask if they indicated sandwich
        question=None,
    ),
}


DEFAULT_COFFEE_FIELDS: dict[str, FieldConfig] = {
    "drink_type": FieldConfig(
        name="drink_type",
        required=True,
        default=None,
        ask_if_empty=True,
        question="What kind of drink would you like - coffee, latte, tea?",
    ),
    "size": FieldConfig(
        name="size",
        required=True,
        default="medium",  # Default to medium, don't ask
        ask_if_empty=False,
        question="What size - small, medium, or large?",
    ),
    "iced": FieldConfig(
        name="iced",
        required=True,
        default=None,  # Must ask
        ask_if_empty=True,
        question="Hot or iced?",
    ),
    "milk": FieldConfig(
        name="milk",
        required=False,
        default=None,
        ask_if_empty=False,  # Only capture if mentioned
        question="What kind of milk?",
    ),
    "sweetener": FieldConfig(
        name="sweetener",
        required=False,
        default=None,
        ask_if_empty=False,  # Only capture if mentioned
        question="Any sweetener?",
    ),
    "extra_shots": FieldConfig(
        name="extra_shots",
        required=False,
        default=0,
        ask_if_empty=False,
        question=None,
    ),
}


DEFAULT_DELIVERY_METHOD_FIELDS: dict[str, FieldConfig] = {
    "order_type": FieldConfig(
        name="order_type",
        required=True,
        default=None,
        ask_if_empty=True,
        question="Is this for pickup or delivery?",
    ),
}


DEFAULT_ADDRESS_FIELDS: dict[str, FieldConfig] = {
    "street": FieldConfig(
        name="street",
        required=True,
        default=None,
        ask_if_empty=True,
        question="What's your delivery address?",
    ),
    "city": FieldConfig(
        name="city",
        required=False,
        default=None,
        ask_if_empty=True,
        question="What city?",
    ),
    "zip_code": FieldConfig(
        name="zip_code",
        required=True,
        default=None,
        ask_if_empty=True,
        question="And the zip code?",
    ),
    "apt_unit": FieldConfig(
        name="apt_unit",
        required=False,
        default=None,
        ask_if_empty=False,  # Only capture if mentioned
        question="Any apartment or unit number?",
    ),
}


DEFAULT_CUSTOMER_INFO_FIELDS: dict[str, FieldConfig] = {
    "name": FieldConfig(
        name="name",
        required=True,
        default=None,
        ask_if_empty=True,
        question="Can I get a name for the order?",
    ),
    "email": FieldConfig(
        name="email",
        required=False,
        default=None,
        ask_if_empty=False,
        question=None,
    ),
    "phone": FieldConfig(
        name="phone",
        required=False,
        default=None,
        ask_if_empty=False,
        question=None,
    ),
}


DEFAULT_PAYMENT_FIELDS: dict[str, FieldConfig] = {
    "method": FieldConfig(
        name="method",
        required=True,
        default=None,
        ask_if_empty=True,
        question="Would you like to pay in store, or should I send you a payment link?",
    ),
}


# =============================================================================
# Menu Field Configuration
# =============================================================================

def _deep_copy_fields(fields: dict[str, FieldConfig]) -> dict[str, FieldConfig]:
    """Deep copy a field config dict to prevent mutation of defaults."""
    return {name: config.model_copy() for name, config in fields.items()}


class MenuFieldConfig(BaseModel):
    """
    Menu-based field configuration.

    This is loaded from the menu data and allows customization
    of field requirements and defaults per store/menu.
    """

    bagel_fields: dict[str, FieldConfig] = Field(default_factory=lambda: _deep_copy_fields(DEFAULT_BAGEL_FIELDS))
    coffee_fields: dict[str, FieldConfig] = Field(default_factory=lambda: _deep_copy_fields(DEFAULT_COFFEE_FIELDS))
    delivery_method_fields: dict[str, FieldConfig] = Field(default_factory=lambda: _deep_copy_fields(DEFAULT_DELIVERY_METHOD_FIELDS))
    address_fields: dict[str, FieldConfig] = Field(default_factory=lambda: _deep_copy_fields(DEFAULT_ADDRESS_FIELDS))
    customer_info_fields: dict[str, FieldConfig] = Field(default_factory=lambda: _deep_copy_fields(DEFAULT_CUSTOMER_INFO_FIELDS))
    payment_fields: dict[str, FieldConfig] = Field(default_factory=lambda: _deep_copy_fields(DEFAULT_PAYMENT_FIELDS))

    @classmethod
    def from_menu_data(cls, menu_data: dict | None) -> "MenuFieldConfig":
        """
        Create field config from menu data.

        Menu data can override defaults like:
        {
            "field_config": {
                "bagel": {
                    "toasted": {"default": False, "ask_if_empty": False},
                    "spread": {"ask_if_empty": False}
                },
                "coffee": {
                    "size": {"default": "large", "ask_if_empty": True, "question": "What size?"}
                }
            }
        }
        """
        config = cls()

        if not menu_data:
            return config

        field_overrides = menu_data.get("field_config", {})

        # Apply bagel overrides
        if "bagel" in field_overrides:
            config._apply_overrides(config.bagel_fields, field_overrides["bagel"])

        # Apply coffee overrides
        if "coffee" in field_overrides:
            config._apply_overrides(config.coffee_fields, field_overrides["coffee"])

        # Apply delivery method overrides
        if "delivery_method" in field_overrides:
            config._apply_overrides(config.delivery_method_fields, field_overrides["delivery_method"])

        # Apply address overrides
        if "address" in field_overrides:
            config._apply_overrides(config.address_fields, field_overrides["address"])

        # Apply customer info overrides
        if "customer_info" in field_overrides:
            config._apply_overrides(config.customer_info_fields, field_overrides["customer_info"])

        # Apply payment overrides
        if "payment" in field_overrides:
            config._apply_overrides(config.payment_fields, field_overrides["payment"])

        return config

    def _apply_overrides(
        self,
        fields: dict[str, FieldConfig],
        overrides: dict[str, dict],
    ) -> None:
        """Apply overrides to a field configuration dict."""
        for field_name, override_values in overrides.items():
            if field_name in fields:
                # Update existing field config
                for key, value in override_values.items():
                    if hasattr(fields[field_name], key):
                        setattr(fields[field_name], key, value)
            else:
                # Create new field config
                fields[field_name] = FieldConfig(name=field_name, **override_values)

    def get_fields_for_item_type(self, item_type: str) -> dict[str, FieldConfig]:
        """Get field configs for a specific item type."""
        if item_type == "bagel":
            return self.bagel_fields
        elif item_type == "coffee":
            return self.coffee_fields
        else:
            return {}


# =============================================================================
# Helper Functions
# =============================================================================

def get_field_config(
    item_type: str,
    field_name: str,
    menu_config: MenuFieldConfig | None = None,
) -> FieldConfig | None:
    """Get field configuration for a specific field."""
    if menu_config is None:
        menu_config = MenuFieldConfig()

    fields = menu_config.get_fields_for_item_type(item_type)
    return fields.get(field_name)


def get_default_value(
    item_type: str,
    field_name: str,
    menu_config: MenuFieldConfig | None = None,
) -> Any:
    """Get default value for a field."""
    config = get_field_config(item_type, field_name, menu_config)
    if config:
        return config.default
    return None


def should_ask_field(
    item_type: str,
    field_name: str,
    current_value: Any,
    menu_config: MenuFieldConfig | None = None,
) -> bool:
    """Check if we should ask about a field."""
    config = get_field_config(item_type, field_name, menu_config)
    if config:
        return config.needs_asking(current_value)
    return False


def get_field_question(
    item_type: str,
    field_name: str,
    menu_config: MenuFieldConfig | None = None,
) -> str | None:
    """Get the question to ask for a field."""
    config = get_field_config(item_type, field_name, menu_config)
    if config:
        return config.question
    return None
