"""Add child display groups under sandwiches.

Revision ID: display_grp_04
Revises: b7e2a1f4c893
Create Date: 2026-02-26

Creates child display groups under "sandwiches" so the user sees sub-group
names (Egg Sandwiches, Deli Sandwiches, ...) instead of 94 flat items.
Each child group inherits overall_category_id from the parent and gets
the item types previously on the parent group reassigned.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "display_grp_04"
down_revision = "b7e2a1f4c893"
branch_labels = None
depends_on = None

# Child groups to create under "sandwiches"
# Format: (slug, display_name, display_order, item_type_slug, aliases)
SANDWICH_CHILDREN = [
    (
        "egg_sandwiches", "Egg Sandwiches", 1, "egg_sandwich",
        ["egg sandwich", "egg sandwiches", "breakfast sandwich", "breakfast sandwiches"],
    ),
    (
        "deli_sandwiches", "Deli Sandwiches", 2, "deli_sandwich",
        ["deli sandwich", "deli sandwiches", "deli"],
    ),
    (
        "fish_sandwiches", "Fish Sandwiches", 3, "fish_sandwich",
        ["fish sandwich", "fish sandwiches"],
    ),
    (
        "spread_sandwiches", "Spread Sandwiches", 4, "spread_sandwich",
        ["spread sandwich", "spread sandwiches"],
    ),
    (
        "cheese_sandwiches", "Cheese Sandwiches", 5, "cheese_sandwich",
        ["cheese sandwich", "cheese sandwiches", "grilled cheese"],
    ),
    (
        "healthy_sandwiches", "Healthy Sandwiches", 6, "healthy_sandwich",
        ["healthy sandwich", "healthy sandwiches"],
    ),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Get the parent "sandwiches" group
    parent = conn.execute(
        sa.text("SELECT id, overall_category_id FROM menu_display_groups WHERE slug = 'sandwiches'")
    ).fetchone()
    if not parent:
        print("Warning: 'sandwiches' display group not found, skipping")
        return

    parent_id = parent[0]
    parent_category_id = parent[1]

    for slug, display_name, display_order, item_type_slug, aliases in SANDWICH_CHILDREN:
        # Create child display group
        conn.execute(
            sa.text("""
                INSERT INTO menu_display_groups
                    (slug, display_name, display_order, parent_id, overall_category_id)
                VALUES (:slug, :display_name, :display_order, :parent_id, :category_id)
            """),
            {
                "slug": slug,
                "display_name": display_name,
                "display_order": display_order,
                "parent_id": parent_id,
                "category_id": parent_category_id,
            },
        )
        print(f"Created child group: {slug} under sandwiches")

        # Get the new child group ID
        child = conn.execute(
            sa.text("SELECT id FROM menu_display_groups WHERE slug = :slug"),
            {"slug": slug},
        ).fetchone()
        if not child:
            print(f"Warning: Could not find newly created group '{slug}'")
            continue

        child_id = child[0]

        # Move the item type to point to the new child group
        conn.execute(
            sa.text("""
                UPDATE item_types
                SET menu_display_group_id = :child_id
                WHERE slug = :item_type_slug
            """),
            {"child_id": child_id, "item_type_slug": item_type_slug},
        )
        print(f"  Moved item type '{item_type_slug}' to '{slug}'")

        # Add aliases
        for alias in aliases:
            try:
                conn.execute(
                    sa.text("""
                        INSERT INTO menu_display_group_aliases (menu_display_group_id, alias)
                        VALUES (:group_id, :alias)
                    """),
                    {"group_id": child_id, "alias": alias.lower()},
                )
                print(f"  Added alias '{alias}'")
            except Exception as e:
                print(f"  Warning: Could not add alias '{alias}': {e}")


def downgrade() -> None:
    conn = op.get_bind()

    # Get parent sandwiches group ID
    parent = conn.execute(
        sa.text("SELECT id FROM menu_display_groups WHERE slug = 'sandwiches'")
    ).fetchone()
    if not parent:
        return

    parent_id = parent[0]

    for slug, _, _, item_type_slug, _ in SANDWICH_CHILDREN:
        # Move item type back to parent group
        conn.execute(
            sa.text("""
                UPDATE item_types
                SET menu_display_group_id = :parent_id
                WHERE slug = :item_type_slug
            """),
            {"parent_id": parent_id, "item_type_slug": item_type_slug},
        )

        # Delete aliases for this child group
        conn.execute(
            sa.text("""
                DELETE FROM menu_display_group_aliases
                WHERE menu_display_group_id = (
                    SELECT id FROM menu_display_groups WHERE slug = :slug
                )
            """),
            {"slug": slug},
        )

        # Delete the child group
        conn.execute(
            sa.text("DELETE FROM menu_display_groups WHERE slug = :slug"),
            {"slug": slug},
        )
        print(f"Removed child group: {slug}")
