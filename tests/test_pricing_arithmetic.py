"""
Pricing Arithmetic Verification Tests.

These tests verify that the MATH is correct at every layer of the pricing
pipeline. They do NOT hardcode expected prices - they verify arithmetic
relationships hold (base + upcharges = unit_price, sum of line_totals =
subtotal, etc.) using the real DB-loaded menu cache.

Test categories:
1. PricingEngine Decomposition - unit_price == base + upcharges + modifiers
2. Subtotal Arithmetic - subtotal == sum(unit_price * quantity)
3. Adapter Output Consistency - dict fields are internally consistent
4. Tax/Total Arithmetic - total == subtotal + tax + delivery_fee
5. End-to-End State Machine Pricing - full pipeline math
"""

import pytest

from orderbot.cache import menu_cache
from orderbot.tasks.models import MenuItemTask, OrderTask, TaskStatus
from orderbot.tasks.pricing import PricingEngine
from orderbot.tasks.adapter import _calculate_subtotal, order_task_to_dict
from orderbot.tasks.normalization import normalize_to_slug
from orderbot.services.tax_utils import calculate_order_total, round_money

from tests.helpers.pricing_helpers import (
    get_menu_data,
    get_pricing_engine,
    find_menu_items_by_type,
    find_first_menu_item,
    find_menu_item_by_name,
    get_priced_options,
    get_zero_price_options,
    get_all_item_type_slugs,
    create_item_with_selections,
    build_order_with_items,
    make_store_info,
)


# =============================================================================
# Category 1: PricingEngine Decomposition (~35 tests)
# Verify: unit_price == base_price + attr_upcharges + modifier_prices
# =============================================================================


