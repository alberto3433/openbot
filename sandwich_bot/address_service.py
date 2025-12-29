"""
Address completion service using Nominatim (OpenStreetMap).

This module provides address autocomplete/validation functionality that:
1. Takes partial addresses like "123 Main St"
2. Queries Nominatim for possible matches in NYC
3. Filters results to only ZIP codes in the store's delivery area
4. Returns completed addresses or None if not deliverable

Rate limits: Nominatim allows 1 request/second (sufficient for voice orders)
Attribution: Results from OpenStreetMap must be attributed
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Nominatim API endpoint
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# User agent (required by Nominatim TOS)
USER_AGENT = "ZuckersOrderBot/1.0 (delivery address validation)"

# Request timeout in seconds
REQUEST_TIMEOUT = 10

# Regex pattern to match apartment/unit numbers
# Matches: #3A, Apt 3A, Apt. 3A, Apartment 3A, Unit 3A, Suite 100, Ste 100, Floor 3, Fl 3
APARTMENT_PATTERN = re.compile(
    r'''
    (?:,?\s*)                           # Optional comma and whitespace before
    (?:
        \#\s*[\w-]+                     # #3A, #123, #3-A
        |
        (?:apt|apartment|unit|suite|ste|floor|fl)\.?\s*[\w-]+  # Apt 3A, Suite 100, etc.
    )
    (?:\s*,?\s*)?                       # Optional comma and whitespace after
    ''',
    re.IGNORECASE | re.VERBOSE
)


def strip_apartment_number(address: str) -> tuple[str, str | None]:
    """
    Strip apartment/unit numbers from an address for geocoding.

    Nominatim doesn't handle apartment numbers well, so we strip them
    before querying but preserve the original for storage.

    Args:
        address: The full address possibly containing an apartment number

    Returns:
        Tuple of (stripped_address, apartment_number or None)
    """
    if not address:
        return (address, None)

    match = APARTMENT_PATTERN.search(address)
    if match:
        apartment = match.group(0).strip().strip(',').strip()
        stripped = APARTMENT_PATTERN.sub('', address).strip().strip(',').strip()
        # Clean up any double spaces
        stripped = re.sub(r'\s+', ' ', stripped)
        return (stripped, apartment)

    return (address, None)


@dataclass
class CompletedAddress:
    """A validated and completed address."""
    full_address: str
    house_number: Optional[str]
    street: Optional[str]
    city: str
    state: str
    zip_code: str

    def format_short(self) -> str:
        """Format as a short address for confirmation."""
        if self.house_number and self.street:
            return f"{self.house_number} {self.street}, {self.city} {self.zip_code}"
        return f"{self.street or 'Unknown'}, {self.city} {self.zip_code}"

    def format_full(self) -> str:
        """Format as a full address for storage."""
        # If we don't have structured parts, use the original full_address
        if not self.house_number and not self.street and self.full_address:
            return self.full_address
        parts = []
        if self.house_number:
            parts.append(self.house_number)
        if self.street:
            parts.append(self.street)
        parts.append(self.city)
        parts.append(self.state)
        parts.append(self.zip_code)
        return ", ".join(parts)


@dataclass
class AddressCompletionResult:
    """Result of address completion attempt."""
    success: bool
    addresses: list[CompletedAddress]
    error_message: Optional[str] = None
    needs_clarification: bool = False

    @property
    def single_match(self) -> Optional[CompletedAddress]:
        """Return the address if there's exactly one match."""
        if len(self.addresses) == 1:
            return self.addresses[0]
        return None


def complete_address(
    partial_address: str,
    allowed_zip_codes: list[str],
    city: str = "New York",
    state: str = "NY",
) -> AddressCompletionResult:
    """
    Complete a partial address and validate it's in the delivery area.

    Args:
        partial_address: The partial address (e.g., "123 Main St")
        allowed_zip_codes: List of ZIP codes where delivery is available
        city: City to search in (default: New York)
        state: State to search in (default: NY)

    Returns:
        AddressCompletionResult with matched addresses or error
    """
    if not partial_address or not partial_address.strip():
        return AddressCompletionResult(
            success=False,
            addresses=[],
            error_message="Please provide a delivery address.",
        )

    if not allowed_zip_codes:
        return AddressCompletionResult(
            success=False,
            addresses=[],
            error_message="Sorry, delivery is not available from this location.",
        )

    # Strip apartment number before processing (Nominatim doesn't handle them well)
    stripped_address, apartment = strip_apartment_number(partial_address)

    # Check if address already has a ZIP code
    existing_zip = _extract_zip_code(partial_address)
    if existing_zip:
        if existing_zip in allowed_zip_codes:
            # ZIP is valid, return as-is (user provided complete address)
            return AddressCompletionResult(
                success=True,
                addresses=[CompletedAddress(
                    full_address=partial_address,
                    house_number=None,
                    street=None,
                    city=city,
                    state=state,
                    zip_code=existing_zip,
                )],
            )
        else:
            return AddressCompletionResult(
                success=False,
                addresses=[],
                error_message=f"Sorry, we don't deliver to {existing_zip}. Would you like to do pickup instead?",
            )

    # Query Nominatim for address completion (using stripped address without apartment)
    try:
        matches = _query_nominatim(stripped_address, city, state, allowed_zip_codes)
    except Exception as e:
        logger.error("Nominatim query failed: %s", e)
        return AddressCompletionResult(
            success=False,
            addresses=[],
            error_message="I couldn't verify that address. Could you include the ZIP code?",
        )

    if not matches:
        return AddressCompletionResult(
            success=False,
            addresses=[],
            error_message="I couldn't find that address in our delivery area. Could you check the address or provide the ZIP code?",
        )

    # Add apartment number back to matches if it was stripped
    if apartment:
        for match in matches:
            # Build full address with apartment number included
            if match.house_number and match.street:
                match.full_address = f"{match.house_number} {match.street} {apartment}, {match.city}, {match.state} {match.zip_code}"
            else:
                # Insert apartment after first part of address
                parts = match.full_address.split(',', 1)
                if len(parts) > 1:
                    match.full_address = f"{parts[0]} {apartment},{parts[1]}"
                else:
                    match.full_address = f"{match.full_address} {apartment}"

    # Deduplicate by ZIP code (keep first match per ZIP)
    seen_zips = set()
    unique_matches = []
    for match in matches:
        if match.zip_code not in seen_zips:
            seen_zips.add(match.zip_code)
            unique_matches.append(match)

    if len(unique_matches) == 1:
        return AddressCompletionResult(
            success=True,
            addresses=unique_matches,
        )

    # Multiple matches - need clarification
    return AddressCompletionResult(
        success=True,
        addresses=unique_matches,
        needs_clarification=True,
    )


