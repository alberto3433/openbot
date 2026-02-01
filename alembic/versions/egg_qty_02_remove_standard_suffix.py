"""Remove "(standard)" suffix from attribute option display names

The "(standard)" suffix is confusing in the cart display. Instead of showing
"3 eggs (standard)", just show "3 Eggs".

Revision ID: egg_qty_02_standard
Revises: egg_qty_01_modifies
Create Date: 2026-02-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'egg_qty_02_standard'
down_revision = 'egg_qty_01_modifies'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Remove " (standard)" suffix from all display names
    conn.execute(
        sa.text("""
            UPDATE global_attribute_options
            SET display_name = REPLACE(display_name, ' (standard)', '')
            WHERE display_name LIKE '% (standard)'
        """)
    )


def downgrade() -> None:
    # Note: We can't fully restore the original values, but we can add
    # (standard) back to default options
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            UPDATE global_attribute_options
            SET display_name = display_name || ' (standard)'
            WHERE is_default = true
              AND (display_name LIKE '%eggs' OR display_name LIKE '%egg')
              AND display_name NOT LIKE '%(standard)'
        """)
    )
