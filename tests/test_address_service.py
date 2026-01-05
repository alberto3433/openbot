"""
Tests for the address completion service.
"""

from unittest.mock import patch, MagicMock

from sandwich_bot.address_service import (
    complete_address,
    CompletedAddress,
    AddressCompletionResult,
    _extract_zip_code,
    strip_apartment_number,
)


class TestStripApartmentNumber:
    """Tests for apartment number stripping."""

    def test_strip_hash_format(self):
        stripped, apt = strip_apartment_number("355 W 39th St #3A")
        assert stripped == "355 W 39th St"
        assert apt == "#3A"

    def test_strip_apt_format(self):
        stripped, apt = strip_apartment_number("123 Main St Apt 4B")
        assert stripped == "123 Main St"
        assert apt == "Apt 4B"

    def test_strip_apartment_format(self):
        stripped, apt = strip_apartment_number("456 Broadway Apartment 12")
        assert stripped == "456 Broadway"
        assert apt == "Apartment 12"

    def test_strip_unit_format(self):
        stripped, apt = strip_apartment_number("789 Park Ave Unit 5C")
        assert stripped == "789 Park Ave"
        assert apt == "Unit 5C"

    def test_strip_suite_format(self):
        stripped, apt = strip_apartment_number("100 Wall St Suite 200")
        assert stripped == "100 Wall St"
        assert apt == "Suite 200"

    def test_strip_floor_format(self):
        stripped, apt = strip_apartment_number("50 Rockefeller Plz Floor 3")
        assert stripped == "50 Rockefeller Plz"
        assert apt == "Floor 3"

    def test_strip_with_comma(self):
        stripped, apt = strip_apartment_number("355 W 39th St, #3A")
        assert stripped == "355 W 39th St"
        assert apt == "#3A"

    def test_no_apartment(self):
        stripped, apt = strip_apartment_number("123 Main St")
        assert stripped == "123 Main St"
        assert apt is None

    def test_empty_address(self):
        stripped, apt = strip_apartment_number("")
        assert stripped == ""
        assert apt is None

    def test_none_address(self):
        stripped, apt = strip_apartment_number(None)
        assert stripped is None
        assert apt is None


class TestExtractZipCode:
    """Tests for ZIP code extraction helper."""

    def test_extract_from_full_address(self):
        assert _extract_zip_code("123 Main St, New York, NY 10001") == "10001"

    def test_extract_zip_plus_4(self):
        assert _extract_zip_code("456 Broadway, NY 10013-1234") == "10013"

    def test_no_zip(self):
        assert _extract_zip_code("123 Main St, New York") is None

    def test_empty(self):
        assert _extract_zip_code("") is None
        assert _extract_zip_code(None) is None


class TestCompletedAddress:
    """Tests for CompletedAddress dataclass."""

    def test_format_short(self):
        addr = CompletedAddress(
            full_address="123 Main St, City of New York, NY, 10001, USA",
            house_number="123",
            street="Main Street",
            city="City of New York",
            state="NY",
            zip_code="10001",
        )
        assert addr.format_short() == "123 Main Street, City of New York 10001"

    def test_format_full(self):
        addr = CompletedAddress(
            full_address="123 Main St, City of New York, NY, 10001, USA",
            house_number="123",
            street="Main Street",
            city="City of New York",
            state="NY",
            zip_code="10001",
        )
        assert addr.format_full() == "123, Main Street, City of New York, NY, 10001"

    def test_format_full_uses_original_when_no_parts(self):
        """When house_number and street are None, use full_address as fallback."""
        addr = CompletedAddress(
            full_address="456 Broadway, New York, NY 10013",
            house_number=None,
            street=None,
            city="New York",
            state="NY",
            zip_code="10013",
        )
        assert addr.format_full() == "456 Broadway, New York, NY 10013"


class TestAddressCompletionResult:
    """Tests for AddressCompletionResult dataclass."""

    def test_single_match(self):
        addr = CompletedAddress(
            full_address="test",
            house_number="123",
            street="Main St",
            city="NYC",
            state="NY",
            zip_code="10001",
        )
        result = AddressCompletionResult(success=True, addresses=[addr])
        assert result.single_match == addr

    def test_no_single_match_when_multiple(self):
        addr1 = CompletedAddress("", "1", "A St", "NYC", "NY", "10001")
        addr2 = CompletedAddress("", "2", "B St", "NYC", "NY", "10002")
        result = AddressCompletionResult(success=True, addresses=[addr1, addr2])
        assert result.single_match is None


class TestCompleteAddressValidation:
    """Tests for input validation in complete_address."""

    def test_empty_address(self):
        result = complete_address("", ["10001"])
        assert not result.success
        assert "provide a delivery address" in result.error_message

    def test_no_allowed_zips(self):
        result = complete_address("123 Main St", [])
        assert not result.success
        assert "not available" in result.error_message

    def test_none_allowed_zips(self):
        result = complete_address("123 Main St", None)
        assert not result.success
        assert "not available" in result.error_message


class TestCompleteAddressWithExistingZip:
    """Tests when address already has a ZIP code."""

    def test_valid_zip_in_allowed_list(self):
        result = complete_address("123 Main St, NY 10001", ["10001", "10002"])
        assert result.success
        assert len(result.addresses) == 1
        assert result.addresses[0].zip_code == "10001"

    def test_invalid_zip_not_in_list(self):
        result = complete_address("123 Main St, NY 10099", ["10001", "10002"])
        assert not result.success
        assert "10099" in result.error_message
        assert "pickup" in result.error_message.lower()


