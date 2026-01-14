"""
Modifier Change Handler.

This module handles user requests to change modifiers on ordered items,
such as "change it to blueberry cream cheese" or "make the bagel salt instead".

It detects change requests, determines if clarification is needed for ambiguous
modifiers, and applies changes once resolved.

The handler is data-driven - it uses attribute slugs from the database rather
than hardcoded food-specific categories.
"""

import logging
from dataclasses import dataclass

from typing import TYPE_CHECKING

from .models import MenuItemTask
from .parsers.constants import (
    CHANGE_REQUEST_PATTERNS,
    normalize_bagel_type,
    normalize_spread,
    normalize_coffee_size,
)
from sandwich_bot.menu_data_cache import menu_cache

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


# Attribute slugs used for modifier changes (from database)
# These are standard attribute slugs, not hardcoded food names
ATTR_BREAD = "bread"  # Bagel type (plain, everything, etc.)
ATTR_SPREAD_TYPE = "spread_type"  # Cream cheese type (scallion, etc.)
ATTR_TOASTED = "toasted"  # Boolean toasted attribute
ATTR_CHEESE = "cheese"  # Cheese selection
ATTR_SIZE = "size"  # Beverage size
ATTR_MILK = "milk_sweetener_syrup"  # Milk/sweetener for beverages
ATTR_TEMPERATURE = "temperature"  # Hot/iced
ATTR_DECAF = "decaf"  # Decaf boolean
ATTR_UNKNOWN = "unknown"  # Unknown attribute


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
        config: "HandlerConfig | None" = None,
        **kwargs,
    ):
        """Initialize the modifier change handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.pricing = config.pricing
        else:
            # Legacy support for direct parameters
            self.pricing = kwargs.get("pricing")

        # Cache data-driven lookups
        self._spread_phrases: set[str] | None = None
        self._target_attr_map: dict[str, str] | None = None

    def _get_spread_phrases(self) -> set[str]:
        """Get compound spread phrases from the database.

        Returns phrases like "scallion cream cheese" that indicate a spread type.
        Uses menu_cache.get_bagel_spreads() filtered for phrases containing
        "cream cheese" or "spread".
        """
        if self._spread_phrases is None:
            try:
                all_spreads = menu_cache.get_bagel_spreads()
                self._spread_phrases = {
                    s for s in all_spreads
                    if "cream cheese" in s or " spread" in s
                }
            except Exception:
                # Fallback to empty set if cache not loaded
                self._spread_phrases = set()
        return self._spread_phrases

    def _get_target_attr_map(self) -> dict[str, str]:
        """Get mapping from target words to attribute slugs.

        Maps user words like "bagel", "spread" to attribute slugs.
        Built dynamically from menu_cache data.
        """
        if self._target_attr_map is None:
            # Build mapping from attribute display names and common terms
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
                            # Also map slug itself
                            self._target_attr_map[attr_slug.replace("_", " ")] = attr_slug
                    except Exception:
                        continue
            except Exception:
                pass

            # Add common aliases that map to standard attribute slugs
            self._target_attr_map.update({
                "bagel": ATTR_BREAD,
                "bagel type": ATTR_BREAD,
                "spread": ATTR_SPREAD_TYPE,
                "cream cheese": ATTR_SPREAD_TYPE,
                "cheese": ATTR_CHEESE,
                "size": ATTR_SIZE,
                "milk": ATTR_MILK,
            })

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
        attribute(s) a modifier value could apply to.

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

        # Check compound spread phrases from database (highest priority)
        # Only match if the phrase is contained in the value, not vice versa
        spread_phrases = self._get_spread_phrases()
        for phrase in spread_phrases:
            if phrase in new_value_lower:
                return False, [ATTR_SPREAD_TYPE]

        # Check if "cream cheese" is in the value (indicates spread type)
        if "cream cheese" in new_value_lower:
            return False, [ATTR_SPREAD_TYPE]

        # Check for known attribute options using menu_cache
        is_attr_option, attr_slug = menu_cache.is_known_attribute_option(new_value_lower)
        if is_attr_option and attr_slug:
            return False, [attr_slug]

        # Check for unambiguous bread-only types (from database)
        try:
            if new_value_lower in menu_cache.get_bagel_only_types():
                return False, [ATTR_BREAD]
        except Exception:
            pass

        # Check for unambiguous spread-only types (from database)
        try:
            if new_value_lower in menu_cache.get_spread_only_types():
                return False, [ATTR_SPREAD_TYPE]
        except Exception:
            pass

        # Check for ambiguous modifiers (from database)
        try:
            if new_value_lower in menu_cache.get_ambiguous_modifiers():
                # This could be either bread or spread_type - needs clarification
                return True, [ATTR_BREAD, ATTR_SPREAD_TYPE]
        except Exception:
            pass

        # Check if it's a known bagel/bread type
        try:
            bagel_types = menu_cache.get_bagel_types()
            spread_types = menu_cache.get_spread_types()

            if new_value_lower in bagel_types:
                if new_value_lower in spread_types:
                    # Also a spread type - ambiguous
                    return True, [ATTR_BREAD, ATTR_SPREAD_TYPE]
                return False, [ATTR_BREAD]

            # Check if it's a known spread type
            if new_value_lower in spread_types:
                return False, [ATTR_SPREAD_TYPE]
        except Exception:
            pass

        # Check for milk options - build patterns from database
        try:
            milk_patterns: list[str] = []
            db_milks = menu_cache.get_beverage_milks()
            for milk_name in db_milks:
                milk_lower = milk_name.lower()
                milk_patterns.append(milk_lower)
                # Add short form (strip " milk" suffix)
                if milk_lower.endswith(" milk"):
                    milk_patterns.append(milk_lower[:-5])
            # Add special "no milk" patterns
            milk_patterns.extend(["no milk", "black"])
            for milk in milk_patterns:
                if milk in new_value_lower:
                    return False, [ATTR_MILK]
        except Exception:
            pass

        # Unknown modifier
        return False, [ATTR_UNKNOWN]

    def generate_clarification_message(
        self, change_request: ChangeRequest
    ) -> str:
        """
        Generate a clarification message for ambiguous change requests.

        Args:
            change_request: The ambiguous change request

        Returns:
            Message asking user to clarify what they want to change
        """
        new_value = change_request.new_value

        # Build options based on possible attribute slugs
        options = []
        for attr_slug in change_request.possible_attributes:
            if attr_slug == ATTR_BREAD:
                options.append(f"a {new_value} bagel")
            elif attr_slug == ATTR_SPREAD_TYPE:
                options.append(f"{new_value} cream cheese")

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

    def generate_mid_config_message(self) -> str:
        """
        Generate a message when user tries to change during configuration.

        Returns:
            Message asking user to wait until configuration is complete
        """
        return (
            "Sure, let me finish getting the details for your current item first, "
            "and then we can make that change."
        )

    def apply_change(
        self,
        order,
        item_id: str | None,
        attr_slug: str,
        new_value: str,
    ) -> ChangeResult:
        """
        Apply a modifier change to an item.

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

        # Apply the change based on attribute slug
        new_value_lower = new_value.lower().strip()

        if attr_slug == ATTR_BREAD:
            # Normalize the bread/bagel type - extracts valid type from messy input
            # e.g., "make that a sesame bagel" -> "sesame"
            bread_type = normalize_bagel_type(new_value_lower)
            if not bread_type:
                # Fallback: try simple suffix stripping
                bread_type = new_value_lower
                if bread_type.endswith(" bagel"):
                    bread_type = bread_type[:-6].strip()

            old_value = getattr(item, 'bread', None) or getattr(item, 'bagel_choice', None)

            # Try to set bread or bagel_choice depending on item type
            if hasattr(item, 'bread'):
                item.bread = bread_type
            elif hasattr(item, 'bagel_choice'):
                item.bagel_choice = bread_type
            else:
                return ChangeResult(
                    success=False,
                    message="This item doesn't have a bread type to change.",
                )

            if old_value:
                message = f"Got it, I've changed the bagel from {old_value} to {bread_type}."
            else:
                message = f"Got it, {bread_type} bagel."

            return ChangeResult(
                success=True,
                message=message,
                applied_attribute=attr_slug,
            )

        elif attr_slug == ATTR_SPREAD_TYPE:
            # Normalize the spread - extracts valid spread from messy input
            # e.g., "actually scallion cream cheese" -> "scallion cream cheese"
            normalized = normalize_spread(new_value_lower)
            if normalized:
                spread_type = normalized
                # Extract just the type part if it's a compound
                # (e.g., "scallion" from "scallion cream cheese")
                for suffix in [" cream cheese", " spread"]:
                    if spread_type.endswith(suffix):
                        spread_type = spread_type[:-len(suffix)].strip()
                        break
            else:
                # Fallback: try simple suffix stripping
                spread_type = new_value_lower
                for suffix in [" cream cheese", " spread"]:
                    if spread_type.endswith(suffix):
                        spread_type = spread_type[:-len(suffix)].strip()
                        break

            old_value = getattr(item, 'spread_type', None)

            if hasattr(item, 'spread_type'):
                item.spread_type = spread_type
                # Also ensure spread is set to cream cheese if changing spread type
                if hasattr(item, 'spread') and item.spread is None:
                    item.spread = "cream cheese"
            else:
                return ChangeResult(
                    success=False,
                    message="This item doesn't have a spread to change.",
                )

            if old_value:
                message = f"Got it, I've changed the spread from {old_value} to {spread_type} cream cheese."
            else:
                message = f"Got it, {spread_type} cream cheese."

            return ChangeResult(
                success=True,
                message=message,
                applied_attribute=attr_slug,
            )

        elif attr_slug == ATTR_CHEESE:
            old_value = getattr(item, 'cheese', None)

            if hasattr(item, 'cheese'):
                item.cheese = new_value_lower
            else:
                return ChangeResult(
                    success=False,
                    message="This item doesn't have a cheese to change.",
                )

            if old_value:
                message = f"Got it, I've changed the cheese from {old_value} to {new_value_lower}."
            else:
                message = f"Got it, {new_value_lower} cheese."

            return ChangeResult(
                success=True,
                message=message,
                applied_attribute=attr_slug,
            )

        elif attr_slug == ATTR_SIZE:
            if not (isinstance(item, MenuItemTask) and item.has_attribute("size")):
                return ChangeResult(
                    success=False,
                    message="I can only change the size on items that have sizes.",
                )

            # Normalize the size - extracts valid size from messy input
            # e.g., "make that a large instead" -> "large"
            size = normalize_coffee_size(new_value_lower) or new_value_lower
            old_value = item.size
            item.size = size
            logger.info("Changed size from '%s' to '%s'", old_value, size)

            # Recalculate price with new size
            if self.pricing:
                self.pricing.recalculate_item_price(item)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_attribute=attr_slug,
            )

        elif attr_slug == ATTR_MILK:
            if not (isinstance(item, MenuItemTask) and item.has_attribute("size")):
                return ChangeResult(
                    success=False,
                    message="I can only change the milk on beverage items.",
                )

            # Normalize milk value
            milk_value = new_value_lower
            for suffix in [" milk"]:
                if milk_value.endswith(suffix):
                    milk_value = milk_value[:-len(suffix)].strip()
                    break
            if milk_value in ("no", "black", "none"):
                milk_value = None

            old_value = item.milk
            item.milk = milk_value
            logger.info("Changed milk from '%s' to '%s'", old_value, milk_value)

            # Recalculate price with new milk (may have upcharge)
            if self.pricing:
                self.pricing.recalculate_item_price(item)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_attribute=attr_slug,
            )

        elif attr_slug == ATTR_TEMPERATURE:
            if not (isinstance(item, MenuItemTask) and item.has_attribute("size")):
                return ChangeResult(
                    success=False,
                    message="I can only change hot/iced on beverage items.",
                )

            old_style = item.temperature or "hot"
            item.temperature = new_value_lower  # "iced" or "hot"
            new_style = item.temperature
            logger.info("Changed temperature from '%s' to '%s'", old_style, new_style)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_attribute=attr_slug,
            )

        elif attr_slug == ATTR_DECAF:
            if not (isinstance(item, MenuItemTask) and item.has_attribute("size")):
                return ChangeResult(
                    success=False,
                    message="I can only change decaf on beverage items.",
                )

            # "regular" means not decaf, "decaf" or "a decaf" means decaf
            old_decaf = item.decaf
            item.decaf = new_value_lower in ("decaf", "a decaf")
            logger.info("Changed decaf from '%s' to '%s'", old_decaf, item.decaf)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_attribute=attr_slug,
            )

        else:
            return ChangeResult(
                success=False,
                message=f"I'm not sure how to change '{new_value}'. Could you please clarify?",
            )

    def resolve_clarification(
        self, pending_clarification: dict, user_response: str
    ) -> tuple[str | None, str | None]:
        """
        Resolve a pending clarification based on user response.

        Args:
            pending_clarification: Dict with new_value and possible_attributes
            user_response: User's response to the clarification question

        Returns:
            Tuple of (resolved attribute slug, error message if failed)
        """
        user_response_lower = user_response.lower().strip()
        new_value = pending_clarification.get("new_value", "").lower()

        # Check for explicit attribute indicators in response
        if "bagel" in user_response_lower:
            return ATTR_BREAD, None

        if "cream cheese" in user_response_lower or "spread" in user_response_lower:
            return ATTR_SPREAD_TYPE, None

        # Check for affirmative responses to specific options
        # If they said "blueberry bagel" for the first option
        if f"{new_value} bagel" in user_response_lower:
            return ATTR_BREAD, None

        # If they said "blueberry cream cheese" for the second option
        if f"{new_value} cream cheese" in user_response_lower:
            return ATTR_SPREAD_TYPE, None

        # Check for ordinal responses ("the first one", "the second one")
        possible_attributes = pending_clarification.get("possible_attributes", [])
        if len(possible_attributes) >= 1 and any(
            kw in user_response_lower for kw in ["first", "1st", "one"]
        ):
            return possible_attributes[0], None

        if len(possible_attributes) >= 2 and any(
            kw in user_response_lower for kw in ["second", "2nd", "two"]
        ):
            return possible_attributes[1], None

        return None, "I didn't catch that. Could you say whether you'd like the bagel or the cream cheese changed?"
