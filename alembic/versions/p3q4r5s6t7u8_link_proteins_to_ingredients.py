"""Link proteins to ingredients table

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2025-01-07

This migration:
1. Adds missing protein variants to the ingredients table
2. Creates item_type_ingredients links for bagel, egg_sandwich, and omelette
3. Updates protein attributes to use loads_from_ingredients

Pricing is set per item type based on current attribute_options values.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'p3q4r5s6t7u8'
down_revision = 'o2p3q4r5s6t7'
branch_labels = None
depends_on = None


# New protein ingredients to add
# Format: (name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_PROTEIN_INGREDIENTS = [
    ('Turkey Bacon', False, False, True, True),
    ('Applewood Smoked Bacon', False, False, True, True),
    ('Chicken Sausage', False, False, True, True),
    ('Sausage Patty', False, False, True, True),
    ('Smoked Turkey', False, False, True, True),
    ('Roast Beef', False, False, True, True),
    ("Esposito's Sausage", False, False, True, True),
]

# Protein configuration per item type
# Format: (ingredient_name, price_modifier, display_order, is_default)
BAGEL_PROTEIN_CONFIG = [
    ('Egg', 1.50, 1, False),
    ('Egg White', 1.00, 2, False),
    ('Bacon', 2.00, 3, False),
    ('Turkey Bacon', 2.50, 4, False),
    ('Ham', 2.00, 5, False),
    ('Turkey', 2.50, 6, False),
    ('Sausage', 2.00, 7, False),
    ('Pastrami', 3.00, 8, False),
    ('Nova Scotia Salmon', 6.00, 9, False),
]

EGG_SANDWICH_PROTEIN_CONFIG = [
    ('Egg', 0.00, 1, True),  # Default for egg sandwich
    ('Egg White', 0.00, 2, False),
    ('Bacon', 0.00, 3, False),
    ('Turkey Bacon', 2.95, 4, False),
    ('Applewood Smoked Bacon', 2.50, 5, False),
    ('Ham', 2.50, 6, False),
    ('Sausage', 0.00, 7, False),
    ('Sausage Patty', 2.75, 8, False),
    ('Chicken Sausage', 2.95, 9, False),
    ('Smoked Turkey', 3.45, 10, False),
    ('Turkey', 2.95, 11, False),
    ('Pastrami', 3.45, 12, False),
    ('Corned Beef', 3.45, 13, False),
    ('Roast Beef', 3.45, 14, False),
    ('Nova Scotia Salmon', 6.00, 15, False),
]

OMELETTE_PROTEIN_CONFIG = [
    ('Egg', 0.00, 1, True),  # Default for omelette (eggs are base)
    ('Bacon', 0.00, 2, False),
    ('Turkey Bacon', 0.00, 3, False),
    ('Applewood Smoked Bacon', 0.00, 4, False),
    ('Ham', 0.00, 5, False),
    ('Sausage', 0.00, 6, False),
    ("Esposito's Sausage", 0.00, 7, False),
    ('Corned Beef', 0.00, 8, False),
    ('Nova Scotia Salmon', 0.00, 9, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new protein ingredients
    for name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_PROTEIN_INGREDIENTS:
        # Check if ingredient already exists
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, base_price, is_available,
                                           is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher)
                    VALUES (:name, 'protein', 'portion', true, 0.0, true,
                            :is_vegan, :is_vegetarian, :is_gluten_free, :is_dairy_free, true)
                """),
                {
                    "name": name,
                    "is_vegan": is_vegan,
                    "is_vegetarian": is_vegetarian,
                    "is_gluten_free": is_gluten_free,
                    "is_dairy_free": is_dairy_free,
                }
            )

    # Step 2: Link proteins to bagel item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if row:
        bagel_id = row[0]
        _create_protein_links(conn, bagel_id, BAGEL_PROTEIN_CONFIG)
        _update_protein_attribute(conn, bagel_id)

    # Step 3: Link proteins to egg_sandwich item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        _create_protein_links(conn, egg_sandwich_id, EGG_SANDWICH_PROTEIN_CONFIG)
        _update_protein_attribute(conn, egg_sandwich_id)

    # Step 4: Link proteins to omelette item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]
        _create_protein_links(conn, omelette_id, OMELETTE_PROTEIN_CONFIG)
        _update_protein_attribute(conn, omelette_id)


def _create_protein_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for proteins."""
    for ingredient_name, price_modifier, display_order, is_default in config:
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'protein'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'protein', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_protein_attribute(conn, item_type_id: int) -> None:
    """Update protein attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'protein'
            WHERE item_type_id = :item_type_id AND slug = 'protein'
        """),
        {"item_type_id": item_type_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert protein attributes for all item types
    for item_type_slug in ['bagel', 'egg_sandwich', 'omelette']:
        result = conn.execute(
            text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": item_type_slug}
        )
        row = result.fetchone()
        if row:
            item_type_id = row[0]
            # Revert attribute
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = 'protein'
                """),
                {"item_type_id": item_type_id}
            )
            # Remove protein links
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = 'protein'
                """),
                {"item_type_id": item_type_id}
            )

    # Step 2: Remove newly added protein ingredients
    for name, *_ in NEW_PROTEIN_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name AND category = 'protein'"),
            {"name": name}
        )
