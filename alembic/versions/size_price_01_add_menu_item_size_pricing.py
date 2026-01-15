"""Add menu item size pricing tables

Revision ID: size_price_01
Revises: drop_mi_attrs01
Create Date: 2026-01-14

This migration implements variant-based pricing for menu items:
1. Creates menu_item_size_category table (size, weight, quantity)
2. Creates menu_item_size table (small, large, each, 1/4 lb, etc.)
3. Creates menu_item_size_price table (explicit prices per size per item)
4. Adds size_category_id FK to menu_items table

The new pricing model:
- Each menu item has a size_category (e.g., "size" for drinks, "weight" for deli)
- Each menu item has 1+ size_price entries with explicit prices
- If only 1 size exists, no disambiguation needed
- If 2+ sizes exist, user is asked to choose

This replaces the base_price + upcharge model for items with size variants.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'size_price_01'
down_revision = 'drop_mi_attrs01'
branch_labels = None
depends_on = None


# Default size categories with their question text
DEFAULT_SIZE_CATEGORIES = [
    ('size', 'Size', 'What size?'),
    ('weight', 'Weight', 'How much would you like?'),
    ('quantity', 'Quantity', 'How many?'),
]

# Default sizes per category
# Format: (category_slug, size_name, display_order)
DEFAULT_SIZES = [
    # Size category
    ('size', 'small', 1),
    ('size', 'large', 2),
    # Weight category
    ('weight', '1/4 lb', 1),
    ('weight', '1/2 lb', 2),
    ('weight', '1 lb', 3),
    # Quantity category
    ('quantity', 'each', 1),
]


def _table_exists(conn, table_name: str) -> bool:
    """Check if a table exists in the database."""
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :table_name)"
    ), {'table_name': table_name})
    return result.fetchone()[0]


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = :table_name AND column_name = :column_name)"
    ), {'table_name': table_name, 'column_name': column_name})
    return result.fetchone()[0]


def _index_exists(conn, index_name: str) -> bool:
    """Check if an index exists."""
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :index_name)"
    ), {'index_name': index_name})
    return result.fetchone()[0]


def upgrade() -> None:
    # Get the company_id (single-row table)
    conn = op.get_bind()
    result = conn.execute(text("SELECT id FROM company LIMIT 1"))
    row = result.fetchone()
    company_id = row[0] if row else None

    if not company_id:
        # Create a default company if none exists
        conn.execute(text(
            "INSERT INTO company (name, bot_persona_name) VALUES ('Default Company', 'Bot') RETURNING id"
        ))
        result = conn.execute(text("SELECT id FROM company LIMIT 1"))
        row = result.fetchone()
        company_id = row[0]

    # 1. Create menu_item_size_category table (if not exists)
    if not _table_exists(conn, 'menu_item_size_categories'):
        op.create_table(
            'menu_item_size_categories',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(50), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('question_text', sa.String(200), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['company_id'], ['company.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('company_id', 'slug', name='uix_size_category_company_slug'),
        )
    if not _index_exists(conn, 'ix_menu_item_size_categories_company_id'):
        op.create_index('ix_menu_item_size_categories_company_id', 'menu_item_size_categories', ['company_id'])

    # 2. Create menu_item_size table (if not exists)
    if not _table_exists(conn, 'menu_item_sizes'):
        op.create_table(
            'menu_item_sizes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('category_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('display_order', sa.Integer(), nullable=False, default=0),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['company_id'], ['company.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['category_id'], ['menu_item_size_categories.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('category_id', 'name', name='uix_size_category_name'),
        )
    if not _index_exists(conn, 'ix_menu_item_sizes_company_id'):
        op.create_index('ix_menu_item_sizes_company_id', 'menu_item_sizes', ['company_id'])
    if not _index_exists(conn, 'ix_menu_item_sizes_category_id'):
        op.create_index('ix_menu_item_sizes_category_id', 'menu_item_sizes', ['category_id'])

    # 3. Create menu_item_size_price table (if not exists)
    if not _table_exists(conn, 'menu_item_size_prices'):
        op.create_table(
            'menu_item_size_prices',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('menu_item_id', sa.Integer(), nullable=False),
            sa.Column('size_id', sa.Integer(), nullable=False),
            sa.Column('price', sa.Float(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['size_id'], ['menu_item_sizes.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('menu_item_id', 'size_id', name='uix_menu_item_size_price'),
        )
    if not _index_exists(conn, 'ix_menu_item_size_prices_menu_item_id'):
        op.create_index('ix_menu_item_size_prices_menu_item_id', 'menu_item_size_prices', ['menu_item_id'])
    if not _index_exists(conn, 'ix_menu_item_size_prices_size_id'):
        op.create_index('ix_menu_item_size_prices_size_id', 'menu_item_size_prices', ['size_id'])

    # 4. Add size_category_id to menu_items table (if not exists)
    if not _column_exists(conn, 'menu_items', 'size_category_id'):
        op.add_column(
            'menu_items',
            sa.Column('size_category_id', sa.Integer(), nullable=True)
        )
        op.create_foreign_key(
            'fk_menu_items_size_category',
            'menu_items',
            'menu_item_size_categories',
            ['size_category_id'],
            ['id'],
            ondelete='SET NULL'
        )
        op.create_index('ix_menu_items_size_category_id', 'menu_items', ['size_category_id'])

    # 5. Seed default size categories (skip if already exists)
    for slug, name, question_text in DEFAULT_SIZE_CATEGORIES:
        conn.execute(text(
            """
            INSERT INTO menu_item_size_categories (company_id, slug, name, question_text)
            VALUES (:company_id, :slug, :name, :question_text)
            ON CONFLICT (company_id, slug) DO NOTHING
            """
        ), {'company_id': company_id, 'slug': slug, 'name': name, 'question_text': question_text})

    # 6. Seed default sizes (skip if already exists)
    for category_slug, size_name, display_order in DEFAULT_SIZES:
        conn.execute(text(
            """
            INSERT INTO menu_item_sizes (company_id, category_id, name, display_order)
            SELECT :company_id, c.id, :size_name, :display_order
            FROM menu_item_size_categories c
            WHERE c.slug = :category_slug AND c.company_id = :company_id
            ON CONFLICT (category_id, name) DO NOTHING
            """
        ), {
            'company_id': company_id,
            'category_slug': category_slug,
            'size_name': size_name,
            'display_order': display_order
        })


def downgrade() -> None:
    # Remove FK and column from menu_items
    op.drop_index('ix_menu_items_size_category_id', table_name='menu_items')
    op.drop_constraint('fk_menu_items_size_category', 'menu_items', type_='foreignkey')
    op.drop_column('menu_items', 'size_category_id')

    # Drop tables in reverse order
    op.drop_index('ix_menu_item_size_prices_size_id', table_name='menu_item_size_prices')
    op.drop_index('ix_menu_item_size_prices_menu_item_id', table_name='menu_item_size_prices')
    op.drop_table('menu_item_size_prices')

    op.drop_index('ix_menu_item_sizes_category_id', table_name='menu_item_sizes')
    op.drop_index('ix_menu_item_sizes_company_id', table_name='menu_item_sizes')
    op.drop_table('menu_item_sizes')

    op.drop_index('ix_menu_item_size_categories_company_id', table_name='menu_item_size_categories')
    op.drop_table('menu_item_size_categories')