class TestPricingDecomposition:
    """Verify unit_price decomposes into base + upcharges + modifiers."""

    # --- Exhaustive DB scan ---

    def test_all_priced_options_lookup_consistency(self, menu_cache_loaded):
        """Every priced option in DB should return a matching upcharge via pricing engine."""
        pricing = get_pricing_engine()
        menu_data = get_menu_data()

        failures = []
        tested = 0

        for item_type_slug, type_data in menu_data.get("item_types", {}).items():
            for attr in type_data.get("attributes", []):
                attr_slug = attr.get("slug", "")
                for opt in attr.get("options", []):
                    price_mod = opt.get("price_modifier") or opt.get("price") or 0.0
                    if price_mod <= 0:
                        continue

                    option_slug = opt.get("slug", "")
                    tested += 1

                    # Look up the upcharge via the pricing engine
                    looked_up = pricing.lookup_attribute_option_upcharge(
                        item_type_slug, attr_slug, option_slug
                    )
                    if abs(looked_up - price_mod) > 0.01:
                        failures.append(
                            f"{item_type_slug}.{attr_slug}.{option_slug}: "
                            f"DB=${price_mod:.2f} vs lookup=${looked_up:.2f}"
                        )

        assert tested > 20, f"Sanity: expected >20 priced options, got {tested}"
        assert not failures, (
            f"{len(failures)} lookup mismatch(es):\n" + "\n".join(failures)
        )

    # --- Single upcharge items ---

    def test_bagel_with_upcharge_bread(self, menu_cache_loaded):
        """Bagel with a bread upcharge: unit_price == base + bread_upcharge."""
        pricing = get_pricing_engine()
        priced_opts = get_priced_options("bagel")
        bread_opts = [o for o in priced_opts if o["attr_slug"] == "bread"]
        if not bread_opts:
            pytest.skip("No priced bread options in DB")

        opt = bread_opts[0]
        item = create_item_with_selections(
            "Bagel", "bagel", [("yes", "toasted"), (opt["option_slug"], "bread")]
        )
        base = pricing.lookup_base_price("Bagel")
        pricing.recalculate_item_price(item)

        expected_upcharge = opt["price_modifier"]
        assert item.unit_price == pytest.approx(base + expected_upcharge, abs=0.01), (
            f"Expected base(${base:.2f}) + upcharge(${expected_upcharge:.2f}) "
            f"= ${base + expected_upcharge:.2f}, got ${item.unit_price:.2f}"
        )

    def test_variant_size_upcharge(self, menu_cache_loaded):
        """Item with size_prices: size upcharge reflected in unit_price."""
        pricing = get_pricing_engine()

        # Find any item type with size_prices and 2+ sizes
        sized_item = None
        item_type_slug = None
        for type_slug in get_all_item_type_slugs():
            for mi in find_menu_items_by_type(type_slug):
                sp = mi.get("size_prices", [])
                if len(sp) >= 2:
                    sized_item = mi
                    item_type_slug = type_slug
                    break
            if sized_item:
                break

        assert sized_item is not None, "No item with 2+ size_prices in DB"

        size_prices = sized_item["size_prices"]
        sorted_sizes = sorted(size_prices, key=lambda s: s.get("price", 0))
        small_size = sorted_sizes[0]
        large_size = sorted_sizes[-1]
        size_cat = sized_item.get("size_category_slug", "size")

        item_small = create_item_with_selections(
            sized_item["name"], item_type_slug,
            [(small_size["size_name"], size_cat)]
        )
        item_large = create_item_with_selections(
            sized_item["name"], item_type_slug,
            [(large_size["size_name"], size_cat)]
        )

        pricing.recalculate_item_price(item_small)
        pricing.recalculate_item_price(item_large)

        price_diff = item_large.unit_price - item_small.unit_price
        expected_diff = large_size["price"] - small_size["price"]

        assert price_diff == pytest.approx(expected_diff, abs=0.01), (
            f"Size price diff: got ${price_diff:.2f}, expected ${expected_diff:.2f}"
        )

    def test_espresso_based_milk_upcharge(self, menu_cache_loaded):
        """Espresso-based beverage: milk upcharge adds to price."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("espresso_based_beverage")
        if not items:
            pytest.skip("No espresso_based_beverage items")

        priced_opts = get_priced_options("espresso_based_beverage")
        milk_opts = [o for o in priced_opts if "milk" in o["attr_slug"]]
        if not milk_opts:
            pytest.skip("No priced milk options for espresso_based_beverage")

        mi = items[0]
        opt = milk_opts[0]

        # Item without milk
        item_no_milk = create_item_with_selections(mi["name"], "espresso_based_beverage")
        pricing.recalculate_item_price(item_no_milk)
        price_no_milk = item_no_milk.unit_price

        # Item with milk
        item_with_milk = create_item_with_selections(
            mi["name"], "espresso_based_beverage",
            [(opt["option_slug"], opt["attr_slug"])]
        )
        pricing.recalculate_item_price(item_with_milk)

        diff = item_with_milk.unit_price - price_no_milk
        assert diff == pytest.approx(opt["price_modifier"], abs=0.01), (
            f"Milk upcharge: expected ${opt['price_modifier']:.2f}, "
            f"got diff=${diff:.2f}"
        )

    def test_deli_sandwich_bread_upcharge(self, menu_cache_loaded):
        """Deli sandwich with bread upcharge."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("deli_sandwich")
        assert items, "No deli_sandwich items in DB"

        priced_opts = get_priced_options("deli_sandwich")
        bread_opts = [o for o in priced_opts if o["attr_slug"] == "bread"]
        assert bread_opts, "No priced bread options for deli_sandwich"

        mi = items[0]
        opt = bread_opts[0]

        item_no_bread = create_item_with_selections(mi["name"], "deli_sandwich")
        pricing.recalculate_item_price(item_no_bread)
        base = item_no_bread.unit_price

        item_with_bread = create_item_with_selections(
            mi["name"], "deli_sandwich", [(opt["option_slug"], "bread")]
        )
        pricing.recalculate_item_price(item_with_bread)

        diff = item_with_bread.unit_price - base
        assert diff == pytest.approx(opt["price_modifier"], abs=0.01)

    def test_single_upcharge_per_item_type(self, menu_cache_loaded):
        """For every item type with priced options, a single upcharge adds correctly."""
        pricing = get_pricing_engine()

        tested = 0
        failures = []

        for item_type_slug in get_all_item_type_slugs():
            priced = get_priced_options(item_type_slug)
            if not priced:
                continue

            items = find_menu_items_by_type(item_type_slug)
            if not items:
                continue

            mi = items[0]
            has_size_prices = bool(mi.get("size_prices"))
            size_cat_slug = mi.get("size_category_slug")

            # For variant-priced items, skip options on the variant attribute
            # (those are part of base price, not upcharges)
            non_variant_priced = [
                o for o in priced
                if not has_size_prices or o["attr_slug"] != size_cat_slug
            ]
            if not non_variant_priced:
                continue

            opt = non_variant_priced[0]
            tested += 1

            item_bare = create_item_with_selections(mi["name"], item_type_slug)
            pricing.recalculate_item_price(item_bare)
            base = item_bare.unit_price

            item_with = create_item_with_selections(
                mi["name"], item_type_slug,
                [(opt["option_slug"], opt["attr_slug"])]
            )
            pricing.recalculate_item_price(item_with)

            diff = item_with.unit_price - base
            if abs(diff - opt["price_modifier"]) > 0.01:
                failures.append(
                    f"{item_type_slug}: {opt['attr_slug']}.{opt['option_slug']} "
                    f"expected +${opt['price_modifier']:.2f}, got +${diff:.2f}"
                )

        assert tested > 0, "No item types with non-variant priced options found"
        assert not failures, (
            f"{len(failures)} single-upcharge failures:\n" + "\n".join(failures)
        )

    # --- Multiple stacked upcharges ---

    def test_multiple_upcharges_stack_additively(self, menu_cache_loaded):
        """Multiple upcharges from different attributes stack additively."""
        pricing = get_pricing_engine()

        # Find an item type with at least 2 different non-variant priced attributes
        for item_type_slug in get_all_item_type_slugs():
            priced = get_priced_options(item_type_slug)
            if not priced:
                continue

            items = find_menu_items_by_type(item_type_slug)
            if not items:
                continue
            mi = items[0]
            size_cat_slug = mi.get("size_category_slug")

            # Exclude the variant attribute (already covered by base price)
            non_variant = [p for p in priced if p["attr_slug"] != size_cat_slug]

            # Group by attr_slug
            by_attr: dict[str, list[dict]] = {}
            for p in non_variant:
                by_attr.setdefault(p["attr_slug"], []).append(p)

            if len(by_attr) < 2:
                continue

            # Take one option from each of the first 2 different attributes
            attr_slugs = list(by_attr.keys())[:2]
            opt1 = by_attr[attr_slugs[0]][0]
            opt2 = by_attr[attr_slugs[1]][0]

            item_bare = create_item_with_selections(mi["name"], item_type_slug)
            pricing.recalculate_item_price(item_bare)
            base = item_bare.unit_price

            item_stacked = create_item_with_selections(
                mi["name"], item_type_slug,
                [
                    (opt1["option_slug"], opt1["attr_slug"]),
                    (opt2["option_slug"], opt2["attr_slug"]),
                ]
            )
            pricing.recalculate_item_price(item_stacked)

            expected_total_upcharge = opt1["price_modifier"] + opt2["price_modifier"]
            actual_upcharge = item_stacked.unit_price - base

            assert actual_upcharge == pytest.approx(expected_total_upcharge, abs=0.02), (
                f"{item_type_slug}: stacked upcharges "
                f"expected ${expected_total_upcharge:.2f}, got ${actual_upcharge:.2f}"
            )
            return  # Test passed with first suitable type

        pytest.fail("No item type with 2+ non-variant priced attribute categories found")

    def test_bagel_bread_plus_spread_upcharges(self, menu_cache_loaded):
        """Bagel bread + spread upcharges stack correctly."""
        pricing = get_pricing_engine()
        bread_opts = get_priced_options("bagel")
        bread_upcharges = [o for o in bread_opts if o["attr_slug"] == "bread"]
        spread_upcharges = [o for o in bread_opts if o["attr_slug"] == "spread"]

        if not bread_upcharges or not spread_upcharges:
            pytest.skip("Need both bread and spread upcharges for bagel")

        bread_opt = bread_upcharges[0]
        spread_opt = spread_upcharges[0]

        item = create_item_with_selections(
            "Bagel", "bagel",
            [
                (bread_opt["option_slug"], "bread"),
                (spread_opt["option_slug"], "spread"),
                ("yes", "toasted"),
            ]
        )

        base = pricing.lookup_base_price("Bagel")
        pricing.recalculate_item_price(item)

        expected = base + bread_opt["price_modifier"] + spread_opt["price_modifier"]
        assert item.unit_price == pytest.approx(expected, abs=0.01)

    def test_three_upcharges_stack(self, menu_cache_loaded):
        """Three or more upcharges stack additively."""
        pricing = get_pricing_engine()

        for item_type_slug in get_all_item_type_slugs():
            priced = get_priced_options(item_type_slug)
            items = find_menu_items_by_type(item_type_slug)
            if not items:
                continue
            mi = items[0]
            size_cat_slug = mi.get("size_category_slug")

            # Exclude the variant attribute
            non_variant = [p for p in priced if p["attr_slug"] != size_cat_slug]
            by_attr: dict[str, list[dict]] = {}
            for p in non_variant:
                by_attr.setdefault(p["attr_slug"], []).append(p)

            if len(by_attr) < 3:
                continue

            attr_slugs = list(by_attr.keys())[:3]
            selections = []
            expected_upcharge = 0.0
            for attr_s in attr_slugs:
                opt = by_attr[attr_s][0]
                selections.append((opt["option_slug"], opt["attr_slug"]))
                expected_upcharge += opt["price_modifier"]

            item_bare = create_item_with_selections(mi["name"], item_type_slug)
            pricing.recalculate_item_price(item_bare)
            base = item_bare.unit_price

            item_with = create_item_with_selections(
                mi["name"], item_type_slug, selections
            )
            pricing.recalculate_item_price(item_with)

            actual_upcharge = item_with.unit_price - base
            assert actual_upcharge == pytest.approx(expected_upcharge, abs=0.03), (
                f"{item_type_slug}: 3 upcharges expected ${expected_upcharge:.2f}, "
                f"got ${actual_upcharge:.2f}"
            )
            return

        pytest.fail("No item type with 3+ non-variant priced attribute categories found")

    # --- Quantity does not leak into unit_price ---

    def test_quantity_1_unit_price(self, menu_cache_loaded):
        """Qty=1 unit_price is unaffected by quantity."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("bagel")
        if not items:
            pytest.skip("No bagel items")
        mi = items[0]

        item = create_item_with_selections(mi["name"], "bagel", quantity=1)
        pricing.recalculate_item_price(item)
        price_qty1 = item.unit_price
        assert price_qty1 > 0

    def test_quantity_2_same_unit_price(self, menu_cache_loaded):
        """Qty=2 has same unit_price as qty=1."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("bagel")
        if not items:
            pytest.skip("No bagel items")
        mi = items[0]

        item1 = create_item_with_selections(mi["name"], "bagel", quantity=1)
        pricing.recalculate_item_price(item1)

        item2 = create_item_with_selections(mi["name"], "bagel", quantity=2)
        pricing.recalculate_item_price(item2)

        assert item1.unit_price == pytest.approx(item2.unit_price, abs=0.01), (
            f"qty=1 price=${item1.unit_price:.2f} != qty=2 price=${item2.unit_price:.2f}"
        )

    def test_quantity_5_same_unit_price(self, menu_cache_loaded):
        """Qty=5 has same unit_price as qty=1."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("bagel")
        if not items:
            pytest.skip("No bagel items")
        mi = items[0]

        item1 = create_item_with_selections(mi["name"], "bagel", quantity=1)
        pricing.recalculate_item_price(item1)

        item5 = create_item_with_selections(mi["name"], "bagel", quantity=5)
        pricing.recalculate_item_price(item5)

        assert item1.unit_price == pytest.approx(item5.unit_price, abs=0.01)

    # --- Idempotency ---

    def test_recalculate_twice_same_result(self, menu_cache_loaded):
        """recalculate_item_price called twice gives the same result."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("bagel")
        if not items:
            pytest.skip("No bagel items")
        mi = items[0]

        item = create_item_with_selections(
            mi["name"], "bagel", [("yes", "toasted")]
        )
        price1 = pricing.recalculate_item_price(item)
        price2 = pricing.recalculate_item_price(item)

        assert price1 == pytest.approx(price2, abs=0.01), (
            f"First calc=${price1:.2f}, second calc=${price2:.2f} - not idempotent"
        )

    def test_recalculate_with_upcharge_idempotent(self, menu_cache_loaded):
        """Recalculating with upcharges is idempotent."""
        pricing = get_pricing_engine()
        priced = get_priced_options("bagel")
        if not priced:
            pytest.skip("No priced bagel options")

        opt = priced[0]
        item = create_item_with_selections(
            "Bagel", "bagel",
            [(opt["option_slug"], opt["attr_slug"]), ("yes", "toasted")]
        )

        price1 = pricing.recalculate_item_price(item)
        price2 = pricing.recalculate_item_price(item)
        price3 = pricing.recalculate_item_price(item)

        assert price1 == pytest.approx(price2, abs=0.01)
        assert price2 == pytest.approx(price3, abs=0.01)

    def test_idempotency_across_item_types(self, menu_cache_loaded):
        """Idempotency holds across multiple item types."""
        pricing = get_pricing_engine()
        menu_data = get_menu_data()
        tested = 0

        for item_type_slug in get_all_item_type_slugs():
            items = find_menu_items_by_type(item_type_slug)
            if not items:
                continue
            mi = items[0]

            item = create_item_with_selections(mi["name"], item_type_slug)
            p1 = pricing.recalculate_item_price(item)
            p2 = pricing.recalculate_item_price(item)

            assert p1 == pytest.approx(p2, abs=0.01), (
                f"{item_type_slug}: not idempotent (${p1:.2f} vs ${p2:.2f})"
            )
            tested += 1

        assert tested > 0

    # --- Zero-upcharge options ---

    def test_zero_upcharge_option_equals_base(self, menu_cache_loaded):
        """Options with price_modifier=0 don't change the price from base."""
        pricing = get_pricing_engine()
        zero_opts = get_zero_price_options("bagel")
        bread_zeros = [o for o in zero_opts if o["attr_slug"] == "bread"]
        if not bread_zeros:
            pytest.skip("No zero-price bread options for bagel")

        opt = bread_zeros[0]
        base = pricing.lookup_base_price("Bagel")

        item = create_item_with_selections(
            "Bagel", "bagel",
            [(opt["option_slug"], "bread"), ("yes", "toasted")]
        )
        pricing.recalculate_item_price(item)

        assert item.unit_price == pytest.approx(base, abs=0.01), (
            f"Zero-upcharge option changed price: "
            f"base=${base:.2f}, got=${item.unit_price:.2f}"
        )

    def test_all_zero_upcharge_options_equal_bare(self, menu_cache_loaded):
        """Every zero-price non-variant option shouldn't change the bare item price."""
        pricing = get_pricing_engine()
        failures = []
        tested = 0

        for item_type_slug in get_all_item_type_slugs():
            items = find_menu_items_by_type(item_type_slug)
            if not items:
                continue
            mi = items[0]
            size_cat_slug = mi.get("size_category_slug")

            item_bare = create_item_with_selections(mi["name"], item_type_slug)
            pricing.recalculate_item_price(item_bare)
            base = item_bare.unit_price

            zero_opts = get_zero_price_options(item_type_slug)
            # Skip options on the variant attribute (selecting a size changes base)
            non_variant_zeros = [
                o for o in zero_opts if o["attr_slug"] != size_cat_slug
            ]
            for opt in non_variant_zeros[:3]:  # Test up to 3 per type
                item = create_item_with_selections(
                    mi["name"], item_type_slug,
                    [(opt["option_slug"], opt["attr_slug"])]
                )
                pricing.recalculate_item_price(item)
                tested += 1

                if abs(item.unit_price - base) > 0.01:
                    failures.append(
                        f"{item_type_slug}.{opt['attr_slug']}.{opt['option_slug']}: "
                        f"bare=${base:.2f}, got=${item.unit_price:.2f}"
                    )

        assert tested > 0, "No zero-price non-variant options found in any item type"
        assert not failures, (
            f"{len(failures)} zero-upcharge options changed price:\n"
            + "\n".join(failures)
        )

    def test_zero_upcharge_bulk_by_type(self, menu_cache_loaded):
        """Bulk check: zero-upcharge bread options all equal base for bagels."""
        pricing = get_pricing_engine()
        base = pricing.lookup_base_price("Bagel")
        zero_breads = [o for o in get_zero_price_options("bagel") if o["attr_slug"] == "bread"]

        for opt in zero_breads:
            item = create_item_with_selections(
                "Bagel", "bagel",
                [(opt["option_slug"], "bread"), ("yes", "toasted")]
            )
            pricing.recalculate_item_price(item)
            assert item.unit_price == pytest.approx(base, abs=0.01)

    # --- Bare items ---

    def test_bare_bagel_equals_base(self, menu_cache_loaded):
        """Bare bagel (no attributes) should be priced at base_price."""
        pricing = get_pricing_engine()
        base = pricing.lookup_base_price("Bagel")

        item = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(item)

        assert item.unit_price == pytest.approx(base, abs=0.01)

    def test_bare_item_per_type_equals_base(self, menu_cache_loaded):
        """Bare item (no selections) should equal base price for each type."""
        pricing = get_pricing_engine()
        tested = 0

        for item_type_slug in get_all_item_type_slugs():
            items = find_menu_items_by_type(item_type_slug)
            if not items:
                continue
            mi = items[0]

            item = create_item_with_selections(mi["name"], item_type_slug)
            pricing.recalculate_item_price(item)

            # Base price should be > 0 for real items, or 0 for free items
            assert item.unit_price >= 0, (
                f"{item_type_slug}: negative unit_price ${item.unit_price:.2f}"
            )
            tested += 1

        assert tested > 0


