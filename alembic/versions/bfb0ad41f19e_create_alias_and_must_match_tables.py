"""create_alias_and_must_match_tables

Revision ID: bfb0ad41f19e
Revises: c7d8e9f0g1h2
Create Date: 2026-01-10

This migration:
1. Creates child tables for aliases (one per parent table):
   - ingredient_aliases
   - menu_item_aliases
   - item_type_aliases
   - modifier_category_aliases
2. Creates a child table for must_match:
   - ingredient_must_match
3. Migrates existing delimited string data to the new tables
4. Drops the old columns

All aliases are globally unique across all alias tables.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'bfb0ad41f19e'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0g1h2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create alias and must_match child tables and migrate data."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Check if tables already exist (from partial run)
    existing_tables = session.execute(sa.text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )).fetchall()
    existing_table_names = {row[0] for row in existing_tables}

    # 1. Create ingredient_aliases table (if not exists)
    if 'ingredient_aliases' not in existing_table_names:
        op.create_table(
            'ingredient_aliases',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('ingredient_id', sa.Integer(), sa.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False),
            sa.Column('alias', sa.String(100), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('alias', name='uq_ingredient_alias_global'),
            sa.Index('idx_ingredient_aliases_ingredient_id', 'ingredient_id'),
        )

    # 2. Create menu_item_aliases table (if not exists)
    if 'menu_item_aliases' not in existing_table_names:
        op.create_table(
            'menu_item_aliases',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('menu_item_id', sa.Integer(), sa.ForeignKey('menu_items.id', ondelete='CASCADE'), nullable=False),
            sa.Column('alias', sa.String(100), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('alias', name='uq_menu_item_alias_global'),
            sa.Index('idx_menu_item_aliases_menu_item_id', 'menu_item_id'),
        )

    # 3. Create item_type_aliases table (if not exists)
    if 'item_type_aliases' not in existing_table_names:
        op.create_table(
            'item_type_aliases',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id', ondelete='CASCADE'), nullable=False),
            sa.Column('alias', sa.String(100), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('alias', name='uq_item_type_alias_global'),
            sa.Index('idx_item_type_aliases_item_type_id', 'item_type_id'),
        )

    # 4. Create modifier_category_aliases table (if not exists)
    if 'modifier_category_aliases' not in existing_table_names:
        op.create_table(
            'modifier_category_aliases',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('modifier_category_id', sa.Integer(), sa.ForeignKey('modifier_categories.id', ondelete='CASCADE'), nullable=False),
            sa.Column('alias', sa.String(100), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('alias', name='uq_modifier_category_alias_global'),
            sa.Index('idx_modifier_category_aliases_modifier_category_id', 'modifier_category_id'),
        )

    # 5. Create ingredient_must_match table (if not exists)
    if 'ingredient_must_match' not in existing_table_names:
        op.create_table(
            'ingredient_must_match',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('ingredient_id', sa.Integer(), sa.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False),
            sa.Column('must_match', sa.String(100), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint('ingredient_id', 'must_match', name='uq_ingredient_must_match'),
            sa.Index('idx_ingredient_must_match_ingredient_id', 'ingredient_id'),
        )

    # --- DATA MIGRATION ---
    # Track all aliases globally to enforce uniqueness during migration
    all_aliases_seen: set[str] = set()

    def add_alias_if_unique(table: str, fk_col: str, fk_id: int, alias: str) -> bool:
        """Add alias only if globally unique. Returns True if added."""
        alias_lower = alias.strip().lower()
        if not alias_lower:
            return False
        if alias_lower in all_aliases_seen:
            # Log but don't fail - skip duplicate
            print(f"SKIP duplicate alias '{alias}' for {table} fk={fk_id}")
            return False
        all_aliases_seen.add(alias_lower)
        session.execute(
            sa.text(f"INSERT INTO {table} ({fk_col}, alias) VALUES (:fk_id, :alias)"),
            {"fk_id": fk_id, "alias": alias.strip()}
        )
        return True

    # 6. Migrate ingredients.aliases -> ingredient_aliases
    result = session.execute(sa.text("SELECT id, aliases FROM ingredients WHERE aliases IS NOT NULL AND aliases != ''"))
    for row in result:
        ing_id, aliases_str = row
        # Try pipe-separated first, then comma-separated
        if '|' in aliases_str:
            aliases = aliases_str.split('|')
        else:
            aliases = aliases_str.split(',')
        for alias in aliases:
            add_alias_if_unique('ingredient_aliases', 'ingredient_id', ing_id, alias)

    # 7. Migrate ingredients.must_match -> ingredient_must_match
    result = session.execute(sa.text("SELECT id, must_match FROM ingredients WHERE must_match IS NOT NULL AND must_match != ''"))
    for row in result:
        ing_id, must_match_str = row
        # Try pipe-separated first, then comma-separated
        if '|' in must_match_str:
            must_matches = must_match_str.split('|')
        else:
            must_matches = must_match_str.split(',')
        for mm in must_matches:
            mm_stripped = mm.strip()
            if mm_stripped:
                session.execute(
                    sa.text("INSERT INTO ingredient_must_match (ingredient_id, must_match) VALUES (:ing_id, :mm)"),
                    {"ing_id": ing_id, "mm": mm_stripped}
                )

    # 8. Migrate menu_items.aliases -> menu_item_aliases
    result = session.execute(sa.text("SELECT id, aliases FROM menu_items WHERE aliases IS NOT NULL AND aliases != ''"))
    for row in result:
        mi_id, aliases_str = row
        if '|' in aliases_str:
            aliases = aliases_str.split('|')
        else:
            aliases = aliases_str.split(',')
        for alias in aliases:
            add_alias_if_unique('menu_item_aliases', 'menu_item_id', mi_id, alias)

    # 9. Migrate item_types.aliases -> item_type_aliases
    result = session.execute(sa.text("SELECT id, aliases FROM item_types WHERE aliases IS NOT NULL AND aliases != ''"))
    for row in result:
        it_id, aliases_str = row
        if '|' in aliases_str:
            aliases = aliases_str.split('|')
        else:
            aliases = aliases_str.split(',')
        for alias in aliases:
            add_alias_if_unique('item_type_aliases', 'item_type_id', it_id, alias)

    # 10. Migrate modifier_categories.aliases -> modifier_category_aliases
    result = session.execute(sa.text("SELECT id, aliases FROM modifier_categories WHERE aliases IS NOT NULL AND aliases != ''"))
    for row in result:
        mc_id, aliases_str = row
        if '|' in aliases_str:
            aliases = aliases_str.split('|')
        else:
            aliases = aliases_str.split(',')
        for alias in aliases:
            add_alias_if_unique('modifier_category_aliases', 'modifier_category_id', mc_id, alias)

    session.commit()

    # 11. Drop old columns (check if they exist first)
    def column_exists(table: str, column: str) -> bool:
        result = session.execute(sa.text(
            f"SELECT 1 FROM information_schema.columns WHERE table_name = '{table}' AND column_name = '{column}'"
        )).fetchone()
        return result is not None

    if column_exists('ingredients', 'aliases'):
        op.drop_column('ingredients', 'aliases')
    if column_exists('ingredients', 'must_match'):
        op.drop_column('ingredients', 'must_match')
    if column_exists('menu_items', 'aliases'):
        op.drop_column('menu_items', 'aliases')
    if column_exists('item_types', 'aliases'):
        op.drop_column('item_types', 'aliases')
    if column_exists('modifier_categories', 'aliases'):
        op.drop_column('modifier_categories', 'aliases')


def downgrade() -> None:
    """Re-add old columns and migrate data back."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # 1. Re-add the old columns
    op.add_column('ingredients', sa.Column('aliases', sa.Text(), nullable=True))
    op.add_column('ingredients', sa.Column('must_match', sa.Text(), nullable=True))
    op.add_column('menu_items', sa.Column('aliases', sa.String(255), nullable=True))
    op.add_column('item_types', sa.Column('aliases', sa.String(255), nullable=True))
    op.add_column('modifier_categories', sa.Column('aliases', sa.String(255), nullable=True))

    # 2. Migrate ingredient_aliases back to ingredients.aliases
    result = session.execute(sa.text("""
        SELECT ingredient_id, GROUP_CONCAT(alias, '|') as aliases
        FROM ingredient_aliases
        GROUP BY ingredient_id
    """))
    for row in result:
        session.execute(
            sa.text("UPDATE ingredients SET aliases = :aliases WHERE id = :id"),
            {"aliases": row[1], "id": row[0]}
        )

    # 3. Migrate ingredient_must_match back to ingredients.must_match
    result = session.execute(sa.text("""
        SELECT ingredient_id, GROUP_CONCAT(must_match, '|') as must_match_list
        FROM ingredient_must_match
        GROUP BY ingredient_id
    """))
    for row in result:
        session.execute(
            sa.text("UPDATE ingredients SET must_match = :mm WHERE id = :id"),
            {"mm": row[1], "id": row[0]}
        )

    # 4. Migrate menu_item_aliases back to menu_items.aliases
    result = session.execute(sa.text("""
        SELECT menu_item_id, GROUP_CONCAT(alias, '|') as aliases
        FROM menu_item_aliases
        GROUP BY menu_item_id
    """))
    for row in result:
        session.execute(
            sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
            {"aliases": row[1], "id": row[0]}
        )

    # 5. Migrate item_type_aliases back to item_types.aliases
    result = session.execute(sa.text("""
        SELECT item_type_id, GROUP_CONCAT(alias, '|') as aliases
        FROM item_type_aliases
        GROUP BY item_type_id
    """))
    for row in result:
        session.execute(
            sa.text("UPDATE item_types SET aliases = :aliases WHERE id = :id"),
            {"aliases": row[1], "id": row[0]}
        )

    # 6. Migrate modifier_category_aliases back to modifier_categories.aliases
    result = session.execute(sa.text("""
        SELECT modifier_category_id, GROUP_CONCAT(alias, '|') as aliases
        FROM modifier_category_aliases
        GROUP BY modifier_category_id
    """))
    for row in result:
        session.execute(
            sa.text("UPDATE modifier_categories SET aliases = :aliases WHERE id = :id"),
            {"aliases": row[1], "id": row[0]}
        )

    session.commit()

    # 7. Drop the child tables
    op.drop_table('ingredient_must_match')
    op.drop_table('modifier_category_aliases')
    op.drop_table('item_type_aliases')
    op.drop_table('menu_item_aliases')
    op.drop_table('ingredient_aliases')
