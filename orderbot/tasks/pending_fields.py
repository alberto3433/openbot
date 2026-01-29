"""
Constants for pending_field values used in state machine routing.

These constants replace string literals scattered across handler files,
providing a single source of truth for pending field names.
"""


class PendingField:
    """Constants for pending_field values used in order state routing."""

    ITEM_SELECTION = "item_selection"
    MODIFIER_SELECTION = "modifier_selection"
    DUPLICATE_SELECTION = "duplicate_selection"
    SAME_THING_CLARIFICATION = "same_thing_clarification"
    CONFIRM_SUGGESTED_ITEM = "confirm_suggested_item"
    CONFIRM_ITEM_SWITCH = "confirm_item_switch"
    SIDE_CHOICE = "side_choice"
    CUSTOMIZATION_CHECKPOINT = "customization_checkpoint"
    CUSTOMIZATION_SELECTION = "customization_selection"
    MENU_ITEM_CONFIG = "menu_item_config"
    ADDRESS_CONFIRMATION = "address_confirmation"
    CATEGORY_INQUIRY = "category_inquiry"
