"""Add cream cheese alias for plain_cream_cheese

Revision ID: cream_cheese_01
Revises:
Create Date: 2026-02-04

When user says "cream cheese" without a qualifier, they typically mean plain cream cheese.
This alias enables automatic matching of "cream cheese" to the plain_cream_cheese spread.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "cream_cheese_01"
down_revision = None
branch_labels = ("cream_cheese",)
depends_on = None


def upgrade() -> None:
    # Add "cream cheese" alias for plain_cream_cheese
    op.execute("""
        INSERT INTO ingredient_aliases (ingredient_id, alias)
        SELECT id, 'cream cheese'
        FROM ingredients
        WHERE slug = 'plain_cream_cheese'
        AND NOT EXISTS (
            SELECT 1 FROM ingredient_aliases ia
            JOIN ingredients i ON ia.ingredient_id = i.id
            WHERE i.slug = 'plain_cream_cheese' AND ia.alias = 'cream cheese'
        )
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM ingredient_aliases
        WHERE alias = 'cream cheese'
        AND ingredient_id = (SELECT id FROM ingredients WHERE slug = 'plain_cream_cheese')
    """)
