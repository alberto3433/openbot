"""Drop legacy item_type_attributes table

Revision ID: fix_syrup_price_02
Revises: fix_syrup_price_01
Create Date: 2026-01-20

This migration drops the legacy item_type_attributes table entirely.

Background:
-----------
The item_type_attributes table was replaced by the ItemTypeGlobalAttribute +
GlobalAttribute system. However, the table was kept around and continued to
cause issues:

1. Migration fix_syrup_price_01 removed duplicate 'milk_sweetener_syrup' entries
   that were shadowing the GlobalAttribute options and causing $0 pricing.

2. The table could still be populated (manually or by old code), creating
   the same shadowing bug for other attributes.

3. The table's ingredient_group column used values like 'milk_sweetener_syrup'
   that don't match ItemTypeIngredient.ingredient_group values ('milk',
   'sweetener', 'syrup'), causing silent lookup failures.

Solution:
---------
Drop the entire table to prevent any future issues. All attribute configuration
now comes exclusively from GlobalAttribute + ItemTypeGlobalAttribute.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'fix_syrup_price_02'
down_revision = 'consolidate_global_attrs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Log what we're about to drop
    result = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_name = 'item_type_attributes'
    """))
    table_exists = result.scalar() > 0

    if table_exists:
        # Check for any remaining records
        result = conn.execute(text("SELECT COUNT(*) FROM item_type_attributes"))
        record_count = result.scalar()
        print(f"Dropping item_type_attributes table ({record_count} records)")

        op.drop_table('item_type_attributes')
        print("Successfully dropped item_type_attributes table")
    else:
        print("item_type_attributes table does not exist, skipping")


def downgrade() -> None:
    # Recreate the table structure (but not the data)
    # This is provided for rollback purposes only - the table should not be used
    op.create_table(
        'item_type_attributes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slug', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('input_type', sa.String(20), nullable=False, server_default='single_select'),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('allow_none', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('ask_in_conversation', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('question_text', sa.Text(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('loads_from_ingredients', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('ingredient_group', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_item_type_attr_item_type', 'item_type_attributes', ['item_type_id'])
    op.create_unique_constraint('uq_item_type_attr_slug', 'item_type_attributes', ['item_type_id', 'slug'])
    print("Recreated item_type_attributes table (WARNING: this legacy table should not be used)")
