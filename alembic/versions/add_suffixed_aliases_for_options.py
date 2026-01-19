"""Add suffixed aliases for attribute options (data-driven suffix stripping)

Revision ID: add_suffixed_aliases_001
Revises: add_standalone_instruction_001
Create Date: 2026-01-19

This migration adds aliases like "oat milk", "everything bagel", "plain cream cheese"
to their respective option ingredients, enabling data-driven value normalization
without hardcoded suffix stripping.

Also adds boolean options to the decaf attribute with "true"/"false" slugs and
appropriate aliases, making boolean attribute handling fully data-driven.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_suffixed_aliases_001'
down_revision: Union[str, Sequence[str], None] = 'f1d61b7265ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Milk ingredient IDs and their "X milk" aliases to add
MILK_ALIASES = {
    96: ["whole milk"],  # Whole Milk
    97: ["half and half", "half & half"],  # Half N Half
    98: ["lactose free milk", "lactose free"],  # Lactose Free Milk
    99: ["skim milk", "skim"],  # Skim Milk
    100: ["oat milk", "oat"],  # Oat Milk
    101: ["almond milk", "almond"],  # Almond Milk
    102: ["soy milk", "soy"],  # Soy Milk
}

# Bread ingredient IDs and their "X bagel" aliases to add
BREAD_ALIASES = {
    2: ["plain bagel"],  # Plain
    3: ["everything bagel"],  # Everything
    4: ["sesame bagel"],  # Sesame
    5: ["poppy bagel", "poppy seed bagel"],  # Poppy
    6: ["onion bagel"],  # Onion
    7: ["pumpernickel bagel"],  # Pumpernickel
    8: ["salt bagel"],  # Salt
    9: ["cinnamon raisin bagel"],  # Cinnamon Raisin (already has some aliases)
    10: ["garlic bagel"],  # Garlic
    11: ["whole wheat bagel", "wheat bagel"],  # Whole Wheat
    71: ["egg bagel"],  # Egg
    72: ["multigrain bagel"],  # Multigrain
    73: ["asiago bagel"],  # Asiago
    128: ["rainbow bagel"],  # Rainbow
    129: ["french toast bagel"],  # French Toast (already has "bagel" in slug)
    130: ["sun dried tomato bagel"],  # Sun Dried Tomato
    131: ["jalapeno cheddar bagel"],  # Jalapeno Cheddar
}

# Spread ingredient IDs and their "X cream cheese" / "X spread" aliases to add
SPREAD_ALIASES = {
    14: ["plain cream cheese", "plain spread", "plain cc", "regular cream cheese"],  # Plain CC
    15: ["scallion cream cheese"],  # Scallion CC (already has "scallion")
    19: ["honey walnut cream cheese"],  # Honey Walnut CC (already has "honey walnut")
    20: ["strawberry cream cheese"],  # Strawberry CC (already has "strawberry")
    58: ["blueberry cream cheese"],  # Blueberry CC
    61: ["nova scotia cream cheese", "nova cream cheese", "lox spread"],  # Nova Scotia CC
    62: ["truffle cream cheese"],  # Truffle CC
    139: ["chipotle cream cheese"],  # Chipotle CC
    140: ["lox cream cheese"],  # Lox CC
    141: ["olive pimento cream cheese", "olive cream cheese", "pimento cream cheese"],  # Olive Pimento CC
}

# Spread options that need ingredients created first (currently ingredient_id=None)
SPREAD_OPTIONS_NEEDING_INGREDIENTS = [
    {"slug": "veggie_cc", "name": "Veggie Cream Cheese", "aliases": ["veggie cream cheese", "veggie spread", "veggie"]},
    {"slug": "walnut_raisin_cc", "name": "Walnut Raisin Cream Cheese", "aliases": ["walnut raisin cream cheese", "walnut raisin"]},
    {"slug": "jalapeno_cc", "name": "Jalapeno Cream Cheese", "aliases": ["jalapeno cream cheese", "jalapeno spread"]},
    {"slug": "plain_tofu", "name": "Plain Tofu Spread", "aliases": ["plain tofu", "tofu spread", "tofu"]},
    {"slug": "scallion_tofu", "name": "Scallion Tofu Spread", "aliases": ["scallion tofu", "scallion tofu spread"]},
    {"slug": "veggie_tofu", "name": "Veggie Tofu Spread", "aliases": ["veggie tofu", "veggie tofu spread"]},
]


def upgrade() -> None:
    """Add suffixed aliases for milk, bread, and spread options."""
    conn = op.get_bind()

    # 1. Add milk aliases
    for ingredient_id, aliases in MILK_ALIASES.items():
        for alias in aliases:
            # Check if alias already exists (globally unique constraint)
            existing = conn.execute(
                sa.text("SELECT id FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            ).fetchone()
            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                        "VALUES (:ingredient_id, :alias)"
                    ),
                    {"ingredient_id": ingredient_id, "alias": alias}
                )

    # 2. Add bread/bagel aliases
    for ingredient_id, aliases in BREAD_ALIASES.items():
        for alias in aliases:
            existing = conn.execute(
                sa.text("SELECT id FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            ).fetchone()
            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                        "VALUES (:ingredient_id, :alias)"
                    ),
                    {"ingredient_id": ingredient_id, "alias": alias}
                )

    # 3. Add spread/cream cheese aliases
    for ingredient_id, aliases in SPREAD_ALIASES.items():
        for alias in aliases:
            existing = conn.execute(
                sa.text("SELECT id FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            ).fetchone()
            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                        "VALUES (:ingredient_id, :alias)"
                    ),
                    {"ingredient_id": ingredient_id, "alias": alias}
                )

    # 4. Create ingredients for spread options that don't have them, and add aliases
    for opt_info in SPREAD_OPTIONS_NEEDING_INGREDIENTS:
        # Create ingredient
        result = conn.execute(
            sa.text(
                "INSERT INTO ingredients (name, slug, category, unit, track_inventory, base_price, is_available, "
                "is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher, "
                "contains_eggs, contains_fish, contains_sesame, contains_nuts) "
                "VALUES (:name, :slug, 'spread', 'oz', false, 0.0, true, "
                "false, true, true, false, true, "
                "false, false, false, false) "
                "ON CONFLICT (slug) DO UPDATE SET name = :name "
                "RETURNING id"
            ),
            {"name": opt_info["name"], "slug": opt_info["slug"]}
        )
        ingredient_id = result.fetchone()[0]

        # Link ingredient to the option
        conn.execute(
            sa.text(
                "UPDATE global_attribute_options SET ingredient_id = :ingredient_id "
                "WHERE slug = :slug AND ingredient_id IS NULL"
            ),
            {"ingredient_id": ingredient_id, "slug": opt_info["slug"]}
        )

        # Add aliases
        for alias in opt_info["aliases"]:
            existing = conn.execute(
                sa.text("SELECT id FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            ).fetchone()
            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                        "VALUES (:ingredient_id, :alias)"
                    ),
                    {"ingredient_id": ingredient_id, "alias": alias}
                )

    # 5. Create boolean options for decaf attribute
    # First, get the decaf attribute ID
    decaf_attr = conn.execute(
        sa.text("SELECT id FROM global_attributes WHERE slug = 'decaf'")
    ).fetchone()

    if decaf_attr:
        decaf_attr_id = decaf_attr[0]

        # Create "decaf_true" ingredient for the True option
        result = conn.execute(
            sa.text(
                "INSERT INTO ingredients (name, slug, category, unit, track_inventory, base_price, is_available, "
                "is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher, "
                "contains_eggs, contains_fish, contains_sesame, contains_nuts) "
                "VALUES ('Decaf Option', 'decaf_option_true', 'boolean_option', 'unit', false, 0.0, true, "
                "true, true, true, true, true, "
                "false, false, false, false) "
                "ON CONFLICT (slug) DO UPDATE SET name = 'Decaf Option' "
                "RETURNING id"
            )
        )
        decaf_true_ing_id = result.fetchone()[0]

        # Add aliases for true option
        for alias in ["decaf", "yes", "yep", "yeah", "sure", "please"]:
            existing = conn.execute(
                sa.text("SELECT id FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            ).fetchone()
            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                        "VALUES (:ingredient_id, :alias)"
                    ),
                    {"ingredient_id": decaf_true_ing_id, "alias": alias}
                )

        # Create "decaf_false" ingredient for the False option
        result = conn.execute(
            sa.text(
                "INSERT INTO ingredients (name, slug, category, unit, track_inventory, base_price, is_available, "
                "is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher, "
                "contains_eggs, contains_fish, contains_sesame, contains_nuts) "
                "VALUES ('Regular (Not Decaf)', 'decaf_option_false', 'boolean_option', 'unit', false, 0.0, true, "
                "true, true, true, true, true, "
                "false, false, false, false) "
                "ON CONFLICT (slug) DO UPDATE SET name = 'Regular (Not Decaf)' "
                "RETURNING id"
            )
        )
        decaf_false_ing_id = result.fetchone()[0]

        # Add aliases for false option
        for alias in ["regular", "no", "nope", "normal", "not decaf", "caffeinated"]:
            existing = conn.execute(
                sa.text("SELECT id FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            ).fetchone()
            if not existing:
                conn.execute(
                    sa.text(
                        "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                        "VALUES (:ingredient_id, :alias)"
                    ),
                    {"ingredient_id": decaf_false_ing_id, "alias": alias}
                )

        # Create the boolean options if they don't exist
        # True option
        existing_true = conn.execute(
            sa.text(
                "SELECT id FROM global_attribute_options "
                "WHERE global_attribute_id = :attr_id AND slug = 'true'"
            ),
            {"attr_id": decaf_attr_id}
        ).fetchone()

        if not existing_true:
            conn.execute(
                sa.text(
                    "INSERT INTO global_attribute_options "
                    "(global_attribute_id, slug, display_name, price_modifier, iced_price_modifier, is_default, is_available, ingredient_id, display_order) "
                    "VALUES (:attr_id, 'true', 'Decaf', 0.0, 0.0, false, true, :ing_id, 1)"
                ),
                {"attr_id": decaf_attr_id, "ing_id": decaf_true_ing_id}
            )

        # False option
        existing_false = conn.execute(
            sa.text(
                "SELECT id FROM global_attribute_options "
                "WHERE global_attribute_id = :attr_id AND slug = 'false'"
            ),
            {"attr_id": decaf_attr_id}
        ).fetchone()

        if not existing_false:
            conn.execute(
                sa.text(
                    "INSERT INTO global_attribute_options "
                    "(global_attribute_id, slug, display_name, price_modifier, iced_price_modifier, is_default, is_available, ingredient_id, display_order) "
                    "VALUES (:attr_id, 'false', 'Regular', 0.0, 0.0, true, true, :ing_id, 2)"
                ),
                {"attr_id": decaf_attr_id, "ing_id": decaf_false_ing_id}
            )


def downgrade() -> None:
    """Remove the added aliases and boolean options."""
    conn = op.get_bind()

    # Remove milk aliases
    all_milk_aliases = [alias for aliases in MILK_ALIASES.values() for alias in aliases]
    for alias in all_milk_aliases:
        conn.execute(
            sa.text("DELETE FROM ingredient_aliases WHERE alias = :alias"),
            {"alias": alias}
        )

    # Remove bread aliases
    all_bread_aliases = [alias for aliases in BREAD_ALIASES.values() for alias in aliases]
    for alias in all_bread_aliases:
        conn.execute(
            sa.text("DELETE FROM ingredient_aliases WHERE alias = :alias"),
            {"alias": alias}
        )

    # Remove spread aliases
    all_spread_aliases = [alias for aliases in SPREAD_ALIASES.values() for alias in aliases]
    for alias in all_spread_aliases:
        conn.execute(
            sa.text("DELETE FROM ingredient_aliases WHERE alias = :alias"),
            {"alias": alias}
        )

    # Remove spread ingredients that were created and unlink from options
    for opt_info in SPREAD_OPTIONS_NEEDING_INGREDIENTS:
        # Unlink from option
        conn.execute(
            sa.text("UPDATE global_attribute_options SET ingredient_id = NULL WHERE slug = :slug"),
            {"slug": opt_info["slug"]}
        )
        # Delete aliases
        for alias in opt_info["aliases"]:
            conn.execute(
                sa.text("DELETE FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            )
        # Delete ingredient
        conn.execute(
            sa.text("DELETE FROM ingredients WHERE slug = :slug"),
            {"slug": opt_info["slug"]}
        )

    # Remove boolean options and ingredients for decaf
    decaf_attr = conn.execute(
        sa.text("SELECT id FROM global_attributes WHERE slug = 'decaf'")
    ).fetchone()

    if decaf_attr:
        decaf_attr_id = decaf_attr[0]

        # Delete boolean options
        conn.execute(
            sa.text(
                "DELETE FROM global_attribute_options "
                "WHERE global_attribute_id = :attr_id AND slug IN ('true', 'false')"
            ),
            {"attr_id": decaf_attr_id}
        )

    # Delete boolean option aliases
    for alias in ["decaf", "yes", "yep", "yeah", "sure", "please", "regular", "no", "nope", "normal", "not decaf", "caffeinated"]:
        conn.execute(
            sa.text("DELETE FROM ingredient_aliases WHERE alias = :alias"),
            {"alias": alias}
        )

    # Delete boolean option ingredients
    conn.execute(
        sa.text("DELETE FROM ingredients WHERE slug IN ('decaf_option_true', 'decaf_option_false')")
    )
