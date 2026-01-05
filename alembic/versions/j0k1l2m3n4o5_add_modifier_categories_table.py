"""Add modifier_categories table.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-01-05 12:00:00.000000

This migration creates the modifier_categories table to replace the hardcoded
MODIFIER_CATEGORY_KEYWORDS constant in constants.py.

The table maps user input keywords (like "sweetener", "sugar", "milk", "dairy")
to canonical category names (like "sweeteners", "milks") for answering
questions like "what sweeteners do you have?".
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed data for modifier categories
# Format: (slug, display_name, aliases, description, prompt_suffix, loads_from_ingredients, ingredient_category)
MODIFIER_CATEGORIES = [
    # Static categories (not database-backed)
    (
        "sweeteners",
        "Sweeteners",
        "sweetener, sweeteners, sugar, sugars",
        "For sweeteners, we have sugar, raw sugar, honey, Equal, Splenda, and Stevia.",
        "Would you like any of these in your drink?",
        False,
        None,
    ),
    (
        "milks",
        "Milks",
        "milk, milks, cream, dairy",
        "For milk options, we have whole milk, skim, 2%, oat milk, almond milk, and soy milk.",
        "Which would you like?",
        False,
        None,
    ),
    (
        "syrups",
        "Flavor Syrups",
        "syrup, syrups, flavor, flavors, flavor syrup, flavor syrups",
        "We have vanilla, hazelnut, and caramel flavor syrups.",
        "Would you like to add a flavor?",
        False,
        None,
    ),
    (
        "condiments",
        "Condiments",
        "condiment, condiments",
        "We have mayo, mustard, ketchup, hot sauce, and salt & pepper.",
        "Would you like any of these?",
        False,
        None,
    ),
    (
        "add-ons",
        "Add-ons",
        "add-on, add-ons, addon, addons",
        "You can add extra proteins, cheeses, or veggies to most items.",
        "What would you like to add?",
        False,
        None,
    ),
    (
        "extras",
        "Extras",
        "extra, extras",
        "You can add extra proteins, cheeses, or veggies to most items.",
        "What would you like to add?",
        False,
        None,
    ),
    # Database-backed categories (load from Ingredient table)
    (
        "toppings",
        "Toppings",
        "topping, toppings, bagel topping, bagel toppings",
        None,  # Will be generated from database
        "What would you like on your bagel?",
        True,
        "topping",
    ),
    (
        "proteins",
        "Proteins",
        "protein, proteins, meat, meats",
        None,
        "What would you like?",
        True,
        "protein",
    ),
    (
        "cheeses",
        "Cheeses",
        "cheese, cheeses",
        None,
        "Which cheese would you like?",
        True,
        "cheese",
    ),
    (
        "spreads",
        "Spreads",
        "spread, spreads, cream cheese",
        None,
        "What sounds good?",
        True,
        "spread",
    ),
]


def upgrade() -> None:
    # Create the modifier_categories table
    op.create_table(
        "modifier_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("aliases", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("prompt_suffix", sa.String(), nullable=True),
        sa.Column("loads_from_ingredients", sa.Boolean(), nullable=False, default=False),
        sa.Column("ingredient_category", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_modifier_categories_id"), "modifier_categories", ["id"], unique=False)
    op.create_index(op.f("ix_modifier_categories_slug"), "modifier_categories", ["slug"], unique=True)

    # Seed the data
    conn = op.get_bind()
    for slug, display_name, aliases, description, prompt_suffix, loads_from_ingredients, ingredient_category in MODIFIER_CATEGORIES:
        conn.execute(
            sa.text("""
                INSERT INTO modifier_categories
                (slug, display_name, aliases, description, prompt_suffix, loads_from_ingredients, ingredient_category)
                VALUES (:slug, :display_name, :aliases, :description, :prompt_suffix, :loads_from_ingredients, :ingredient_category)
            """),
            {
                "slug": slug,
                "display_name": display_name,
                "aliases": aliases,
                "description": description,
                "prompt_suffix": prompt_suffix,
                "loads_from_ingredients": loads_from_ingredients,
                "ingredient_category": ingredient_category,
            }
        )
        print(f"Created modifier category: {slug}")


def downgrade() -> None:
    op.drop_index(op.f("ix_modifier_categories_slug"), table_name="modifier_categories")
    op.drop_index(op.f("ix_modifier_categories_id"), table_name="modifier_categories")
    op.drop_table("modifier_categories")
