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
