"""
Test for the spread capture fix.

Bug: When answering config question with 'plain bagel toasted scooped with cream cheese':
- toasted=True was captured (boolean attribute)
- scooped=True was captured (boolean attribute)
- spread=cream_cheese was NOT captured (single_select attribute)

Root cause: capture_attributes_from_input() used exact_only=True which disabled
Phase 3 matching (option name contained in user input).

Fix: Added Phase 3 fallback after exact match fails.
"""

import pytest
from orderbot.tasks.state_machine import OrderStateMachine
from orderbot.tasks.models import OrderTask
from orderbot.tasks.schemas import OrderPhase


class TestSpreadCaptureFromConfigAnswer:
    """Test spread capture when included in config answer."""

    def test_spread_captured_from_full_phrase(self):
        """
        Test that spread is captured when answering config question with full phrase.

        Input: 'plain bagel toasted scooped with cream cheese'
        Expected: toasted=True, scooped=True, spread=cream_cheese
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Initial order - just a plain bagel
        result = sm.process("plain bagel", order)

        # Answer the toasted question with full phrase including spread
        result = sm.process("plain bagel toasted scooped with cream cheese", result.order)

        items = result.order.items.get_active_items()
        assert len(items) == 1, f"Should have 1 item, got {len(items)}"

        item = items[0]

        # Check boolean attributes were captured
        assert item.attribute_values.get("toasted") is True, "toasted should be True"
        assert item.attribute_values.get("scooped") is True, "scooped should be True"

        # Check spread was captured - this is the key fix
        spread_selections = item.get_selections("spread")
        assert len(spread_selections) > 0, f"spread should be captured! Selections: {item.selections}"
        # Selection can be either an object with .slug or a dict with 'slug' key
        first_sel = spread_selections[0]
        slug = first_sel.slug if hasattr(first_sel, "slug") else first_sel.get("slug")
        assert slug in ("cream_cheese", "plain_cream_cheese"), (
            f"Expected cream cheese, got {slug}"
        )

    def test_spread_not_falsely_matched_from_omelette(self):
        """
        Ensure Phase 2 remains disabled - 'omelette' should not match option slugs.

        This tests that we don't regress by enabling Phase 2 which would allow
        'omelette' to falsely match 'omelette_gf_everything_bagel' bread option.
        """
        order = OrderTask()
        order.phase = OrderPhase.TAKING_ITEMS.value
        sm = OrderStateMachine()

        # Order omelette
        result = sm.process("cheese omelette", order)

        items = result.order.items.get_active_items()
        assert len(items) >= 1, "Should have omelette"

        omelette = items[0]

        # The bread attribute should NOT be set to omelette_gf_everything_bagel
        # (which would happen if Phase 2 was enabled)
        bread_selections = omelette.get_selections("bread")
        for sel in bread_selections:
            assert "omelette" not in sel.slug.lower(), (
                f"bread should not be set based on item name 'omelette': {sel.slug}"
            )
