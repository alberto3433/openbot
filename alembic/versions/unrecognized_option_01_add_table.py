"""Add unrecognized_option_suggestions table with seed data.

Revision ID: unrecognized_option_01
Revises: fish_by_pound_01
Create Date: 2026-02-05

This table stores common attribute option terms that aren't in our menu,
similar to how unrecognized_item_suggestions handles menu items.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "unrecognized_option_01"
down_revision = "fish_by_pound_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the table
    op.create_table(
        "unrecognized_option_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("input_pattern", sa.String(100), nullable=False, index=True),
        sa.Column("attribute_slug", sa.String(50), nullable=False, index=True),
        sa.Column("suggested_display_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_unrecognized_option_suggestions_id"),
        "unrecognized_option_suggestions",
        ["id"],
    )

    # Seed data: common size terms we don't offer
    op.execute("""
        INSERT INTO unrecognized_option_suggestions (input_pattern, attribute_slug, suggested_display_name, is_active)
        VALUES
        -- Starbucks sizes
        ('venti', 'size', 'Venti', true),
        ('grande', 'size', 'Grande', true),
        ('tall', 'size', 'Tall', true),
        ('trenta', 'size', 'Trenta', true),
        -- Generic sizes we don't have
        ('medium', 'size', 'Medium', true),
        ('med', 'size', 'Medium', true),
        ('regular', 'size', 'Regular', true),
        ('reg', 'size', 'Regular', true),
        ('extra large', 'size', 'Extra Large', true),
        ('xl', 'size', 'Extra Large', true),
        ('extra small', 'size', 'Extra Small', true),
        ('xs', 'size', 'Extra Small', true),
        ('super', 'size', 'Super', true),
        ('jumbo', 'size', 'Jumbo', true),
        ('king', 'size', 'King Size', true),
        ('king size', 'size', 'King Size', true)
    """)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_unrecognized_option_suggestions_id"),
        table_name="unrecognized_option_suggestions",
    )
    op.drop_table("unrecognized_option_suggestions")
