"""
Input Validation Functions.

This module contains validation functions for user-provided data
such as email addresses, phone numbers, and delivery addresses.
"""

import re
import logging

import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException
from email_validator import validate_email, EmailNotValidError

logger = logging.getLogger(__name__)

# Regex for extracting email address (used by multiple parsers)
_EMAIL_EXTRACT_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
)


def validate_email_address(email: str) -> tuple[str | None, str | None]:
    """
    Validate an email address using email-validator library.

    Performs:
    - Syntax validation (RFC 5322 compliant)
    - DNS/MX record check (verifies domain can receive email)
    - Normalization (lowercase domain, unicode handling)

    Args:
        email: The email address to validate

    Returns:
        Tuple of (normalized_email, error_message).
        If valid: (normalized_email, None)
        If invalid: (None, user-friendly error message)
    """
    if not email:
        return (None, "I didn't catch an email address. Could you please repeat it?")

    try:
        # Validate and normalize the email
        # check_deliverability=True - verify domain exists via DNS/MX lookup
        # This catches common typos like gmail.con and made-up domains
        result = validate_email(email, check_deliverability=True)
        # Return the normalized email (lowercased domain, etc.)
        return (result.normalized, None)
    except EmailNotValidError as e:
        # Generate user-friendly error messages
        error_str = str(e).lower()

        if "dns" in error_str or "mx" in error_str or "does not exist" in error_str:
            # Domain doesn't exist or can't receive email
            domain = email.split("@")[-1] if "@" in email else email
            return (None, f"I couldn't verify the domain '{domain}'. Could you double-check the spelling?")
        elif "at sign" in error_str or "@" not in email:
            return (None, "That doesn't seem to have an @ symbol. Could you say your email again?")
        elif "after the @" in error_str or "domain" in error_str:
            return (None, "I didn't catch the domain part after the @. What's your email address?")
        else:
            # Generic fallback
            logger.warning("Email validation failed: %s - %s", email, str(e))
            return (None, "That doesn't look like a valid email address. Could you say it again?")


def validate_phone_number(phone: str) -> tuple[str | None, str | None]:
    """
    Validate a phone number using Google's phonenumbers library.

    Args:
        phone: Raw phone number string (can have various formats)

    Returns:
        Tuple of (validated_phone, error_message).
        - If valid: (formatted_phone, None)
        - If invalid: (None, user_friendly_error_message)

    The formatted_phone is returned in E.164 format (e.g., "+12015551234")
    for consistent storage and SMS delivery.
    """
    if not phone:
        return (None, "I didn't catch a phone number. Could you please repeat it?")

    # Clean up the input - extract just digits
    digits_only = re.sub(r'\D', '', phone)

    # Handle common US formats without country code
    if len(digits_only) == 10:
        digits_only = "1" + digits_only  # Add US country code
    elif len(digits_only) == 11 and digits_only.startswith("1"):
        pass  # Already has US country code
    elif len(digits_only) < 10:
        return (None, "That number seems too short. US phone numbers have 10 digits. Could you say it again?")
    elif len(digits_only) > 11:
        return (None, "That number seems too long. Could you say just the 10-digit phone number?")

    try:
        # Parse the number (assuming US if no country code)
        parsed_number = phonenumbers.parse("+" + digits_only, None)

        # Check if it's a valid number
        if not phonenumbers.is_valid_number(parsed_number):
            return (None, "That doesn't seem to be a valid phone number. Could you double-check and say it again?")

        # Check if it's a US number
        region = phonenumbers.region_code_for_number(parsed_number)
        if region != "US":
            return (None, "I can only accept US phone numbers for text messages. Do you have a US number?")

        # Format in E.164 for consistent storage
        formatted = phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)

        logger.info("Phone validation succeeded: %s -> %s", phone, formatted)
        return (formatted, None)

    except NumberParseException as e:
        logger.warning("Phone validation failed: %s - %s", phone, str(e))
        return (None, "I didn't understand that phone number. Could you say it again slowly?")


def extract_zip_code(address: str) -> str | None:
    """
    Extract a 5-digit ZIP code from an address string.

    Args:
        address: Address string that may contain a ZIP code

    Returns:
        5-digit ZIP code string if found, None otherwise
    """
    if not address:
        return None

    # Look for 5-digit ZIP code pattern (with optional -4 extension)
    zip_pattern = r'\b(\d{5})(?:-\d{4})?\b'
    match = re.search(zip_pattern, address)
    if match:
        return match.group(1)

    return None