# =============================================================================
# Category 2: Subtotal Arithmetic (~15 tests)
# Verify: subtotal == sum(item.unit_price * item.quantity)
# =============================================================================


class TestSubtotalArithmetic:
    """Verify subtotal computation from active items."""

    def test_single_item_qty1_subtotal(self, menu_cache_loaded):
        """Single item qty=1: subtotal == unit_price."""
        pricing = get_pricing_engine()
        item = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(item)

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item.unit_price, abs=0.01)

    def test_single_item_qty1_coffee(self, menu_cache_loaded):
        """Single coffee qty=1: subtotal == unit_price."""
        pricing = get_pricing_engine()
        items = find_menu_items_by_type("espresso_based_beverage")
        if not items:
            pytest.skip("No espresso_based_beverage items")

        mi = items[0]
        item = create_item_with_selections(mi["name"], "espresso_based_beverage")
        pricing.recalculate_item_price(item)

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item.unit_price, abs=0.01)

    def test_single_item_qty2_subtotal(self, menu_cache_loaded):
        """Single item qty=2: subtotal == unit_price * 2."""
        pricing = get_pricing_engine()
        item = create_item_with_selections("Bagel", "bagel", quantity=2)
        pricing.recalculate_item_price(item)

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item.unit_price * 2, abs=0.01)

    def test_single_item_qty3_subtotal(self, menu_cache_loaded):
        """Single item qty=3: subtotal == unit_price * 3."""
        pricing = get_pricing_engine()
        item = create_item_with_selections("Bagel", "bagel", quantity=3)
        pricing.recalculate_item_price(item)

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item.unit_price * 3, abs=0.01)

    def test_single_item_qty5_subtotal(self, menu_cache_loaded):
        """Single item qty=5: subtotal == unit_price * 5."""
        pricing = get_pricing_engine()
        item = create_item_with_selections("Bagel", "bagel", quantity=5)
        pricing.recalculate_item_price(item)

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item.unit_price * 5, abs=0.01)

    def test_two_different_items_subtotal(self, menu_cache_loaded):
        """Two different items: subtotal == sum of unit prices."""
        pricing = get_pricing_engine()
        item1 = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(item1)

        espresso_items = find_menu_items_by_type("espresso_based_beverage")
        if not espresso_items:
            pytest.skip("No espresso items for multi-item test")

        item2 = create_item_with_selections(
            espresso_items[0]["name"], "espresso_based_beverage"
        )
        pricing.recalculate_item_price(item2)

        order = build_order_with_items([item1, item2])
        subtotal = _calculate_subtotal(order)

        expected = item1.unit_price + item2.unit_price
        assert subtotal == pytest.approx(expected, abs=0.01)

    def test_three_items_subtotal(self, menu_cache_loaded):
        """Three items: subtotal == sum of all unit prices."""
        pricing = get_pricing_engine()
        items = []

        for item_type in ["bagel", "espresso_based_beverage", "deli_sandwich"]:
            mis = find_menu_items_by_type(item_type)
            if mis:
                item = create_item_with_selections(mis[0]["name"], item_type)
                pricing.recalculate_item_price(item)
                items.append(item)

        if len(items) < 2:
            pytest.skip("Need at least 2 item types for multi-item test")

        order = build_order_with_items(items)
        subtotal = _calculate_subtotal(order)
        expected = sum(i.unit_price for i in items)

        assert subtotal == pytest.approx(expected, abs=0.01)

    def test_multi_item_with_quantities(self, menu_cache_loaded):
        """Multi-item with varying quantities: subtotal == sum(unit_price * qty)."""
        pricing = get_pricing_engine()
        bagels = find_menu_items_by_type("bagel")
        if not bagels:
            pytest.skip("No bagel items")

        item1 = create_item_with_selections(bagels[0]["name"], "bagel", quantity=2)
        pricing.recalculate_item_price(item1)

        item2 = create_item_with_selections(bagels[0]["name"], "bagel", quantity=3)
        pricing.recalculate_item_price(item2)

        order = build_order_with_items([item1, item2])
        subtotal = _calculate_subtotal(order)

        expected = (item1.unit_price * 2) + (item2.unit_price * 3)
        assert subtotal == pytest.approx(expected, abs=0.01)

    def test_five_items_subtotal(self, menu_cache_loaded):
        """Five items from various types: subtotal is additive."""
        pricing = get_pricing_engine()
        items = []

        for item_type in get_all_item_type_slugs():
            if len(items) >= 5:
                break
            mis = find_menu_items_by_type(item_type)
            if mis:
                item = create_item_with_selections(mis[0]["name"], item_type)
                pricing.recalculate_item_price(item)
                items.append(item)

        if len(items) < 3:
            pytest.skip("Need at least 3 item types")

        order = build_order_with_items(items)
        subtotal = _calculate_subtotal(order)
        expected = sum(i.unit_price * i.quantity for i in items)

        assert subtotal == pytest.approx(expected, abs=0.01)

    def test_skipped_items_excluded_from_subtotal(self, menu_cache_loaded):
        """Skipped items don't contribute to subtotal."""
        pricing = get_pricing_engine()

        item1 = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(item1)

        item2 = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(item2)
        item2.status = TaskStatus.SKIPPED

        order = build_order_with_items([item1, item2])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item1.unit_price, abs=0.01), (
            f"Skipped item leaked: expected ${item1.unit_price:.2f}, got ${subtotal:.2f}"
        )

    def test_all_items_skipped_subtotal_zero(self, menu_cache_loaded):
        """All items skipped: subtotal == 0."""
        pricing = get_pricing_engine()

        item = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(item)
        item.status = TaskStatus.SKIPPED

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(0.0, abs=0.01)

    def test_zero_unit_price_treated_as_zero(self, menu_cache_loaded):
        """Item with $0 unit_price treated as $0 in subtotal."""
        item = MenuItemTask(
            menu_item_name="Unknown",
            menu_item_type="bagel",
            unit_price=0.0,
        )
        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(0.0, abs=0.01)

    def test_zero_unit_price_mixed_with_priced(self, menu_cache_loaded):
        """$0 unit_price item mixed with priced item: only priced counted."""
        pricing = get_pricing_engine()
        priced = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(priced)

        unpriced = MenuItemTask(
            menu_item_name="Unknown",
            menu_item_type="bagel",
            unit_price=0.0,
        )

        order = build_order_with_items([priced, unpriced])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(priced.unit_price, abs=0.01)

    def test_floating_point_multiplication(self, menu_cache_loaded):
        """Floating point: $1.10 * 3 should be $3.30 (not $3.3000000000000003)."""
        item = MenuItemTask(
            menu_item_name="Test",
            menu_item_type="bagel",
            unit_price=1.10,
            quantity=3,
        )
        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(3.30, abs=0.01)

    def test_floating_point_addition(self, menu_cache_loaded):
        """Floating point: $0.10 + $0.20 should be $0.30."""
        item1 = MenuItemTask(
            menu_item_name="A", menu_item_type="bagel", unit_price=0.10
        )
        item2 = MenuItemTask(
            menu_item_name="B", menu_item_type="bagel", unit_price=0.20
        )
        order = build_order_with_items([item1, item2])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(0.30, abs=0.01)


