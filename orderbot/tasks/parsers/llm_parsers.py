"""
LLM-Powered Parsers.

This module contains all parsing functions that use instructor/OpenAI
to parse user input in context-specific ways. Each function is designed
for a specific state in the order flow.
"""

import os
import logging

from typing import TypeVar

import instructor
from openai import OpenAI
from pydantic import BaseModel

# Generic type for response models
T = TypeVar("T", bound=BaseModel)

from ..schemas import (
    ConfirmationResponse,
    DeliveryChoiceResponse,
    EmailResponse,
    NameResponse,
    OpenInputResponse,
    PaymentMethodResponse,
    PhoneResponse,
)
from ..schemas.parser_responses import AttributeChoiceResponse
from .deterministic import (
    parse_open_input_deterministic,
    _parse_multi_item_order,
    _parse_configurable_item,
)

logger = logging.getLogger(__name__)


def get_instructor_client():
    """Get instructor-wrapped OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return instructor.from_openai(OpenAI(api_key=api_key))


def _create_llm_parser(
    prompt_template: str,
    response_model: type[T],
    model: str = "gpt-4o-mini",
) -> T:
    """Generic LLM parser factory.

    Creates a parsed response by sending a prompt to the LLM.

    Args:
        prompt_template: The fully formatted prompt to send
        response_model: The Pydantic model type to parse the response into
        model: The LLM model to use

    Returns:
        Parsed response of type T
    """
    client = get_instructor_client()
    return client.chat.completions.create(
        model=model,
        response_model=response_model,
        messages=[{"role": "user", "content": prompt_template}],
    )


def parse_side_choice(
    user_input: str,
    item_name: str,
    valid_options: list[dict] | None = None,
    question_text: str | None = None,
    model: str = "gpt-4o-mini",
) -> AttributeChoiceResponse:
    """Parse user input when waiting for side choice selection.

    This is a generic, data-driven parser that works with any side choice options
    loaded from the database. It only determines which option was chosen - any
    further configuration of the chosen option is handled by standard item
    configuration handlers.

    Args:
        user_input: The user's response
        item_name: The parent item name (e.g., "Western Omelette")
        valid_options: List of option dicts from DB with keys:
            - slug: option identifier (e.g., "bagel", "fruit_salad")
            - display_name: human-readable name (e.g., "Bagel", "Fruit Salad")
            - aliases: optional list of alternative names
        question_text: The question that was asked (for context in prompt)
        model: OpenAI model to use

    Returns:
        AttributeChoiceResponse with:
            - value: the chosen option slug (or "unclear" if not determined)
            - wants_cancel: True if user wants to cancel the item
    """
    client = get_instructor_client()

    # Build options description from database data
    if valid_options:
        options_list = []
        for opt in valid_options:
            slug = opt.get("slug", "")
            display = opt.get("display_name", slug)
            aliases = opt.get("aliases", [])
            if aliases:
                alias_str = ", ".join(aliases[:3])  # Limit to 3 aliases
                options_list.append(f"- {display} (slug: {slug}, also known as: {alias_str})")
            else:
                options_list.append(f"- {display} (slug: {slug})")
        options_desc = "\n".join(options_list)
    else:
        options_desc = "- (options not specified)"

    # Use provided question or build generic one
    if not question_text:
        question_text = f"Would you like a side with your {item_name}?"

    prompt = f"""The user ordered "{item_name}" which comes with a choice of side.
We asked: "{question_text}"

Available options:
{options_desc}

The user said: "{user_input}"

Determine which option they chose. Return the slug of the chosen option.
If the user wants to cancel or remove the item, set wants_cancel to true.
If you cannot determine their choice, set value to "unclear".

