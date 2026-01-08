"""
Modifier Change Handler.

This module handles user requests to change modifiers on ordered items,
such as "change it to blueberry cream cheese" or "make the bagel salt instead".

It detects change requests, determines if clarification is needed for ambiguous
modifiers, and applies changes once resolved.
"""

import logging
from dataclasses import dataclass
from enum import Enum

from typing import TYPE_CHECKING

from .models import CoffeeItemTask
from .parsers.constants import (
    CHANGE_REQUEST_PATTERNS,
    get_spread_types,
    get_bagel_types,
    get_bagel_only_types,
    get_spread_only_types,
    get_ambiguous_modifiers,
    normalize_bagel_type,
    normalize_spread,
    normalize_coffee_size,
)

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class ModifierCategory(Enum):
    """Categories of modifiers that can be changed."""
    BAGEL_TYPE = "bagel_type"
    SPREAD_TYPE = "spread_type"
    TOASTED = "toasted"
    CHEESE = "cheese"
    COFFEE_SIZE = "coffee_size"
    COFFEE_MILK = "coffee_milk"
    COFFEE_STYLE = "coffee_style"
    COFFEE_DECAF = "coffee_decaf"
    UNKNOWN = "unknown"


@dataclass
class ChangeRequest:
    """Represents a parsed change request from user input."""
    target: str | None  # What to change (e.g., "bagel", "spread") or None for "it"
    new_value: str  # The new value (e.g., "blueberry", "salt")
    is_ambiguous: bool  # Whether clarification is needed
    possible_categories: list[ModifierCategory]  # What categories this could be


@dataclass
class ChangeResult:
    """Result of attempting to apply a modifier change."""
    success: bool
    message: str
    needs_clarification: bool = False
    clarification_options: list[str] | None = None
    applied_category: ModifierCategory | None = None


