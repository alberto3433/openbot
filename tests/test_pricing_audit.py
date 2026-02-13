"""Pricing audit tests — verify price consistency across lookup paths.

The pricing engine resolves modifier prices from multiple sources:

1. menu_item_size_prices.price — base/variant pricing per size
2. global_attribute_options.price_modifier — attribute upcharges (the main path)
3. ingredient price contexts — fallback built from the same options table but
   indexed by ingredient name instead of option slug

Source #3 is built by iterating GlobalAttributeOption rows and keying by
ingredient_id → ingredient.name.lower().  If one ingredient is linked to
multiple options with different price_modifier values, the last one wins in
the context cache while the attribute-option path finds whichever option
matches first — potentially returning a different price.

The priced_slugs set in AttributeUpchargeCalculator prevents double-counting
at the code level, but these tests guard against data-level inconsistencies
that code can't prevent.
"""

import pytest

from orderbot.cache import menu_cache
from orderbot.tasks.normalization import normalize_to_slug


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_menu_data() -> dict:
    """Get the global menu data loaded by conftest."""
    from orderbot.tasks.state_machine import _global_menu_data
    assert _global_menu_data is not None, (
        "Global menu_data not loaded — menu_cache_loaded fixture must run first"
    )
    return _global_menu_data


def _build_attr_option_price_index(menu_data: dict) -> dict[tuple[str, str], float]:
    """Build a lookup of (item_type_slug, normalized_option_slug) -> price.

    Collects every priced option across all item types and attributes.
    Only includes options with price_modifier > 0.
    """
    index: dict[tuple[str, str], float] = {}
    for item_type_slug, type_data in menu_data.get("item_types", {}).items():
        for attr in type_data.get("attributes", []):
            for opt in attr.get("options", []):
                slug = opt.get("slug")
                if not slug:
                    continue
                price = opt.get("price_modifier") or opt.get("price") or 0.0
                if price > 0:
                    index[(item_type_slug, normalize_to_slug(slug))] = price
    return index


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPricingConsistency:
    """Verify no modifier has conflicting prices across lookup paths."""

    def test_no_conflicting_ingredient_context_prices(self, menu_cache_loaded):
        """Each ingredient's context price must match its attribute option price.

        The ingredient price context cache is built from GlobalAttributeOption
        rows keyed by ingredient name.  The attribute option lookup path finds
        the same data keyed by option slug.  If both paths return a non-zero
        price for the same modifier on the same item type, the prices must agree.
        """
        menu_data = _get_menu_data()
        attr_prices = _build_attr_option_price_index(menu_data)

        # Access internal cache — acceptable in audit tests
        price_contexts: dict[str, list[dict]] = getattr(
            menu_cache, "_ingredient_price_contexts", {}
        )

        conflicts = []
        for ing_name, contexts in price_contexts.items():
            ing_slug = normalize_to_slug(ing_name)
            for ctx in contexts:
                if ctx.get("context_type") != "modifier":
                    continue
                item_type = ctx.get("item_type_slug")
                ctx_price = ctx.get("price", 0.0)
                if not item_type or ctx_price <= 0:
                    continue

                key = (item_type, ing_slug)
                if key in attr_prices:
                    attr_price = attr_prices[key]
                    if abs(attr_price - ctx_price) > 0.001:
                        conflicts.append({
                            "ingredient": ing_name,
                            "item_type": item_type,
                            "attr_option_price": attr_price,
                            "ingredient_ctx_price": ctx_price,
                        })

        assert not conflicts, (
            f"Found {len(conflicts)} modifier(s) with conflicting prices "
            f"across lookup paths:\n"
            + "\n".join(
                f"  - '{c['ingredient']}' in {c['item_type']}: "
                f"attr_option=${c['attr_option_price']:.2f} vs "
                f"ingredient_ctx=${c['ingredient_ctx_price']:.2f}"
                for c in conflicts
            )
        )

    def test_ingredient_price_contexts_populated(self, menu_cache_loaded):
        """Sanity check: the ingredient price context cache is not empty.

        If this fails, the cache loader has a problem and the conflict test
        above would vacuously pass.
        """
        price_contexts: dict[str, list[dict]] = getattr(
            menu_cache, "_ingredient_price_contexts", {}
        )
        assert len(price_contexts) > 0, (
            "Ingredient price contexts cache is empty — "
            "cache loader may have failed silently"
        )

    def test_attribute_option_prices_populated(self, menu_cache_loaded):
        """Sanity check: the menu data contains priced attribute options."""
        menu_data = _get_menu_data()
        attr_prices = _build_attr_option_price_index(menu_data)
        assert len(attr_prices) > 0, (
            "No priced attribute options found in menu_data — "
            "menu index builder may have failed"
        )

    def test_no_duplicate_ingredient_prices_in_same_attribute(
        self, menu_cache_loaded,
    ):
        """Each ingredient_id should have one price within a single attribute.

        If the same ingredient appears multiple times in one attribute's options
        with different price_modifiers, the pricing result depends on iteration
        order. This shouldn't happen but is worth guarding against.
        """
        menu_data = _get_menu_data()
        duplicates = []

        for item_type_slug, type_data in menu_data.get("item_types", {}).items():
            for attr in type_data.get("attributes", []):
                attr_slug = attr.get("slug", "")
                seen: dict[str, float] = {}  # slug -> first price seen
                for opt in attr.get("options", []):
                    slug = opt.get("slug")
                    if not slug:
                        continue
                    price = opt.get("price_modifier") or opt.get("price") or 0.0
                    norm_slug = normalize_to_slug(slug)

                    if norm_slug in seen:
                        if abs(seen[norm_slug] - price) > 0.001:
                            duplicates.append({
                                "item_type": item_type_slug,
                                "attribute": attr_slug,
                                "slug": norm_slug,
                                "price_1": seen[norm_slug],
                                "price_2": price,
                            })
                    else:
                        seen[norm_slug] = price

        assert not duplicates, (
            f"Found {len(duplicates)} duplicate option slug(s) with "
            f"conflicting prices within the same attribute:\n"
            + "\n".join(
                f"  - {d['item_type']}.{d['attribute']}: '{d['slug']}' "
                f"has ${d['price_1']:.2f} and ${d['price_2']:.2f}"
                for d in duplicates
            )
        )
