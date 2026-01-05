"""Add classifier column to menu_items for sub-category grouping.

Revision ID: a1b2c3d4e5f7
Revises: z0a1b2c3d4e5
Create Date: 2025-01-04 22:00:00.000000

This migration adds a 'classifier' column to menu_items for finer-grained grouping
within categories. For example, all muffins have classifier='muffin', all cookies
have classifier='cookie'. This enables queries like "what muffins do you have?"
to filter by classifier instead of relying on hardcoded KNOWN_MENU_ITEMS.

The classifier is separate from item_type_id because:
- item_type_id defines behavior (configurable, skip_config, attributes)
- classifier is purely for filtering/grouping related items

Examples:
- "Blueberry Muffin" (item_type=pastry, classifier=muffin)
- "Chocolate Chip Cookie" (item_type=pastry, classifier=cookie)
- "Brownie" (item_type=pastry, classifier=brownie)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "z0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Classifier mappings: (name_pattern, classifier_value)
# These are applied based on item name matching
CLASSIFIER_MAPPINGS = [
    # Pastries - muffins
    ("muffin", "muffin"),
    # Pastries - cookies
    ("cookie", "cookie"),
    # Pastries - brownies/bars
    ("brownie", "brownie"),
    ("blondie", "brownie"),
    ("square", "brownie"),
    # Pastries - babka
    ("babka", "babka"),
    # Pastries - rugelach
    ("rugelach", "rugelach"),
    # Pastries - danish
    ("danish", "danish"),
    # Pastries - macaroons
    ("macaroon", "macaroon"),
    # Pastries - pound cake
    ("pound cake", "pound_cake"),
    ("coffee cake", "coffee_cake"),
    # Omelettes
    ("omelette", "omelette"),
    ("omelet", "omelette"),
    # Chips
    ("chips", "chips"),
    ("chip", "chips"),
    # Juices
    ("juice", "juice"),
    # Sodas
    ("soda", "soda"),
    ("coca-cola", "soda"),
    ("sprite", "soda"),
    ("ginger ale", "soda"),
    # Coffee
    ("coffee", "coffee"),
    ("espresso", "coffee"),
    ("latte", "coffee"),
    ("cappuccino", "coffee"),
    ("macchiato", "coffee"),
    ("americano", "coffee"),
    # Tea
    ("tea", "tea"),
    # Matcha
    ("matcha", "matcha"),
    # Hot chocolate
    ("hot chocolate", "hot_chocolate"),
    ("hot cocoa", "hot_chocolate"),
    # Soup
    ("soup", "soup"),
    # Salad (as menu item)
    ("salad", "salad"),
]


def upgrade() -> None:
    """Add classifier column and populate values."""
    # Add the column
    op.add_column(
        'menu_items',
        sa.Column('classifier', sa.String(), nullable=True)
    )

    # Add index for efficient filtering
    op.create_index('ix_menu_items_classifier', 'menu_items', ['classifier'])

    # Populate classifier values based on name patterns
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        for pattern, classifier in CLASSIFIER_MAPPINGS:
            # Update items where name contains the pattern (case-insensitive)
            session.execute(
                sa.text("""
                    UPDATE menu_items
                    SET classifier = :classifier
                    WHERE LOWER(name) LIKE :pattern
                    AND classifier IS NULL
                """),
                {"classifier": classifier, "pattern": f"%{pattern.lower()}%"}
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """Remove classifier column."""
    op.drop_index('ix_menu_items_classifier', 'menu_items')
    op.drop_column('menu_items', 'classifier')
