"""Add boolean options for toasted and scooped attributes (data-driven)

Revision ID: add_toasted_scooped_opts_001
Revises: remove_bagel_choice_attr_001
Create Date: 2026-01-19

This migration adds boolean options with aliases for the toasted and scooped
attributes, making boolean attribute parsing fully data-driven (matching the
pattern already used for decaf).

Pattern:
1. Create ingredients (toasted_option_true, toasted_option_false, etc.)
2. Add aliases to those ingredients for pattern matching
3. Create global_attribute_options with slugs 'true' and 'false' linked to ingredients
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_toasted_scooped_opts_001'
down_revision: Union[str, Sequence[str], None] = 'remove_bagel_choice_attr_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Boolean attribute configurations
# Format: attr_slug -> {true_aliases, false_aliases}
# Note: Avoid ambiguous aliases like "plain" (could mean plain bagel) or "whole" (could mean whole wheat)
BOOLEAN_CONFIGS = {
    "toasted": {
        "true_name": "Toasted",
        "true_aliases": [
            "toasted", "toast it", "tosted", "tostd",
            # Note: "toast" alone is not included as it may match "french toast bagel"
        ],
        "false_name": "Not Toasted",
        "false_aliases": [
            "untoasted", "not toasted", "no toast", "un toasted",
            # Note: "plain" is not included as it's ambiguous (could mean plain bagel)
        ],
    },
    "scooped": {
        "true_name": "Scooped",
        "true_aliases": [
            "scooped", "scoop it", "scooped out", "hollowed out",
            # Note: "hollow" alone not included as it's uncommon usage
        ],
        "false_name": "Not Scooped",
        "false_aliases": [
            "not scooped", "unscooped", "no scoop",
            # Note: "whole" is not included as it's ambiguous (could mean whole wheat)
        ],
    },
}


def upgrade() -> None:
    """Add boolean options with aliases for toasted and scooped attributes."""
    conn = op.get_bind()

    for attr_slug, config in BOOLEAN_CONFIGS.items():
        # Get the attribute ID
        attr_row = conn.execute(
            sa.text("SELECT id FROM global_attributes WHERE slug = :slug"),
            {"slug": attr_slug}
        ).fetchone()

        if not attr_row:
            print(f"Warning: {attr_slug} attribute not found, skipping")
            continue

        attr_id = attr_row[0]

        # Create "true" option ingredient
        result = conn.execute(
            sa.text(
                "INSERT INTO ingredients (name, slug, category, unit, track_inventory, base_price, is_available, "
                "is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher, "
                "contains_eggs, contains_fish, contains_sesame, contains_nuts) "
                "VALUES (:name, :slug, 'boolean_option', 'unit', false, 0.0, true, "
                "true, true, true, true, true, "
                "false, false, false, false) "
                "ON CONFLICT (slug) DO UPDATE SET name = :name "
                "RETURNING id"
            ),
            {"name": config["true_name"], "slug": f"{attr_slug}_option_true"}
        )
        true_ing_id = result.fetchone()[0]

        # Add aliases for true option
        for alias in config["true_aliases"]:
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
                    {"ingredient_id": true_ing_id, "alias": alias}
                )

        # Create "false" option ingredient
        result = conn.execute(
            sa.text(
                "INSERT INTO ingredients (name, slug, category, unit, track_inventory, base_price, is_available, "
                "is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher, "
                "contains_eggs, contains_fish, contains_sesame, contains_nuts) "
                "VALUES (:name, :slug, 'boolean_option', 'unit', false, 0.0, true, "
                "true, true, true, true, true, "
                "false, false, false, false) "
                "ON CONFLICT (slug) DO UPDATE SET name = :name "
                "RETURNING id"
            ),
            {"name": config["false_name"], "slug": f"{attr_slug}_option_false"}
        )
        false_ing_id = result.fetchone()[0]

        # Add aliases for false option
        for alias in config["false_aliases"]:
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
                    {"ingredient_id": false_ing_id, "alias": alias}
                )

        # Create the boolean options if they don't exist
        # True option
        existing_true = conn.execute(
            sa.text(
                "SELECT id FROM global_attribute_options "
                "WHERE global_attribute_id = :attr_id AND slug = 'true'"
            ),
            {"attr_id": attr_id}
        ).fetchone()

        if not existing_true:
            conn.execute(
                sa.text(
                    "INSERT INTO global_attribute_options "
                    "(global_attribute_id, slug, display_name, price_modifier, iced_price_modifier, is_default, is_available, ingredient_id, display_order) "
                    "VALUES (:attr_id, 'true', :display_name, 0.0, 0.0, false, true, :ing_id, 1)"
                ),
                {"attr_id": attr_id, "display_name": config["true_name"], "ing_id": true_ing_id}
            )

        # False option
        existing_false = conn.execute(
            sa.text(
                "SELECT id FROM global_attribute_options "
                "WHERE global_attribute_id = :attr_id AND slug = 'false'"
            ),
            {"attr_id": attr_id}
        ).fetchone()

        if not existing_false:
            conn.execute(
                sa.text(
                    "INSERT INTO global_attribute_options "
                    "(global_attribute_id, slug, display_name, price_modifier, iced_price_modifier, is_default, is_available, ingredient_id, display_order) "
                    "VALUES (:attr_id, 'false', :display_name, 0.0, 0.0, true, true, :ing_id, 2)"
                ),
                {"attr_id": attr_id, "display_name": config["false_name"], "ing_id": false_ing_id}
            )

        print(f"Created boolean options for {attr_slug} attribute")


def downgrade() -> None:
    """Remove the boolean options and ingredients for toasted and scooped."""
    conn = op.get_bind()

    for attr_slug, config in BOOLEAN_CONFIGS.items():
        # Get the attribute ID
        attr_row = conn.execute(
            sa.text("SELECT id FROM global_attributes WHERE slug = :slug"),
            {"slug": attr_slug}
        ).fetchone()

        if attr_row:
            attr_id = attr_row[0]
            # Remove options
            conn.execute(
                sa.text(
                    "DELETE FROM global_attribute_options "
                    "WHERE global_attribute_id = :attr_id AND slug IN ('true', 'false')"
                ),
                {"attr_id": attr_id}
            )

        # Remove aliases
        for alias in config["true_aliases"] + config["false_aliases"]:
            conn.execute(
                sa.text("DELETE FROM ingredient_aliases WHERE alias = :alias"),
                {"alias": alias}
            )

        # Remove ingredients
        for slug_suffix in ["_option_true", "_option_false"]:
            conn.execute(
                sa.text("DELETE FROM ingredients WHERE slug = :slug"),
                {"slug": f"{attr_slug}{slug_suffix}"}
            )

        print(f"Removed boolean options for {attr_slug} attribute")
