"""Migrate by_pound_categories to ItemType.

Revision ID: b5c6d7e8f9g1
Revises: 57a09fe179d1
Create Date: 2026-01-11 01:00:00.000000

This migration:
1. Creates 5 new ItemType entries (cheese, cold_cut, fish, salad, spread)
   with display_name_plural for human-readable category names
2. Updates MenuItem.item_type_id to point to the new category types
   instead of the generic "by_the_lb" type
3. Drops the by_pound_category column (now redundant)
4. Drops the by_pound_categories table (replaced by ItemType)

This eliminates the domain-specific by_pound_categories table in favor
of the generic ItemType system.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9g1"
down_revision: Union[str, None] = "57a09fe179d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New ItemTypes to create
# Format: slug -> (display_name, display_name_plural)
NEW_ITEM_TYPES = {
    "cheese": ("Cheese", "cheeses"),
    "cold_cut": ("Cold Cut", "cold cuts"),
    "fish": ("Smoked Fish", "smoked fish"),
    "salad": ("Salad", "salads"),
    "spread": ("Spread", "spreads"),
}

# The by_pound_category values map directly to new item_type slugs
BY_POUND_CATEGORIES = ["cheese", "cold_cut", "fish", "salad", "spread"]


def upgrade() -> None:
    """Create new ItemTypes and migrate by-pound items to use them."""
    conn = op.get_bind()

    # Step 1: Create the 5 new ItemType entries
    new_type_ids = {}
    for slug, (display_name, display_name_plural) in NEW_ITEM_TYPES.items():
        # Check if type already exists
        result = conn.execute(
            sa.text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": slug}
        )
        existing = result.fetchone()

        if existing:
            # Type exists, just update display_name_plural if needed
            new_type_ids[slug] = existing[0]
            conn.execute(
                sa.text("""
                    UPDATE item_types
                    SET display_name_plural = :plural
                    WHERE id = :id
                """),
                {"plural": display_name_plural, "id": existing[0]}
            )
        else:
            # Create new type
            conn.execute(
                sa.text("""
                    INSERT INTO item_types (slug, display_name, display_name_plural)
                    VALUES (:slug, :name, :plural)
                """),
                {"slug": slug, "name": display_name, "plural": display_name_plural}
            )
            result = conn.execute(
                sa.text("SELECT id FROM item_types WHERE slug = :slug"),
                {"slug": slug}
            )
            new_type_ids[slug] = result.fetchone()[0]

    # Step 2: Update MenuItem.item_type_id based on by_pound_category
    for category in BY_POUND_CATEGORIES:
        if category in new_type_ids:
            conn.execute(
                sa.text("""
                    UPDATE menu_items
                    SET item_type_id = :new_type_id
                    WHERE by_pound_category = :category
                """),
                {"new_type_id": new_type_ids[category], "category": category}
            )

    # Step 3: Drop the by_pound_category column
    op.drop_column("menu_items", "by_pound_category")

    # Step 4: Drop by_pound_categories table if it exists
    try:
        op.drop_index("ix_by_pound_categories_slug", table_name="by_pound_categories")
    except Exception:
        pass  # Index may not exist

    try:
        op.drop_table("by_pound_categories")
    except Exception:
        pass  # Table may not exist


def downgrade() -> None:
    """Restore by_pound_category column and by_pound_categories table."""
    conn = op.get_bind()

    # Step 1: Re-add by_pound_category column
    op.add_column(
        "menu_items",
        sa.Column("by_pound_category", sa.String(), nullable=True)
    )

    # Step 2: Restore by_pound_category values from item_type_id
    for category in BY_POUND_CATEGORIES:
        # Get the item_type_id for this category
        result = conn.execute(
            sa.text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": category}
        )
        row = result.fetchone()
        if row:
            type_id = row[0]
            conn.execute(
                sa.text("""
                    UPDATE menu_items
                    SET by_pound_category = :category
                    WHERE item_type_id = :type_id
                """),
                {"category": category, "type_id": type_id}
            )

    # Step 3: Recreate by_pound_categories table
    op.create_table(
        "by_pound_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_by_pound_categories_slug", "by_pound_categories", ["slug"])

    # Seed the category names
    for slug, (_, display_name_plural) in NEW_ITEM_TYPES.items():
        conn.execute(
            sa.text("""
                INSERT INTO by_pound_categories (slug, display_name)
                VALUES (:slug, :display_name)
            """),
            {"slug": slug, "display_name": display_name_plural}
        )

    # Note: We don't delete the ItemType entries in downgrade
    # as they may be useful and don't cause conflicts
