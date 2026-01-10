"""Add aliases column to global_attribute_options and populate shot aliases.

Revision ID: t1u2v3w4x5y6
Revises: s7t8u9v0w1x2
Create Date: 2026-01-09

This migration:
1. Adds 'aliases' column to global_attribute_options table
2. Populates aliases for shot options (single, double, triple, quad)
   to enable parsing "2", "two", "double shot" etc. to the correct option

The aliases column uses pipe-separated values, e.g., "2|two|double shot|2 shots"
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 't1u2v3w4x5y6'
down_revision = 's7t8u9v0w1x2'
branch_labels = None
depends_on = None


# Shot option aliases for espresso
# Format: (slug, aliases)
SHOT_ALIASES = [
    ('single', '1|one|single shot|1 shot'),
    ('double', '2|two|double shot|2 shots'),
    ('triple', '3|three|triple shot|3 shots'),
    ('quad', '4|four|quad shot|4 shots|quadruple'),
]


def upgrade() -> None:
    # Step 1: Add aliases column to global_attribute_options
    op.add_column(
        'global_attribute_options',
        sa.Column('aliases', sa.String(255), nullable=True)
    )

    # Step 2: Populate shot option aliases
    conn = op.get_bind()

    # Get the 'shots' global attribute id
    result = conn.execute(
        sa.text("SELECT id FROM global_attributes WHERE slug = 'shots'")
    )
    row = result.fetchone()
    if not row:
        print("Warning: 'shots' global attribute not found, skipping alias population")
        return

    shots_attr_id = row[0]
    print(f"Found 'shots' global attribute id: {shots_attr_id}")

    # Update each shot option with its aliases
    for slug, aliases in SHOT_ALIASES:
        result = conn.execute(
            sa.text("""
                UPDATE global_attribute_options
                SET aliases = :aliases
                WHERE global_attribute_id = :attr_id AND slug = :slug
            """),
            {"aliases": aliases, "attr_id": shots_attr_id, "slug": slug}
        )
        if result.rowcount > 0:
            print(f"  Set aliases for {slug}: {aliases}")
        else:
            print(f"  Warning: option '{slug}' not found for shots attribute")


def downgrade() -> None:
    # Remove aliases column
    op.drop_column('global_attribute_options', 'aliases')
