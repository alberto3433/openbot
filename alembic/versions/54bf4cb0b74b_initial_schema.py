"""initial schema

Revision ID: 54bf4cb0b74b
Revises:
Create Date: 2025-12-11 21:15:37.225368

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54bf4cb0b74b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if tables already exist (for existing databases)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create tables if they don't exist (fresh database)
    if 'recipes' not in existing_tables:
        op.create_table('recipes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_recipes_id'), 'recipes', ['id'], unique=False)

    if 'ingredients' not in existing_tables:
        op.create_table('ingredients',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('category', sa.String(), nullable=False),
            sa.Column('unit', sa.String(), nullable=False),
            sa.Column('track_inventory', sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name')
        )
        op.create_index(op.f('ix_ingredients_id'), 'ingredients', ['id'], unique=False)

    if 'menu_items' not in existing_tables:
        op.create_table('menu_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('category', sa.String(), nullable=False),
            sa.Column('is_signature', sa.Boolean(), nullable=False),
            sa.Column('base_price', sa.Float(), nullable=False),
            sa.Column('available_qty', sa.Integer(), nullable=False),
            sa.Column('extra_metadata', sa.Text(), nullable=True),
            sa.Column('recipe_id', sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_menu_items_id'), 'menu_items', ['id'], unique=False)

    if 'orders' not in existing_tables:
        op.create_table('orders',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('customer_name', sa.String(), nullable=True),
            sa.Column('phone', sa.String(), nullable=True),
            sa.Column('pickup_time', sa.String(), nullable=True),
            sa.Column('total_price', sa.Float(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_orders_id'), 'orders', ['id'], unique=False)

    if 'recipe_choice_groups' not in existing_tables:
        op.create_table('recipe_choice_groups',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('recipe_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('min_choices', sa.Integer(), nullable=False),
            sa.Column('max_choices', sa.Integer(), nullable=False),
            sa.Column('is_required', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_recipe_choice_groups_id'), 'recipe_choice_groups', ['id'], unique=False)

    if 'recipe_ingredients' not in existing_tables:
        op.create_table('recipe_ingredients',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('recipe_id', sa.Integer(), nullable=False),
            sa.Column('ingredient_id', sa.Integer(), nullable=False),
            sa.Column('quantity', sa.Float(), nullable=False),
            sa.Column('unit_override', sa.String(), nullable=True),
            sa.Column('is_required', sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ),
            sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_recipe_ingredients_id'), 'recipe_ingredients', ['id'], unique=False)

    if 'order_items' not in existing_tables:
        op.create_table('order_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('order_id', sa.Integer(), nullable=False),
            sa.Column('menu_item_id', sa.Integer(), nullable=True),
            sa.Column('menu_item_name', sa.String(), nullable=False),
            sa.Column('item_type', sa.String(), nullable=True),
            sa.Column('size', sa.String(), nullable=True),
            sa.Column('bread', sa.String(), nullable=True),
            sa.Column('protein', sa.String(), nullable=True),
            sa.Column('cheese', sa.String(), nullable=True),
            sa.Column('toppings', sa.JSON(), nullable=True),
            sa.Column('sauces', sa.JSON(), nullable=True),
            sa.Column('toasted', sa.Boolean(), nullable=True),
            sa.Column('quantity', sa.Integer(), nullable=False),
            sa.Column('unit_price', sa.Float(), nullable=False),
            sa.Column('line_total', sa.Float(), nullable=False),
            sa.Column('extra', sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ),
            sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_order_items_id'), 'order_items', ['id'], unique=False)

    if 'recipe_choice_items' not in existing_tables:
        op.create_table('recipe_choice_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('choice_group_id', sa.Integer(), nullable=False),
            sa.Column('ingredient_id', sa.Integer(), nullable=False),
            sa.Column('is_default', sa.Boolean(), nullable=False),
            sa.Column('extra_price', sa.Float(), nullable=False),
            sa.ForeignKeyConstraint(['choice_group_id'], ['recipe_choice_groups.id'], ),
            sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_recipe_choice_items_id'), 'recipe_choice_items', ['id'], unique=False)

    if 'chat_sessions' not in existing_tables:
        op.create_table('chat_sessions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.String(), nullable=False),
            sa.Column('history', sa.JSON(), nullable=False),
            sa.Column('order_state', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_chat_sessions_id'), 'chat_sessions', ['id'], unique=False)
        op.create_index(op.f('ix_chat_sessions_session_id'), 'chat_sessions', ['session_id'], unique=True)

    # Add indexes (these may not exist in older databases)
    # Use try/except to handle cases where indexes already exist
    existing_indexes = {}
    for table in existing_tables:
        existing_indexes[table] = [idx['name'] for idx in inspector.get_indexes(table)]

    if 'menu_items' in existing_tables:
        if 'ix_menu_items_category' not in existing_indexes.get('menu_items', []):
            op.create_index(op.f('ix_menu_items_category'), 'menu_items', ['category'], unique=False)

    if 'order_items' in existing_tables:
        if 'ix_order_items_order_id' not in existing_indexes.get('order_items', []):
            op.create_index(op.f('ix_order_items_order_id'), 'order_items', ['order_id'], unique=False)

    if 'orders' in existing_tables:
        if 'ix_orders_created_at' not in existing_indexes.get('orders', []):
            op.create_index(op.f('ix_orders_created_at'), 'orders', ['created_at'], unique=False)
        if 'ix_orders_status' not in existing_indexes.get('orders', []):
            op.create_index(op.f('ix_orders_status'), 'orders', ['status'], unique=False)
        if 'ix_orders_status_created_at' not in existing_indexes.get('orders', []):
            op.create_index('ix_orders_status_created_at', 'orders', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes first
    op.drop_index('ix_orders_status_created_at', table_name='orders')
    op.drop_index(op.f('ix_orders_status'), table_name='orders')
    op.drop_index(op.f('ix_orders_created_at'), table_name='orders')
    op.drop_index(op.f('ix_order_items_order_id'), table_name='order_items')
    op.drop_index(op.f('ix_menu_items_category'), table_name='menu_items')

    # Drop tables in reverse order of creation (respecting foreign keys)
    op.drop_index(op.f('ix_chat_sessions_session_id'), table_name='chat_sessions')
    op.drop_index(op.f('ix_chat_sessions_id'), table_name='chat_sessions')
    op.drop_table('chat_sessions')

    op.drop_index(op.f('ix_recipe_choice_items_id'), table_name='recipe_choice_items')
    op.drop_table('recipe_choice_items')

    op.drop_index(op.f('ix_order_items_id'), table_name='order_items')
    op.drop_table('order_items')

    op.drop_index(op.f('ix_recipe_ingredients_id'), table_name='recipe_ingredients')
    op.drop_table('recipe_ingredients')

    op.drop_index(op.f('ix_recipe_choice_groups_id'), table_name='recipe_choice_groups')
    op.drop_table('recipe_choice_groups')

    op.drop_index(op.f('ix_orders_id'), table_name='orders')
    op.drop_table('orders')

    op.drop_index(op.f('ix_menu_items_id'), table_name='menu_items')
    op.drop_table('menu_items')

    op.drop_index(op.f('ix_ingredients_id'), table_name='ingredients')
    op.drop_table('ingredients')

    op.drop_index(op.f('ix_recipes_id'), table_name='recipes')
    op.drop_table('recipes')
