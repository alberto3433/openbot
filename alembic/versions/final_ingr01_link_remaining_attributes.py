"""Link remaining attributes to ingredients table

Revision ID: final_ingr01
Revises: espresso_ingr01
Create Date: 2026-01-07

This migration completes the ingredient migration by linking:
1. bagel.bagel_type - 22 bagel type options
2. egg_sandwich.egg_style - 6 egg cooking style options
3. egg_sandwich.egg_quantity - 3 egg quantity options
4. fish_sandwich.extra_protein - 15 protein options
5. omelette.egg_style - 2 egg style options
6. omelette.egg_quantity - 4 egg quantity options
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'final_ingr01'
down_revision = 'f0g1h2i3j4k5'
branch_labels = None
depends_on = None


# New egg style ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_EGG_STYLE_INGREDIENTS = [
    ('Fried Eggs', 'egg_style', False, True, True, True),
    ('Over Easy Eggs', 'egg_style', False, True, True, True),
    ('Over Medium Eggs', 'egg_style', False, True, True, True),
    ('Over Hard Eggs', 'egg_style', False, True, True, True),
    ('Regular Eggs', 'egg_style', False, True, True, True),  # For omelette
]

# New egg quantity ingredients
NEW_EGG_QUANTITY_INGREDIENTS = [
    ('2 Eggs', 'egg_quantity', False, True, True, True),
    ('3 Eggs', 'egg_quantity', False, True, True, True),
    ('4 Eggs', 'egg_quantity', False, True, True, True),
    ('5 Eggs', 'egg_quantity', False, True, True, True),
    ('6 Eggs', 'egg_quantity', False, True, True, True),
]


# Bagel type configuration for bagel item type
# Format: (ingredient_name, price_modifier, display_order, is_default)
BAGEL_TYPE_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),
    ('Everything Bagel', 0.00, 2, False),
    ('Sesame Bagel', 0.00, 3, False),
    ('Poppy Bagel', 0.00, 4, False),
    ('Onion Bagel', 0.00, 5, False),
    ('Salt Bagel', 0.00, 6, False),
    ('Pumpernickel Bagel', 0.00, 7, False),
    ('Whole Wheat Bagel', 0.00, 8, False),
    ('Cinnamon Raisin Bagel', 0.00, 9, False),
    ('Egg Bagel', 0.00, 10, False),
    ('Garlic Bagel', 0.00, 12, False),
    ('Whole Wheat Everything Bagel', 0.00, 13, False),
    ('Whole Wheat Flatz', 0.00, 14, False),
    ('Whole Wheat Everything Flatz', 0.00, 15, False),
    ('Plain Sourdough Bagel', 0.00, 16, False),
    ('Sesame Sourdough Bagel', 0.00, 17, False),
    ('Everything Sourdough Bagel', 0.00, 18, False),
    ('Plain Sourdough Bagel Flatz', 0.00, 19, False),
    ('Everything Sourdough Bagel Flatz', 0.00, 20, False),
    ('Bialy', 0.00, 21, False),
    ('GF Plain Bagel', 1.85, 22, False),
    ('GF Everything Bagel', 1.85, 23, False),
]


# Egg style configuration for egg_sandwich
EGG_SANDWICH_EGG_STYLE_CONFIG = [
    ('Scrambled Eggs', 0.00, 1, True),
    ('Fried Eggs', 0.00, 2, False),
    ('Over Easy Eggs', 0.00, 3, False),
    ('Over Medium Eggs', 0.00, 4, False),
    ('Over Hard Eggs', 0.00, 5, False),
    ('Egg White', 2.05, 6, False),  # Substitute Egg Whites
]


# Egg quantity configuration for egg_sandwich
EGG_SANDWICH_EGG_QUANTITY_CONFIG = [
    ('2 Eggs', 0.00, 1, True),  # 2 eggs (standard)
    ('3 Eggs', 1.50, 2, False),
    ('4 Eggs', 3.00, 3, False),
]


# Extra protein configuration for fish_sandwich
FISH_SANDWICH_EXTRA_PROTEIN_CONFIG = [
    ('Bacon', 2.50, 1, False),
    ('Turkey Bacon', 2.95, 2, False),
    ('Smoked Turkey', 3.45, 3, False),
    ('Black Forest Ham', 3.45, 4, False),
    ('Corned Beef', 3.45, 5, False),
    ('Pastrami', 3.45, 6, False),
    ('Egg Salad', 2.55, 7, False),
    ('Applewood Smoked Bacon', 2.50, 8, False),
    ('Sausage', 2.75, 9, False),
    ('Sausage Patty', 2.75, 10, False),
    ('Chicken Sausage', 2.95, 11, False),
    ('Ham', 3.45, 12, False),
    ('Nova Scotia Salmon', 6.00, 13, False),
    ('Roast Beef', 3.45, 14, False),
    ("Esposito's Sausage", 2.75, 15, False),
]


# Egg style configuration for omelette
OMELETTE_EGG_STYLE_CONFIG = [
    ('Regular Eggs', 0.00, 1, True),
    ('Egg White', 1.50, 2, False),
]


# Egg quantity configuration for omelette
OMELETTE_EGG_QUANTITY_CONFIG = [
    ('3 Eggs', 0.00, 1, True),  # 3 eggs (standard)
    ('4 Eggs', 1.50, 2, False),
    ('5 Eggs', 3.00, 3, False),
    ('6 Eggs', 4.50, 4, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new egg style ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_EGG_STYLE_INGREDIENTS:
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
            print(f"Added egg_style ingredient: {name}")

    # Step 2: Add new egg quantity ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_EGG_QUANTITY_INGREDIENTS:
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
            print(f"Added egg_quantity ingredient: {name}")

    # Step 3: Link bagel.bagel_type
    bagel_id = _get_item_type_id(conn, 'bagel')
    if bagel_id:
        _create_ingredient_links(conn, bagel_id, 'bagel_type', BAGEL_TYPE_CONFIG)
        _update_attribute(conn, bagel_id, 'bagel_type', 'bagel_type')

    # Step 4: Link egg_sandwich.egg_style and egg_quantity
    egg_sandwich_id = _get_item_type_id(conn, 'egg_sandwich')
    if egg_sandwich_id:
        _create_ingredient_links(conn, egg_sandwich_id, 'egg_style', EGG_SANDWICH_EGG_STYLE_CONFIG)
        _update_attribute(conn, egg_sandwich_id, 'egg_style', 'egg_style')

        _create_ingredient_links(conn, egg_sandwich_id, 'egg_quantity', EGG_SANDWICH_EGG_QUANTITY_CONFIG)
        _update_attribute(conn, egg_sandwich_id, 'egg_quantity', 'egg_quantity')

    # Step 5: Link fish_sandwich.extra_protein
    fish_sandwich_id = _get_item_type_id(conn, 'fish_sandwich')
    if fish_sandwich_id:
        _create_ingredient_links(conn, fish_sandwich_id, 'extra_protein', FISH_SANDWICH_EXTRA_PROTEIN_CONFIG)
        _update_attribute(conn, fish_sandwich_id, 'extra_protein', 'extra_protein')

    # Step 6: Link omelette.egg_style and egg_quantity
    omelette_id = _get_item_type_id(conn, 'omelette')
    if omelette_id:
        _create_ingredient_links(conn, omelette_id, 'egg_style', OMELETTE_EGG_STYLE_CONFIG)
        _update_attribute(conn, omelette_id, 'egg_style', 'egg_style')

        _create_ingredient_links(conn, omelette_id, 'egg_quantity', OMELETTE_EGG_QUANTITY_CONFIG)
        _update_attribute(conn, omelette_id, 'egg_quantity', 'egg_quantity')


def _get_item_type_id(conn, slug: str) -> int | None:
    """Get item type ID by slug."""
    result = conn.execute(
        text("SELECT id FROM item_types WHERE slug = :slug"),
        {"slug": slug}
    )
    row = result.fetchone()
    if row:
        print(f"Found {slug} item_type_id: {row[0]}")
        return row[0]
    print(f"Warning: {slug} item type not found")
    return None


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

    print(f"Created {created} {ingredient_group} links")


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

    # Revert bagel.bagel_type
    bagel_id = _get_item_type_id(conn, 'bagel')
    if bagel_id:
        _revert_attribute(conn, bagel_id, 'bagel_type')
        _remove_links(conn, bagel_id, 'bagel_type')

    # Revert egg_sandwich attributes
    egg_sandwich_id = _get_item_type_id(conn, 'egg_sandwich')
    if egg_sandwich_id:
        _revert_attribute(conn, egg_sandwich_id, 'egg_style')
        _remove_links(conn, egg_sandwich_id, 'egg_style')
        _revert_attribute(conn, egg_sandwich_id, 'egg_quantity')
        _remove_links(conn, egg_sandwich_id, 'egg_quantity')

    # Revert fish_sandwich.extra_protein
    fish_sandwich_id = _get_item_type_id(conn, 'fish_sandwich')
    if fish_sandwich_id:
        _revert_attribute(conn, fish_sandwich_id, 'extra_protein')
        _remove_links(conn, fish_sandwich_id, 'extra_protein')

    # Revert omelette attributes
    omelette_id = _get_item_type_id(conn, 'omelette')
    if omelette_id:
        _revert_attribute(conn, omelette_id, 'egg_style')
        _remove_links(conn, omelette_id, 'egg_style')
        _revert_attribute(conn, omelette_id, 'egg_quantity')
        _remove_links(conn, omelette_id, 'egg_quantity')

    # Remove new ingredients
    for name, *_ in NEW_EGG_STYLE_INGREDIENTS + NEW_EGG_QUANTITY_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )


def _revert_attribute(conn, item_type_id: int, attr_slug: str) -> None:
    """Revert attribute to not use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = false, ingredient_group = NULL
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": attr_slug}
    )


def _remove_links(conn, item_type_id: int, ingredient_group: str) -> None:
    """Remove item_type_ingredients links."""
    conn.execute(
        text("""
            DELETE FROM item_type_ingredients
            WHERE item_type_id = :item_type_id AND ingredient_group = :group
        """),
        {"item_type_id": item_type_id, "group": ingredient_group}
    )
