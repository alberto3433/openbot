"""
Modifier Change Handler.

This module handles user requests to change modifiers on ordered items,
such as "change it to blueberry cream cheese" or "make the bagel salt instead".

It detects change requests, determines if clarification is needed for ambiguous
modifiers, and applies changes once resolved.

The handler is data-driven - it uses attribute slugs from the database rather
than hardcoded food-specific categories. Value normalization uses database-defined
option aliases via menu_cache.resolve_option_by_alias().
"""

import logging
import re
from dataclasses import dataclass

from .models import MenuItemTask
from .normalization import (
    resolve_to_canonical,
    get_attribute_display_name as _get_attr_display_name_from_db,
)
from .parsers.constants import CHANGE_REQUEST_PATTERNS
from .parsers.quantity_utils import BASIC_WORD_TO_NUM
from .utils.text import format_english_list
from orderbot.menu_data_cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError

logger = logging.getLogger(__name__)


@dataclass
class ChangeRequest:
    """Represents a parsed change request from user input."""
    target: str | None  # What to change (e.g., "bagel", "spread") or None for "it"
    new_value: str  # The new value (e.g., "blueberry", "salt")
    is_ambiguous: bool  # Whether clarification is needed
    possible_attributes: list[str]  # What attribute slugs this could be


@dataclass
class ChangeResult:
    """Result of attempting to apply a modifier change."""
    success: bool
    message: str
    needs_clarification: bool = False
    clarification_options: list[str] | None = None
    applied_attribute: str | None = None


