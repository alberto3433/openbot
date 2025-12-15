"""Add generic item type system

Revision ID: l5e6f7g8h9i0
Revises: d19f94b7638e
Create Date: 2025-12-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l5e6f7g8h9i0'
down_revision: Union[str, Sequence[str], None] = 'd19f94b7638e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create item_types table
    op.create_table('item_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('is_configurable', sa.Boolean(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_item_types_id'), 'item_types', ['id'], unique=False)
    op.create_index(op.f('ix_item_types_slug'), 'item_types', ['slug'], unique=True)

    # Create attribute_definitions table
    op.create_table('attribute_definitions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_type_id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('input_type', sa.String(), nullable=False, server_default='single_select'),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('allow_none', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('min_selections', sa.Integer(), nullable=True),
        sa.Column('max_selections', sa.Integer(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['item_type_id'], ['item_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_type_id', 'slug', name='uix_item_type_attr_slug')
    )
    op.create_index(op.f('ix_attribute_definitions_id'), 'attribute_definitions', ['id'], unique=False)
    op.create_index(op.f('ix_attribute_definitions_item_type_id'), 'attribute_definitions', ['item_type_id'], unique=False)

    # Create attribute_options table
    op.create_table('attribute_options',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attribute_definition_id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('price_modifier', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['attribute_definition_id'], ['attribute_definitions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attribute_definition_id', 'slug', name='uix_attr_def_option_slug')
    )
    op.create_index(op.f('ix_attribute_options_id'), 'attribute_options', ['id'], unique=False)
    op.create_index(op.f('ix_attribute_options_attribute_definition_id'), 'attribute_options', ['attribute_definition_id'], unique=False)

    # Create attribute_option_ingredients table
    op.create_table('attribute_option_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attribute_option_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False, server_default='1.0'),
        sa.ForeignKeyConstraint(['attribute_option_id'], ['attribute_options.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attribute_option_id', 'ingredient_id', name='uix_attr_option_ingredient')
    )
    op.create_index(op.f('ix_attribute_option_ingredients_id'), 'attribute_option_ingredients', ['id'], unique=False)
    op.create_index(op.f('ix_attribute_option_ingredients_attribute_option_id'), 'attribute_option_ingredients', ['attribute_option_id'], unique=False)
    op.create_index(op.f('ix_attribute_option_ingredients_ingredient_id'), 'attribute_option_ingredients', ['ingredient_id'], unique=False)

    # Add columns to menu_items table
    op.add_column('menu_items', sa.Column('item_type_id', sa.Integer(), nullable=True))
    op.add_column('menu_items', sa.Column('default_config', sa.JSON(), nullable=True))
    op.create_foreign_key('fk_menu_items_item_type', 'menu_items', 'item_types', ['item_type_id'], ['id'])
    op.create_index(op.f('ix_menu_items_item_type_id'), 'menu_items', ['item_type_id'], unique=False)

    # Add columns to order_items table
    op.add_column('order_items', sa.Column('item_type_id', sa.Integer(), nullable=True))
    op.add_column('order_items', sa.Column('item_config', sa.JSON(), nullable=True))
    op.create_foreign_key('fk_order_items_item_type', 'order_items', 'item_types', ['item_type_id'], ['id'])
    op.create_index(op.f('ix_order_items_item_type_id'), 'order_items', ['item_type_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove columns from order_items
    op.drop_index(op.f('ix_order_items_item_type_id'), table_name='order_items')
    op.drop_constraint('fk_order_items_item_type', 'order_items', type_='foreignkey')
    op.drop_column('order_items', 'item_config')
    op.drop_column('order_items', 'item_type_id')

    # Remove columns from menu_items
    op.drop_index(op.f('ix_menu_items_item_type_id'), table_name='menu_items')
    op.drop_constraint('fk_menu_items_item_type', 'menu_items', type_='foreignkey')
    op.drop_column('menu_items', 'default_config')
    op.drop_column('menu_items', 'item_type_id')

    # Drop attribute_option_ingredients table
    op.drop_index(op.f('ix_attribute_option_ingredients_ingredient_id'), table_name='attribute_option_ingredients')
    op.drop_index(op.f('ix_attribute_option_ingredients_attribute_option_id'), table_name='attribute_option_ingredients')
    op.drop_index(op.f('ix_attribute_option_ingredients_id'), table_name='attribute_option_ingredients')
    op.drop_table('attribute_option_ingredients')

    # Drop attribute_options table
    op.drop_index(op.f('ix_attribute_options_attribute_definition_id'), table_name='attribute_options')
    op.drop_index(op.f('ix_attribute_options_id'), table_name='attribute_options')
    op.drop_table('attribute_options')

    # Drop attribute_definitions table
    op.drop_index(op.f('ix_attribute_definitions_item_type_id'), table_name='attribute_definitions')
    op.drop_index(op.f('ix_attribute_definitions_id'), table_name='attribute_definitions')
    op.drop_table('attribute_definitions')

    # Drop item_types table
    op.drop_index(op.f('ix_item_types_slug'), table_name='item_types')
    op.drop_index(op.f('ix_item_types_id'), table_name='item_types')
    op.drop_table('item_types')
