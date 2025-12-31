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
        # check_deliverability=False - only check syntax, don't do DNS/MX lookups
        # DNS checks are overly strict: domains may be valid but have temporary DNS issues,
        # use private mail servers, or be new TLDs not in the library's list.
        # We should accept syntactically valid emails and handle bounces asynchronously.
        result = validate_email(email, check_deliverability=False)
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


def parse_yes_no_deterministic(
    user_input: str,
    no_patterns: str | None = None,
    yes_patterns: str | None = None,
) -> bool | None:
    """
    Deterministically parse yes/no responses using regex patterns.

    Checks NO patterns FIRST (before yes) to handle phrases like
    "not toasted" which contains "toasted" but means no.

    Args:
        user_input: The user's response text
        no_patterns: Regex pattern for negative responses.
                     Defaults to common negative words.
        yes_patterns: Regex pattern for positive responses.
                      Defaults to common positive words.

    Returns:
        True if positive, False if negative, None if unclear
    """
    if not user_input:
        return None

    input_lower = user_input.lower().strip()

    # Default patterns
    if no_patterns is None:
        no_patterns = r'\b(no|nope|nah|not|don\'t|none|neither)\b'
    if yes_patterns is None:
        yes_patterns = r'\b(yes|yeah|yep|yup|sure|please|ok|okay)\b'

    # Check NO first (important for "not X" phrases)
    if re.search(no_patterns, input_lower):
        return False

    # Then check YES
    if re.search(yes_patterns, input_lower):
        return True

    return None


def parse_toasted_deterministic(user_input: str) -> bool | None:
    """
    Deterministically parse toasted preference.

    Handles special cases like "not toasted", "untoasted", "toast it".

    Returns:
        True if wants toasted, False if not, None if unclear
    """
    return parse_yes_no_deterministic(
        user_input,
        no_patterns=r'\b(not toasted|untoasted|don\'t toast|no|nope|nah)\b',
        yes_patterns=r'\b(yes|yeah|yep|yup|sure|please|toasted|toast it)\b',
    )


def parse_hot_iced_deterministic(user_input: str) -> bool | None:
    """
    Deterministically parse hot/iced preference for coffee.

    Returns:
        True if wants iced, False if wants hot, None if unclear
    """
    input_lower = user_input.lower()

    if re.search(r'\b(iced|cold)\b', input_lower):
        return True
    if re.search(r'\b(hot|warm|regular)\b', input_lower):
        return False

    return None


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