# Note: parse_toasted_deterministic was removed - toasted preference is now
# parsed via data-driven boolean attribute extraction in _extract_attribute_values().

# Note: parse_hot_iced_deterministic removed - temperature (hot/iced) is now
# part of the menu item name (e.g., "Iced Latte" vs "Hot Latte"), not a
# separate configuration question.


def validate_delivery_zip_code(
    address: str,
    allowed_zip_codes: list[str],
) -> tuple[str | None, str | None]:
    """
    Validate that a delivery address is within the allowed delivery area.

    Args:
        address: The delivery address string
        allowed_zip_codes: List of ZIP codes where delivery is available

    Returns:
        Tuple of (zip_code, error_message).
        - If valid: (zip_code, None)
        - If invalid: (None, user_friendly_error_message)
    """
    # If no zip codes configured, delivery is not available
    if not allowed_zip_codes:
        return (None, "Sorry, we don't currently offer delivery from this location. Would you like to do pickup instead?")

    # Extract zip code from address
    zip_code = extract_zip_code(address)

    if not zip_code:
        return (None, "I need a ZIP code to check if we deliver to your area. What's your ZIP code?")

    # Check if zip code is in allowed list
    if zip_code in allowed_zip_codes:
        logger.info("Delivery ZIP code validated: %s is in allowed list", zip_code)
        return (zip_code, None)
    else:
        logger.info("Delivery ZIP code rejected: %s not in %s", zip_code, allowed_zip_codes)
        return (None, f"Sorry, we don't deliver to {zip_code}. Would you like to do pickup instead?")


# =============================================================================
# Deterministic Parsers (replacing LLM-based parsers)
# =============================================================================

from ..schemas import (
    ConfirmationResponse,
    DeliveryChoiceResponse,
    EmailResponse,
    NameResponse,
    PaymentMethodResponse,
    PhoneResponse,
)
from ..schemas.parser_responses import AttributeChoiceResponse
from orderbot.cache import menu_cache
from orderbot.cache.base import normalize_text


def parse_confirmation_deterministic(user_input: str) -> ConfirmationResponse:
    """Parse yes/no confirmation using database patterns.

    Uses menu_cache.is_affirmative() and is_negative() which load patterns
    from the database response_pattern table.

    Args:
        user_input: User's input text

    Returns:
        ConfirmationResponse with confirmed, wants_changes, or asks_about_tax
    """
    text = normalize_text(user_input)

    # Check for tax question patterns first
    tax_patterns = [
        "tax", "total with tax", "with tax", "after tax",
        "including tax", "plus tax", "how much with tax",
    ]
    if any(p in text for p in tax_patterns):
        return ConfirmationResponse(asks_about_tax=True)

    # Check for affirmative response using database patterns
    if menu_cache.is_affirmative(text):
        return ConfirmationResponse(confirmed=True)

    # Check for negative/change response using database patterns
    if menu_cache.is_negative(text):
        return ConfirmationResponse(wants_changes=True)

    # Additional change request patterns not in database
    change_patterns = [
        "wait", "hold on", "actually", "change", "modify",
        "add", "remove", "different", "instead", "switch",
        "can i", "could i", "i want to",
    ]
    if any(p in text for p in change_patterns):
        return ConfirmationResponse(wants_changes=True)

    # Additional confirmation patterns
    confirm_patterns = [
        "looks good", "that's right", "thats right", "correct",
        "perfect", "sounds good", "all good", "good to go",
        "that's it", "thats it", "confirmed", "confirm",
    ]
    if any(p in text for p in confirm_patterns):
        return ConfirmationResponse(confirmed=True)

    # Can't determine - return with neither set
    # The handler will re-ask for clarification
    logger.debug("Confirmation parse unclear for: %s", text[:50])
    return ConfirmationResponse()


