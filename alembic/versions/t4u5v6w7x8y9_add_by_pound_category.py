"""Add by_pound_category column to menu_items.

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2025-01-04 12:00:00.000000

This migration:
1. Adds by_pound_category column to menu_items
2. Populates it for existing by_the_lb (fish) and cream_cheese (spread) items
3. Adds aliases for common synonyms (lox, nova, etc.)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "t4u5v6w7x8y9"
down_revision: Union[str, None] = "s3t4u5v6w7x8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# By-pound category assignments based on item_type_id
# item_type_id 4 = by_the_lb (fish items)
# item_type_id 5 = cream_cheese (spread items)
BY_POUND_CATEGORIES = {
    4: "fish",      # by_the_lb type
    5: "spread",    # cream_cheese type
}

# Aliases for by-the-pound items
# Maps item name pattern to comma-separated aliases
BY_POUND_ALIASES = {
    # Fish items
    "Nova Scotia Salmon": "nova, lox, nova lox, nova scotia salmon (lox), smoked salmon",
    "Belly Lox": "belly, belly salmon",
    "Whitefish Salad": "whitefish",
    "Whitefish (Whole)": "whole whitefish",
    "Sable": "sable fish, sablefish",
    "Lake Sturgeon": "sturgeon, smoked sturgeon",
    "Gravlax": "cured salmon",
    "Smoked Trout": "trout",
    # Cream cheese items - base names without size suffixes
    "Plain Cream Cheese": "plain cc, regular cream cheese, regular cc",
    "Scallion Cream Cheese": "scallion cc, chive cream cheese, chive cc",
    "Vegetable Cream Cheese": "veggie cream cheese, veggie cc, vegetable cc",
    "Strawberry Cream Cheese": "strawberry cc",
    "Blueberry Cream Cheese": "blueberry cc",
    "Jalapeno Cream Cheese": "jalapeño cc, jalapeno cc, spicy cream cheese",
    "Nova Scotia Cream Cheese": "lox spread, nova cc, nova spread",
    "Truffle Cream Cheese": "truffle cc",
    "Maple Raisin Walnut Cream Cheese": "maple walnut cc, maple raisin cc",
    "Kalamata Olive Cream Cheese": "olive cc, olive cream cheese",
    "Sun-Dried Tomato Cream Cheese": "sun dried tomato cc, tomato cc",
}


def upgrade() -> None:
    # Add by_pound_category column
    op.add_column(
        "menu_items",
        sa.Column("by_pound_category", sa.String(), nullable=True)
    )

    # Get connection for data updates
    conn = op.get_bind()

    # Update by_pound_category based on item_type_id
    for type_id, category in BY_POUND_CATEGORIES.items():
        conn.execute(
            sa.text("""
                UPDATE menu_items
                SET by_pound_category = :category
                WHERE item_type_id = :type_id
            """),
            {"category": category, "type_id": type_id}
        )

    # Add aliases for by-pound items
    for name_pattern, aliases in BY_POUND_ALIASES.items():
        # Update items that match the pattern (handles both "Name (1 lb)" and "Name (1/4 lb)")
        conn.execute(
            sa.text("""
                UPDATE menu_items
                SET aliases = :aliases
                WHERE name LIKE :pattern
                AND aliases IS NULL
            """),
            {"aliases": aliases, "pattern": f"{name_pattern}%"}
        )


def downgrade() -> None:
    # Remove by_pound_category column
    op.drop_column("menu_items", "by_pound_category")

    # Clear aliases that were added (only those matching our patterns)
    conn = op.get_bind()
    for name_pattern in BY_POUND_ALIASES.keys():
        conn.execute(
            sa.text("""
                UPDATE menu_items
                SET aliases = NULL
                WHERE name LIKE :pattern
            """),
            {"pattern": f"{name_pattern}%"}
        )
