"""Reorder egg_quantity attribute to appear after egg_style

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-01-07

Moves egg_quantity to display right after egg_style/egg_preparation
instead of being at the end of the attribute list.
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'y2z3a4b5c6d7'
down_revision = 'x1y2z3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Move egg_quantity to appear right after egg_style."""
    conn = op.get_bind()

    # For egg_sandwich: egg_style is at 4, move egg_quantity to 5 and shift others
    egg_sandwich_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'")
    ).fetchone()

    if egg_sandwich_type:
        item_type_id = egg_sandwich_type[0]

        # Shift attributes with display_order >= 5 up by 1 (except egg_quantity)
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = display_order + 1
                WHERE item_type_id = :item_type_id
                AND display_order >= 5
                AND slug != 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        )

        # Set egg_quantity to display_order 5 (right after egg_style at 4)
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = 5
                WHERE item_type_id = :item_type_id
                AND slug = 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        )
        print("Reordered egg_quantity for egg_sandwich to display_order=5")

    # For omelette: egg_style is at 3, move egg_quantity to 4 and shift others
    omelette_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    if omelette_type:
        item_type_id = omelette_type[0]

        # Shift attributes with display_order >= 4 up by 1 (except egg_quantity)
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = display_order + 1
                WHERE item_type_id = :item_type_id
                AND display_order >= 4
                AND slug != 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        )

        # Set egg_quantity to display_order 4 (right after egg_style at 3)
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = 4
                WHERE item_type_id = :item_type_id
                AND slug = 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        )
        print("Reordered egg_quantity for omelette to display_order=4")


def downgrade() -> None:
    """Move egg_quantity back to the end."""
    conn = op.get_bind()

    # For egg_sandwich: move egg_quantity back to end
    egg_sandwich_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'")
    ).fetchone()

    if egg_sandwich_type:
        item_type_id = egg_sandwich_type[0]

        # Get max display_order
        max_order = conn.execute(
            text("""
                SELECT MAX(display_order) FROM item_type_attributes
                WHERE item_type_id = :item_type_id
            """),
            {"item_type_id": item_type_id}
        ).scalar() or 0

        # Move egg_quantity to end
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = :max_order
                WHERE item_type_id = :item_type_id
                AND slug = 'egg_quantity'
            """),
            {"item_type_id": item_type_id, "max_order": max_order}
        )

        # Shift attributes back down
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = display_order - 1
                WHERE item_type_id = :item_type_id
                AND display_order > 5
                AND slug != 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        )

    # For omelette: move egg_quantity back to end
    omelette_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    if omelette_type:
        item_type_id = omelette_type[0]

        # Get max display_order
        max_order = conn.execute(
            text("""
                SELECT MAX(display_order) FROM item_type_attributes
                WHERE item_type_id = :item_type_id
            """),
            {"item_type_id": item_type_id}
        ).scalar() or 0

        # Move egg_quantity to end
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = :max_order
                WHERE item_type_id = :item_type_id
                AND slug = 'egg_quantity'
            """),
            {"item_type_id": item_type_id, "max_order": max_order}
        )

        # Shift attributes back down
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET display_order = display_order - 1
                WHERE item_type_id = :item_type_id
                AND display_order > 4
                AND slug != 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        )
