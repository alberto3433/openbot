"""link_global_options_to_ingredients

Revision ID: b6c7d8e9f0g1
Revises: a5b6c7d8e9f0
Create Date: 2026-01-10

This migration:
1. Creates Ingredient records for espresso shot options (Single, Double, Triple, Quad)
2. Links all GlobalAttributeOptions with aliases/must_match to their Ingredients
3. Migrates any missing aliases from GlobalAttributeOption to Ingredient

This is part of the normalization effort to have Ingredient as the single
source of truth for aliases and must_match values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0g1'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Link GlobalAttributeOptions to Ingredients and migrate aliases."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # 1. Create Ingredient records for espresso shots
    shot_ingredients = [
        ("Single Shot", "1|one|single shot|1 shot"),
        ("Double Shot", "2|two|double shot|2 shots"),
        ("Triple Shot", "3|three|triple shot|3 shots"),
        ("Quad Shot", "4|four|quad shot|4 shots|quadruple"),
    ]

    shot_ingredient_ids = {}
    for name, aliases in shot_ingredients:
        # Insert the ingredient with all required columns
        slug = name.lower().replace(" ", "_")
        result = session.execute(
            sa.text("""
                INSERT INTO ingredients (
                    name, slug, category, unit, track_inventory, base_price,
                    is_available, is_vegan, is_vegetarian, is_gluten_free,
                    is_dairy_free, is_kosher, contains_eggs, contains_fish,
                    contains_sesame, contains_nuts, aliases
                )
                VALUES (
                    :name, :slug, 'espresso', 'shot', false, 0.0,
                    true, true, true, true,
                    true, false, false, false,
                    false, false, :aliases
                )
                ON CONFLICT (name) DO UPDATE SET aliases = :aliases
                RETURNING id
            """),
            {"name": name, "slug": slug, "aliases": aliases}
        )
        row = result.fetchone()
        shot_ingredient_ids[name.lower().replace(" ", "_").replace("_shot", "")] = row[0]

    # 2. Link shot options to their new ingredients
    shot_slugs = ["single", "double", "triple", "quad"]
    for slug in shot_slugs:
        ing_id = shot_ingredient_ids.get(slug)
        if ing_id:
            session.execute(
                sa.text("""
                    UPDATE global_attribute_options
                    SET ingredient_id = :ing_id
                    WHERE slug = :slug AND ingredient_id IS NULL
                """),
                {"ing_id": ing_id, "slug": slug}
            )

    # 3. Link syrup options to their ingredients and add aliases
    syrup_mappings = [
        ("vanilla_syrup", "Vanilla Syrup", "vanilla"),
        ("hazelnut_syrup", "Hazelnut Syrup", "hazelnut"),
        ("caramel_syrup", "Caramel Syrup", "caramel"),
        ("peppermint_syrup", "Peppermint Syrup", "peppermint"),
    ]

    for option_slug, ing_name, alias_to_add in syrup_mappings:
        # Get ingredient id
        result = session.execute(
            sa.text("SELECT id, aliases FROM ingredients WHERE name = :name"),
            {"name": ing_name}
        )
        row = result.fetchone()
        if row:
            ing_id, existing_aliases = row
            # Add alias if not already present
            if existing_aliases:
                if alias_to_add not in existing_aliases.split("|"):
                    new_aliases = f"{existing_aliases}|{alias_to_add}"
                else:
                    new_aliases = existing_aliases
            else:
                new_aliases = alias_to_add

            session.execute(
                sa.text("UPDATE ingredients SET aliases = :aliases WHERE id = :id"),
                {"aliases": new_aliases, "id": ing_id}
            )

            # Link the option
            session.execute(
                sa.text("""
                    UPDATE global_attribute_options
                    SET ingredient_id = :ing_id
                    WHERE slug = :slug AND ingredient_id IS NULL
                """),
                {"ing_id": ing_id, "slug": option_slug}
            )

    # 4. Link milk options to their ingredients (already have must_match)
    milk_mappings = [
        ("skim_milk", "Skim Milk"),
        ("oat_milk", "Oat Milk"),
        ("almond_milk", "Almond Milk"),
        ("soy_milk", "Soy Milk"),
        ("lactose_free_milk", "Lactose Free Milk"),
        ("whole_milk", "Whole Milk"),
        ("half_n_half", "Half & Half"),
    ]

    for option_slug, ing_name in milk_mappings:
        result = session.execute(
            sa.text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": ing_name}
        )
        row = result.fetchone()
        if row:
            ing_id = row[0]
            session.execute(
                sa.text("""
                    UPDATE global_attribute_options
                    SET ingredient_id = :ing_id
                    WHERE slug = :slug AND ingredient_id IS NULL
                """),
                {"ing_id": ing_id, "slug": option_slug}
            )

    # 5. Link sugar option to Domino Sugar and add "regular sugar" alias
    result = session.execute(
        sa.text("SELECT id, aliases FROM ingredients WHERE name = 'Domino Sugar'")
    )
    row = result.fetchone()
    if row:
        ing_id, existing_aliases = row
        # Add "regular sugar" alias if not present
        if existing_aliases:
            if "regular sugar" not in existing_aliases.split("|"):
                new_aliases = f"{existing_aliases}|regular sugar"
            else:
                new_aliases = existing_aliases
        else:
            new_aliases = "sugar|regular sugar"

        session.execute(
            sa.text("UPDATE ingredients SET aliases = :aliases WHERE id = :id"),
            {"aliases": new_aliases, "id": ing_id}
        )

        session.execute(
            sa.text("""
                UPDATE global_attribute_options
                SET ingredient_id = :ing_id
                WHERE slug = 'sugar' AND ingredient_id IS NULL
            """),
            {"ing_id": ing_id}
        )

    # 6. Link sweetener options
    sweetener_mappings = [
        ("sugar_in_the_raw", "Sugar in the Raw"),
        ("splenda", "Splenda"),
        ("equal", "Equal"),
        ("sweet_n_low", "Sweet'N Low"),
    ]

    for option_slug, ing_name in sweetener_mappings:
        result = session.execute(
            sa.text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": ing_name}
        )
        row = result.fetchone()
        if row:
            ing_id = row[0]
            session.execute(
                sa.text("""
                    UPDATE global_attribute_options
                    SET ingredient_id = :ing_id
                    WHERE slug = :slug AND ingredient_id IS NULL
                """),
                {"ing_id": ing_id, "slug": option_slug}
            )

    session.commit()


def downgrade() -> None:
    """Remove the ingredient links (but keep the ingredients)."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Unlink the options we linked
    slugs_to_unlink = [
        "single", "double", "triple", "quad",
        "vanilla_syrup", "hazelnut_syrup", "caramel_syrup", "peppermint_syrup",
        "skim_milk", "oat_milk", "almond_milk", "soy_milk", "lactose_free_milk",
        "whole_milk", "half_n_half", "sugar", "sugar_in_the_raw", "splenda",
        "equal", "sweet_n_low",
    ]

    for slug in slugs_to_unlink:
        session.execute(
            sa.text("""
                UPDATE global_attribute_options
                SET ingredient_id = NULL
                WHERE slug = :slug
            """),
            {"slug": slug}
        )

    # Note: We don't delete the shot ingredients as they may be used elsewhere
    # If needed, they can be manually removed

    session.commit()
