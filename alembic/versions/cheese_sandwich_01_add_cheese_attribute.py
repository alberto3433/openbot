"""Add cheese attribute to cheese_sandwich item type.

The cheese_sandwich item type was missing the 'cheese' global attribute,
which prevented default cheese ingredients (e.g., mozzarella on Mozzarella
Cheese Sandwich) from being displayed in the order cart.

Settings:
- listen_only=true: Accept cheese modifications but don't prompt
- ask_in_conversation=false: Don't ask "What cheese would you like?"
- is_required=false: Cheese is optional
- allow_none=true: Can order without cheese

Revision ID: cheese_sandwich_01
Revises: schema_cleanup_02
Create Date: 2025-02-10
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'cheese_sandwich_01'
down_revision = 'schema_cleanup_02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get IDs for cheese_sandwich item type and cheese global attribute
    # cheese_sandwich item_type_id = 38
    # cheese global_attribute_id = 4

    op.execute("""
        INSERT INTO item_type_global_attributes
            (item_type_id, global_attribute_id, display_order, is_required, allow_none, ask_in_conversation, listen_only)
        VALUES
            (38, 4, 10, false, true, false, true)
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM item_type_global_attributes
        WHERE item_type_id = 38 AND global_attribute_id = 4
    """)
