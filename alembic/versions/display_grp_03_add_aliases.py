"""Add menu_display_group_aliases table.

Revision ID: display_grp_03
Revises: display_grp_02
Create Date: 2026-02-05

Adds aliases table so users can reference display groups by various names.
E.g., "desserts_pastries" group can be found via "pastries", "pastry", "sweets".
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "display_grp_03"
down_revision = "display_grp_02"
branch_labels = None
depends_on = None


# Initial aliases for each display group
# Format: group_slug -> list of aliases
DISPLAY_GROUP_ALIASES = {
    "breads": ["bread", "bagel", "bagels", "bialy", "bialys"],
    "sandwiches": ["sandwich", "sandwiches"],
    "omelettes_breakfasts": [
        "omelette", "omelettes", "omelet", "omelets",
        "breakfast", "breakfasts", "breakfast items"
    ],
    "drinks": ["drink", "drinks", "beverage", "beverages", "coffee", "coffees", "tea", "teas"],
    "desserts_pastries": [
        "dessert", "desserts", "pastry", "pastries",
        "sweets", "sweet", "baked goods", "treats"
    ],
    "sides": ["side", "sides", "side dish", "side dishes"],
    "food_by_pound": [
        "by the pound", "by pound", "pound",
        "fish", "smoked fish", "lox",
        "cheese", "cheeses",
        "cold cuts", "deli meats", "meats",
        "spreads", "spread"
    ],
}


def upgrade() -> None:
    # Create the menu_display_group_aliases table
    op.create_table(
        "menu_display_group_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("menu_display_group_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["menu_display_group_id"],
            ["menu_display_groups.id"],
            ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_menu_display_group_aliases_id"),
        "menu_display_group_aliases",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_menu_display_group_aliases_menu_display_group_id"),
        "menu_display_group_aliases",
        ["menu_display_group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_menu_display_group_aliases_alias"),
        "menu_display_group_aliases",
        ["alias"],
        unique=True,
    )

    # Seed initial aliases
    conn = op.get_bind()
    for group_slug, aliases in DISPLAY_GROUP_ALIASES.items():
        # Get the group ID
        result = conn.execute(
            sa.text("SELECT id FROM menu_display_groups WHERE slug = :slug"),
            {"slug": group_slug}
        )
        row = result.fetchone()
        if not row:
            print(f"Warning: Display group '{group_slug}' not found, skipping aliases")
            continue

        group_id = row[0]

        for alias in aliases:
            try:
                conn.execute(
                    sa.text("""
                        INSERT INTO menu_display_group_aliases (menu_display_group_id, alias)
                        VALUES (:group_id, :alias)
                    """),
                    {"group_id": group_id, "alias": alias.lower()}
                )
                print(f"Added alias '{alias}' for group '{group_slug}'")
            except Exception as e:
                print(f"Warning: Could not add alias '{alias}': {e}")


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_display_group_aliases_alias"), table_name="menu_display_group_aliases")
    op.drop_index(op.f("ix_menu_display_group_aliases_menu_display_group_id"), table_name="menu_display_group_aliases")
    op.drop_index(op.f("ix_menu_display_group_aliases_id"), table_name="menu_display_group_aliases")
    op.drop_table("menu_display_group_aliases")
