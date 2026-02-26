"""add_milk_alias_for_whole_milk

Revision ID: a3ba59fb3da9
Revises: z8d9e0f1g2h3
Create Date: 2026-02-25 11:44:14.224250

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3ba59fb3da9'
down_revision = 'z8d9e0f1g2h3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 'milk' as an alias for the whole_milk ingredient."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE slug = 'whole_milk'")
    ).fetchone()
    if result:
        ingredient_id = result[0]
        conn.execute(
            sa.text(
                "INSERT INTO ingredient_aliases (ingredient_id, alias) "
                "VALUES (:ingredient_id, 'milk')"
            ),
            {"ingredient_id": ingredient_id},
        )


def downgrade() -> None:
    """Remove the 'milk' alias for whole_milk."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE slug = 'whole_milk'")
    ).fetchone()
    if result:
        ingredient_id = result[0]
        conn.execute(
            sa.text(
                "DELETE FROM ingredient_aliases "
                "WHERE ingredient_id = :ingredient_id AND alias = 'milk'"
            ),
            {"ingredient_id": ingredient_id},
        )
