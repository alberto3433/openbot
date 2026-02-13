"""Add FK constraints for ingredient category references.

Revision ID: fk_ingr_cat_001
Revises: link_options_001
Create Date: 2026-02-13

Adds foreign key constraints enforcing that:
- ingredients.category references ingredient_categories.slug
- modifier_categories.ingredient_category references ingredient_categories.slug

Both columns already follow this convention by design but had no database-level
enforcement. A typo in either column would silently break runtime behavior
(e.g., ingredients disappearing from category listings, "what spreads do you
have?" returning empty).

ingredient_categories.slug already has a UNIQUE index (ix_ingredient_categories_slug),
so it is a valid FK target.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fk_ingr_cat_001"
down_revision: Union[str, Sequence[str], None] = "link_options_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1: Validate existing data ──────────────────────────────────
    # Any invalid values will cause the FK constraint to fail. Detect them
    # early with a clear error message so the operator can fix the data.

    invalid_ingredients = conn.execute(sa.text(
        "SELECT i.id, i.name, i.category "
        "FROM ingredients i "
        "LEFT JOIN ingredient_categories ic ON i.category = ic.slug "
        "WHERE ic.slug IS NULL"
    )).fetchall()

    if invalid_ingredients:
        details = "; ".join(
            f"id={r[0]} name='{r[1]}' category='{r[2]}'"
            for r in invalid_ingredients
        )
        raise RuntimeError(
            f"Cannot add FK: {len(invalid_ingredients)} ingredient(s) have "
            f"category values not in ingredient_categories.slug: {details}"
        )

    invalid_mod_cats = conn.execute(sa.text(
        "SELECT mc.id, mc.slug, mc.ingredient_category "
        "FROM modifier_categories mc "
        "LEFT JOIN ingredient_categories ic ON mc.ingredient_category = ic.slug "
        "WHERE mc.ingredient_category IS NOT NULL AND ic.slug IS NULL"
    )).fetchall()

    if invalid_mod_cats:
        details = "; ".join(
            f"id={r[0]} slug='{r[1]}' ingredient_category='{r[2]}'"
            for r in invalid_mod_cats
        )
        raise RuntimeError(
            f"Cannot add FK: {len(invalid_mod_cats)} modifier_categories row(s) "
            f"have invalid ingredient_category values: {details}"
        )

    # ── Step 2: Add FK constraints ──────────────────────────────────────
    op.create_foreign_key(
        "fk_ingredients_category_ingredient_categories",
        "ingredients",
        "ingredient_categories",
        ["category"],
        ["slug"],
    )

    op.create_foreign_key(
        "fk_modifier_categories_ingredient_category",
        "modifier_categories",
        "ingredient_categories",
        ["ingredient_category"],
        ["slug"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_modifier_categories_ingredient_category",
        "modifier_categories",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_ingredients_category_ingredient_categories",
        "ingredients",
        type_="foreignkey",
    )