class ModifierChangeHandler:
    """
    Handles modifier change requests for order items.

    Detects when users want to change modifiers (bagel type, spread, etc.),
    determines if clarification is needed for ambiguous requests, and
    applies changes to the appropriate items.
    """

    # Compound phrases to check first (higher priority)
    # These are phrases where we can determine the category from context
    COMPOUND_SPREAD_PHRASES = {
        "blueberry cream cheese",
        "strawberry cream cheese",
        "scallion cream cheese",
        "veggie cream cheese",
        "vegetable cream cheese",
        "honey walnut cream cheese",
        "jalapeno cream cheese",
        "jalapeño cream cheese",
        "truffle cream cheese",
        "olive cream cheese",
        "tofu cream cheese",
        "plain cream cheese",
        "lox spread",
        "nova cream cheese",
    }

    # Target word mappings to modifier categories
    TARGET_CATEGORY_MAP = {
        "bagel": ModifierCategory.BAGEL_TYPE,
        "bagel type": ModifierCategory.BAGEL_TYPE,
        "spread": ModifierCategory.SPREAD_TYPE,
        "cream cheese": ModifierCategory.SPREAD_TYPE,
        "cheese": ModifierCategory.CHEESE,
    }

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

                # Analyze the new value to determine possible categories
                is_ambiguous, possible_categories = self._analyze_modifier(
                    new_value, target
                )

                return ChangeRequest(
                    target=target,
                    new_value=new_value,
                    is_ambiguous=is_ambiguous,
                    possible_categories=possible_categories,
                )

        return None

    def _analyze_modifier(
        self, new_value: str, target: str | None
    ) -> tuple[bool, list[ModifierCategory]]:
        """
        Analyze a modifier value to determine possible categories.

        Args:
            new_value: The new value being requested
            target: Optional explicit target (e.g., "bagel", "spread")

        Returns:
            Tuple of (is_ambiguous, list of possible categories)
        """
        new_value_lower = new_value.lower().strip()

        # If target is explicitly specified, use that category
        if target:
            target_lower = target.lower()
            if target_lower in self.TARGET_CATEGORY_MAP:
                return False, [self.TARGET_CATEGORY_MAP[target_lower]]

        # Check compound phrases first (highest priority)
        # Only match if the phrase is contained in the value, not vice versa
        # This prevents "blueberry" from matching "blueberry cream cheese"
        for phrase in self.COMPOUND_SPREAD_PHRASES:
            if phrase in new_value_lower:
                return False, [ModifierCategory.SPREAD_TYPE]

        # Check if "cream cheese" is in the value (indicates spread type)
        if "cream cheese" in new_value_lower:
            return False, [ModifierCategory.SPREAD_TYPE]

        # Check if "bagel" is in the value (indicates bagel type)
        if "bagel" in new_value_lower:
            # Extract the bagel type from "X bagel"
            return False, [ModifierCategory.BAGEL_TYPE]

        # Check for unambiguous bagel-only types
        if new_value_lower in get_bagel_only_types():
            return False, [ModifierCategory.BAGEL_TYPE]

        # Check for unambiguous spread-only types
        if new_value_lower in get_spread_only_types():
            return False, [ModifierCategory.SPREAD_TYPE]

        # Check for ambiguous modifiers
        if new_value_lower in get_ambiguous_modifiers():
            # This could be either - needs clarification
            return True, [ModifierCategory.BAGEL_TYPE, ModifierCategory.SPREAD_TYPE]

        # Check if it's a known bagel type (but not in BAGEL_ONLY)
        if new_value_lower in get_bagel_types():
            # Could be bagel type
            if new_value_lower in get_spread_types():
                # Also a spread type - ambiguous
                return True, [ModifierCategory.BAGEL_TYPE, ModifierCategory.SPREAD_TYPE]
            return False, [ModifierCategory.BAGEL_TYPE]

        # Check if it's a known spread type (but not in SPREAD_ONLY)
        if new_value_lower in get_spread_types():
            return False, [ModifierCategory.SPREAD_TYPE]

        # Check for coffee size
        if new_value_lower in ("small", "large"):
            return False, [ModifierCategory.COFFEE_SIZE]

        # Check for coffee milk - check longer patterns first
        milk_patterns = [
            "oat milk", "almond milk", "whole milk", "skim milk",
            "2% milk", "soy milk", "coconut milk", "half and half",
            "oat", "almond", "whole", "skim", "soy", "coconut",
            "no milk", "black",
        ]
        for milk in milk_patterns:
            if milk in new_value_lower:
                return False, [ModifierCategory.COFFEE_MILK]

        # Check for coffee style (hot/iced)
        if new_value_lower in ("hot", "iced"):
            return False, [ModifierCategory.COFFEE_STYLE]

        # Check for coffee decaf
        if new_value_lower in ("decaf", "a decaf", "regular"):
            return False, [ModifierCategory.COFFEE_DECAF]

        # Unknown modifier
        return False, [ModifierCategory.UNKNOWN]

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

        # Build options based on possible categories
        options = []
        for category in change_request.possible_categories:
            if category == ModifierCategory.BAGEL_TYPE:
                options.append(f"a {new_value} bagel")
            elif category == ModifierCategory.SPREAD_TYPE:
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
        category: ModifierCategory,
        new_value: str,
    ) -> ChangeResult:
        """
        Apply a modifier change to an item.

        Args:
            order: The order to modify
            item_id: The ID of the item to modify (None for last item)
            category: The category of modifier to change
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

        # Apply the change based on category
        new_value_lower = new_value.lower().strip()

        if category == ModifierCategory.BAGEL_TYPE:
            # Normalize the bagel type - extracts valid type from messy input
            # e.g., "make that a sesame bagel" -> "sesame"
            bagel_type = normalize_bagel_type(new_value_lower)
            if not bagel_type:
                # Fallback: try simple suffix stripping
                bagel_type = new_value_lower
                if bagel_type.endswith(" bagel"):
                    bagel_type = bagel_type[:-6].strip()

            old_value = getattr(item, 'bagel_type', None) or getattr(item, 'bagel_choice', None)

            # Try to set bagel_type or bagel_choice depending on item type
            if hasattr(item, 'bagel_type'):
                item.bagel_type = bagel_type
            elif hasattr(item, 'bagel_choice'):
                item.bagel_choice = bagel_type
            else:
                return ChangeResult(
                    success=False,
                    message="This item doesn't have a bagel type to change.",
                )

            if old_value:
                message = f"Got it, I've changed the bagel from {old_value} to {bagel_type}."
            else:
                message = f"Got it, {bagel_type} bagel."

            return ChangeResult(
                success=True,
                message=message,
                applied_category=category,
            )

        elif category == ModifierCategory.SPREAD_TYPE:
            # Normalize the spread - extracts valid spread from messy input
            # e.g., "actually scallion cream cheese" -> "scallion cream cheese"
            normalized = normalize_spread(new_value_lower)
            if normalized:
                spread_type = normalized
                # Extract just the type part if it's a compound (e.g., "scallion" from "scallion cream cheese")
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
                applied_category=category,
            )

        elif category == ModifierCategory.CHEESE:
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
                applied_category=category,
            )

        elif category == ModifierCategory.COFFEE_SIZE:
            if not isinstance(item, CoffeeItemTask):
                return ChangeResult(
                    success=False,
                    message="I can only change the size of a coffee drink.",
                )

            # Normalize the size - extracts valid size from messy input
            # e.g., "make that a large instead" -> "large"
            size = normalize_coffee_size(new_value_lower) or new_value_lower
            old_value = item.size
            item.size = size
            logger.info("Changed coffee size from '%s' to '%s'", old_value, size)

            # Recalculate price with new size
            if self.pricing:
                self.pricing.recalculate_coffee_price(item)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_category=category,
            )

        elif category == ModifierCategory.COFFEE_MILK:
            if not isinstance(item, CoffeeItemTask):
                return ChangeResult(
                    success=False,
                    message="I can only change the milk for a coffee drink.",
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
            logger.info("Changed coffee milk from '%s' to '%s'", old_value, milk_value)

            # Recalculate price with new milk (may have upcharge)
            if self.pricing:
                self.pricing.recalculate_coffee_price(item)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_category=category,
            )

        elif category == ModifierCategory.COFFEE_STYLE:
            if not isinstance(item, CoffeeItemTask):
                return ChangeResult(
                    success=False,
                    message="I can only change hot/iced for a coffee drink.",
                )

            old_style = "iced" if item.iced else "hot"
            item.iced = (new_value_lower == "iced")
            new_style = "iced" if item.iced else "hot"
            logger.info("Changed coffee style from '%s' to '%s'", old_style, new_style)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_category=category,
            )

        elif category == ModifierCategory.COFFEE_DECAF:
            if not isinstance(item, CoffeeItemTask):
                return ChangeResult(
                    success=False,
                    message="I can only change decaf for a coffee drink.",
                )

            # "regular" means not decaf, "decaf" or "a decaf" means decaf
            old_decaf = item.decaf
            item.decaf = new_value_lower in ("decaf", "a decaf")
            logger.info("Changed coffee decaf from '%s' to '%s'", old_decaf, item.decaf)

            summary = item.get_summary()
            return ChangeResult(
                success=True,
                message=f"Sure, I've changed that to {summary}. Anything else?",
                applied_category=category,
            )

        else:
            return ChangeResult(
                success=False,
                message=f"I'm not sure how to change '{new_value}'. Could you please clarify?",
            )

    def resolve_clarification(
        self, pending_clarification: dict, user_response: str
    ) -> tuple[ModifierCategory | None, str | None]:
        """
        Resolve a pending clarification based on user response.

        Args:
            pending_clarification: Dict with new_value and possible_categories
            user_response: User's response to the clarification question

        Returns:
            Tuple of (resolved category, error message if failed)
        """
        user_response_lower = user_response.lower().strip()
        new_value = pending_clarification.get("new_value", "").lower()

        # Check for explicit category indicators in response
        if "bagel" in user_response_lower:
            return ModifierCategory.BAGEL_TYPE, None

        if "cream cheese" in user_response_lower or "spread" in user_response_lower:
            return ModifierCategory.SPREAD_TYPE, None

        # Check for affirmative responses to specific options
        # If they said "blueberry bagel" for the first option
        if f"{new_value} bagel" in user_response_lower:
            return ModifierCategory.BAGEL_TYPE, None

        # If they said "blueberry cream cheese" for the second option
        if f"{new_value} cream cheese" in user_response_lower:
            return ModifierCategory.SPREAD_TYPE, None

        # Check for ordinal responses ("the first one", "the second one")
        possible_categories = pending_clarification.get("possible_categories", [])
        if len(possible_categories) >= 1 and any(
            kw in user_response_lower for kw in ["first", "1st", "one"]
        ):
            return possible_categories[0], None

        if len(possible_categories) >= 2 and any(
            kw in user_response_lower for kw in ["second", "2nd", "two"]
        ):
            return possible_categories[1], None

        return None, "I didn't catch that. Could you say whether you'd like the bagel or the cream cheese changed?"