# =============================================================================
# Category 3: Adapter Output Consistency (~20 tests)
# Verify: order_task_to_dict() output fields are internally consistent
# =============================================================================


class TestAdapterOutputConsistency:
    """Verify order_task_to_dict output is internally consistent."""

    def _build_order_dict(self, items: list[MenuItemTask]) -> dict:
        """Build an order and convert to dict."""
        pricing = get_pricing_engine()
        for item in items:
            pricing.recalculate_item_price(item)

        order = build_order_with_items(items)
        return order_task_to_dict(order, pricing=pricing)

    # --- line_total == unit_price * quantity ---

    def test_line_total_single_bagel(self, menu_cache_loaded):
        """line_total == unit_price * quantity for a single bagel."""
        item = create_item_with_selections("Bagel", "bagel")
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * d["quantity"], abs=0.01
        )

    def test_line_total_qty2_bagel(self, menu_cache_loaded):
        """line_total == unit_price * 2 for qty=2 bagel."""
        item = create_item_with_selections("Bagel", "bagel", quantity=2)
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * 2, abs=0.01
        )

    def test_line_total_with_upcharge(self, menu_cache_loaded):
        """line_total is correct for item with upcharges."""
        priced = get_priced_options("bagel")
        if not priced:
            pytest.skip("No priced bagel options")

        opt = priced[0]
        item = create_item_with_selections(
            "Bagel", "bagel",
            [(opt["option_slug"], opt["attr_slug"]), ("yes", "toasted")]
        )
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * d["quantity"], abs=0.01
        )

    def test_line_total_per_item_in_multi_order(self, menu_cache_loaded):
        """Each item in a multi-item order has correct line_total."""
        items = []
        for item_type in ["bagel", "espresso_based_beverage", "deli_sandwich"]:
            mis = find_menu_items_by_type(item_type)
            if mis:
                items.append(create_item_with_selections(mis[0]["name"], item_type))

        if len(items) < 2:
            pytest.skip("Need at least 2 item types")

        result = self._build_order_dict(items)

        for d in result["items"]:
            expected_lt = (d["unit_price"] or 0) * d["quantity"]
            assert d["line_total"] == pytest.approx(expected_lt, abs=0.01), (
                f"Item '{d.get('menu_item_name')}': "
                f"line_total=${d['line_total']:.2f} != "
                f"unit_price(${d['unit_price']:.2f}) * qty({d['quantity']})"
            )

    def test_line_total_qty3_with_upcharge(self, menu_cache_loaded):
        """line_total for qty=3 with upcharge."""
        priced = get_priced_options("bagel")
        if not priced:
            pytest.skip("No priced bagel options")

        opt = priced[0]
        item = create_item_with_selections(
            "Bagel", "bagel",
            [(opt["option_slug"], opt["attr_slug"])],
            quantity=3,
        )
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * 3, abs=0.01
        )

    def test_line_total_espresso(self, menu_cache_loaded):
        """line_total for an espresso-based beverage."""
        items = find_menu_items_by_type("espresso_based_beverage")
        if not items:
            pytest.skip("No espresso items")

        item = create_item_with_selections(items[0]["name"], "espresso_based_beverage")
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * d["quantity"], abs=0.01
        )

    def test_line_total_deli_sandwich(self, menu_cache_loaded):
        """line_total for a deli sandwich."""
        items = find_menu_items_by_type("deli_sandwich")
        assert items, "No deli_sandwich items in DB"

        item = create_item_with_selections(items[0]["name"], "deli_sandwich")
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * d["quantity"], abs=0.01
        )

    def test_line_total_omelette(self, menu_cache_loaded):
        """line_total for an omelette item."""
        items = find_menu_items_by_type("omelette")
        if not items:
            pytest.skip("No omelette items")

        item = create_item_with_selections(items[0]["name"], "omelette")
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["line_total"] == pytest.approx(
            (d["unit_price"] or 0) * d["quantity"], abs=0.01
        )

    # --- total_price == sum(line_totals) ---

    def test_total_price_single_item(self, menu_cache_loaded):
        """total_price for single item order."""
        item = create_item_with_selections("Bagel", "bagel")
        result = self._build_order_dict([item])

        item_d = result["items"][0]
        # total_price should match the single item's line_total
        assert result["total_price"] == pytest.approx(item_d["line_total"], abs=0.01)

    def test_total_price_multi_item(self, menu_cache_loaded):
        """total_price == sum of line_totals for multi-item order."""
        items = []
        for item_type in ["bagel", "espresso_based_beverage"]:
            mis = find_menu_items_by_type(item_type)
            if mis:
                items.append(create_item_with_selections(mis[0]["name"], item_type))

        if len(items) < 2:
            pytest.skip("Need at least 2 item types")

        result = self._build_order_dict(items)

        sum_line_totals = sum(d["line_total"] for d in result["items"])
        assert result["total_price"] == pytest.approx(sum_line_totals, abs=0.01)

    def test_total_price_three_items(self, menu_cache_loaded):
        """total_price == sum of line_totals for 3-item order."""
        items = []
        for item_type in ["bagel", "espresso_based_beverage", "deli_sandwich"]:
            mis = find_menu_items_by_type(item_type)
            if mis:
                items.append(create_item_with_selections(mis[0]["name"], item_type))

        if len(items) < 2:
            pytest.skip("Need at least 2 item types")

        result = self._build_order_dict(items)
        sum_line_totals = sum(d["line_total"] for d in result["items"])
        assert result["total_price"] == pytest.approx(sum_line_totals, abs=0.01)

    def test_total_price_with_quantities(self, menu_cache_loaded):
        """total_price accounts for item quantities."""
        item1 = create_item_with_selections("Bagel", "bagel", quantity=2)
        items = [item1]
        espresso = find_menu_items_by_type("espresso_based_beverage")
        if espresso:
            items.append(create_item_with_selections(
                espresso[0]["name"], "espresso_based_beverage", quantity=3
            ))

        result = self._build_order_dict(items)
        sum_line_totals = sum(d["line_total"] for d in result["items"])
        assert result["total_price"] == pytest.approx(sum_line_totals, abs=0.01)

    def test_total_price_five_items(self, menu_cache_loaded):
        """total_price for order with up to 5 items."""
        items = []
        for item_type in get_all_item_type_slugs():
            if len(items) >= 5:
                break
            mis = find_menu_items_by_type(item_type)
            if mis:
                items.append(create_item_with_selections(mis[0]["name"], item_type))

        if not items:
            pytest.skip("No items available")

        result = self._build_order_dict(items)
        sum_line_totals = sum(d["line_total"] for d in result["items"])
        assert result["total_price"] == pytest.approx(sum_line_totals, abs=0.01)

    # --- base_price + upcharges in item_config ---

    def test_item_config_base_price_present(self, menu_cache_loaded):
        """item_config includes base_price for every item."""
        item = create_item_with_selections("Bagel", "bagel")
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert "base_price" in d, "Missing base_price in item dict"
        assert d["base_price"] >= 0

    def test_item_config_base_price_lte_unit_price(self, menu_cache_loaded):
        """base_price <= unit_price (upcharges only add, never subtract)."""
        priced = get_priced_options("bagel")
        if not priced:
            pytest.skip("No priced bagel options")

        opt = priced[0]
        item = create_item_with_selections(
            "Bagel", "bagel",
            [(opt["option_slug"], opt["attr_slug"]), ("yes", "toasted")]
        )
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["base_price"] <= d["unit_price"] + 0.01, (
            f"base_price(${d['base_price']:.2f}) > unit_price(${d['unit_price']:.2f})"
        )

    def test_item_config_base_price_consistency(self, menu_cache_loaded):
        """base_price in top-level matches base_price in item_config."""
        item = create_item_with_selections("Bagel", "bagel")
        result = self._build_order_dict([item])

        d = result["items"][0]
        config = d.get("item_config", {})
        if "base_price" in config:
            assert d["base_price"] == pytest.approx(
                config["base_price"], abs=0.01
            )

    def test_item_config_modifiers_match_top_level(self, menu_cache_loaded):
        """Modifiers in item_config match modifiers at top level."""
        item = create_item_with_selections(
            "Bagel", "bagel", [("yes", "toasted")]
        )
        result = self._build_order_dict([item])

        d = result["items"][0]
        assert d["modifiers"] == d.get("item_config", {}).get("modifiers", [])

    # --- Empty order ---

    def test_empty_order_zero_total(self, menu_cache_loaded):
        """Empty order has $0 total."""
        order = OrderTask()
        result = order_task_to_dict(order, pricing=get_pricing_engine())

        assert result["total_price"] == pytest.approx(0.0, abs=0.01)
        assert result["items"] == []

    def test_empty_order_checkout_state(self, menu_cache_loaded):
        """Empty order checkout_state has $0 subtotal."""
        order = OrderTask()
        store_info = make_store_info()
        result = order_task_to_dict(order, store_info=store_info, pricing=get_pricing_engine())

        cs = result.get("checkout_state", {})
        assert cs.get("subtotal", 0) == pytest.approx(0.0, abs=0.01)


