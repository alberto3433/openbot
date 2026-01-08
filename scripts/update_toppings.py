"""
Update toppings/condiments based on Zucker's Extra Toppings menu.

This script:
1. Adds missing ingredients
2. Updates ingredient base_prices
3. Updates attribute_options prices
4. Adds missing attribute options for all sandwich types
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()
import os
from sqlalchemy import create_engine, text

# Toppings from the image with their prices
TOPPINGS = {
    'Butter': 0.55,
    'Avocado': 3.50,
    'Beefsteak Tomatoes': 1.00,
    'Lettuce': 0.60,
    'Red Onions': 0.75,
    'Cucumbers': 0.75,
    'Breakfast Potato Latke': 2.80,
    'Spinach': 0.85,
    'Capers': 0.75,
    'Onion, Pepper & Caper Relish': 0.85,
    'Mayo': 0.00,
    'Mustard': 0.00,
    'Ketchup': 0.00,
    'Salt': 0.00,
    'Grape Jelly': 0.55,
    'Strawberry Jelly': 0.55,
    'Pepper': 0.00,
    'Hot Sauce': 0.00,
}

# Classify into categories
CONDIMENTS = ['Mayo', 'Mustard', 'Ketchup', 'Hot Sauce', 'Salt', 'Pepper']
SPREADS = ['Grape Jelly', 'Strawberry Jelly', 'Butter']
# Rest are toppings

engine = create_engine(os.environ['DATABASE_URL'])

with engine.connect() as conn:
    print("=" * 60)
    print("STEP 1: Add missing ingredients")
    print("=" * 60)

    # Check which ingredients exist
    result = conn.execute(text("SELECT name FROM ingredients"))
    existing_ingredients = {r.name.lower() for r in result}

    # Map of ingredient names to check (handle variations)
    ingredient_name_map = {
        'butter': 'Butter',
        'avocado': 'Avocado',
        'beefsteak tomatoes': 'Beefsteak Tomatoes',
        'lettuce': 'Lettuce',
        'red onions': 'Red Onion',  # Already exists as "Red Onion"
        'red onion': 'Red Onion',
        'cucumbers': 'Cucumber',  # Already exists as "Cucumber"
        'cucumber': 'Cucumber',
        'breakfast potato latke': 'Breakfast Potato Latke',
        'spinach': 'Spinach',
        'capers': 'Capers',
        'onion, pepper & caper relish': 'Onion, Pepper & Caper Relish',
        'mayo': 'Mayo',
        'mustard': 'Mustard',
        'ketchup': 'Ketchup',
        'salt': 'Salt',
        'grape jelly': 'Grape Jelly',
        'strawberry jelly': 'Strawberry Jelly',
        'pepper': 'Black Pepper',  # Already exists as "Black Pepper"
        'black pepper': 'Black Pepper',
        'hot sauce': 'Hot Sauce',
    }

    # Add missing ingredients
    missing_ingredients = []
    for name, price in TOPPINGS.items():
        # Check various name forms
        name_lower = name.lower()
        canonical_name = ingredient_name_map.get(name_lower, name)

        if canonical_name.lower() not in existing_ingredients:
            # Determine category
            if name in CONDIMENTS:
                category = 'condiment'
            elif name in SPREADS:
                category = 'spread'
            else:
                category = 'topping'

            missing_ingredients.append((canonical_name, category, price))

    for name, category, price in missing_ingredients:
        print(f"  Adding: {name} ({category}) - ${price:.2f}")
        conn.execute(text('''
            INSERT INTO ingredients (name, category, base_price, is_available, track_inventory, unit)
            VALUES (:name, :category, :price, true, false, 'each')
        '''), {'name': name, 'category': category, 'price': price})

    if not missing_ingredients:
        print("  No missing ingredients to add")

    print()
    print("=" * 60)
    print("STEP 2: Update ingredient base_prices")
    print("=" * 60)

    # Update prices for existing ingredients
    price_updates = [
        ('Butter', 0.55),
        ('Avocado', 3.50),
        ('Beefsteak Tomatoes', 1.00),
        ('Lettuce', 0.60),
        ('Red Onion', 0.75),
        ('Cucumber', 0.75),
        ('Breakfast Potato Latke', 2.80),
        ('Spinach', 0.85),
        ('Capers', 0.75),
        ('Ketchup', 0.00),
        ('Salt', 0.00),
        ('Black Pepper', 0.00),
        ('Hot Sauce', 0.00),
        ('Mayo', 0.00),
        ('Mustard', 0.00),
    ]

    for name, price in price_updates:
        result = conn.execute(text('''
            UPDATE ingredients SET base_price = :price WHERE name = :name
        '''), {'name': name, 'price': price})
        if result.rowcount > 0:
            print(f"  Updated: {name} -> ${price:.2f}")

    print()
    print("=" * 60)
    print("STEP 3: Update attribute_options prices")
    print("=" * 60)

    # Price updates for attribute options
    # Format: (display_name pattern, new_price)
    option_price_updates = [
        ('Beefsteak Tomatoes', 1.00),
        ('Spinach', 0.85),
        ('Capers', 0.75),
        ('Butter', 0.55),
        ('Lettuce', 0.60),
        ('Red Onions', 0.75),
        ('Cucumber', 0.75),
        ('Cucumbers', 0.75),
        ('Avocado', 3.50),
        ('Breakfast Potato Latke', 2.80),
    ]

    for name, price in option_price_updates:
        # Update for all sandwich types
        result = conn.execute(text('''
            UPDATE attribute_options ao
            SET price_modifier = :price
            FROM item_type_attributes ita
            JOIN item_types it ON ita.item_type_id = it.id
            WHERE ao.item_type_attribute_id = ita.id
            AND it.slug IN ('egg_sandwich', 'deli_sandwich', 'fish_sandwich')
            AND ita.slug IN ('toppings', 'condiments', 'extras')
            AND ao.display_name = :name
        '''), {'name': name, 'price': price})
        if result.rowcount > 0:
            print(f"  Updated {result.rowcount} option(s): {name} -> ${price:.2f}")

    print()
    print("=" * 60)
    print("STEP 4: Add missing attribute options")
    print("=" * 60)

    # Get toppings attribute IDs for each sandwich type
    result = conn.execute(text('''
        SELECT it.slug as item_type, ita.id as attr_id, ita.slug as attr_slug
        FROM item_type_attributes ita
        JOIN item_types it ON ita.item_type_id = it.id
        WHERE it.slug IN ('egg_sandwich', 'deli_sandwich', 'fish_sandwich')
        AND ita.slug IN ('toppings', 'condiments')
    '''))

    attr_ids = {}
    for r in result:
        key = (r.item_type, r.attr_slug)
        attr_ids[key] = r.attr_id

    # Check if condiments exists for egg_sandwich
    if ('egg_sandwich', 'condiments') not in attr_ids:
        print("  Note: egg_sandwich doesn't have condiments attribute - adding to toppings instead")

    # New options to add
    new_options = [
        ('Onion, Pepper & Caper Relish', 'onion_pepper_caper_relish', 0.85, 'toppings'),
        ('Ketchup', 'ketchup', 0.00, 'condiments'),
        ('Salt', 'salt', 0.00, 'condiments'),
        ('Pepper', 'pepper', 0.00, 'condiments'),
        ('Grape Jelly', 'grape_jelly', 0.55, 'toppings'),
        ('Strawberry Jelly', 'strawberry_jelly', 0.55, 'toppings'),
    ]

    for item_type in ['egg_sandwich', 'deli_sandwich', 'fish_sandwich']:
        print(f"\n  {item_type}:")

        # Get existing options for this item type
        result = conn.execute(text('''
            SELECT LOWER(ao.display_name) as name
            FROM attribute_options ao
            JOIN item_type_attributes ita ON ao.item_type_attribute_id = ita.id
            JOIN item_types it ON ita.item_type_id = it.id
            WHERE it.slug = :item_type
            AND ita.slug IN ('toppings', 'condiments')
        '''), {'item_type': item_type})
        existing_options = {r.name for r in result}

        # Get max display_order
        result = conn.execute(text('''
            SELECT COALESCE(MAX(ao.display_order), 0) as max_order
            FROM attribute_options ao
            JOIN item_type_attributes ita ON ao.item_type_attribute_id = ita.id
            JOIN item_types it ON ita.item_type_id = it.id
            WHERE it.slug = :item_type
            AND ita.slug IN ('toppings', 'condiments')
        '''), {'item_type': item_type})
        max_order = result.fetchone().max_order

        for display_name, slug, price, preferred_attr in new_options:
            if display_name.lower() in existing_options:
                print(f"    Skipping (exists): {display_name}")
                continue

            # Determine which attribute to use
            attr_key = (item_type, preferred_attr)
            if attr_key not in attr_ids:
                # Fall back to toppings
                attr_key = (item_type, 'toppings')

            if attr_key not in attr_ids:
                print(f"    ERROR: No toppings/condiments attribute for {item_type}")
                continue

            attr_id = attr_ids[attr_key]
            max_order += 1

            conn.execute(text('''
                INSERT INTO attribute_options
                (item_type_attribute_id, slug, display_name, price_modifier, display_order, is_default, is_available)
                VALUES (:attr_id, :slug, :name, :price, :order, false, true)
            '''), {
                'attr_id': attr_id,
                'slug': f"{item_type}_{slug}",
                'name': display_name,
                'price': price,
                'order': max_order,
            })
            price_str = f"${price:.2f}" if price > 0 else "FREE"
            print(f"    Added: {display_name} ({price_str})")

    conn.commit()
    print()
    print("=" * 60)
    print("DONE!")
    print("=" * 60)
