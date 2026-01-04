"""Seed missing by-pound items (cheese, cold cuts, salads).

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2025-01-04 14:00:00.000000

This migration adds the missing by-the-pound items that were previously
hardcoded in BY_POUND_ITEMS constant:
- Cheese items (Muenster, Swiss, etc.)
- Cold cut items (Turkey Breast, Roast Beef, etc.)
- Salad items (Tuna Salad, Egg Salad, etc.)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "u5v6w7x8y9z0"
down_revision: Union[str, None] = "t4u5v6w7x8y9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# By-pound items to add, organized by category
# Format: (name, aliases, base_price_per_lb)
BY_POUND_ITEMS = {
    "cheese": [
        ("Muenster (1/4 lb)", "muenster", 4.50),
        ("Muenster (1 lb)", "muenster", 16.00),
        ("Swiss (1/4 lb)", "swiss", 4.50),
        ("Swiss (1 lb)", "swiss", 16.00),
        ("American (1/4 lb)", "american, american cheese", 4.00),
        ("American (1 lb)", "american, american cheese", 14.00),
        ("Cheddar (1/4 lb)", "cheddar, cheddar cheese", 4.50),
        ("Cheddar (1 lb)", "cheddar, cheddar cheese", 16.00),
        ("Provolone (1/4 lb)", "provolone", 4.50),
        ("Provolone (1 lb)", "provolone", 16.00),
        ("Gouda (1/4 lb)", "gouda", 5.00),
        ("Gouda (1 lb)", "gouda", 18.00),
    ],
    "cold_cut": [
        ("Turkey Breast (1/4 lb)", "turkey, turkey breast, sliced turkey", 5.00),
        ("Turkey Breast (1 lb)", "turkey, turkey breast, sliced turkey", 18.00),
        ("Roast Beef (1/4 lb)", "roast beef, beef", 5.50),
        ("Roast Beef (1 lb)", "roast beef, beef", 20.00),
        ("Pastrami (1/4 lb)", "pastrami", 5.50),
        ("Pastrami (1 lb)", "pastrami", 20.00),
        ("Corned Beef (1/4 lb)", "corned beef", 5.50),
        ("Corned Beef (1 lb)", "corned beef", 20.00),
        ("Ham (1/4 lb)", "ham, sliced ham", 4.50),
        ("Ham (1 lb)", "ham, sliced ham", 16.00),
        ("Salami (1/4 lb)", "salami", 5.00),
        ("Salami (1 lb)", "salami", 18.00),
        ("Bologna (1/4 lb)", "bologna", 4.00),
        ("Bologna (1 lb)", "bologna", 14.00),
    ],
    "salad": [
        ("Tuna Salad (1/4 lb)", "tuna, tuna salad", 5.00),
        ("Tuna Salad (1 lb)", "tuna, tuna salad", 18.00),
        ("Egg Salad (1/4 lb)", "egg salad", 4.50),
        ("Egg Salad (1 lb)", "egg salad", 16.00),
        ("Chicken Salad (1/4 lb)", "chicken salad", 5.50),
        ("Chicken Salad (1 lb)", "chicken salad", 20.00),
    ],
}


def upgrade() -> None:
    conn = op.get_bind()

    # Get the by_the_lb item type ID
    result = conn.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'by_the_lb'")
    )
    by_the_lb_type_id = result.scalar()

    if by_the_lb_type_id is None:
        # Create the item type if it doesn't exist
        conn.execute(
            sa.text("INSERT INTO item_types (slug, name) VALUES ('by_the_lb', 'By the Pound')")
        )
        result = conn.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'by_the_lb'")
        )
        by_the_lb_type_id = result.scalar()

    # Insert the by-pound items
    for category, items in BY_POUND_ITEMS.items():
        for name, aliases, price in items:
            # Check if item already exists
            result = conn.execute(
                sa.text("SELECT id FROM menu_items WHERE name = :name"),
                {"name": name}
            )
            if result.scalar() is None:
                conn.execute(
                    sa.text("""
                        INSERT INTO menu_items (
                            name, category, is_signature, base_price, available_qty,
                            item_type_id, aliases, by_pound_category
                        )
                        VALUES (
                            :name, :item_category, :is_signature, :price, :available_qty,
                            :type_id, :aliases, :by_pound_category
                        )
                    """),
                    {
                        "name": name,
                        "item_category": "By the Pound",  # Required category column
                        "is_signature": False,  # Not a signature item
                        "price": price,
                        "available_qty": 999,  # Always available
                        "type_id": by_the_lb_type_id,
                        "aliases": aliases,
                        "by_pound_category": category,
                    }
                )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove the items we added
    for category, items in BY_POUND_ITEMS.items():
        for name, _, _ in items:
            conn.execute(
                sa.text("DELETE FROM menu_items WHERE name = :name"),
                {"name": name}
            )