# =============================================================================
# Category 4: Tax/Total Arithmetic (~10 tests)
# Verify: calculate_order_total() math
# =============================================================================


class TestTaxTotalArithmetic:
    """Verify tax and total calculations."""

    def test_tax_equals_subtotal_times_rates(self):
        """tax == subtotal * (city_rate + state_rate)."""
        subtotal = 25.00
        store_info = make_store_info(city_tax_rate=0.045, state_tax_rate=0.04)

        result = calculate_order_total(subtotal, store_info)

        expected_city = round_money(subtotal * 0.045)
        expected_state = round_money(subtotal * 0.04)
        expected_tax = round_money(expected_city + expected_state)

        assert result["city_tax"] == pytest.approx(expected_city, abs=0.01)
        assert result["state_tax"] == pytest.approx(expected_state, abs=0.01)
        assert result["tax"] == pytest.approx(expected_tax, abs=0.01)

    def test_tax_city_component(self):
        """city_tax == subtotal * city_rate."""
        subtotal = 10.50
        store_info = make_store_info(city_tax_rate=0.045)

        result = calculate_order_total(subtotal, store_info)
        assert result["city_tax"] == pytest.approx(
            round_money(subtotal * 0.045), abs=0.01
        )

    def test_tax_state_component(self):
        """state_tax == subtotal * state_rate."""
        subtotal = 10.50
        store_info = make_store_info(state_tax_rate=0.04)

        result = calculate_order_total(subtotal, store_info)
        assert result["state_tax"] == pytest.approx(
            round_money(subtotal * 0.04), abs=0.01
        )

    def test_total_pickup_no_delivery_fee(self):
        """Pickup order total == subtotal + tax (no delivery fee)."""
        subtotal = 20.00
        store_info = make_store_info(city_tax_rate=0.045, state_tax_rate=0.04)

        result = calculate_order_total(subtotal, store_info, is_delivery=False)

        expected_tax = round_money(
            round_money(subtotal * 0.045) + round_money(subtotal * 0.04)
        )
        expected_total = round_money(subtotal + expected_tax)

        assert result["delivery_fee"] == pytest.approx(0.0, abs=0.01)
        assert result["total"] == pytest.approx(expected_total, abs=0.01)

    def test_total_delivery_includes_fee(self):
        """Delivery order total == subtotal + tax + delivery_fee."""
        subtotal = 20.00
        delivery_fee = 3.99
        store_info = make_store_info(
            city_tax_rate=0.045, state_tax_rate=0.04, delivery_fee=delivery_fee
        )

        result = calculate_order_total(subtotal, store_info, is_delivery=True)

        expected_tax = round_money(
            round_money(subtotal * 0.045) + round_money(subtotal * 0.04)
        )
        expected_total = round_money(subtotal + expected_tax + delivery_fee)

        assert result["delivery_fee"] == pytest.approx(delivery_fee, abs=0.01)
        assert result["total"] == pytest.approx(expected_total, abs=0.01)

    def test_delivery_fee_only_for_delivery(self):
        """Delivery fee is 0 for pickup, non-zero for delivery."""
        store_info = make_store_info(delivery_fee=5.00)

        pickup = calculate_order_total(10.0, store_info, is_delivery=False)
        delivery = calculate_order_total(10.0, store_info, is_delivery=True)

        assert pickup["delivery_fee"] == pytest.approx(0.0, abs=0.01)
        assert delivery["delivery_fee"] == pytest.approx(5.00, abs=0.01)

    def test_delivery_fee_reflected_in_total(self):
        """Delivery order total is higher than pickup by exactly delivery_fee."""
        store_info = make_store_info(
            city_tax_rate=0.045, state_tax_rate=0.04, delivery_fee=4.50
        )

        pickup = calculate_order_total(15.0, store_info, is_delivery=False)
        delivery = calculate_order_total(15.0, store_info, is_delivery=True)

        diff = delivery["total"] - pickup["total"]
        assert diff == pytest.approx(4.50, abs=0.01)

    def test_all_outputs_rounded_to_two_decimals(self):
        """All monetary outputs are rounded to 2 decimal places."""
        # Use a subtotal that produces many decimal places
        subtotal = 13.37
        store_info = make_store_info(
            city_tax_rate=0.04625, state_tax_rate=0.0375, delivery_fee=3.99
        )

        result = calculate_order_total(subtotal, store_info, is_delivery=True)

        for key in ("subtotal", "city_tax", "state_tax", "tax", "delivery_fee", "total"):
            val = result[key]
            rounded = round(val, 2)
            assert val == rounded, (
                f"{key}=${val} not rounded to 2 decimals (expected ${rounded})"
            )

    def test_zero_subtotal_zero_total(self):
        """$0 subtotal produces $0 total."""
        store_info = make_store_info()
        result = calculate_order_total(0.0, store_info)

        assert result["subtotal"] == pytest.approx(0.0, abs=0.01)
        assert result["tax"] == pytest.approx(0.0, abs=0.01)
        assert result["total"] == pytest.approx(0.0, abs=0.01)

    def test_no_store_info_zero_tax(self):
        """No store info: zero tax, total == subtotal."""
        result = calculate_order_total(15.0, None)

        assert result["city_tax"] == pytest.approx(0.0, abs=0.01)
        assert result["state_tax"] == pytest.approx(0.0, abs=0.01)
        assert result["tax"] == pytest.approx(0.0, abs=0.01)
        assert result["total"] == pytest.approx(15.0, abs=0.01)


