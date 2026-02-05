"""Move overall_category from item_types to menu_display_groups.

Revision ID: display_grp_02
Revises: display_grp_01
Create Date: 2026-02-05

This migration normalizes the schema by moving the overall_category relationship
from item_types to menu_display_groups. The category (food vs beverage) is
really a property of the display group, not individual item types.

Changes:
1. Add overall_category_id to menu_display_groups
2. Populate display groups with categories based on their item types
3. Ensure all item types have a display group (make FK NOT NULL)
4. Drop overall_category_id from item_types
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "display_grp_02"
down_revision = "display_grp_01"
branch_labels = None
depends_on = None


# Display group to category mapping
# Based on the logical grouping: drinks are beverages, everything else is food
DISPLAY_GROUP_CATEGORIES = {
    "breads": "food",
    "sandwiches": "food",
    "omelettes_breakfasts": "food",
    "drinks": "beverage",
    "desserts_pastries": "food",
    "sides": "food",
    "food_by_pound": "food",
}


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add overall_category_id to menu_display_groups
    op.add_column(
        "menu_display_groups",
        sa.Column(
            "overall_category_id",
            sa.Integer(),
            sa.ForeignKey("overall_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_menu_display_groups_overall_category_id"),
        "menu_display_groups",
        ["overall_category_id"],
        unique=False,
    )

    # Step 2: Populate display groups with categories
    for group_slug, category_slug in DISPLAY_GROUP_CATEGORIES.items():
        conn.execute(
            sa.text("""
                UPDATE menu_display_groups
                SET overall_category_id = (
                    SELECT id FROM overall_categories WHERE slug = :category_slug
                )
                WHERE slug = :group_slug
            """),
            {"group_slug": group_slug, "category_slug": category_slug},
        )
        print(f"Set {group_slug} -> {category_slug}")

    # Step 3: Check for item types without display groups and assign them
    orphan_item_types = conn.execute(
        sa.text("""
            SELECT id, slug, overall_category_id
            FROM item_types
            WHERE menu_display_group_id IS NULL
        """)
    ).fetchall()

    if orphan_item_types:
        print(f"Found {len(orphan_item_types)} item types without display groups")
        # Assign orphans to a reasonable default based on their category
        for item_type_id, item_type_slug, category_id in orphan_item_types:
            # Get the category slug
            if category_id:
                result = conn.execute(
                    sa.text("SELECT slug FROM overall_categories WHERE id = :id"),
                    {"id": category_id},
                ).fetchone()
                category_slug = result[0] if result else "food"
            else:
                category_slug = "food"

            # Assign to appropriate display group
            if category_slug == "beverage":
                target_group = "drinks"
            else:
                target_group = "sides"  # Default for misc food items

            conn.execute(
                sa.text("""
                    UPDATE item_types
                    SET menu_display_group_id = (
                        SELECT id FROM menu_display_groups WHERE slug = :group_slug
                    )
                    WHERE id = :item_type_id
                """),
                {"group_slug": target_group, "item_type_id": item_type_id},
            )
            print(f"Assigned orphan item type '{item_type_slug}' to '{target_group}'")

    # Step 4: Make menu_display_group_id NOT NULL on item_types
    op.alter_column(
        "item_types",
        "menu_display_group_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Step 5: Drop overall_category_id from item_types
    op.drop_index(op.f("ix_item_types_overall_category_id"), table_name="item_types")
    op.drop_column("item_types", "overall_category_id")


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add overall_category_id back to item_types
    op.add_column(
        "item_types",
        sa.Column(
            "overall_category_id",
            sa.Integer(),
            sa.ForeignKey("overall_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_item_types_overall_category_id"),
        "item_types",
        ["overall_category_id"],
        unique=False,
    )

    # Step 2: Populate item_types.overall_category_id from their display groups
    conn.execute(
        sa.text("""
            UPDATE item_types
            SET overall_category_id = (
                SELECT mdg.overall_category_id
                FROM menu_display_groups mdg
                WHERE mdg.id = item_types.menu_display_group_id
            )
        """)
    )

    # Step 3: Make menu_display_group_id nullable again
    op.alter_column(
        "item_types",
        "menu_display_group_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # Step 4: Drop overall_category_id from menu_display_groups
    op.drop_index(
        op.f("ix_menu_display_groups_overall_category_id"),
        table_name="menu_display_groups",
    )
    op.drop_column("menu_display_groups", "overall_category_id")
