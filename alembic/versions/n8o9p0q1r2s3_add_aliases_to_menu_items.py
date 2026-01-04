"""add_aliases_to_menu_items

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-01-04

Adds an 'aliases' column to menu_items table for storing alternative names/synonyms.
This allows user input like "coke" to match "Coca-Cola" or "oj" to match orange juice.

The aliases column is comma-separated text, similar to required_match_phrases:
- required_match_phrases: Input MUST contain one of these (filter OUT false matches)
- aliases: Input CAN match any of these (filter IN additional matches)

This migration also populates aliases for beverage items to replace the hardcoded
SODA_DRINK_TYPES constant in constants.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'n8o9p0q1r2s3'
down_revision: Union[str, Sequence[str], None] = 'm7n8o9p0q1r2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Beverage aliases mapping: item name -> comma-separated aliases
BEVERAGE_ALIASES = {
    # Coca-Cola products
    "Coca-Cola": "coke, coca cola, coca-cola",
    "Diet Coke": "diet coca cola, diet coca-cola",

    # Sprite
    "Sprite": "sprite",

    # Ginger Ale
    "Ginger Ale": "ginger ale",
    "Boylan's Ginger Ale": "boylans ginger ale, boylan ginger ale",

    # Root Beer
    "Boylan's Root Beer": "root beer, boylans root beer, boylan root beer",

    # Dr. Brown's sodas
    "Dr. Brown's Cream Soda": "dr browns cream soda, dr brown's cream soda, dr. browns cream soda",
    "Dr. Brown's Black Cherry": "dr browns black cherry, dr brown's black cherry, dr. browns black cherry",
    "Dr. Brown's Cel-Ray": "cel-ray, celray, dr browns cel-ray, dr brown's cel-ray, dr. browns cel-ray",

    # Water
    "Bottled Water": "water, bottled water",
    "Poland Spring": "poland spring",
    "San Pellegrino": "pellegrino, san pellegrino, sparkling water, seltzer",

    # Juices
    "Fresh Squeezed Orange Juice": "oj, orange juice, fresh oj",
    "Apple Juice": "apple juice",
    "Cranberry Juice": "cranberry juice, cran juice",
    "Tropicana Orange Juice No Pulp": "tropicana, tropicana oj, tropicana orange juice",
    "Tropicana Orange Juice 46 oz": "tropicana 46, large tropicana",

    # Snapple
    "Snapple Iced Tea": "snapple iced tea, snapple tea",
    "Snapple Lemonade": "snapple lemonade",
    "Snapple Peach Tea": "snapple peach, snapple peach tea",

    # Milk
    "Chocolate Milk": "chocolate milk, choc milk",

    # Iced Tea (bottled)
    "ITO EN Green Tea": "ito en, itoen, ito en green tea",
}


def upgrade() -> None:
    """Add aliases column to menu_items table and populate beverage aliases."""
    # Add the aliases column
    op.add_column(
        'menu_items',
        sa.Column('aliases', sa.String(), nullable=True)
    )

    # Populate aliases for beverages
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Get menu_items table
        menu_items = sa.table(
            'menu_items',
            sa.column('id', sa.Integer),
            sa.column('name', sa.String),
            sa.column('aliases', sa.String),
        )

        # Update each beverage with its aliases
        for item_name, aliases in BEVERAGE_ALIASES.items():
            session.execute(
                menu_items.update()
                .where(menu_items.c.name == item_name)
                .values(aliases=aliases)
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """Remove aliases column from menu_items table."""
    op.drop_column('menu_items', 'aliases')
