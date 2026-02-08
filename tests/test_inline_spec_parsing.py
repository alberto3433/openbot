"""
Tests for inline attribute specification parsing.

Tests the handling of patterns like "2 bagels 1 everything 1 plain"
where users specify attribute values inline with quantity.
"""

import pytest

from orderbot.tasks.parsers.deterministic.inline_spec_parsing import (
    get_primary_configurable_attribute,
    parse_inline_attribute_specs,
    extract_text_after_item_match,
)


class TestGetPrimaryConfigurableAttribute:
    """Tests for get_primary_configurable_attribute function."""

    def test_bagel_returns_bread_attribute(self):
        """Bagel item type should return 'bread' as primary attribute."""
        result = get_primary_configurable_attribute("bagel")
        assert result is not None
        assert result["slug"] == "bread"
        assert len(result["options"]) > 0

    def test_nonexistent_type_returns_none(self):
        """Unknown item type should return None."""
        result = get_primary_configurable_attribute("nonexistent_type_xyz")
        assert result is None


class TestExtractTextAfterItemMatch:
    """Tests for extract_text_after_item_match function."""

    def test_extracts_text_after_bagel(self):
        """Should extract text after 'bagel' trigger."""
        result = extract_text_after_item_match(
            "2 bagels 1 everything 1 plain",
            ["bagel"]
        )
        assert result == "1 everything 1 plain"

    def test_handles_plural_form(self):
        """Should handle plural 'bagels'."""
        result = extract_text_after_item_match(
            "3 bagels 2 plain 1 sesame",
            ["bagel"]
        )
        assert result == "2 plain 1 sesame"

    def test_returns_none_for_no_match(self):
        """Should return None if no trigger found."""
        result = extract_text_after_item_match(
            "2 coffees please",
            ["bagel"]
        )
        assert result is None

    def test_handles_multiple_triggers(self):
        """Should prefer longer trigger matches."""
        result = extract_text_after_item_match(
            "2 plain bagels 1 with cream cheese",
            ["plain bagel", "bagel"]
        )
        # Should match "plain bagels" and return text after
        assert result == "1 with cream cheese"


class TestParseInlineAttributeSpecs:
    """Tests for parse_inline_attribute_specs function."""

    def test_parses_two_specs(self):
        """Should parse '1 everything 1 plain' into 2 specs."""
        result = parse_inline_attribute_specs(
            "1 everything 1 plain",
            total_qty=2,
            item_type_slug="bagel"
        )
        assert result is not None
        assert len(result) == 2

        # Check that we got everything and plain (slugs may include _bagel suffix)
        slugs = {s["attr_value"] for s in result}
        assert any("everything" in s for s in slugs)
        assert any("plain" in s for s in slugs)

        # Check quantities - find by partial match
        everything_spec = next(s for s in result if "everything" in s["attr_value"])
        plain_spec = next(s for s in result if "plain" in s["attr_value"])
        assert everything_spec["quantity"] == 1
        assert plain_spec["quantity"] == 1

    def test_parses_three_specs(self):
        """Should parse '2 plain 1 sesame' into 2 specs (one with qty 2)."""
        result = parse_inline_attribute_specs(
            "2 plain 1 sesame",
            total_qty=3,
            item_type_slug="bagel"
        )
        assert result is not None
        assert len(result) == 2

        # Find by partial match (slugs may include _bagel suffix)
        plain_spec = next(s for s in result if "plain" in s["attr_value"])
        sesame_spec = next(s for s in result if "sesame" in s["attr_value"])
        assert plain_spec["quantity"] == 2
        assert sesame_spec["quantity"] == 1

    def test_partial_spec(self):
        """Should allow partial specs (specified < total)."""
        result = parse_inline_attribute_specs(
            "2 everything",
            total_qty=3,
            item_type_slug="bagel"
        )
        assert result is not None
        assert len(result) == 1
        assert "everything" in result[0]["attr_value"]  # slug may include _bagel suffix
        assert result[0]["quantity"] == 2

    def test_rejects_over_specified(self):
        """Should return None if specs exceed total quantity."""
        result = parse_inline_attribute_specs(
            "2 everything 1 plain",  # Total: 3
            total_qty=2,  # Only ordered 2
            item_type_slug="bagel"
        )
        assert result is None

    def test_no_specs_returns_none(self):
        """Should return None if no valid specs found."""
        result = parse_inline_attribute_specs(
            "with cream cheese",  # No quantity+option pattern
            total_qty=2,
            item_type_slug="bagel"
        )
        assert result is None

    def test_handles_and_separator(self):
        """Should handle 'and' separator between specs."""
        result = parse_inline_attribute_specs(
            "1 everything and 1 plain",
            total_qty=2,
            item_type_slug="bagel"
        )
        assert result is not None
        assert len(result) == 2

    def test_handles_comma_separator(self):
        """Should handle comma separator between specs."""
        result = parse_inline_attribute_specs(
            "1 everything, 1 plain",
            total_qty=2,
            item_type_slug="bagel"
        )
        assert result is not None
        assert len(result) == 2

    def test_includes_attr_slug(self):
        """Each spec should include the attribute slug."""
        result = parse_inline_attribute_specs(
            "1 everything",
            total_qty=1,
            item_type_slug="bagel"
        )
        assert result is not None
        assert result[0]["attr_slug"] == "bread"

    def test_includes_display_name(self):
        """Each spec should include a display name."""
        result = parse_inline_attribute_specs(
            "1 plain",
            total_qty=1,
            item_type_slug="bagel"
        )
        assert result is not None
        assert "display_name" in result[0]
        assert result[0]["display_name"]  # Should be non-empty


