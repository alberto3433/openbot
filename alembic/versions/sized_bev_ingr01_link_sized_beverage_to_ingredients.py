"""Link sized_beverage attributes to ingredients table

Revision ID: sized_bev_ingr01
Revises: omelette_ingr01
Create Date: 2026-01-07

This migration:
1. Adds beverage ingredients (drink types, sizes, styles, iced options, extras)
2. Creates item_type_ingredients links for drink_type, size, style, iced, extras
3. Updates sized_beverage attributes to use loads_from_ingredients

Note: sweetener, milk, syrup attributes were already migrated.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'sized_bev_ingr01'
down_revision = 'omelette_ingr01'
branch_labels = None
depends_on = None


# New beverage ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_DRINK_TYPE_INGREDIENTS = [
    ('Coffee', 'beverage', True, True, True, True),
    ('Tea', 'beverage', True, True, True, True),
    ('Hot Chocolate', 'beverage', True, True, True, False),  # Contains milk typically
    ('Chai Latte', 'beverage', True, True, True, False),  # Contains milk
    ('Matcha Latte', 'beverage', True, True, True, False),  # Contains milk
    ('Latte', 'beverage', True, True, True, False),  # Contains milk
    ('Cappuccino', 'beverage', True, True, True, False),  # Contains milk
    ('Americano', 'beverage', True, True, True, True),
    ('Cold Brew', 'beverage', True, True, True, True),
]

NEW_SIZE_INGREDIENTS = [
    ('Small', 'size', True, True, True, True),
    ('Medium', 'size', True, True, True, True),
    ('Large', 'size', True, True, True, True),
]

NEW_STYLE_INGREDIENTS = [
    ('Black', 'style', True, True, True, True),
    ('Light', 'style', True, True, True, True),
    ('Dark', 'style', True, True, True, True),
]

NEW_ICED_INGREDIENTS = [
    ('Hot', 'temperature', True, True, True, True),
    ('Iced', 'temperature', True, True, True, True),
]

NEW_EXTRAS_INGREDIENTS = [
    ('Extra Shot', 'coffee_extra', True, True, True, True),
    ('Double Shot', 'coffee_extra', True, True, True, True),
    ('Triple Shot', 'coffee_extra', True, True, True, True),
]


# Drink type configuration for sized_beverage
# Format: (ingredient_name, price_modifier, display_order, is_default)
SIZED_BEVERAGE_DRINK_TYPE_CONFIG = [
    ('Coffee', 0.00, 1, True),
    ('Tea', 0.00, 2, False),
    ('Hot Chocolate', 0.00, 3, False),
    ('Chai Latte', 0.00, 4, False),
    ('Matcha Latte', 0.00, 5, False),
    ('Latte', 0.00, 6, False),
    ('Cappuccino', 0.00, 7, False),
    ('Americano', 0.00, 8, False),
    ('Cold Brew', 0.00, 9, False),
]

SIZED_BEVERAGE_SIZE_CONFIG = [
    ('Small', 0.00, 1, False),
    ('Medium', 0.50, 2, True),
    ('Large', 0.90, 3, False),
]

SIZED_BEVERAGE_STYLE_CONFIG = [
    ('Black', 0.00, 1, True),
    ('Light', 0.00, 2, False),
    ('Dark', 0.00, 3, False),
]

SIZED_BEVERAGE_ICED_CONFIG = [
    ('Hot', 0.00, 1, True),
    ('Iced', 0.00, 2, False),
]

SIZED_BEVERAGE_EXTRAS_CONFIG = [
    ('Extra Shot', 2.50, 1, False),
    ('Double Shot', 0.50, 2, False),
    ('Triple Shot', 1.00, 3, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new ingredients
    all_ingredients = (
        NEW_DRINK_TYPE_INGREDIENTS +
        NEW_SIZE_INGREDIENTS +
        NEW_STYLE_INGREDIENTS +
        NEW_ICED_INGREDIENTS +
        NEW_EXTRAS_INGREDIENTS
    )

    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in all_ingredients:
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, base_price, is_available,
                                           is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher)
                    VALUES (:name, :category, 'portion', false, 0.0, true,
                            :is_vegan, :is_vegetarian, :is_gluten_free, :is_dairy_free, true)
                """),
                {
                    "name": name,
                    "category": category,
                    "is_vegan": is_vegan,
                    "is_vegetarian": is_vegetarian,
                    "is_gluten_free": is_gluten_free,
                    "is_dairy_free": is_dairy_free,
                }
            )
            print(f"Added {category} ingredient: {name}")

    # Step 2: Get sized_beverage item type id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'sized_beverage'"))
    row = result.fetchone()
    if not row:
        print("Warning: sized_beverage item type not found, skipping")
        return

    sized_beverage_id = row[0]
    print(f"Found sized_beverage item_type_id: {sized_beverage_id}")

    # Step 3: Create links for each attribute
    _create_ingredient_links(conn, sized_beverage_id, 'drink_type', SIZED_BEVERAGE_DRINK_TYPE_CONFIG)
    _create_ingredient_links(conn, sized_beverage_id, 'size', SIZED_BEVERAGE_SIZE_CONFIG)
    _create_ingredient_links(conn, sized_beverage_id, 'style', SIZED_BEVERAGE_STYLE_CONFIG)
    _create_ingredient_links(conn, sized_beverage_id, 'iced', SIZED_BEVERAGE_ICED_CONFIG)
    _create_ingredient_links(conn, sized_beverage_id, 'extras', SIZED_BEVERAGE_EXTRAS_CONFIG)

    # Step 4: Update attributes to use loads_from_ingredients
    _update_attribute(conn, sized_beverage_id, 'drink_type', 'drink_type')
    _update_attribute(conn, sized_beverage_id, 'size', 'size')
    _update_attribute(conn, sized_beverage_id, 'style', 'style')
    _update_attribute(conn, sized_beverage_id, 'iced', 'iced')
    _update_attribute(conn, sized_beverage_id, 'extras', 'extras')


