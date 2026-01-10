"""Sync bagel attributes to match deli_sandwich exactly

Revision ID: m7n8o9p0q1r3
Revises: l6m7n8o9p0q2
Create Date: 2026-01-08

This migration makes bagel item type attributes match deli_sandwich exactly:

1. Rename bagel_type → bread (change slug, display_name, ingredient_group)
2. Update toasted to be optional (is_required=False, allow_none=True)
3. Add scooped attribute (boolean, optional, ask=False)
4. Update spread to not ask in conversation (ask_in_conversation=False)
5. Add add_egg attribute with 6 egg options at $2.05 each
6. Update cheese to single_select and ask=True, sync options/prices
7. Update extra_protein: ask=True, ingredient_group="extra_protein", sync options
8. Rename topping → toppings, ask=True, sync options/prices
9. Add condiments attribute with ingredient options
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = 'm7n8o9p0q1r3'
down_revision: Union[str, Sequence[str], None] = 'l6m7n8o9p0q2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Egg options (same as deli_sandwich)
EGG_OPTIONS = [
    ('scrambled_egg', 'Scrambled Egg', 1),
    ('fried_egg_sunny_side_up', 'Fried Egg (Sunny Side Up)', 2),
    ('over_easy_egg', 'Over Easy Egg', 3),
    ('over_medium_egg', 'Over Medium Egg', 4),
    ('over_hard_egg', 'Over Hard Egg', 5),
    ('egg_whites_2', 'Egg Whites (2)', 6),
]
EGG_UPCHARGE = 2.05

# Condiment ingredients (same as deli_sandwich)
CONDIMENT_INGREDIENTS = [
    ('Mayo', 0.00, 1),
    ('Mustard', 0.00, 2),
    ('Russian Dressing', 0.00, 3),
    ('Olive Oil', 0.00, 4),
    ('Hot Sauce', 0.00, 5),
]

# Additional bread options from deli_sandwich that bagel doesn't have
ADDITIONAL_BREAD_OPTIONS = [
    ('Rainbow Bagel', 0.00, 11),
    ('French Toast Bagel', 0.00, 12),
    ('Sun Dried Tomato Bagel', 0.00, 13),
    ('Multigrain Bagel', 0.00, 14),
    ('Asiago Bagel', 0.00, 16),
    ('Jalapeno Cheddar Bagel', 0.00, 17),
    ('Flagel', 0.00, 19),
    ('Croissant', 1.80, 24),
    ('Wrap', 0.00, 25),
    ('Gluten Free Wrap', 1.00, 26),
    ('No Bread', 2.00, 27),
    # Additional GF bagels from deli_sandwich
    ('Gluten Free Sesame Bagel', 1.85, 22),
    ('Gluten Free Cinnamon Raisin Bagel', 1.85, 23),
]

# Additional cheese options from deli_sandwich
ADDITIONAL_CHEESE_OPTIONS = [
    ('Pepper Jack Cheese', 1.50, 6),
    ('Havarti Cheese', 1.50, 7),
    ('Fresh Mozzarella Cheese', 1.50, 8),
]

# Extra protein options to match deli_sandwich
EXTRA_PROTEIN_OPTIONS = [
    ('Bacon', 2.50, 1),
    ('Turkey Bacon', 2.95, 3),
    ('Chicken Sausage', 2.95, 6),
    ('Ham', 2.50, 7),
    ('Corned Beef', 3.45, 8),
    ('Pastrami', 3.45, 9),
    ('Roast Beef', 3.45, 10),
    ('Smoked Turkey', 3.45, 11),
    ('Egg Salad', 0.00, 12),
]

# Topping options to match deli_sandwich
TOPPING_OPTIONS = [
    ('Lettuce', 0.60, 1),
    ('Tomato', 1.00, 2),
    ('Onion', 0.75, 3),
    ('Red Onion', 0.75, 4),
    ('Cucumber', 0.75, 5),
    ('Pickles', 0.75, 6),
    ('Spinach', 1.00, 7),
    ('Capers', 1.00, 8),
    ('Roasted Peppers', 1.00, 9),
    ('Jalapeno', 0.75, 10),
    ('Sauteed Mushrooms', 1.50, 11),
    ('Sauteed Onions', 1.00, 12),
    ('Hash Browns', 2.50, 13),
    ('Breakfast Potato Latke', 2.80, 14),
    ('Avocado', 3.50, 15),
]


def upgrade() -> None:
    """Sync bagel attributes to match deli_sandwich."""
    conn = op.get_bind()

    # Get bagel item type ID
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if not row:
        print("Warning: bagel item type not found, skipping")
        return
    bagel_id = row[0]
    print(f"Found bagel item_type_id: {bagel_id}")

    # 1. Rename bagel_type → bread
    print("\n1. Renaming bagel_type to bread...")
    conn.execute(text("""
        UPDATE item_type_attributes
        SET slug = 'bread', display_name = 'Bread', ingredient_group = 'bread'
        WHERE item_type_id = :bagel_id AND slug = 'bagel_type'
    """), {'bagel_id': bagel_id})

    # Update item_type_ingredients group from bagel_type to bread
    conn.execute(text("""
        UPDATE item_type_ingredients
        SET ingredient_group = 'bread'
        WHERE item_type_id = :bagel_id AND ingredient_group = 'bagel_type'
    """), {'bagel_id': bagel_id})
    print("  - Renamed bagel_type to bread")

    # Add additional bread options from deli_sandwich
    for ing_name, price, display_order in ADDITIONAL_BREAD_OPTIONS:
        result = conn.execute(text("SELECT id FROM ingredients WHERE name = :name"), {"name": ing_name})
        ing_row = result.fetchone()
        if not ing_row:
            print(f"  - Warning: Ingredient '{ing_name}' not found, skipping")
            continue
        ingredient_id = ing_row[0]

        # Check if already exists
        result = conn.execute(text("""
            SELECT id FROM item_type_ingredients
            WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'bread'
        """), {"item_type_id": bagel_id, "ingredient_id": ingredient_id})
        if not result.fetchone():
            conn.execute(text("""
                INSERT INTO item_type_ingredients
                (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                VALUES (:item_type_id, :ingredient_id, 'bread', :price, :order, false, true)
            """), {
                "item_type_id": bagel_id,
                "ingredient_id": ingredient_id,
                "price": price,
                "order": display_order,
            })
            print(f"  - Added bread option: {ing_name}")

    # 2. Update toasted to be optional
    print("\n2. Updating toasted to be optional...")
    conn.execute(text("""
        UPDATE item_type_attributes
        SET is_required = FALSE, allow_none = TRUE
        WHERE item_type_id = :bagel_id AND slug = 'toasted'
    """), {'bagel_id': bagel_id})
    print("  - toasted is now optional")

    # 3. Add scooped attribute
    print("\n3. Adding scooped attribute...")
    # Get toasted display_order
    result = conn.execute(text("""
        SELECT display_order FROM item_type_attributes
        WHERE item_type_id = :bagel_id AND slug = 'toasted'
    """), {'bagel_id': bagel_id})
    toasted_row = result.fetchone()
    scooped_order = (toasted_row[0] + 1) if toasted_row else 3

    # Shift attributes to make room
    conn.execute(text("""
        UPDATE item_type_attributes
        SET display_order = display_order + 1
        WHERE item_type_id = :bagel_id AND display_order >= :scooped_order AND slug != 'toasted'
    """), {'bagel_id': bagel_id, 'scooped_order': scooped_order})

    # Check if scooped already exists
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :bagel_id AND slug = 'scooped'
    """), {'bagel_id': bagel_id})
    if not result.fetchone():
        conn.execute(text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type,
                is_required, allow_none, ask_in_conversation,
                loads_from_ingredients, display_order
            ) VALUES (
                :bagel_id, 'scooped', 'Scooped', 'boolean',
                FALSE, TRUE, FALSE,
                FALSE, :display_order
            )
        """), {'bagel_id': bagel_id, 'display_order': scooped_order})
        print(f"  - Added scooped attribute at display_order={scooped_order}")
    else:
        print("  - scooped attribute already exists")

    # 4. Update spread to not ask in conversation
    print("\n4. Updating spread to not ask in conversation...")
    conn.execute(text("""
        UPDATE item_type_attributes
        SET ask_in_conversation = FALSE
        WHERE item_type_id = :bagel_id AND slug = 'spread'
    """), {'bagel_id': bagel_id})
    # Also remove default from spread options (deli_sandwich has no default)
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :bagel_id AND slug = 'spread'
    """), {'bagel_id': bagel_id})
    spread_attr = result.fetchone()
    if spread_attr:
        conn.execute(text("""
            UPDATE item_type_ingredients
            SET is_default = FALSE
            WHERE item_type_id = :bagel_id AND ingredient_group = 'spread'
        """), {'bagel_id': bagel_id})
    print("  - spread no longer asks in conversation, removed default")

    # 5. Add add_egg attribute
    print("\n5. Adding add_egg attribute...")
    # Get max display_order for attributes
    result = conn.execute(text("""
        SELECT COALESCE(MAX(display_order), 0) FROM item_type_attributes
        WHERE item_type_id = :bagel_id
    """), {'bagel_id': bagel_id})
    max_order = result.fetchone()[0]

    # Check if add_egg already exists
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :bagel_id AND slug = 'add_egg'
    """), {'bagel_id': bagel_id})
    existing_egg = result.fetchone()

    if not existing_egg:
        # Find where to insert (after spread in deli_sandwich it's position 5)
        result = conn.execute(text("""
            SELECT display_order FROM item_type_attributes
            WHERE item_type_id = :bagel_id AND slug = 'spread'
        """), {'bagel_id': bagel_id})
        spread_row = result.fetchone()
        add_egg_order = (spread_row[0] + 1) if spread_row else 5

        # Shift attributes to make room
        conn.execute(text("""
            UPDATE item_type_attributes
            SET display_order = display_order + 1
            WHERE item_type_id = :bagel_id AND display_order >= :egg_order AND slug NOT IN ('bread', 'toasted', 'scooped', 'spread')
        """), {'bagel_id': bagel_id, 'egg_order': add_egg_order})

        conn.execute(text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type,
                is_required, allow_none, ask_in_conversation,
                loads_from_ingredients, display_order
            ) VALUES (
                :bagel_id, 'add_egg', 'Add Egg', 'single_select',
                FALSE, TRUE, FALSE,
                FALSE, :display_order
            )
        """), {'bagel_id': bagel_id, 'display_order': add_egg_order})
        print(f"  - Added add_egg attribute at display_order={add_egg_order}")

        # Get the new attribute ID
        result = conn.execute(text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :bagel_id AND slug = 'add_egg'
        """), {'bagel_id': bagel_id})
        add_egg_attr_id = result.fetchone()[0]

        # Add egg options
        for slug, display_name, display_order in EGG_OPTIONS:
            conn.execute(text("""
                INSERT INTO attribute_options (
                    item_type_attribute_id, slug, display_name,
                    price_modifier, display_order, is_available, is_default
                ) VALUES (
                    :attr_id, :slug, :display_name,
                    :price, :display_order, TRUE, FALSE
                )
            """), {
                'attr_id': add_egg_attr_id,
                'slug': slug,
                'display_name': display_name,
                'price': EGG_UPCHARGE,
                'display_order': display_order,
            })
            print(f"  - Added egg option: {display_name}")
    else:
        print("  - add_egg attribute already exists")

    # 6. Update cheese to single_select, ask=True, and sync options/prices
    print("\n6. Updating cheese attribute...")
    conn.execute(text("""
        UPDATE item_type_attributes
        SET input_type = 'single_select', ask_in_conversation = TRUE
        WHERE item_type_id = :bagel_id AND slug = 'cheese'
    """), {'bagel_id': bagel_id})
    print("  - cheese is now single_select with ask=True")

    # Update cheese prices to match deli_sandwich ($1.50)
    conn.execute(text("""
        UPDATE item_type_ingredients
        SET price_modifier = 1.50
        WHERE item_type_id = :bagel_id AND ingredient_group = 'cheese'
    """), {'bagel_id': bagel_id})
    print("  - Updated cheese prices to $1.50")

    # Add additional cheese options
    for ing_name, price, display_order in ADDITIONAL_CHEESE_OPTIONS:
        result = conn.execute(text("SELECT id FROM ingredients WHERE name = :name"), {"name": ing_name})
        ing_row = result.fetchone()
        if not ing_row:
            print(f"  - Warning: Ingredient '{ing_name}' not found, skipping")
            continue
        ingredient_id = ing_row[0]

        result = conn.execute(text("""
            SELECT id FROM item_type_ingredients
            WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'cheese'
        """), {"item_type_id": bagel_id, "ingredient_id": ingredient_id})
        if not result.fetchone():
            conn.execute(text("""
                INSERT INTO item_type_ingredients
                (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                VALUES (:item_type_id, :ingredient_id, 'cheese', :price, :order, false, true)
            """), {
                "item_type_id": bagel_id,
                "ingredient_id": ingredient_id,
                "price": price,
                "order": display_order,
            })
            print(f"  - Added cheese option: {ing_name}")

    # 7. Update extra_protein: ask=True, ingredient_group="extra_protein", sync options
    print("\n7. Updating extra_protein attribute...")
    conn.execute(text("""
        UPDATE item_type_attributes
        SET ask_in_conversation = TRUE, ingredient_group = 'extra_protein'
        WHERE item_type_id = :bagel_id AND slug = 'extra_protein'
    """), {'bagel_id': bagel_id})

    # Update ingredient_group in item_type_ingredients from 'protein' to 'extra_protein'
    conn.execute(text("""
        UPDATE item_type_ingredients
        SET ingredient_group = 'extra_protein'
        WHERE item_type_id = :bagel_id AND ingredient_group = 'protein'
    """), {'bagel_id': bagel_id})
    print("  - Updated extra_protein ask=True and ingredient_group")

    # Clear existing protein options and add deli_sandwich options
    conn.execute(text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :bagel_id AND ingredient_group = 'extra_protein'
    """), {'bagel_id': bagel_id})

    for ing_name, price, display_order in EXTRA_PROTEIN_OPTIONS:
        result = conn.execute(text("SELECT id FROM ingredients WHERE name = :name"), {"name": ing_name})
        ing_row = result.fetchone()
        if not ing_row:
            print(f"  - Warning: Ingredient '{ing_name}' not found, skipping")
            continue
        ingredient_id = ing_row[0]

        conn.execute(text("""
            INSERT INTO item_type_ingredients
            (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
            VALUES (:item_type_id, :ingredient_id, 'extra_protein', :price, :order, false, true)
        """), {
            "item_type_id": bagel_id,
            "ingredient_id": ingredient_id,
            "price": price,
            "order": display_order,
        })
        print(f"  - Added extra_protein option: {ing_name}")

    # 8. Rename topping -> toppings, ask=True, sync options
    print("\n8. Updating topping -> toppings attribute...")
    conn.execute(text("""
        UPDATE item_type_attributes
        SET slug = 'toppings', display_name = 'Toppings', ask_in_conversation = TRUE
        WHERE item_type_id = :bagel_id AND slug = 'topping'
    """), {'bagel_id': bagel_id})
    print("  - Renamed topping to toppings with ask=True")

    # Clear existing topping options and add deli_sandwich options
    conn.execute(text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :bagel_id AND ingredient_group = 'topping'
    """), {'bagel_id': bagel_id})

    for ing_name, price, display_order in TOPPING_OPTIONS:
        result = conn.execute(text("SELECT id FROM ingredients WHERE name = :name"), {"name": ing_name})
        ing_row = result.fetchone()
        if not ing_row:
            print(f"  - Warning: Ingredient '{ing_name}' not found, skipping")
            continue
        ingredient_id = ing_row[0]

        conn.execute(text("""
            INSERT INTO item_type_ingredients
            (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
            VALUES (:item_type_id, :ingredient_id, 'topping', :price, :order, false, true)
        """), {
            "item_type_id": bagel_id,
            "ingredient_id": ingredient_id,
            "price": price,
            "order": display_order,
        })
        print(f"  - Added topping option: {ing_name}")

    # 9. Add condiments attribute
    print("\n9. Adding condiments attribute...")
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :bagel_id AND slug = 'condiments'
    """), {'bagel_id': bagel_id})
    if not result.fetchone():
        # Get max display_order
        result = conn.execute(text("""
            SELECT COALESCE(MAX(display_order), 0) FROM item_type_attributes
            WHERE item_type_id = :bagel_id
        """), {'bagel_id': bagel_id})
        max_order = result.fetchone()[0]

        conn.execute(text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type,
                is_required, allow_none, ask_in_conversation,
                loads_from_ingredients, ingredient_group, display_order
            ) VALUES (
                :bagel_id, 'condiments', 'Condiments', 'multi_select',
                FALSE, TRUE, TRUE,
                TRUE, 'condiment', :display_order
            )
        """), {'bagel_id': bagel_id, 'display_order': max_order + 1})
        print(f"  - Added condiments attribute at display_order={max_order + 1}")

        # Add condiment ingredient links
        for ing_name, price, display_order in CONDIMENT_INGREDIENTS:
            result = conn.execute(text("SELECT id FROM ingredients WHERE name = :name"), {"name": ing_name})
            ing_row = result.fetchone()
            if not ing_row:
                print(f"  - Warning: Ingredient '{ing_name}' not found, skipping")
                continue
            ingredient_id = ing_row[0]

            conn.execute(text("""
                INSERT INTO item_type_ingredients
                (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                VALUES (:item_type_id, :ingredient_id, 'condiment', :price, :order, false, true)
            """), {
                "item_type_id": bagel_id,
                "ingredient_id": ingredient_id,
                "price": price,
                "order": display_order,
            })
            print(f"  - Added condiment option: {ing_name}")
    else:
        print("  - condiments attribute already exists")

    print("\nDone - Bagel attributes now match deli_sandwich!")


def downgrade() -> None:
    """Revert bagel attributes to original state."""
    conn = op.get_bind()

    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if not row:
        return
    bagel_id = row[0]

    # 9. Remove condiments
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes WHERE item_type_id = :bagel_id AND slug = 'condiments'
    """), {'bagel_id': bagel_id})
    if result.fetchone():
        conn.execute(text("""
            DELETE FROM item_type_ingredients WHERE item_type_id = :bagel_id AND ingredient_group = 'condiment'
        """), {'bagel_id': bagel_id})
        conn.execute(text("""
            DELETE FROM item_type_attributes WHERE item_type_id = :bagel_id AND slug = 'condiments'
        """), {'bagel_id': bagel_id})

    # 8. Rename toppings back to topping
    conn.execute(text("""
        UPDATE item_type_attributes
        SET slug = 'topping', display_name = 'Topping', ask_in_conversation = FALSE
        WHERE item_type_id = :bagel_id AND slug = 'toppings'
    """), {'bagel_id': bagel_id})

    # 7. Revert extra_protein
    conn.execute(text("""
        UPDATE item_type_attributes
        SET ask_in_conversation = FALSE, ingredient_group = 'protein'
        WHERE item_type_id = :bagel_id AND slug = 'extra_protein'
    """), {'bagel_id': bagel_id})
    conn.execute(text("""
        UPDATE item_type_ingredients
        SET ingredient_group = 'protein'
        WHERE item_type_id = :bagel_id AND ingredient_group = 'extra_protein'
    """), {'bagel_id': bagel_id})

    # 6. Revert cheese
    conn.execute(text("""
        UPDATE item_type_attributes
        SET input_type = 'multi_select', ask_in_conversation = FALSE
        WHERE item_type_id = :bagel_id AND slug = 'cheese'
    """), {'bagel_id': bagel_id})
    conn.execute(text("""
        UPDATE item_type_ingredients SET price_modifier = 0.75
        WHERE item_type_id = :bagel_id AND ingredient_group = 'cheese'
    """), {'bagel_id': bagel_id})

    # 5. Remove add_egg
    result = conn.execute(text("""
        SELECT id FROM item_type_attributes WHERE item_type_id = :bagel_id AND slug = 'add_egg'
    """), {'bagel_id': bagel_id})
    attr_row = result.fetchone()
    if attr_row:
        conn.execute(text("DELETE FROM attribute_options WHERE item_type_attribute_id = :attr_id"), {'attr_id': attr_row[0]})
        conn.execute(text("DELETE FROM item_type_attributes WHERE id = :attr_id"), {'attr_id': attr_row[0]})

    # 4. Revert spread
    conn.execute(text("""
        UPDATE item_type_attributes SET ask_in_conversation = TRUE
        WHERE item_type_id = :bagel_id AND slug = 'spread'
    """), {'bagel_id': bagel_id})

    # 3. Remove scooped
    conn.execute(text("""
        DELETE FROM item_type_attributes WHERE item_type_id = :bagel_id AND slug = 'scooped'
    """), {'bagel_id': bagel_id})

    # 2. Revert toasted
    conn.execute(text("""
        UPDATE item_type_attributes SET is_required = TRUE, allow_none = FALSE
        WHERE item_type_id = :bagel_id AND slug = 'toasted'
    """), {'bagel_id': bagel_id})

    # 1. Rename bread back to bagel_type
    conn.execute(text("""
        UPDATE item_type_attributes
        SET slug = 'bagel_type', display_name = 'Bagel Type', ingredient_group = 'bagel_type'
        WHERE item_type_id = :bagel_id AND slug = 'bread'
    """), {'bagel_id': bagel_id})
    conn.execute(text("""
        UPDATE item_type_ingredients
        SET ingredient_group = 'bagel_type'
        WHERE item_type_id = :bagel_id AND ingredient_group = 'bread'
    """), {'bagel_id': bagel_id})

    print("Reverted bagel attributes to original state")