class TestIntegration:
    """Integration tests using the full parser."""

    def test_two_bagels_one_everything_one_plain(self):
        """Full integration: '2 bagels 1 everything 1 plain' creates 2 items."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic

        result = parse_open_input_deterministic("2 bagels 1 everything 1 plain")

        assert result is not None
        assert result.parsed_items is not None
        assert len(result.parsed_items) == 2

        # Check that we have 2 separate items with quantity 1 each
        items = result.parsed_items
        assert all(item.quantity == 1 for item in items)

        # Check that bread attributes are set correctly (slugs may include _bagel suffix)
        bread_values = []
        for item in items:
            for sel in item.selections:
                if sel.category == "bread":
                    bread_values.append(sel.slug)

        assert any("everything" in v for v in bread_values)
        assert any("plain" in v for v in bread_values)

    def test_three_bagels_two_plain_one_sesame(self):
        """'3 bagels 2 plain 1 sesame' creates 2 items with correct quantities."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic

        result = parse_open_input_deterministic("3 bagels 2 plain 1 sesame")

        assert result is not None
        assert result.parsed_items is not None
        assert len(result.parsed_items) == 2

        # Get quantities by bread type (slugs may include _bagel suffix)
        items_by_bread = {}
        for item in result.parsed_items:
            for sel in item.selections:
                if sel.category == "bread":
                    items_by_bread[sel.slug] = item.quantity

        # Check by partial match
        plain_qty = next((q for s, q in items_by_bread.items() if "plain" in s), None)
        sesame_qty = next((q for s, q in items_by_bread.items() if "sesame" in s), None)
        assert plain_qty == 2
        assert sesame_qty == 1

    def test_partial_spec_creates_unspecified_item(self):
        """'3 bagels 2 everything' creates 2 items (2 specified + 1 unspecified)."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic

        result = parse_open_input_deterministic("3 bagels 2 everything")

        assert result is not None
        assert result.parsed_items is not None
        # Should have 2 items: one with everything (qty 2), one generic (qty 1)
        assert len(result.parsed_items) == 2

        total_qty = sum(item.quantity for item in result.parsed_items)
        assert total_qty == 3

    def test_plain_two_bagels_no_spec(self):
        """'2 bagels' without specs should create single item with qty 2."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic

        result = parse_open_input_deterministic("2 bagels")

        assert result is not None
        assert result.parsed_items is not None
        # Without inline specs, should create single item with quantity 2
        assert len(result.parsed_items) == 1
        assert result.parsed_items[0].quantity == 2

    def test_over_specified_falls_back_to_regular(self):
        """'2 bagels 2 everything 1 plain' should fall back to regular parsing."""
        from orderbot.tasks.parsers.deterministic.core import parse_open_input_deterministic

        result = parse_open_input_deterministic("2 bagels 2 everything 1 plain")

        # Over-specified (3 > 2), so inline specs should be ignored
        # Should fall back to regular parsing (single item, qty 2)
        assert result is not None
        assert result.parsed_items is not None
        # The exact behavior depends on how regular parsing handles this
        # At minimum, the total quantity should not exceed 2
        total_qty = sum(item.quantity for item in result.parsed_items)
        assert total_qty <= 2
