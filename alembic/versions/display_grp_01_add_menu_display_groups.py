"""Add menu_display_groups table and FK to item_types.

Revision ID: display_grp_01
Revises: show_options_01
Create Date: 2026-02-05

Adds a menu_display_groups table to consolidate item types into user-friendly
groups for menu listing. When user asks "what's on your menu?", we show these
7 groups instead of 25+ granular item types.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "display_grp_01"
down_revision = "show_options_01"
branch_labels = None
depends_on = None


# Display groups with their order
# Format: (slug, display_name, display_order)
DISPLAY_GROUPS = [
    ("breads", "Breads", 1),
    ("sandwiches", "Sandwiches", 2),
    ("omelettes_breakfasts", "Omelettes and Breakfasts", 3),
    ("drinks", "Drinks", 4),
    ("desserts_pastries", "Desserts and Pastries", 5),
    ("sides", "Sides", 6),
    ("food_by_pound", "Food by the Pound", 7),
]

# Mapping of item_type slug to display_group slug
ITEM_TYPE_TO_GROUP = {
    # Breads
    "bagel": "breads",
    # Sandwiches
    "egg_sandwich": "sandwiches",
    "fish_sandwich": "sandwiches",
    "spread_sandwich": "sandwiches",
    "deli_sandwich": "sandwiches",
    "cheese_sandwich": "sandwiches",
    # Omelettes and Breakfasts
    "omelette": "omelettes_breakfasts",
    "breakfast": "omelettes_breakfasts",
    # Drinks
    "sized_beverage": "drinks",
    "espresso_based": "drinks",
    "espresso": "drinks",
    "tea": "drinks",
    "iced_tea": "drinks",
    "chai_drink": "drinks",
    "beverage": "drinks",
    # Desserts and Pastries
    "snack": "desserts_pastries",
    "pastry": "desserts_pastries",
    # Sides
    "side": "sides",
    "fruit_salad": "sides",
    "soup": "sides",
    "salad": "sides",
    # Food by the Pound
    "fish": "food_by_pound",
    "cheese": "food_by_pound",
    "cold_cut": "food_by_pound",
    "spread": "food_by_pound",
}


def upgrade() -> None:
    # Create the menu_display_groups table
    op.create_table(
        "menu_display_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_menu_display_groups_id"),
        "menu_display_groups",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_menu_display_groups_slug"),
        "menu_display_groups",
        ["slug"],
        unique=True,
    )

    # Add FK column to item_types
    op.add_column(
        "item_types",
        sa.Column(
            "menu_display_group_id",
            sa.Integer(),
            sa.ForeignKey("menu_display_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_item_types_menu_display_group_id"),
        "item_types",
        ["menu_display_group_id"],
        unique=False,
    )

    # Seed the display groups
    conn = op.get_bind()
    for slug, display_name, display_order in DISPLAY_GROUPS:
        conn.execute(
            sa.text("""
                INSERT INTO menu_display_groups (slug, display_name, display_order)
                VALUES (:slug, :display_name, :display_order)
            """),
            {"slug": slug, "display_name": display_name, "display_order": display_order},
        )
        print(f"Created display group: {slug}")

    # Update item_types with their display group IDs
    for item_type_slug, group_slug in ITEM_TYPE_TO_GROUP.items():
        conn.execute(
            sa.text("""
                UPDATE item_types
                SET menu_display_group_id = (
                    SELECT id FROM menu_display_groups WHERE slug = :group_slug
                )
                WHERE slug = :item_type_slug
            """),
            {"item_type_slug": item_type_slug, "group_slug": group_slug},
        )
        print(f"Mapped {item_type_slug} -> {group_slug}")


def downgrade() -> None:
    # Remove FK from item_types
    op.drop_index(op.f("ix_item_types_menu_display_group_id"), table_name="item_types")
    op.drop_column("item_types", "menu_display_group_id")

    # Drop the menu_display_groups table
    op.drop_index(op.f("ix_menu_display_groups_slug"), table_name="menu_display_groups")
    op.drop_index(op.f("ix_menu_display_groups_id"), table_name="menu_display_groups")
    op.drop_table("menu_display_groups")