def _create_ingredient_links(conn, item_type_id: int, ingredient_group: str, config: list) -> None:
    """Create item_type_ingredients links for a group."""
    created = 0
    for ingredient_name, price_modifier, display_order, is_default in config:
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": ingredient_name}
        )
        row = result.fetchone()
        if row is None:
            print(f"Warning: Ingredient '{ingredient_name}' not found, skipping")
            continue
        ingredient_id = row[0]

        result = conn.execute(
            text("""
                SELECT id FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = :group
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id, "group": ingredient_group}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, :group, :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "group": ingredient_group,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )
            created += 1

    print(f"Created {created} {ingredient_group} links for sized_beverage")


def _update_attribute(conn, item_type_id: int, attr_slug: str, ingredient_group: str) -> None:
    """Update attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = :group
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": attr_slug, "group": ingredient_group}
    )
    print(f"Updated {attr_slug} attribute to use ingredient_group={ingredient_group}")


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert attributes and remove links for sized_beverage
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'sized_beverage'"))
    row = result.fetchone()
    if row:
        sized_beverage_id = row[0]

        # Revert attributes
        for attr_slug in ['drink_type', 'size', 'style', 'iced', 'extras']:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": sized_beverage_id, "slug": attr_slug}
            )

        # Remove links
        for ingredient_group in ['drink_type', 'size', 'style', 'iced', 'extras']:
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = :group
                """),
                {"item_type_id": sized_beverage_id, "group": ingredient_group}
            )

    # Step 2: Remove newly added ingredients
    all_ingredients = (
        NEW_DRINK_TYPE_INGREDIENTS +
        NEW_SIZE_INGREDIENTS +
        NEW_STYLE_INGREDIENTS +
        NEW_ICED_INGREDIENTS +
        NEW_EXTRAS_INGREDIENTS
    )
    for name, *_ in all_ingredients:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
