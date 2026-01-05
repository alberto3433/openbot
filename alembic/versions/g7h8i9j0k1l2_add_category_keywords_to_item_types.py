"""Add category keyword support to item_types table.

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-01-05 12:00:00.000000

This migration:
1. Adds columns to item_types for category keyword support:
   - aliases: comma-separated keywords that map to this type
   - expands_to: JSON array of slugs to query for meta-categories
   - name_filter: substring filter for item names
   - is_virtual: true for meta-categories without direct items

2. Populates aliases for existing item_types (bagels, omelettes, etc.)

3. Creates virtual/meta category rows for:
   - dessert (expands to pastry + snack)
   - beverage_all (expands to sized_beverage + beverage)
   - coffee (expands to sized_beverage)
   - tea (expands to sized_beverage with name_filter)
   - soda (expands to beverage)
   - sandwich_all (expands to all sandwich types)

This replaces the hardcoded MENU_CATEGORY_KEYWORDS in constants.py.
"""

from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Aliases for existing item_types
# Format: (slug, aliases_csv)
EXISTING_TYPE_ALIASES = [
    ("bagel", "bagels"),
    ("omelette", "omelettes,omelets"),
    ("side", "sides"),
    ("egg_sandwich", "egg sandwiches"),
    ("fish_sandwich", "fish sandwiches"),
    ("spread_sandwich", "spread sandwiches,cream cheese sandwiches"),
    ("salad_sandwich", "salad sandwiches"),
    ("signature_sandwich", "signature sandwiches"),
    ("deli_classic", "deli sandwiches,deli classics"),
    ("snack", "snacks"),
    ("pastry", "pastries"),
    ("soup", "soups"),
    ("salad", "salads"),
    ("breakfast", "breakfasts"),
]

# Virtual/meta categories to create
# Format: (slug, display_name, aliases_csv, expands_to_json, name_filter)
VIRTUAL_CATEGORIES = [
    (
        "dessert",
        "Desserts",
        "desserts,sweets,sweet stuff,bakery,baked goods,treats,cookies,muffins,brownies,donuts,doughnuts",
        ["pastry", "snack"],
        None,
    ),
    (
        "beverage_all",
        "Drinks",
        "drinks,beverages",
        ["sized_beverage", "beverage"],
        None,
    ),
    (
        "coffee",
        "Coffee",
        "coffees,lattes,cappuccinos,espressos",
        ["sized_beverage"],
        None,
    ),
    (
        "tea",
        "Tea",
        "teas",
        ["sized_beverage"],
        "tea",  # name_filter to match items with "tea" in name
    ),
    (
        "soda",
        "Sodas",
        "sodas",
        ["beverage"],
        None,
    ),
    (
        "sandwich_all",
        "Sandwiches",
        "sandwiches",
        ["egg_sandwich", "fish_sandwich", "spread_sandwich", "salad_sandwich", "signature_sandwich", "deli_classic", "smoked_fish_sandwich"],
        None,
    ),
]


def upgrade() -> None:
    """Add category keyword columns and populate data."""
    # Step 1: Add new columns
    op.add_column('item_types', sa.Column('aliases', sa.String(), nullable=True))
    op.add_column('item_types', sa.Column('expands_to', sa.JSON(), nullable=True))
    op.add_column('item_types', sa.Column('name_filter', sa.String(), nullable=True))
    op.add_column('item_types', sa.Column('is_virtual', sa.Boolean(), nullable=True, server_default='false'))

    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Step 2: Update aliases on existing item_types
        for slug, aliases in EXISTING_TYPE_ALIASES:
            session.execute(
                sa.text("UPDATE item_types SET aliases = :aliases WHERE slug = :slug"),
                {"slug": slug, "aliases": aliases}
            )
            print(f"  Updated aliases for item_type: {slug}")

        # Step 3: Create virtual/meta category rows
        for slug, display_name, aliases, expands_to, name_filter in VIRTUAL_CATEGORIES:
            # Check if already exists
            result = session.execute(
                sa.text("SELECT id FROM item_types WHERE slug = :slug"),
                {"slug": slug}
            )
            existing = result.fetchone()

            if existing:
                # Update existing row
                session.execute(
                    sa.text("""
                        UPDATE item_types
                        SET display_name = :display_name,
                            aliases = :aliases,
                            expands_to = :expands_to,
                            name_filter = :name_filter,
                            is_virtual = true
                        WHERE slug = :slug
                    """),
                    {
                        "slug": slug,
                        "display_name": display_name,
                        "aliases": aliases,
                        "expands_to": json.dumps(expands_to),
                        "name_filter": name_filter,
                    }
                )
                print(f"  Updated virtual category: {slug}")
            else:
                # Insert new row
                session.execute(
                    sa.text("""
                        INSERT INTO item_types (slug, display_name, aliases, expands_to, name_filter, is_virtual, is_configurable, skip_config)
                        VALUES (:slug, :display_name, :aliases, :expands_to, :name_filter, true, false, true)
                    """),
                    {
                        "slug": slug,
                        "display_name": display_name,
                        "aliases": aliases,
                        "expands_to": json.dumps(expands_to),
                        "name_filter": name_filter,
                    }
                )
                print(f"  Created virtual category: {slug}")

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """Remove category keyword columns and virtual categories."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Remove virtual categories
        for slug, _, _, _, _ in VIRTUAL_CATEGORIES:
            session.execute(
                sa.text("DELETE FROM item_types WHERE slug = :slug AND is_virtual = true"),
                {"slug": slug}
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

    # Remove columns
    op.drop_column('item_types', 'is_virtual')
    op.drop_column('item_types', 'name_filter')
    op.drop_column('item_types', 'expands_to')
    op.drop_column('item_types', 'aliases')