class TestCompleteAddressWithNominatim:
    """Tests for Nominatim API integration (mocked)."""

    @patch("sandwich_bot.address_service.requests.get")
    def test_single_match_in_delivery_area(self, mock_get):
        """Test successful address completion with single match."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "display_name": "143 Chambers Street, City of New York, NY, 10007, USA",
                "address": {
                    "house_number": "143",
                    "road": "Chambers Street",
                    "city": "City of New York",
                    "state": "New York",
                    "postcode": "10007",
                },
            }
        ]
        mock_get.return_value = mock_response

        result = complete_address("143 Chambers Street", ["10007", "10013"])

        assert result.success
        assert len(result.addresses) == 1
        assert result.addresses[0].zip_code == "10007"
        assert result.addresses[0].house_number == "143"

    @patch("sandwich_bot.address_service.requests.get")
    def test_no_matches_in_delivery_area(self, mock_get):
        """Test when address exists but not in delivery area."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "display_name": "123 Main St, Brooklyn, NY, 11201, USA",
                "address": {
                    "house_number": "123",
                    "road": "Main Street",
                    "city": "Brooklyn",
                    "state": "New York",
                    "postcode": "11201",  # Not in allowed list
                },
            }
        ]
        mock_get.return_value = mock_response

        result = complete_address("123 Main St", ["10007", "10013"])

        assert not result.success
        assert "couldn't find" in result.error_message.lower()

    @patch("sandwich_bot.address_service.requests.get")
    def test_multiple_matches_needs_clarification(self, mock_get):
        """Test when multiple addresses match in different ZIP codes."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "display_name": "500 Broadway, Tribeca, NY, 10013, USA",
                "address": {
                    "house_number": "500",
                    "road": "Broadway",
                    "city": "City of New York",
                    "postcode": "10013",
                },
            },
            {
                "display_name": "500 Broadway, SoHo, NY, 10003, USA",
                "address": {
                    "house_number": "500",
                    "road": "Broadway",
                    "city": "City of New York",
                    "postcode": "10003",
                },
            },
        ]
        mock_get.return_value = mock_response

        result = complete_address("500 Broadway", ["10013", "10003", "10007"])

        assert result.success
        assert result.needs_clarification
        assert len(result.addresses) == 2

    @patch("sandwich_bot.address_service.requests.get")
    def test_deduplicates_same_zip(self, mock_get):
        """Test that duplicate ZIP codes are deduplicated."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "display_name": "40 East 23rd Street, Floor 1, NY, 10010, USA",
                "address": {"house_number": "40", "road": "East 23rd Street", "postcode": "10010"},
            },
            {
                "display_name": "40 East 23rd Street, Floor 2, NY, 10010, USA",
                "address": {"house_number": "40", "road": "East 23rd Street", "postcode": "10010"},
            },
        ]
        mock_get.return_value = mock_response

        result = complete_address("40 East 23rd Street", ["10010"])

        assert result.success
        assert len(result.addresses) == 1  # Deduplicated
        assert not result.needs_clarification

    @patch("sandwich_bot.address_service.requests.get")
    def test_api_error_handled(self, mock_get):
        """Test handling of API errors."""
        mock_get.side_effect = Exception("Network error")

        result = complete_address("123 Main St", ["10001"])

        assert not result.success
        assert "couldn't verify" in result.error_message.lower()

    @patch("sandwich_bot.address_service.requests.get")
    def test_empty_api_response(self, mock_get):
        """Test handling of empty API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        result = complete_address("999 Nonexistent St", ["10001"])

        assert not result.success
        assert "couldn't find" in result.error_message.lower()

    @patch("sandwich_bot.address_service.requests.get")
    def test_apartment_number_stripped_for_query(self, mock_get):
        """Test that apartment numbers are stripped before querying Nominatim."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "display_name": "355 West 39th Street, New York, NY, 10018, USA",
                "address": {
                    "house_number": "355",
                    "road": "West 39th Street",
                    "city": "New York",
                    "state": "New York",
                    "postcode": "10018",
                },
            }
        ]
        mock_get.return_value = mock_response

        result = complete_address("355 W 39th St #3A", ["10018"])

        assert result.success
        assert len(result.addresses) == 1
        # Verify apartment was added back to full_address
        assert "#3A" in result.addresses[0].full_address
        # Verify the query was made with stripped address
        call_args = mock_get.call_args
        query_param = call_args[1]["params"]["q"]
        assert "#3A" not in query_param
        assert "355 W 39th St" in query_param

    @patch("sandwich_bot.address_service.requests.get")
    def test_apartment_preserved_in_full_address_with_existing_zip(self, mock_get):
        """Test that apartment is preserved when ZIP is already provided."""
        # When ZIP is already in address, we don't call Nominatim
        result = complete_address("355 W 39th St #3A, NY 10018", ["10018"])

        assert result.success
        assert len(result.addresses) == 1
        # Original address with apartment should be preserved
        assert "#3A" in result.addresses[0].full_address
        # Nominatim should not have been called
        mock_get.assert_not_called()
