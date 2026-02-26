"""
Constants for pending_field values used in state machine routing.

These constants replace string literals scattered across handler files,
providing a single source of truth for pending field names.
"""

from enum import Enum


# Sentinel value used when the config_change_handler cannot determine which
# attribute an incoming value belongs to. Checked by config_change_handler
# to trigger special "unknown attribute" resolution logic.
UNKNOWN_ATTRIBUTE_SLUG = "unknown"


class PendingField(str, Enum):
    """Constants for pending_field values used in order state routing."""

    ITEM_SELECTION = "item_selection"
    MODIFIER_SELECTION = "modifier_selection"
    DUPLICATE_SELECTION = "duplicate_selection"
    SAME_THING_CLARIFICATION = "same_thing_clarification"
    CONFIRM_SUGGESTED_ITEM = "confirm_suggested_item"
    CONFIRM_INGREDIENT_SUGGESTION = "confirm_ingredient_suggestion"
    CONFIRM_ITEM_SWITCH = "confirm_item_switch"
    SIDE_CHOICE = "side_choice"
    CUSTOMIZATION_CHECKPOINT = "customization_checkpoint"
    CUSTOMIZATION_SELECTION = "customization_selection"
    MENU_ITEM_CONFIG = "menu_item_config"
    ADDRESS_CONFIRMATION = "address_confirmation"
    CATEGORY_INQUIRY = "category_inquiry"
    ORDER_HISTORY_SELECTION = "order_history_selection"
    REORDER_ITEM_SELECTION = "reorder_item_selection"
    CONFIRM_DIETARY_FOLLOWUP = "confirm_dietary_followup"
    QUANTITY_ADDITION_SELECTION = "quantity_addition_selection"
    AMBIGUOUS_SELECTION = "ambiguous_selection"
    REORDER_OFFER_CONFIRMATION = "reorder_offer_confirmation"
    CONFIRM_DEFAULT_EXTRA = "confirm_default_extra"


# PendingField values that indicate an item configuration is in progress.
# Used by ItemsTask.is_configuring_item() for O(1) membership check.
CONFIGURING_PENDING_FIELDS: frozenset[PendingField] = frozenset({
    PendingField.ITEM_SELECTION,
    PendingField.CATEGORY_INQUIRY,
    PendingField.DUPLICATE_SELECTION,
    PendingField.CONFIRM_SUGGESTED_ITEM,
    PendingField.MODIFIER_SELECTION,
    PendingField.CONFIRM_ITEM_SWITCH,
    PendingField.CONFIRM_INGREDIENT_SUGGESTION,
    PendingField.CONFIRM_DIETARY_FOLLOWUP,
    PendingField.QUANTITY_ADDITION_SELECTION,
    PendingField.CONFIRM_DEFAULT_EXTRA,
})