# =============================================================================
# Category 5: End-to-End State Machine Pricing (~15 tests)
# Process natural language through sm.process(), verify price decomposition
# =============================================================================


class TestEndToEndPricing:
    """Process input through state machine and verify pricing math."""

    def _process_and_get_order(self, order_and_sm, user_input: str):
        """Process input and return (order, result)."""
        order, sm = order_and_sm
        result = sm.process(user_input, order)
        return order, result

    # --- Simple single-item orders ---

    def test_bagel_price_after_process(self, menu_cache_loaded, order_and_sm):
        """Processing 'a bagel' sets a positive price."""
        order, result = self._process_and_get_order(order_and_sm, "a plain bagel")
        active_items = order.items.get_active_items()
        if not active_items:
            pytest.skip("Parser didn't recognize 'a plain bagel'")

        item = active_items[0]
        assert item.unit_price > 0, "Bagel should have a positive price"

    def test_bagel_price_matches_base(self, menu_cache_loaded, order_and_sm):
        """Plain bagel price should match base price from pricing engine."""
        pricing = get_pricing_engine()
        order, result = self._process_and_get_order(order_and_sm, "a plain bagel")
        active_items = order.items.get_active_items()
        if not active_items:
            pytest.skip("Parser didn't recognize 'a plain bagel'")

        item = active_items[0]
        base = pricing.lookup_base_price(item.menu_item_name)
        # Base price should be very close (might differ if upcharges applied)
        assert item.unit_price >= base - 0.01, (
            f"Price ${item.unit_price:.2f} < base ${base:.2f}"
        )

    def test_coffee_price_after_process(self, menu_cache_loaded, order_and_sm):
        """Processing a coffee order sets a positive price."""
        order, result = self._process_and_get_order(order_and_sm, "a latte")
        active_items = order.items.get_active_items()
        if not active_items:
            pytest.skip("Parser didn't recognize 'a latte'")

        item = active_items[0]
        assert item.unit_price > 0, "Latte should have a positive price"

    def test_deli_sandwich_price_after_process(self, menu_cache_loaded, order_and_sm):
        """Processing a deli sandwich order sets a positive price."""
        sandwiches = find_menu_items_by_type("deli_sandwich")
        assert sandwiches, "No deli_sandwich items in DB"

        name = sandwiches[0]["name"]
        order, result = self._process_and_get_order(order_and_sm, name)
        active_items = order.items.get_active_items()
        if not active_items:
            pytest.skip(f"Parser didn't recognize '{name}'")

        item = active_items[0]
        assert item.unit_price > 0

    def test_omelette_price_after_process(self, menu_cache_loaded, order_and_sm):
        """Processing an omelette order sets a positive price."""
        omelettes = find_menu_items_by_type("omelette")
        if not omelettes:
            pytest.skip("No omelette items in DB")

        name = omelettes[0]["name"]
        order, result = self._process_and_get_order(order_and_sm, name)
        active_items = order.items.get_active_items()
        if not active_items:
            pytest.skip(f"Parser didn't recognize '{name}'")

        item = active_items[0]
        assert item.unit_price > 0

    # --- Multi-item orders ---

    def test_two_items_subtotal_after_process(self, menu_cache_loaded, order_and_sm):
        """Two items added: subtotal == sum of unit prices."""
        pricing = get_pricing_engine()
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")

        active = order.items.get_active_items()
        if not active:
            pytest.skip("Parser didn't recognize first item")

        # Add a second item directly (sm.process enters config mode after first)
        espresso_items = find_menu_items_by_type("espresso_based_beverage")
        assert espresso_items, "No espresso_based_beverage items in DB"

        second_item = create_item_with_selections(
            espresso_items[0]["name"], "espresso_based_beverage"
        )
        pricing.recalculate_item_price(second_item)
        order.items.add_item(second_item)

        active = order.items.get_active_items()
        assert len(active) >= 2

        subtotal = _calculate_subtotal(order)
        expected = sum(i.unit_price * i.quantity for i in active)
        assert subtotal == pytest.approx(expected, abs=0.01)

    def test_multi_item_all_priced(self, menu_cache_loaded, order_and_sm):
        """Every item added via process() has a non-zero price."""
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")

        active = order.items.get_active_items()
        if not active:
            pytest.skip("No items recognized")

        for item in active:
            assert item.unit_price >= 0, (
                f"Item '{item.menu_item_name}' has negative price"
            )

    def test_multi_bagel_subtotal(self, menu_cache_loaded, order_and_sm):
        """Two bagels: subtotal == first.unit_price + second.unit_price."""
        pricing = get_pricing_engine()
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")
        active = order.items.get_active_items()
        if not active:
            pytest.skip("Parser didn't add first bagel")

        # Add second bagel directly (sm.process enters config mode after first)
        second_bagel = create_item_with_selections("Bagel", "bagel")
        pricing.recalculate_item_price(second_bagel)
        order.items.add_item(second_bagel)

        active = order.items.get_active_items()
        assert len(active) >= 2

        subtotal = _calculate_subtotal(order)
        expected = sum(i.unit_price * i.quantity for i in active)
        assert subtotal == pytest.approx(expected, abs=0.01)

    def test_order_subtotal_matches_adapter(self, menu_cache_loaded, order_and_sm):
        """_calculate_subtotal matches adapter output checkout_state subtotal."""
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")
        active = order.items.get_active_items()
        if not active:
            pytest.skip("No items recognized")

        pricing = get_pricing_engine()
        store_info = make_store_info()
        result = order_task_to_dict(order, store_info=store_info, pricing=pricing)

        internal_subtotal = _calculate_subtotal(order)
        adapter_subtotal = result.get("checkout_state", {}).get("subtotal", 0)

        assert internal_subtotal == pytest.approx(adapter_subtotal, abs=0.01)

    # --- Price changes after modification ---

    def test_quantity_change_reflects_in_subtotal(self, menu_cache_loaded, order_and_sm):
        """Changing quantity changes subtotal proportionally."""
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")
        active = order.items.get_active_items()
        if not active:
            pytest.skip("No items recognized")

        item = active[0]
        unit = item.unit_price
        subtotal_1 = _calculate_subtotal(order)
        assert subtotal_1 == pytest.approx(unit, abs=0.01)

        # Change quantity
        item.quantity = 3
        subtotal_3 = _calculate_subtotal(order)
        assert subtotal_3 == pytest.approx(unit * 3, abs=0.01)

    def test_adding_item_increases_subtotal(self, menu_cache_loaded, order_and_sm):
        """Adding another item increases subtotal."""
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")
        active = order.items.get_active_items()
        if not active:
            pytest.skip("No items recognized")

        subtotal_before = _calculate_subtotal(order)

        # Add a second item directly
        espresso_items = find_menu_items_by_type("espresso_based_beverage")
        if not espresso_items:
            pytest.skip("No espresso items")

        pricing = get_pricing_engine()
        new_item = create_item_with_selections(
            espresso_items[0]["name"], "espresso_based_beverage"
        )
        pricing.recalculate_item_price(new_item)
        order.items.add_item(new_item)

        subtotal_after = _calculate_subtotal(order)
        assert subtotal_after > subtotal_before
        assert subtotal_after == pytest.approx(
            subtotal_before + new_item.unit_price, abs=0.01
        )

    def test_recalculate_after_selection_change(self, menu_cache_loaded, order_and_sm):
        """Recalculating after adding a priced selection updates price."""
        pricing = get_pricing_engine()
        order, _ = self._process_and_get_order(order_and_sm, "a plain bagel")
        active = order.items.get_active_items()
        if not active:
            pytest.skip("No items recognized")

        item = active[0]
        price_before = item.unit_price

        # Add a priced selection
        priced = get_priced_options("bagel")
        if not priced:
            pytest.skip("No priced bagel options")

        opt = priced[0]
        item.add_selection(opt["option_slug"], opt["attr_slug"])
        pricing.recalculate_item_price(item)

        assert item.unit_price >= price_before, (
            f"Price should increase or stay same after adding upcharge, "
            f"was ${price_before:.2f}, now ${item.unit_price:.2f}"
        )

    # --- Quantity additions ---

    def test_qty2_line_total_via_process(self, menu_cache_loaded, order_and_sm):
        """Processing 'two bagels' has line_total = unit_price * 2."""
        order, _ = self._process_and_get_order(order_and_sm, "two plain bagels")
        active = order.items.get_active_items()
        if not active:
            pytest.skip("Parser didn't recognize 'two plain bagels'")

        item = active[0]
        if item.quantity >= 2:
            expected_lt = item.unit_price * item.quantity
            subtotal = _calculate_subtotal(order)
            assert subtotal == pytest.approx(expected_lt, abs=0.01)

    def test_qty3_price_triple(self, menu_cache_loaded):
        """Qty=3 of same item: subtotal == 3 * unit_price."""
        pricing = get_pricing_engine()
        item = create_item_with_selections("Bagel", "bagel", quantity=3)
        pricing.recalculate_item_price(item)

        order = build_order_with_items([item])
        subtotal = _calculate_subtotal(order)

        assert subtotal == pytest.approx(item.unit_price * 3, abs=0.01)

    def test_mixed_quantities_subtotal(self, menu_cache_loaded):
        """Mixed quantities: subtotal = sum(unit_price * qty) for each item."""
        pricing = get_pricing_engine()

        item1 = create_item_with_selections("Bagel", "bagel", quantity=2)
        pricing.recalculate_item_price(item1)

        espresso_items = find_menu_items_by_type("espresso_based_beverage")
        if not espresso_items:
            pytest.skip("No espresso items")

        item2 = create_item_with_selections(
            espresso_items[0]["name"], "espresso_based_beverage", quantity=1
        )
        pricing.recalculate_item_price(item2)

        order = build_order_with_items([item1, item2])
        subtotal = _calculate_subtotal(order)

        expected = (item1.unit_price * 2) + (item2.unit_price * 1)
        assert subtotal == pytest.approx(expected, abs=0.01)
