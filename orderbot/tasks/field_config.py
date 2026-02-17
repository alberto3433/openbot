"""
Field configuration for task fields.

This module provides field configuration by loading from the database.
Field configs include:
- Required vs optional fields
- Default values (if set, don't ask)
- Whether to ask if empty (for optional fields)
- The question to ask

All configuration is loaded from the item_type_attributes table.
"""

from typing import Any
from pydantic import BaseModel, Field

from .models import FieldConfig
from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError




# =============================================================================
# Order Flow Field Configurations (not item-specific)
# These are used for checkout flow and are not in item_type_attributes table
# =============================================================================

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


def _load_fields_from_db(item_type: str) -> dict[str, FieldConfig]:
    """Load field configurations from database for an item type.

    Returns a dict mapping code field names to FieldConfig objects.

    Raises:
        MenuDataNotLoadedError: If no field configs found in database for this item type
    """
    # Resolve item type alias to canonical database slug (data-driven)
    db_item_type = menu_cache.resolve_item_type_slug(item_type)

    # Get field configs from database (raises if cache not loaded)
    db_configs = menu_cache.get_all_field_configs(db_item_type)
    if not db_configs:
        raise MenuDataNotLoadedError(
            f"No field configurations found in database for item type '{db_item_type}'. "
            f"Check that item_type_attributes table has entries for this item type."
        )

    # Get the field name mapping for this item type (data-driven from DB)
    # This maps code field names (ingredient categories) to attribute slugs
    field_map = menu_cache.get_field_to_slug_map(db_item_type)

    # Create a reverse map: slug -> field_name
    # Note: Multiple field names may map to the same slug, we keep the first one found
    slug_to_field: dict[str, str] = {}
    for field_name, slug in field_map.items():
        if slug not in slug_to_field:
            slug_to_field[slug] = field_name

    result: dict[str, FieldConfig] = {}

    for db_slug, config in db_configs.items():
        # Map database slug to code field name
        field_name = slug_to_field.get(db_slug, db_slug)

        result[field_name] = FieldConfig(
            name=field_name,
            required=config.get("is_required", False),
            default=config.get("default"),
            ask_if_empty=config.get("ask_in_conversation", True),
            question=config.get("question_text"),
        )

    return result


class MenuFieldConfig(BaseModel):
    """
    Menu-based field configuration.

    Field configurations are loaded from the database via menu_data_cache.
    Order flow fields (delivery, address, customer info, payment) use hardcoded defaults.
    """

    # Generic cache for all item type field configs (lazy-loaded)
    _fields_cache: dict[str, dict[str, FieldConfig]] = {}
    delivery_method_fields: dict[str, FieldConfig] = Field(
        default_factory=lambda: _deep_copy_fields(DEFAULT_DELIVERY_METHOD_FIELDS)
    )
    address_fields: dict[str, FieldConfig] = Field(
        default_factory=lambda: _deep_copy_fields(DEFAULT_ADDRESS_FIELDS)
    )
    customer_info_fields: dict[str, FieldConfig] = Field(
        default_factory=lambda: _deep_copy_fields(DEFAULT_CUSTOMER_INFO_FIELDS)
    )
    payment_fields: dict[str, FieldConfig] = Field(
        default_factory=lambda: _deep_copy_fields(DEFAULT_PAYMENT_FIELDS)
    )

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_menu_data(cls, menu_data: dict | None) -> "MenuFieldConfig":
        """Create field config from menu data (overrides not currently supported)."""
        return cls()

    def get_fields_for_item_type(self, item_type: str) -> dict[str, FieldConfig]:
        """Get field configs for a specific item type from database.

        Uses a generic cache for all item types - no hardcoded item type checks.
        """
        if item_type not in self._fields_cache:
            self._fields_cache[item_type] = _load_fields_from_db(item_type)
        return self._fields_cache[item_type]


# =============================================================================
# Helper Functions
# =============================================================================

def _get_db_field_config(item_type: str, field_name: str) -> dict | None:
    """Get field config directly from database.

    This is the preferred method - directly queries the database cache.
    """
    # Resolve item type alias to canonical database slug (data-driven)
    db_item_type = menu_cache.resolve_item_type_slug(item_type)

    # Map field name to database slug (data-driven from DB ingredient categories)
    db_field_slug = menu_cache.resolve_field_to_slug(db_item_type, field_name)

    return menu_cache.get_field_config(db_item_type, db_field_slug)


def get_field_config(
    item_type: str,
    field_name: str,
    menu_config: MenuFieldConfig | None = None,
) -> FieldConfig | None:
    """Get field configuration for a specific field.

    First tries to load from database, falls back to MenuFieldConfig if needed.
    """
    # Try direct database lookup first
    db_config = _get_db_field_config(item_type, field_name)
    if db_config:
        return FieldConfig(
            name=field_name,
            required=db_config.get("required", False),
            default=db_config.get("default"),
            ask_if_empty=db_config.get("ask_if_empty", True),
            question=db_config.get("question"),
        )

    # Fall back to MenuFieldConfig for non-item fields (delivery, address, etc.)
    if menu_config is None:
        menu_config = MenuFieldConfig()

    fields = menu_config.get_fields_for_item_type(item_type)
    return fields.get(field_name)


def get_default_value(
    item_type: str,
    field_name: str,
    menu_config: MenuFieldConfig | None = None,
) -> Any:
    """Get default value for a field from database."""
    # Try direct database lookup
    db_config = _get_db_field_config(item_type, field_name)
    if db_config:
        return db_config.get("default")

    # Fall back to FieldConfig
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
    """Check if we should ask about a field based on database config."""
    # Try direct database lookup
    db_config = _get_db_field_config(item_type, field_name)
    if db_config:
        ask_if_empty = db_config.get("ask_if_empty", True)
        default = db_config.get("default")
        # Should ask if: ask_if_empty is True AND current value is empty/None
        if not ask_if_empty:
            return False
        if current_value is None:
            return True
        if isinstance(current_value, (list, dict)) and len(current_value) == 0:
            return True
        return False

    # Fall back to FieldConfig
    config = get_field_config(item_type, field_name, menu_config)
    if config:
        return config.needs_asking(current_value)
    return False


