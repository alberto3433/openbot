"""Change MenuItem child table FKs from CASCADE to RESTRICT

Revision ID: restrict_mi_fks_001
Revises: add_quantity_unit_001
Create Date: 2026-01-28

Changes ondelete behavior from CASCADE to RESTRICT on all foreign keys
pointing from child tables to menu_items.id. This prevents accidental
deletion of a MenuItem from silently wiping out its aliases, ingredient
links, category assignments, size prices, and store availability records.

With RESTRICT, you must explicitly remove dependent records before deleting
a MenuItem. The admin_menu.py delete endpoint provides clear error messages
listing what needs cleanup.

Tables affected:
- menu_item_aliases.menu_item_id
- menu_item_ingredients.menu_item_id
- menu_item_categories.menu_item_id
- menu_item_size_prices.menu_item_id
- menu_item_store_availability.menu_item_id
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "restrict_mi_fks_001"
down_revision: Union[str, None] = "add_quantity_unit_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table_name, constraint_name, column, referred_table, referred_column)
_FK_SPECS = [
    ("menu_item_aliases", "menu_item_aliases_menu_item_id_fkey", "menu_item_id", "menu_items", "id"),
    ("menu_item_ingredients", "menu_item_ingredients_menu_item_id_fkey", "menu_item_id", "menu_items", "id"),
    ("menu_item_categories", "menu_item_categories_menu_item_id_fkey", "menu_item_id", "menu_items", "id"),
    ("menu_item_size_prices", "menu_item_size_prices_menu_item_id_fkey", "menu_item_id", "menu_items", "id"),
    ("menu_item_store_availability", "menu_item_store_availability_menu_item_id_fkey", "menu_item_id", "menu_items", "id"),
]


def upgrade() -> None:
    for table, constraint, column, ref_table, ref_column in _FK_SPECS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, ref_table,
            [column], [ref_column],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    for table, constraint, column, ref_table, ref_column in _FK_SPECS:
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.create_foreign_key(
            constraint, table, ref_table,
            [column], [ref_column],
            ondelete="CASCADE",
        )
