"""add_modifier_qualifiers_table

Revision ID: a2b3c4d5e6f7
Revises: 1648e574384f
Create Date: 2026-01-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'q1r2s3t4u5v7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create modifier_qualifiers table and seed with default qualifiers."""
    # Check if table exists (may have been auto-created by SQLAlchemy create_all)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'modifier_qualifiers' not in tables:
        # Create the table
        op.create_table(
            'modifier_qualifiers',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('pattern', sa.String(length=100), nullable=False),
            sa.Column('normalized_form', sa.String(length=50), nullable=False),
            sa.Column('category', sa.String(length=50), nullable=False, server_default='amount'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_modifier_qualifiers_id'), 'modifier_qualifiers', ['id'], unique=False)
        op.create_index(op.f('ix_modifier_qualifiers_pattern'), 'modifier_qualifiers', ['pattern'], unique=True)

    # Seed with default qualifier patterns
    # Categories:
    #   - amount: quantity modifiers (can conflict with each other)
    #   - position: location modifiers (on the side, on top)
    #   - preparation: how to prepare (crispy, well done)

    default_qualifiers = [
        # Amount - More/Extra
        ('extra', 'extra', 'amount'),
        ('more', 'extra', 'amount'),
        ('lots of', 'extra', 'amount'),
        ('heavy', 'extra', 'amount'),
        ('heavy on the', 'extra', 'amount'),

        # Amount - Double/Triple
        ('double', 'double', 'amount'),
        ('triple', 'triple', 'amount'),

        # Amount - Light/Less
        ('light', 'light', 'amount'),
        ('lite', 'light', 'amount'),
        ('easy', 'light', 'amount'),
        ('easy on the', 'light', 'amount'),
        ('go light on the', 'light', 'amount'),
        ('go easy on the', 'light', 'amount'),
        ('a little', 'light', 'amount'),
        ('a little bit of', 'light', 'amount'),
        ('just a little', 'light', 'amount'),
        ('just a touch of', 'light', 'amount'),
        ('a touch of', 'light', 'amount'),

        # Amount - Splash/Drizzle (for liquids)
        ('a splash of', 'splash', 'amount'),
        ('splash of', 'splash', 'amount'),
        ('a drizzle of', 'drizzle', 'amount'),
        ('drizzle of', 'drizzle', 'amount'),

        # Position
        ('on the side', 'on the side', 'position'),
        ('on side', 'on the side', 'position'),

        # Preparation
        ('crispy', 'crispy', 'preparation'),
        ('well done', 'well done', 'preparation'),
        ('well-done', 'well done', 'preparation'),
        ('soft', 'soft', 'preparation'),
        ('runny', 'runny', 'preparation'),
    ]

    # Insert default qualifiers (only if table is empty)
    modifier_qualifiers = sa.table(
        'modifier_qualifiers',
        sa.column('pattern', sa.String),
        sa.column('normalized_form', sa.String),
        sa.column('category', sa.String),
        sa.column('is_active', sa.Boolean),
    )

    # Check if table already has data
    result = conn.execute(sa.text("SELECT COUNT(*) FROM modifier_qualifiers"))
    count = result.scalar()

    if count == 0:
        op.bulk_insert(
            modifier_qualifiers,
            [
                {
                    'pattern': pattern,
                    'normalized_form': normalized,
                    'category': category,
                    'is_active': True,
                }
                for pattern, normalized, category in default_qualifiers
            ]
        )


def downgrade() -> None:
    """Drop modifier_qualifiers table."""
    op.drop_index(op.f('ix_modifier_qualifiers_pattern'), table_name='modifier_qualifiers')
    op.drop_index(op.f('ix_modifier_qualifiers_id'), table_name='modifier_qualifiers')
    op.drop_table('modifier_qualifiers')