def parse_delivery_choice_deterministic(user_input: str) -> DeliveryChoiceResponse:
    """Parse pickup/delivery choice using patterns.

    Args:
        user_input: User's input text

    Returns:
        DeliveryChoiceResponse with choice and optional address
    """
    text = normalize_text(user_input)
    original = user_input.strip()

    # Pickup patterns
    pickup_patterns = [
        "pickup", "pick up", "pick-up", "i'll pick", "i will pick",
        "come get", "in store", "in-store", "walk in", "walk-in",
        "picking up", "picking it up", "get it myself",
    ]

    # Delivery patterns
    delivery_patterns = [
        "delivery", "deliver", "delivered", "to my", "drop off",
        "drop-off", "send it", "bring it", "ship it",
    ]

    # Check for pickup
    for p in pickup_patterns:
        if p in text:
            return DeliveryChoiceResponse(choice="pickup")

    # Check for delivery - may include an address
    for p in delivery_patterns:
        if p in text:
            # Try to extract address from the input
            # Look for patterns like "delivery to 123 Main St" or "deliver to my address at 123..."
            address = None
            address_patterns = [
                r"(?:deliver(?:y|ed)?|to|at)\s+(.+?)(?:\s*[,.]?\s*(?:please|thanks|thank you)?)?$",
                r"(?:to|at)\s+(.+)$",
            ]
            for pattern in address_patterns:
                match = re.search(pattern, original, re.IGNORECASE)
                if match:
                    potential_address = match.group(1).strip()
                    # Validate it looks like an address (has numbers or street words)
                    if re.search(r'\d|street|st\b|ave\b|avenue|road|rd\b|drive|dr\b|blvd|lane|ln\b|way\b|place|pl\b|court|ct\b', potential_address, re.IGNORECASE):
                        address = potential_address
                        break

            return DeliveryChoiceResponse(choice="delivery", address=address)

    # Can't determine choice, but input might be a bare address
    # (e.g., user already chose delivery and is now providing their address)
    if re.search(
        r'\d+\s+\w+.*(street|st\b|ave\b|avenue|road|rd\b|drive|dr\b|blvd|lane|ln\b|way\b|place|pl\b|court|ct\b)',
        text, re.IGNORECASE,
    ):
        return DeliveryChoiceResponse(choice="unclear", address=original)

    return DeliveryChoiceResponse(choice="unclear")


def parse_payment_method_deterministic(user_input: str) -> PaymentMethodResponse:
    """Parse text/email payment link choice.

    Also extracts phone number or email if provided in the input.

    Args:
        user_input: User's input text

    Returns:
        PaymentMethodResponse with choice, optional phone_number, optional email_address
    """
    text = normalize_text(user_input)
    original = user_input.strip()

    # Text/SMS patterns
    text_patterns = ["text", "sms", "message me", "text me", "send a text"]

    # Email patterns
    email_patterns = ["email", "mail", "e-mail", "email me", "send an email"]

    # Try to extract phone number (10 digits, various formats)
    phone_match = re.search(r'(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})', original)
    phone_number = None
    if phone_match:
        # Clean up to just digits
        phone_number = re.sub(r'\D', '', phone_match.group(1))

    # Try to extract email address
    email_match = _EMAIL_EXTRACT_PATTERN.search(original)
    email_address = email_match.group() if email_match else None

    # If we found an email, that's likely the choice
    if email_address:
        return PaymentMethodResponse(choice="email", email_address=email_address)

    # If we found a phone number without explicit email preference, assume text
    if phone_number and not any(p in text for p in email_patterns):
        return PaymentMethodResponse(choice="text", phone_number=phone_number)

    # Check explicit text preference
    for p in text_patterns:
        if p in text:
            return PaymentMethodResponse(choice="text", phone_number=phone_number)

    # Check explicit email preference
    for p in email_patterns:
        if p in text:
            return PaymentMethodResponse(choice="email", email_address=email_address)

    # Can't determine
    return PaymentMethodResponse(choice="unclear")


# =============================================================================
# Deterministic Parsers for Name, Phone, Email, Side Choice
# (Replacing LLM-based parsers from llm_parsers.py)
# =============================================================================

# Regex for stripping conversational prefixes from name input
_NAME_PREFIX_PATTERN = re.compile(
    r"^(?:my\s+name\s+is|i'?m|it'?s|call\s+me|this\s+is|the\s+name\s+is|"
    r"name\s+is|i\s+am|just)\s+",
    re.IGNORECASE,
)

# Regex for stripping trailing pleasantries
_NAME_SUFFIX_PATTERN = re.compile(
    r"\s+(?:please|thanks|thank\s+you|thx)\.?$",
    re.IGNORECASE,
)


