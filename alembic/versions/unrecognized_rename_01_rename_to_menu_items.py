"""Rename unrecognized item tables to unrecognized menu item tables.

Revision ID: unrecognized_rename_01
Revises: flagel_bialy_01
Create Date: 2026-02-18

Renames:
- unrecognized_item_suggestions -> unrecognized_menu_item_suggestions
- unrecognized_suggestion_menu_items -> unrecognized_menu_item_suggestion_items
- unrecognized_item_log -> unrecognized_menu_item_log

This clarifies that these tables are for unrecognized *menu items*, as opposed
to the new unrecognized *ingredient* suggestions table.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'unrecognized_rename_01'
down_revision: Union[str, Sequence[str], None] = 'flagel_bialy_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("unrecognized_item_suggestions", "unrecognized_menu_item_suggestions")
    op.rename_table("unrecognized_suggestion_menu_items", "unrecognized_menu_item_suggestion_items")
    op.rename_table("unrecognized_item_log", "unrecognized_menu_item_log")

    # Rename FK constraints on junction table to match new table names
    # Drop old FKs and recreate with new names
    op.drop_constraint(
        "unrecognized_suggestion_menu_items_suggestion_id_fkey",
        "unrecognized_menu_item_suggestion_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "unrecognized_suggestion_menu_items_menu_item_id_fkey",
        "unrecognized_menu_item_suggestion_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "unrecognized_menu_item_suggestion_items_suggestion_id_fkey",
        "unrecognized_menu_item_suggestion_items",
        "unrecognized_menu_item_suggestions",
        ["suggestion_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "unrecognized_menu_item_suggestion_items_menu_item_id_fkey",
        "unrecognized_menu_item_suggestion_items",
        "menu_items",
        ["menu_item_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Reverse FK renames
    op.drop_constraint(
        "unrecognized_menu_item_suggestion_items_suggestion_id_fkey",
        "unrecognized_menu_item_suggestion_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "unrecognized_menu_item_suggestion_items_menu_item_id_fkey",
        "unrecognized_menu_item_suggestion_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "unrecognized_suggestion_menu_items_suggestion_id_fkey",
        "unrecognized_suggestion_menu_items",
        "unrecognized_item_suggestions",
        ["suggestion_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "unrecognized_suggestion_menu_items_menu_item_id_fkey",
        "unrecognized_suggestion_menu_items",
        "menu_items",
        ["menu_item_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.rename_table("unrecognized_menu_item_log", "unrecognized_item_log")
    op.rename_table("unrecognized_menu_item_suggestion_items", "unrecognized_suggestion_menu_items")
    op.rename_table("unrecognized_menu_item_suggestions", "unrecognized_item_suggestions")