IMPORTANT: Only return the option slug - do NOT try to extract additional details
like specific types or modifications. Those will be asked separately.
"""

    return client.chat.completions.create(
        model=model,
        response_model=AttributeChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_open_input(
    user_input: str,
    context: str = "",
    model: str = "gpt-4o-mini",
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
) -> OpenInputResponse:
    """Parse user input when open for new orders.

    Uses deterministic parsing only - no LLM fallback.
    All parsing is data-driven via database-loaded patterns.

    Args:
        user_input: The user's input string
        context: Unused (kept for API compatibility)
        model: Unused (kept for API compatibility)
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
        ingredient_to_items: Mapping of ingredient names to menu items containing them
            (e.g., {"chicken": [{"name": "Chicken Salad Sandwich", ...}]})
    """
    # Check if input likely contains multiple items
    input_lower = user_input.lower()
    # Clean up common phrases that contain "and" but aren't multi-item orders
    # Order matters: longer phrases first to match properly
    cleaned = input_lower
    for phrase in [
        # Egg sandwich phrases (must come first - longer phrases)
        "bacon egg and cheese", "ham egg and cheese", "sausage egg and cheese",
        "bacon and egg and cheese", "ham and egg and cheese",
        "bacon eggs and cheese", "ham eggs and cheese", "egg and cheese",
        "egg cheese and bacon", "egg, cheese and bacon",
        # Other compound phrases
        "ham and cheese", "ham and egg", "bacon and egg", "egg and bacon",
        "lox and cream cheese", "salt and pepper", "cream cheese and lox",
        "eggs and bacon", "black and white", "spinach and feta",
    ]:
        cleaned = cleaned.replace(phrase, "")

    # If "and" or comma still appears, it might be multi-item OR a single item with modifiers
    # Pattern: "bagel with X, Y, and Z" is a single item with modifiers, NOT multi-item
    if " and " in cleaned or ", " in cleaned:
        # Check for explicit multi-item separators that indicate separate items
        # Pattern: " and a ", " and an ", ", a ", ", an " usually indicate a new item
        # e.g., "latte and a bagel", "coffee, a bagel, and an omelette"
        multi_item_separators = [" and a ", " and an ", " plus a ", " plus an ", ", a ", ", an "]
        has_multi_item_separator = any(sep in input_lower for sep in multi_item_separators)

        if has_multi_item_separator:
            # Multi-item order detected - try multi-item parsing first
            logger.info("Multi-item separator detected, trying multi-item parse: %s", user_input[:50])
            result = _parse_multi_item_order(user_input)
            if result is not None:
                logger.info("Parsed multi-item order deterministically: %s", user_input[:50])
                return result
            # Fall through to configurable item if multi-item parse fails
            logger.info("Multi-item parse failed, trying configurable item: %s", user_input[:50])

        # Try configurable item patterns (bagels, coffees, etc.)
        # e.g., "plain bagel with Egg Whites, Swiss, and Spinach", "large iced latte"
        logger.info("Trying configurable item pattern: %s", user_input[:50])
        result = _parse_configurable_item(user_input)
        if result is not None:
            logger.info("Parsed configurable item: %s", user_input[:50])
            return result

        # Try multi-item parsing if we haven't already
        if not has_multi_item_separator:
            logger.info("Configurable item failed, trying multi-item parse: %s", user_input[:50])
            result = _parse_multi_item_order(user_input)
            if result is not None:
                logger.info("Parsed multi-item order deterministically: %s", user_input[:50])
                return result

    # Try deterministic parsing for single-item orders
    result = parse_open_input_deterministic(
        user_input,
        modifier_category_keywords=modifier_category_keywords,
        modifier_item_keywords=modifier_item_keywords,
        ingredient_to_items=ingredient_to_items,
    )
    if result is not None:
        logger.info("Parsed deterministically: %s", user_input[:50])
        return result

    # No LLM fallback - return unclear response
    logger.info("Unable to parse deterministically, returning unclear: %s", user_input[:50])
    return OpenInputResponse(unclear=True)


def parse_delivery_choice(user_input: str, model: str = "gpt-4o-mini") -> DeliveryChoiceResponse:
    """Parse user input when waiting for pickup/delivery choice."""
    prompt = f"""We asked the user if their order is for pickup or delivery.
The user said: "{user_input}"

Examples:
- "pickup" / "pick up" / "I'll pick it up" -> choice: "pickup"
- "delivery" / "deliver" / "delivered" -> choice: "delivery"
- "delivery to 123 Main St" -> choice: "delivery", address: "123 Main St"
"""
    return _create_llm_parser(prompt, DeliveryChoiceResponse, model)


def parse_name(user_input: str, model: str = "gpt-4o-mini") -> NameResponse:
    """Parse user input when waiting for name."""
    prompt = f"""We asked the user for their name for the order.
The user said: "{user_input}"

Extract just the name. Examples:
- "John" -> name: "John"
- "It's Sarah" -> name: "Sarah"
- "My name is Mike" -> name: "Mike"
"""
    return _create_llm_parser(prompt, NameResponse, model)


def parse_confirmation(user_input: str, model: str = "gpt-4o-mini") -> ConfirmationResponse:
    """Parse user input when waiting for order confirmation."""
    prompt = f"""We showed the user their order summary and asked if it looks right.
The user said: "{user_input}"

Examples:
- "yes" / "looks good" / "correct" / "perfect" -> confirmed: true
- "no" / "wait" / "change" / "actually" -> wants_changes: true
"""
    return _create_llm_parser(prompt, ConfirmationResponse, model)


def parse_payment_method(user_input: str, model: str = "gpt-4o-mini") -> PaymentMethodResponse:
    """Parse user input when asking how to send order details."""
    prompt = f"""We asked the user for a phone number or email to send the order confirmation.
The user said: "{user_input}"

Examples:
- "text" / "text me" / "sms" -> choice: "text"
- "email" / "email me" / "send me an email" -> choice: "email"
- "text me at 555-1234" -> choice: "text", phone_number: "555-1234"
- "555-123-4567" -> choice: "text", phone_number: "555-123-4567"
- "email it to john@example.com" -> choice: "email", email_address: "john@example.com"
- "john@example.com" -> choice: "email", email_address: "john@example.com"
"""
    return _create_llm_parser(prompt, PaymentMethodResponse, model)


def parse_email(user_input: str, model: str = "gpt-4o-mini") -> EmailResponse:
    """Parse user input when collecting email address."""
    prompt = f"""We asked the user for their email address.
The user said: "{user_input}"

Extract the email address from their response.
Examples:
- "john@example.com" -> email: "john@example.com"
- "it's john at gmail dot com" -> email: "john@gmail.com"
- "my email is test.user@company.org" -> email: "test.user@company.org"
"""
    return _create_llm_parser(prompt, EmailResponse, model)


def parse_phone(user_input: str, model: str = "gpt-4o-mini") -> PhoneResponse:
    """Parse user input when collecting phone number."""
    prompt = f"""We asked the user for their phone number to text order confirmation.
The user said: "{user_input}"

Extract the phone number from their response. Return just the digits (10 digits for US numbers).
Examples:
- "555-123-4567" -> phone: "5551234567"
- "it's 732 555 1234" -> phone: "7325551234"
- "(908) 555-9999" -> phone: "9085559999"
- "my number is 201.555.0000" -> phone: "2015550000"
"""
    return _create_llm_parser(prompt, PhoneResponse, model)