def parse_name_deterministic(user_input: str, model: str = "gpt-4o-mini") -> NameResponse:
    """Parse user input when waiting for name (deterministic).

    Strips conversational prefixes/suffixes and title-cases the result.
    The `model` parameter is accepted for call-site compatibility but ignored.

    Args:
        user_input: User's input text
        model: Ignored (kept for API compatibility)

    Returns:
        NameResponse with extracted name or None
    """
    text = user_input.strip()
    if not text:
        return NameResponse(name=None)

    # Strip conversational prefixes
    text = _NAME_PREFIX_PATTERN.sub("", text).strip()

    # Strip trailing pleasantries
    text = _NAME_SUFFIX_PATTERN.sub("", text).strip()

    # Strip surrounding quotes or punctuation
    text = text.strip("\"'.,!?")

    if not text:
        return NameResponse(name=None)

    # Guard: if more than 4 words remain, probably not just a name
    if len(text.split()) > 4:
        return NameResponse(name=None)

    return NameResponse(name=text.title())


def parse_phone_deterministic(user_input: str, model: str = "gpt-4o-mini") -> PhoneResponse:
    """Parse user input when collecting phone number (deterministic).

    Extracts digits and validates as a 10-digit US number.
    Downstream validate_phone_number() does full E.164 validation.

    Args:
        user_input: User's input text
        model: Ignored (kept for API compatibility)

    Returns:
        PhoneResponse with extracted phone digits or None
    """
    text = user_input.strip()
    if not text:
        return PhoneResponse(phone=None)

    # Extract all digits
    digits = re.sub(r'\D', '', text)

    # 10-digit US number
    if len(digits) == 10:
        return PhoneResponse(phone=digits)

    # 11 digits starting with country code 1
    if len(digits) == 11 and digits.startswith("1"):
        return PhoneResponse(phone=digits[1:])

    return PhoneResponse(phone=None)


# Regex for stripping conversational prefixes from email input
_EMAIL_PREFIX_PATTERN = re.compile(
    r"^(?:my\s+email\s+(?:address\s+)?is|it'?s|email\s+is|"
    r"the\s+email\s+is|send\s+(?:it\s+)?to|use)\s+",
    re.IGNORECASE,
)

def parse_email_deterministic(user_input: str, model: str = "gpt-4o-mini") -> EmailResponse:
    """Parse user input when collecting email address (deterministic).

    Handles natural language like 'john at gmail dot com' and extracts
    email via regex. Downstream validate_email_address() does full validation.

    Args:
        user_input: User's input text
        model: Ignored (kept for API compatibility)

    Returns:
        EmailResponse with extracted email or None
    """
    text = user_input.strip()
    if not text:
        return EmailResponse(email=None)

    # Strip conversational prefixes
    text = _EMAIL_PREFIX_PATTERN.sub("", text).strip()

    # Natural language conversion: " at " -> "@", " dot " -> "."
    text = re.sub(r'\s+at\s+', '@', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+dot\s+', '.', text, flags=re.IGNORECASE)

    # Try to extract email via regex
    match = _EMAIL_EXTRACT_PATTERN.search(text)
    if match:
        return EmailResponse(email=match.group(0).lower())

    return EmailResponse(email=None)


def parse_side_choice_deterministic(
    user_input: str,
    item_name: str,
    valid_options: list[dict] | None = None,
    question_text: str | None = None,
    model: str = "gpt-4o-mini",
) -> AttributeChoiceResponse:
    """Parse side choice selection using deterministic option matching.

    Uses OptionMatcher.match_single() against valid_options. Falls back
    to unclear if no match or multiple matches found.

    Args:
        user_input: User's input text
        item_name: Parent item name (for context)
        valid_options: List of option dicts with slug/display_name/aliases
        question_text: The question that was asked (unused, kept for API compat)
        model: Ignored (kept for API compatibility)

    Returns:
        AttributeChoiceResponse with matched value, unclear, or wants_cancel
    """
    text = normalize_text(user_input)

    # Check cancel patterns first
    cancel_patterns = ["remove", "cancel", "nevermind", "never mind", "skip", "don't want"]
    if any(p in text for p in cancel_patterns) or menu_cache.is_negative(text):
        return AttributeChoiceResponse(wants_cancel=True)

    if not valid_options:
        return AttributeChoiceResponse(unclear=True)

    # Import here to avoid circular import
    # (validators -> OptionMatcher -> InputNormalizer -> parsers/__init__ -> validators)
    from ..utils.option_matcher import OptionMatcher

    # Use OptionMatcher for robust matching
    matcher = OptionMatcher()
    matched, partial_matches = matcher.match_single(text, valid_options)

    if matched:
        return AttributeChoiceResponse(value=matched["slug"])

    # No unique match found
    return AttributeChoiceResponse(unclear=True)