class ModifierChangeHandler:
    """
    Handles modifier change requests for order items.

    Detects when users want to change modifiers (bagel type, spread, etc.),
    determines if clarification is needed for ambiguous requests, and
    applies changes to the appropriate items.

    This handler is data-driven - it uses menu_cache to determine valid
    modifiers and their categories rather than hardcoding food-specific logic.
    """

    def __init__(
        self,
        config: "HandlerConfig",
    ):
        """Initialize the modifier change handler.

        Args:
            config: HandlerConfig with shared dependencies.
        """
        self.pricing = config.pricing

        # Cache data-driven lookups
        self._target_attr_map: dict[str, str] | None = None

    def _get_target_attr_map(self) -> dict[str, str]:
        """Get mapping from target words to attribute slugs.

        Built dynamically from:
        1. Attribute display names from the database
        2. Attribute slugs (with underscores replaced by spaces)
        3. Global attribute aliases from the database

        No hardcoded mappings - all data comes from the database.
        """
        if self._target_attr_map is None:
            # Build mapping from attribute display names and slugs
            self._target_attr_map = {}

            # Get all item type slugs and their attributes
            try:
                for item_type_slug in menu_cache.get_all_item_type_slugs():
                    try:
                        attrs = menu_cache.get_item_type_attributes(item_type_slug)
                        for attr_slug, attr_info in attrs.items():
                            # Map display name to attribute slug
                            display_name = attr_info.get("display_name", "").lower()
                            if display_name:
                                self._target_attr_map[display_name] = attr_slug
                            # Also map slug itself (replace underscores with spaces)
                            self._target_attr_map[attr_slug.replace("_", " ")] = attr_slug
                    except MenuDataNotLoadedError:
                        logger.debug("Menu cache not loaded when getting attributes for %s", item_type_slug)
                        continue
            except MenuDataNotLoadedError:
                logger.warning("Menu cache not loaded when building target attribute map")

            # Add global attribute aliases from the database
            # (e.g., "cream cheese" -> "spread")
            try:
                db_aliases = menu_cache.get_all_global_attribute_aliases()
                self._target_attr_map.update(db_aliases)
            except MenuDataNotLoadedError:
                logger.debug("Menu cache not loaded when getting global attribute aliases")

        return self._target_attr_map

    def detect_change_request(self, user_input: str) -> ChangeRequest | None:
        """
        Detect if user input is a change request.

        Args:
            user_input: The user's message

        Returns:
            ChangeRequest if detected, None otherwise
        """
        user_input_lower = user_input.lower().strip()

        for pattern, group_indices in CHANGE_REQUEST_PATTERNS:
            match = pattern.search(user_input_lower)
            if match:
                target_group, value_group = group_indices

                # Extract target (if present) and new value
                target = match.group(target_group).strip() if target_group else None
                new_value = match.group(value_group).strip()

                logger.debug(
                    "Change request detected: target=%s, new_value=%s",
                    target, new_value
                )

                # Analyze the new value to determine possible attribute slugs
                is_ambiguous, possible_attributes = self._analyze_modifier(
                    new_value, target
                )

                return ChangeRequest(
                    target=target,
                    new_value=new_value,
                    is_ambiguous=is_ambiguous,
                    possible_attributes=possible_attributes,
                )

        return None

    def _analyze_modifier(
        self, new_value: str, target: str | None
    ) -> tuple[bool, list[str]]:
        """
        Analyze a modifier value to determine possible attribute slugs.

        Uses data-driven lookups from menu_cache to determine which
        attribute(s) a modifier value could apply to. This is fully generic -
        it queries all ingredient categories to find matches rather than
        checking hardcoded category names.

        Args:
            new_value: The new value being requested
            target: Optional explicit target (e.g., "bagel", "spread")

        Returns:
            Tuple of (is_ambiguous, list of possible attribute slugs)
        """
        new_value_lower = new_value.lower().strip()
        target_attr_map = self._get_target_attr_map()

        # If target is explicitly specified, use that attribute
        if target:
            target_lower = target.lower()
            if target_lower in target_attr_map:
                return False, [target_attr_map[target_lower]]

        # Check for known attribute options using menu_cache (handles size, temperature, etc.)
        is_attr_option, attr_slug = menu_cache.is_known_attribute_option(new_value_lower)
        if is_attr_option and attr_slug:
            return False, [attr_slug]

        # Find ALL ingredient categories this value matches (data-driven)
        try:
            matching_categories = menu_cache.find_all_categories_for_ingredient(new_value_lower)

            if len(matching_categories) == 1:
                # Unambiguous - maps to exactly one category
                attr_slug = menu_cache.get_category_attribute_slug(matching_categories[0])
                return False, [attr_slug]
            elif len(matching_categories) > 1:
                # Ambiguous - maps to multiple categories, needs clarification
                attr_slugs = [
                    menu_cache.get_category_attribute_slug(cat)
                    for cat in matching_categories
                ]
                # Dedupe while preserving order
                seen = set()
                unique_slugs = []
                for slug in attr_slugs:
                    if slug not in seen:
                        seen.add(slug)
                        unique_slugs.append(slug)
                return True, unique_slugs
        except Exception:
            # Attribute option check failed - fall through to try alternate parsing
            pass

        # Try stripping quantity prefix and re-analyzing
        # e.g., "2 vanilla syrups" -> "vanilla syrups" -> "vanilla syrup"
        stripped_value = self._strip_quantity_prefix(new_value_lower)
        if stripped_value != new_value_lower:
            # Recurse with stripped value
            is_ambiguous, attrs = self._analyze_modifier(stripped_value, target)
            if attrs and attrs[0] != "unknown":
                return is_ambiguous, attrs

        # Unknown modifier
        return False, ["unknown"]

    def _strip_quantity_prefix(self, value: str) -> str:
        """Strip quantity prefixes like '2 ', 'two ', 'double ' from value.

        Also handles pluralization (e.g., "syrups" -> "syrup").

        Args:
            value: The value to strip quantity from

        Returns:
            Value with quantity prefix stripped, or original if no prefix found
        """
        original = value

        # Strip numeric prefix: "2 vanilla syrups" -> "vanilla syrups"
        value = re.sub(r"^\d+\s+", "", value)

        # Strip word prefix: "two vanilla syrups" -> "vanilla syrups"
        quantity_words = [
            "one", "two", "three", "four", "five", "six",
            "seven", "eight", "nine", "ten",
            "double", "triple", "quad", "quadruple",
        ]
        for word in quantity_words:
            if value.startswith(word + " "):
                value = value[len(word) + 1:]
                break

        # Strip trailing 's' for plural: "vanilla syrups" -> "vanilla syrup"
        if value.endswith("s") and not value.endswith("ss"):
            singular = value[:-1]
            # Verify the singular form is recognized as an ingredient
            try:
                if menu_cache.find_all_categories_for_ingredient(singular):
                    return singular
            except Exception:
                # Cache lookup failed - continue without verification
                pass

        # Return stripped value (even if we couldn't verify singular)
        if value != original:
            return value

        return original

    def generate_clarification_message(
        self, change_request: ChangeRequest
    ) -> str:
        """
        Generate a clarification message for ambiguous change requests.

        Uses data-driven attribute display names from the database.

        Args:
            change_request: The ambiguous change request

        Returns:
            Message asking user to clarify what they want to change
        """
        new_value = change_request.new_value

        # Build options using data-driven attribute display names
        options = []
        for attr_slug in change_request.possible_attributes:
            display_name = self._get_attr_display_name(attr_slug)
            options.append(f"{new_value} {display_name}")

        if len(options) == 2:
            return (
                f"Just to clarify - would you like {options[0]} "
                f"or {options[1]}?"
            )
        elif len(options) == 1:
            return f"Just to confirm - you'd like {options[0]}?"
        else:
            return (
                f"I'm not sure what you'd like to change to '{new_value}'. "
                f"Could you please clarify?"
            )

    def _extract_quantity_from_value(self, value: str) -> tuple[int, str]:
        """Extract quantity prefix from a value.

        Args:
            value: The raw value string (e.g., "2 vanilla syrups")

        Returns:
            Tuple of (quantity, stripped_value)
        """
        value = value.strip()
        quantity = 1

        # Check for numeric prefix: "2 vanilla syrups"
        match = re.match(r"^(\d+)\s+(.+)$", value)
        if match:
            quantity = int(match.group(1))
            value = match.group(2)
        else:
            # Check for word prefix
            quantity_map = BASIC_WORD_TO_NUM
            for word, qty in quantity_map.items():
                if value.startswith(word + " "):
                    quantity = qty
                    value = value[len(word) + 1:]
                    break

        return quantity, value

    def apply_change(
        self,
        order,
        item_id: str | None,
        attr_slug: str,
        new_value: str,
    ) -> ChangeResult:
        """
        Apply a modifier change to an item.

        This method uses a data-driven approach where attribute handling is
        determined by the ATTR_NORMALIZERS registry and item capabilities
        queried from the database.

        Args:
            order: The order to modify
            item_id: The ID of the item to modify (None for last item)
            attr_slug: The attribute slug to change (e.g., "bread", "size")
            new_value: The new value to set

        Returns:
            ChangeResult indicating success/failure and any message
        """
        # Find the target item
        active_items = order.items.get_active_items()
        if item_id is None:
            # Use the last item
            if not active_items:
                return ChangeResult(
                    success=False,
                    message="I don't see any items to change. What would you like to order?",
                )
            item = active_items[-1]
        else:
            # Find specific item by ID
            item = next((t for t in active_items if t.id == item_id), None)
            if item is None:
                return ChangeResult(
                    success=False,
                    message="I couldn't find that item to change.",
                )

        new_value_lower = new_value.lower().strip()

        # Check if item has this attribute
        if isinstance(item, MenuItemTask) and not item.has_attribute(attr_slug):
            # Get attribute display name for better error message
            display_name = self._get_attr_display_name(attr_slug)
            return ChangeResult(
                success=False,
                message=f"This item doesn't have a {display_name} to change.",
            )

        # Extract quantity from value (e.g., "2 vanilla syrups" -> quantity=2, value="vanilla syrups")
        quantity, stripped_value = self._extract_quantity_from_value(new_value_lower)

        # Use data-driven normalization based on database option aliases
        item_type_slug = item.item_type if isinstance(item, MenuItemTask) else None
        normalized_value = self._normalize_attribute_value(
            attr_slug, stripped_value, item_type_slug
        )

        # For multi-select attributes (like syrup), use add_selection with quantity
        # Data-driven: get multi-select attribute slugs from database configuration
        multi_select_slugs = menu_cache.get_multi_select_attribute_slugs(item_type_slug) if item_type_slug else set()
        if isinstance(item, MenuItemTask) and attr_slug in multi_select_slugs:
            # Normalize the slug: "vanilla syrups" -> "vanilla_syrup"
            modifier_slug = normalized_value.replace(" ", "_")
            if modifier_slug.endswith("s") and not modifier_slug.endswith("ss"):
                modifier_slug = modifier_slug[:-1]  # Remove trailing 's' for plural

            # Check if we're updating an existing selection
            # Match on slug containing the base modifier name
            base_name = modifier_slug.replace("_syrup", "").replace("_", "")
            existing_mods = [
                m for m in (item.modifiers or [])
                if base_name in m.get("slug", "").replace("_", "").lower()
            ]

            if existing_mods:
                # Update quantity on existing modifier
                existing_mods[0]["quantity"] = quantity
                logger.info("Updated %s quantity to %d", existing_mods[0].get("slug"), quantity)
            else:
                # Add new selection with quantity
                item.add_selection(
                    modifier_slug,
                    attr_slug,
                    quantity=quantity,
                )
                logger.info("Added %s x%d to %s", modifier_slug, quantity, attr_slug)

            # Recalculate price
            if self.pricing:
                self.pricing.recalculate_item_price(item)

            return ChangeResult(
                success=True,
                message=self._build_change_message(item, attr_slug, None, normalized_value),
                applied_attribute=attr_slug,
            )

        # Get old value and set new value (for single-select attributes)
        old_value = self._get_attr_value(item, attr_slug)
        success = self._set_attr_value(item, attr_slug, normalized_value)

        if not success:
            display_name = self._get_attr_display_name(attr_slug)
            return ChangeResult(
                success=False,
                message=f"This item doesn't have a {display_name} to change.",
            )

        logger.info("Changed %s from '%s' to '%s'", attr_slug, old_value, normalized_value)

        # Recalculate price - any attribute change could affect pricing
        # (size, bread type, temperature, spread type, milk, etc.)
        if self.pricing:
            self.pricing.recalculate_item_price(item)

        # Build response message
        message = self._build_change_message(item, attr_slug, old_value, normalized_value)

        return ChangeResult(
            success=True,
            message=message,
            applied_attribute=attr_slug,
        )

    def _normalize_attribute_value(
        self,
        attr_slug: str,
        value: str,
        item_type_slug: str | None = None,
    ) -> str | bool | None:
        """Normalize an attribute value using data-driven option resolution.

        Delegates to normalization.resolve_to_canonical() for unified handling.

        Args:
            attr_slug: The attribute slug (e.g., "size", "milk", "bread")
            value: The raw user input value
            item_type_slug: Optional item type for context-specific resolution

        Returns:
            Normalized value: canonical option slug, boolean, None, or cleaned input
        """
        return resolve_to_canonical(attr_slug, value, item_type_slug)

    def _get_attr_display_name(self, attr_slug: str) -> str:
        """Get human-readable display name for an attribute."""
        return _get_attr_display_name_from_db(attr_slug)

    def _get_attr_value(self, item, attr_slug: str):
        """Get current value of an attribute from an item."""
        if isinstance(item, MenuItemTask):
            # Try property accessor first (handles special cases)
            if hasattr(item, attr_slug):
                return getattr(item, attr_slug)
            # Fall back to selection lookup
            return item.get(attr_slug)
        # For other item types, try direct attribute access
        return getattr(item, attr_slug, None)

    def _set_attr_value(self, item, attr_slug: str, value) -> bool:
        """Set value of an attribute on an item. Returns True if successful."""
        if isinstance(item, MenuItemTask):
            # Get property name from database (handles cases like "milk_sweetener_syrup" -> "milk")
            property_name = menu_cache.get_property_name_for_attribute(attr_slug)
            # Try property setter first (handles special cases like milk unified storage)
            if hasattr(item, property_name):
                try:
                    setattr(item, property_name, value)
                    return True
                except AttributeError:
                    # Property exists but is read-only - try alternate approaches
                    pass
            # Also try the original attr_slug if different
            if property_name != attr_slug and hasattr(item, attr_slug):
                try:
                    setattr(item, attr_slug, value)
                    return True
                except AttributeError:
                    # Attribute exists but is read-only - fall through to selection API
                    pass
            # Fall back to selection API
            item[attr_slug] = value
            return True
        # For other item types, try direct attribute setting
        if hasattr(item, attr_slug):
            setattr(item, attr_slug, value)
            return True
        return False

    def _build_change_message(
        self, item, attr_slug: str, old_value, new_value
    ) -> str:
        """Build a response message for a change."""
        display_name = self._get_attr_display_name(attr_slug)

        # Use item summary for beverage items (data-driven check)
        if isinstance(item, MenuItemTask) and item.menu_item_type:
            modifier_category = menu_cache.get_modifier_category(item.menu_item_type)
            if modifier_category == "beverage":
                summary = item.get_summary()
                return f"Sure, I've changed that to {summary}. Anything else?"

        # Format value for display
        display_value = new_value
        if isinstance(new_value, bool):
            display_value = "yes" if new_value else "no"
        elif new_value is None:
            display_value = "none"

        if old_value:
            return f"Got it, I've changed the {display_name} from {old_value} to {display_value}."
        else:
            return f"Got it, {display_value} {display_name}."

    def resolve_clarification(
        self, pending_clarification: dict, user_response: str
    ) -> tuple[str | None, str | None]:
        """
        Resolve a pending clarification based on user response.

        Uses data-driven attribute matching - checks if any word in the user's
        response matches an attribute alias from the database.

        Args:
            pending_clarification: Dict with new_value and possible_attributes
            user_response: User's response to the clarification question

        Returns:
            Tuple of (resolved attribute slug, error message if failed)
        """
        user_response_lower = user_response.lower().strip()
        new_value = pending_clarification.get("new_value", "").lower()
        possible_attributes = pending_clarification.get("possible_attributes", [])

        # Get data-driven mapping of keywords to attribute slugs
        target_attr_map = self._get_target_attr_map()

        # Check if user response contains any known attribute keyword
        # This handles cases like "the bagel" or "cream cheese" or "the spread"
        for keyword, attr_slug in target_attr_map.items():
            if keyword in user_response_lower and attr_slug in possible_attributes:
                return attr_slug, None

        # Check for "{value} {keyword}" patterns (e.g., "blueberry bagel")
        for keyword, attr_slug in target_attr_map.items():
            if f"{new_value} {keyword}" in user_response_lower and attr_slug in possible_attributes:
                return attr_slug, None

        # Check for ordinal responses ("the first one", "the second one")
        if len(possible_attributes) >= 1 and any(
            kw in user_response_lower for kw in ["first", "1st", "one"]
        ):
            return possible_attributes[0], None

        if len(possible_attributes) >= 2 and any(
            kw in user_response_lower for kw in ["second", "2nd", "two"]
        ):
            return possible_attributes[1], None

        # Build error message dynamically from possible attributes
        attr_names = [self._get_attr_display_name(attr) for attr in possible_attributes]
        if len(attr_names) >= 2:
            prefixed = [f"the {n}" for n in attr_names]
            options_str = format_english_list(prefixed, conjunction="or")
        else:
            options_str = "which option"

        return None, f"I didn't catch that. Could you say whether you'd like {options_str} changed?"
