"""
LLM-Powered Parsers.

This module contains parsing functions that use instructor/OpenAI
to parse user input in context-specific ways. Each function is designed
for a specific state in the order flow.

Note: parse_open_input has been moved to deterministic/core.py since it
no longer uses LLM fallback. parse_confirmation, parse_delivery_choice,
and parse_payment_method have deterministic replacements in validators.py.

Remaining LLM parsers in this module:
- parse_side_choice: Complex option matching for side choices
- parse_name: Name extraction from conversational input
- parse_phone: Phone number extraction
- parse_email: Email address extraction
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
    EmailResponse,
    NameResponse,
    PhoneResponse,
)
from ..schemas.parser_responses import AttributeChoiceResponse

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