def _query_nominatim(
    partial_address: str,
    city: str,
    state: str,
    allowed_zip_codes: list[str],
) -> list[CompletedAddress]:
    """
    Query Nominatim API for address matches.

    Args:
        partial_address: The partial address to search
        city: City context
        state: State context
        allowed_zip_codes: ZIP codes to filter by

    Returns:
        List of matching CompletedAddress objects
    """
    # Build query with city context for better results
    query = f"{partial_address}, {city}, {state}"

    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "countrycodes": "us",
        "limit": 10,
    }

    headers = {"User-Agent": USER_AGENT}

    logger.debug("Querying Nominatim: %s", query)

    response = requests.get(
        NOMINATIM_URL,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    results = response.json()
    logger.debug("Nominatim returned %d results", len(results))

    matches = []
    for result in results:
        addr = result.get("address", {})
        postcode = addr.get("postcode", "")

        # Only include if ZIP is in allowed delivery areas
        if postcode not in allowed_zip_codes:
            continue

        # Extract address components
        house_number = addr.get("house_number")
        road = addr.get("road")
        city_name = (
            addr.get("city") or
            addr.get("town") or
            addr.get("borough") or
            addr.get("municipality") or
            city
        )
        state_name = addr.get("state", state)

        matches.append(CompletedAddress(
            full_address=result.get("display_name", ""),
            house_number=house_number,
            street=road,
            city=city_name,
            state=state_name,
            zip_code=postcode,
        ))

    return matches


def _extract_zip_code(address: str) -> Optional[str]:
    """Extract a 5-digit ZIP code from an address string."""
    if not address:
        return None

    zip_pattern = r'\b(\d{5})(?:-\d{4})?\b'
    match = re.search(zip_pattern, address)
    if match:
        return match.group(1)

    return None


def geocode_to_zip(
    address: str,
    city: str = "New York",
    state: str = "NY",
) -> Optional[str]:
    """
    Geocode an address and return just the ZIP code.

    Useful for delivery zone inquiries where we need to determine
    the ZIP code from a partial address like "1065 5th Ave".

    Args:
        address: The address to geocode (e.g., "1065 5th Ave")
        city: City context (default: New York)
        state: State context (default: NY)

    Returns:
        ZIP code string if found, None otherwise
    """
    if not address or not address.strip():
        return None

    # First check if there's already a ZIP in the address
    existing_zip = _extract_zip_code(address)
    if existing_zip:
        return existing_zip

    # Strip apartment number for better geocoding
    stripped_address, _ = strip_apartment_number(address)

    # Build query with city context
    query = f"{stripped_address}, {city}, {state}"

    params = {
        "q": query,
        "format": "json",
        "addressdetails": 1,
        "countrycodes": "us",
        "limit": 1,  # Just need the best match
    }

    headers = {"User-Agent": USER_AGENT}

    try:
        logger.debug("Geocoding for ZIP: %s", query)
        response = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        results = response.json()
        if results:
            addr = results[0].get("address", {})
            postcode = addr.get("postcode", "")
            if postcode:
                logger.debug("Geocoded '%s' to ZIP: %s", address, postcode)
                return postcode

    except Exception as e:
        logger.warning("Geocoding failed for '%s': %s", address, e)

    return None


def format_address_options(addresses: list[CompletedAddress]) -> str:
    """
    Format multiple address options for user clarification.

    Args:
        addresses: List of possible addresses

    Returns:
        Formatted string asking user to choose
    """
    if not addresses:
        return "I couldn't find any matching addresses."

    if len(addresses) == 1:
        return f"Is this the right address: {addresses[0].format_short()}?"

    options = []
    for i, addr in enumerate(addresses, 1):
        options.append(f"{i}. {addr.format_short()}")

    return "I found a few possible addresses:\n" + "\n".join(options) + "\nWhich one is correct?"
