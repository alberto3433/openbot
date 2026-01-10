"""Add spread attribute to deli_sandwich item type

Revision ID: l6m7n8o9p0q2
Revises: k5l6m7n8o9p1
Create Date: 2026-01-08

This migration adds a "spread" attribute to deli_sandwich with the same
spread options as the bagel item type, loaded from ingredients.

The attribute is:
- Single select (pick one spread)
- Optional (allow_none=True)
- Not asked in conversation (only if customer requests)
- Loaded from ingredients (uses item_type_ingredients table)

Prices match bagel spreads:
- Plain Cream Cheese: $1.50
- Standard specialty CC: $1.75 (Scallion, Vegetable, etc.)
- Premium CC: $2.00-$2.75 (Truffle, Nova, Honey Walnut)
- Butter: $0.50
- Other spreads: $0.75-$2.25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = 'l6m7n8o9p0q2'
down_revision: Union[str, Sequence[str], None] = 'k5l6m7n8o9p1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Spread ingredients configuration (same as bagel)
# Format: (ingredient_name, price_modifier, display_order, is_default)
SPREAD_CONFIG = [
    # Cream Cheeses - most popular first
    ('Plain Cream Cheese', 1.50, 1, False),  # Not default for deli sandwich
    ('Scallion Cream Cheese', 1.75, 2, False),
    ('Vegetable Cream Cheese', 1.75, 3, False),
    ('Strawberry Cream Cheese', 1.75, 4, False),
    ('Blueberry Cream Cheese', 1.75, 5, False),
    ('Jalapeño Cream Cheese', 1.75, 6, False),
    ('Olive Cream Cheese', 1.75, 7, False),
    ('Sun-Dried Tomato Cream Cheese', 2.00, 8, False),
    ('Kalamata Olive Cream Cheese', 2.00, 9, False),
    ('Honey Walnut Cream Cheese', 2.25, 10, False),
    ('Maple Raisin Walnut Cream Cheese', 2.25, 11, False),
    ('Nova Scotia Cream Cheese', 2.50, 12, False),
    ('Truffle Cream Cheese', 2.75, 13, False),

    # Tofu cream cheeses (dairy-free options)
    ('Tofu Cream Cheese', 1.75, 14, False),
    ('Tofu Scallion Cream Cheese', 2.00, 15, False),
    ('Tofu Vegetable Cream Cheese', 2.00, 16, False),
    ('Tofu Nova Cream Cheese', 2.50, 17, False),

    # Other spreads
    ('Butter', 0.50, 18, False),
    ('Peanut Butter', 1.25, 19, False),
    ('Nutella', 1.50, 20, False),
    ('Hummus', 1.75, 21, False),
    ('Avocado Spread', 2.25, 22, False),
    ('Jam', 0.75, 23, False),
    ('Jelly', 0.75, 24, False),
]


def upgrade() -> None:
    """Add spread attribute to deli_sandwich."""
    conn = op.get_bind()

    # Get deli_sandwich item type ID
    result = conn.execute(text(
        "SELECT id FROM item_types WHERE slug = 'deli_sandwich'"
    ))
    row = result.fetchone()
    if not row:
        print("Warning: deli_sandwich item type not found, skipping")
        return

    deli_sandwich_id = row[0]
    print(f"Found deli_sandwich item_type_id: {deli_sandwich_id}")

    # Get the display_order of the 'scooped' attribute to insert after it
    result = conn.execute(text("""
        SELECT display_order FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'scooped'
    """), {'item_type_id': deli_sandwich_id})
    scooped_row = result.fetchone()

    if scooped_row:
        scooped_order = scooped_row[0]
        spread_order = scooped_order + 1

        # Shift existing attributes to make room
        conn.execute(text("""
            UPDATE item_type_attributes
            SET display_order = display_order + 1
            WHERE item_type_id = :item_type_id AND display_order > :scooped_order
        """), {'item_type_id': deli_sandwich_id, 'scooped_order': scooped_order})
        print(f"Shifted existing attributes after scooped (order={scooped_order})")
    else:
        # No scooped attribute found, try after toasted
        result = conn.execute(text("""
            SELECT display_order FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'toasted'
        """), {'item_type_id': deli_sandwich_id})
        toasted_row = result.fetchone()

        if toasted_row:
            toasted_order = toasted_row[0]
            spread_order = toasted_order + 1
            conn.execute(text("""
                UPDATE item_type_attributes
                SET display_order = display_order + 1
                WHERE item_type_id = :item_type_id AND display_order > :toasted_order
            """), {'item_type_id': deli_sandwich_id, 'toasted_order': toasted_order})
        else:
            # Fall back to end
            result = conn.execute(text("""
                SELECT COALESCE(MAX(display_order), 0) FROM item_type_attributes
                WHERE item_type_id = :item_type_id
            """), {'item_type_id': deli_sandwich_id})
            max_order = result.fetchone()[0]
            spread_order = max_order + 1

    print(f"spread attribute will have display_order={spread_order}")

    # Check if spread attribute already exists
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'spread'
    """), {'item_type_id': deli_sandwich_id})

    if result.fetchone():
        print("spread attribute already exists, skipping attribute creation")
    else:
        # Create the spread attribute (single_select, loads from ingredients)
        conn.execute(text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type,
                is_required, allow_none, ask_in_conversation,
                question_text, loads_from_ingredients, ingredient_group, display_order
            ) VALUES (
                :item_type_id, 'spread', 'Spread', 'single_select',
                FALSE, TRUE, FALSE,
                'Any spread on that?', TRUE, 'spread', :display_order
            )
        """), {'item_type_id': deli_sandwich_id, 'display_order': spread_order})
        print(f"Created spread attribute with display_order={spread_order}")

    # Create item_type_ingredients links for spreads
    created_count = 0
    for ingredient_name, price_modifier, display_order, is_default in SPREAD_CONFIG:
        # Get ingredient id
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": ingredient_name}
        )
        row = result.fetchone()
        if row is None:
            print(f"Warning: Ingredient '{ingredient_name}' not found, skipping")
            continue
        ingredient_id = row[0]

        # Check if link already exists
        result = conn.execute(
            text("""
                SELECT id FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'spread'
            """),
            {"item_type_id": deli_sandwich_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'spread', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": deli_sandwich_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )
            created_count += 1

    print(f"Created {created_count} spread ingredient links for deli_sandwich")


def downgrade() -> None:
    """Remove spread attribute from deli_sandwich."""
    conn = op.get_bind()

    # Get deli_sandwich item type ID
    result = conn.execute(text(
        "SELECT id FROM item_types WHERE slug = 'deli_sandwich'"
    ))
    row = result.fetchone()
    if not row:
        return

    deli_sandwich_id = row[0]

    # Get spread attribute display_order before deleting
    result = conn.execute(text("""
        SELECT display_order FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'spread'
    """), {'item_type_id': deli_sandwich_id})
    spread_row = result.fetchone()
    spread_order = spread_row[0] if spread_row else None

    # Remove item_type_ingredients links for spreads
    conn.execute(
        text("""
            DELETE FROM item_type_ingredients
            WHERE item_type_id = :item_type_id AND ingredient_group = 'spread'
        """),
        {"item_type_id": deli_sandwich_id}
    )

    # Delete the spread attribute
    conn.execute(text("""
        DELETE FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'spread'
    """), {'item_type_id': deli_sandwich_id})

    # Shift attributes back if we know the original order
    if spread_order is not None:
        conn.execute(text("""
            UPDATE item_type_attributes
            SET display_order = display_order - 1
            WHERE item_type_id = :item_type_id AND display_order > :spread_order
        """), {'item_type_id': deli_sandwich_id, 'spread_order': spread_order})

    print("Removed spread attribute and ingredient links from deli_sandwich")
