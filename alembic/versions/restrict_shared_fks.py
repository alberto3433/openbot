"""Change shared/config FK constraints from CASCADE to RESTRICT

Revision ID: restrict_shared_fks_001
Revises: restrict_mi_fks_001
Create Date: 2026-01-28

Changes ondelete behavior from CASCADE to RESTRICT on 7 foreign keys that
reference shared configuration data. This prevents accidental deletion of
a parent record from silently destroying shared references.

Constraints changed:
- global_attribute_options.global_attribute_id (options owned by attribute)
- item_type_global_attributes.item_type_id (attribute config per item type)
- item_type_global_attributes.global_attribute_id (attribute config per item type)
- item_type_ingredients.item_type_id (ingredient associations per item type)
- item_type_ingredients.ingredient_id (ingredient associations per item type)
- menu_item_ingredients.ingredient_id (default ingredients per menu item)
- menu_item_categories.category_id (category assignments per menu item)
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "restrict_shared_fks_001"
down_revision: Union[str, None] = "restrict_mi_fks_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table_name, constraint_name, column, referred_table, referred_column)
_FK_SPECS = [
    ("global_attribute_options", "global_attribute_options_global_attribute_id_fkey", "global_attribute_id", "global_attributes", "id"),
    ("item_type_global_attributes", "item_type_global_attributes_item_type_id_fkey", "item_type_id", "item_types", "id"),
    ("item_type_global_attributes", "item_type_global_attributes_global_attribute_id_fkey", "global_attribute_id", "global_attributes", "id"),
    ("item_type_ingredients", "item_type_ingredients_item_type_id_fkey", "item_type_id", "item_types", "id"),
    ("item_type_ingredients", "item_type_ingredients_ingredient_id_fkey", "ingredient_id", "ingredients", "id"),
    ("menu_item_ingredients", "menu_item_ingredients_ingredient_id_fkey", "ingredient_id", "ingredients", "id"),
    ("menu_item_categories", "menu_item_categories_category_id_fkey", "category_id", "categories", "id"),
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
