"""Add forward delegation schema extensions

Adds two new columns to support data-driven forward delegation:
1. global_attributes.options_source_category - specifies which ingredient category
   provides options for package_multi_select input types
2. global_attribute_options.forward_to_attribute_id - enables auto-selecting an option
   and forwarding to a target attribute when user input matches target options

Also populates data for existing package attributes:
- package_contents.options_source_category = 'bread'
- package_variety.custom option forwards to package_contents

Revision ID: forward_delegation_01
Revises: bagel_package_01
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "forward_delegation_01"
down_revision = "bagel_package_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add options_source_category column to global_attributes
    op.add_column(
        'global_attributes',
        sa.Column('options_source_category', sa.String(50), nullable=True)
    )

    # 2. Add forward_to_attribute_id column to global_attribute_options
    op.add_column(
        'global_attribute_options',
        sa.Column(
            'forward_to_attribute_id',
            sa.Integer(),
            sa.ForeignKey('global_attributes.id', ondelete='SET NULL'),
            nullable=True,
        )
    )

    # 3. Create index on forward_to_attribute_id for efficient lookups
    op.create_index(
        'ix_global_attribute_options_forward_to_attribute_id',
        'global_attribute_options',
        ['forward_to_attribute_id']
    )

    # 4. Populate data for existing package attributes

    # Set options_source_category = 'bread' for package_contents attribute
    op.execute("""
        UPDATE global_attributes
        SET options_source_category = 'bread'
        WHERE slug = 'package_contents'
    """)

    # Set forward_to_attribute_id for the "custom" option in package_variety
    # This option should forward to package_contents when user provides bagel types directly
    op.execute("""
        UPDATE global_attribute_options
        SET forward_to_attribute_id = (
            SELECT id FROM global_attributes WHERE slug = 'package_contents'
        )
        WHERE global_attribute_id = (
            SELECT id FROM global_attributes WHERE slug = 'package_variety'
        )
        AND slug = 'custom'
    """)


def downgrade() -> None:
    # Clear data first
    op.execute("""
        UPDATE global_attribute_options
        SET forward_to_attribute_id = NULL
        WHERE forward_to_attribute_id IS NOT NULL
    """)

    op.execute("""
        UPDATE global_attributes
        SET options_source_category = NULL
        WHERE options_source_category IS NOT NULL
    """)

    # Drop index
    op.drop_index(
        'ix_global_attribute_options_forward_to_attribute_id',
        table_name='global_attribute_options'
    )

    # Drop columns
    op.drop_column('global_attribute_options', 'forward_to_attribute_id')
    op.drop_column('global_attributes', 'options_source_category')
