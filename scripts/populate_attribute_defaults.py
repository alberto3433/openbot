"""
Populate attribute defaults for menu items based on descriptions.

This script handles:
- single_select and boolean: stored in menu_item_attribute_values
- multi_select: stored in menu_item_attribute_selections
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()
import os
from sqlalchemy import create_engine, text
from datetime import datetime, timezone

engine = create_engine(os.environ['DATABASE_URL'])

with engine.connect() as conn:
    # Get all attributes indexed by (item_type, attr_slug)
    attrs = {}
    result = conn.execute(text('''
        SELECT it.slug as item_type, ita.id as attr_id, ita.slug as attr_slug, ita.input_type
        FROM item_types it
        JOIN item_type_attributes ita ON it.id = ita.item_type_id
        WHERE it.slug IN ('egg_sandwich', 'deli_sandwich', 'omelette', 'fish_sandwich')
    '''))
    for r in result:
        key = (r.item_type, r.attr_slug)
        attrs[key] = {'id': r.attr_id, 'input_type': r.input_type}

    # Get all options indexed by (item_type, attr_slug, lower_name)
    options = {}
    result = conn.execute(text('''
        SELECT it.slug as item_type, ita.slug as attr_slug, ao.id as opt_id,
               LOWER(ao.display_name) as opt_name, ao.slug as opt_slug
        FROM item_types it
        JOIN item_type_attributes ita ON it.id = ita.item_type_id
        JOIN attribute_options ao ON ita.id = ao.item_type_attribute_id
        WHERE it.slug IN ('egg_sandwich', 'deli_sandwich', 'omelette', 'fish_sandwich')
    '''))
    for r in result:
        key = (r.item_type, r.attr_slug, r.opt_name)
        if key not in options:
            options[key] = r.opt_id
        key2 = (r.item_type, r.attr_slug, r.opt_slug)
        if key2 not in options:
            options[key2] = r.opt_id

    def find_opt(item_type, attr, name):
        name_lower = name.lower()
        key = (item_type, attr, name_lower)
        if key in options:
            return options[key]
        # Try partial match - name in option or option in name
        for k, v in options.items():
            if k[0] == item_type and k[1] == attr:
                opt_name = k[2]
                if name_lower in opt_name or opt_name in name_lower:
                    return v
        return None

    def get_attr_id(item_type, attr_slug):
        key = (item_type, attr_slug)
        return attrs.get(key, {}).get('id')

    def get_attr_type(item_type, attr_slug):
        key = (item_type, attr_slug)
        return attrs.get(key, {}).get('input_type')

    # Define the mappings: menu_item_id -> dict of attr_slug -> values
    # IMPORTANT: Use EXACT option display names from the database
    MAPPINGS = {
        # === EGG SANDWICHES ===

        # 359: The Classic BEC - "Two Eggs, Applewood Smoked Bacon, and Cheddar"
        359: {
            'item_type': 'egg_sandwich',
            'protein': ['Applewood Smoked Bacon'],
            'cheese': ['Cheddar'],
        },

        # 360: The Leo - "Smoked Nova Scotia Salmon, Eggs, and Sauteed Onions"
        360: {
            'item_type': 'egg_sandwich',
            'protein': ['Nova Scotia Salmon'],
            'toppings': ['Sauteed Onions'],
        },

        # 361: The Avocado Toast - "Crushed Avocado with Diced Tomatoes"
        361: {
            'item_type': 'egg_sandwich',
            'toppings': ['Avocado', 'Tomatoes'],
        },

        # 362: The Delancey - "Two Eggs, Corned Beef or Pastrami, Breakfast Potato Latke, Sauteed Onions, and Swiss"
        362: {
            'item_type': 'egg_sandwich',
            'protein': ['Corned Beef'],
            'cheese': ['Swiss'],
            'toppings': ['Breakfast Potato Latke', 'Sauteed Onions'],
        },

        # 363: The Health Nut - "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes"
        363: {
            'item_type': 'egg_sandwich',
            'egg_style': 'Substitute Egg Whites',
            'toppings': ['Sauteed Mushrooms', 'Spinach', 'Roasted Peppers', 'Tomatoes'],
        },

        # 386: The Lexington - "Egg Whites, Swiss, and Spinach"
        386: {
            'item_type': 'egg_sandwich',
            'egg_style': 'Substitute Egg Whites',
            'cheese': ['Swiss'],
            'toppings': ['Spinach'],
        },

        # 390: The Columbus - "Three Egg Whites, Turkey Bacon, Avocado, and Swiss Cheese"
        390: {
            'item_type': 'egg_sandwich',
            'egg_style': 'Substitute Egg Whites',
            'protein': ['Turkey Bacon'],
            'cheese': ['Swiss'],
            'toppings': ['Avocado'],
        },

        # 567: The Truffled Egg - "Two Eggs, Swiss, Truffle Cream Cheese, and Sauteed Mushrooms"
        567: {
            'item_type': 'egg_sandwich',
            'cheese': ['Swiss'],
            'spread': ['Truffle Cream Cheese'],
            'toppings': ['Sauteed Mushrooms'],
        },

        # 568: The Latke BEC - "Two Eggs, Applewood Smoked Bacon, Cheddar, and a Breakfast Potato Latke"
        568: {
            'item_type': 'egg_sandwich',
            'protein': ['Applewood Smoked Bacon'],
            'cheese': ['Cheddar'],
            'toppings': ['Breakfast Potato Latke'],
        },

        # 9839: The Pizza BEC - "Tomato Sauce, Mozzarella, Choice of Pepperoni, Bacon, Or Sausage Topped with 2 Fried Eggs"
        9839: {
            'item_type': 'egg_sandwich',
            'egg_style': 'Fried',
            'cheese': ['Fresh Mozzarella'],
            'protein': ['Bacon'],  # Default to regular bacon for pizza style
        },

        # 9840: The Mulberry - "Two eggs, esposito's sausage, green and red peppers and sauteed onions"
        9840: {
            'item_type': 'egg_sandwich',
            'protein': ['Sausage'],
            'toppings': ['Roasted Peppers', 'Sauteed Onions'],
        },

        # === DELI SANDWICHES ===

        # 529: The BLT - "Applewood Smoked Bacon, Lettuce, Beefsteak Tomatoes, and Mayo"
        529: {
            'item_type': 'deli_sandwich',
            'extra_proteins': ['Applewood Smoked Bacon'],
            'toppings': ['Lettuce', 'Beefsteak Tomatoes'],
            'condiments': ['Mayo'],
        },

        # 527: The Chelsea Club - "Chicken Salad, Cheddar, Smoked Bacon, Beefsteak Tomatoes, Lettuce, and Red Onions"
        527: {
            'item_type': 'deli_sandwich',
            'cheese': 'Cheddar',
            'extra_proteins': ['Applewood Smoked Bacon'],
            'toppings': ['Beefsteak Tomatoes', 'Lettuce', 'Red Onions'],
        },

        # 387: The Grand Central - "Grilled chicken, smoked bacon, beefsteak tomatoes, lettuce and dijon mayo"
        387: {
            'item_type': 'deli_sandwich',
            'extra_proteins': ['Applewood Smoked Bacon'],
            'toppings': ['Beefsteak Tomatoes', 'Lettuce'],
            'condiments': ['Mayo'],
        },

        # 389: The Tribeca - "Roast turkey, havarti, lettuce, beefsteak tomatoes, basil mayo"
        389: {
            'item_type': 'deli_sandwich',
            'extra_proteins': ['Smoked Turkey'],
            'cheese': 'Havarti',
            'toppings': ['Lettuce', 'Beefsteak Tomatoes'],
            'condiments': ['Mayo'],
        },

        # 367: The Reuben - "Corned Beef, Pastrami, or Roast Turkey with Sauerkraut, Swiss Cheese, and Russian Dressing"
        367: {
            'item_type': 'deli_sandwich',
            'extra_proteins': ['Corned Beef'],
            'cheese': 'Swiss',
            'condiments': ['Russian Dressing'],
        },

        # 9838: The RB Prime - "Fresh Carved Roast Beef, Cheddar, Romaine, Beefsteak Tomatoes"
        9838: {
            'item_type': 'deli_sandwich',
            'extra_proteins': ['Roast Beef'],
            'cheese': 'Cheddar',
            'toppings': ['Lettuce', 'Beefsteak Tomatoes'],
        },

        # 9841: The Tuna Melt - "tuna, melted swiss"
        9841: {
            'item_type': 'deli_sandwich',
            'cheese': 'Swiss',
            'toasted': True,
        },

        # === FISH SANDWICHES ===

        # 365: The Traditional - "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers"
        365: {
            'item_type': 'fish_sandwich',
            'fish': 'Nova Scotia Salmon',
            'spread': 'Plain Cream Cheese',
            'extras': ['Beefsteak Tomatoes', 'Red Onion', 'Capers'],
        },

        # 457: The Flatiron - "Everything-seeded Salmon with Scallion Cream Cheese and Fresh Avocado"
        457: {
            'item_type': 'fish_sandwich',
            'fish': 'Everything Seeded Salmon',
            'spread': 'Scallion Cream Cheese',
            'extras': ['Avocado'],
        },

        # 458: The Alton Brown - "Smoked Trout, Plain Cream Cheese, Avocado, Horseradish and Onion Pepper & Caper Relish"
        458: {
            'item_type': 'fish_sandwich',
            'fish': 'Smoked Trout',
            'spread': 'Plain Cream Cheese',
            'extras': ['Avocado Horseradish', 'Capers'],
        },

        # 459: The Max Zucker - "Smoked Whitefish Salad with Beefsteak Tomatoes and Red Onions"
        459: {
            'item_type': 'fish_sandwich',
            'fish': 'Whitefish Salad',
            'extras': ['Beefsteak Tomatoes', 'Red Onion'],
        },

        # 9843: Sweet & Spicy Traditional - "Nova Scotia salmon, beefsteak tomatoes, red onions, and capers"
        9843: {
            'item_type': 'fish_sandwich',
            'fish': 'Nova Scotia Salmon',
            'extras': ['Beefsteak Tomatoes', 'Red Onion', 'Capers'],
        },

        # 9844: The Flatiron Traditional - "Everything seeded salmon, scallion, cream cheese and fresh avocado"
        9844: {
            'item_type': 'fish_sandwich',
            'fish': 'Everything Seeded Salmon',
            'spread': 'Scallion Cream Cheese',
            'extras': ['Avocado'],
        },

        # === OMELETTES ===

        # 381: The Chipotle Egg Omelette - "pepper jack, chipotle cream cheese, avocado and pico de gallo"
        381: {
            'item_type': 'omelette',
            'cheese': ['Pepper Jack'],
            'spread': 'Chipotle Cream Cheese',
            'extras': ['Avocado', 'Pico de Gallo'],
        },

        # 519: The Truffled Egg Omelette
        519: {
            'item_type': 'omelette',
            'cheese': ['Swiss'],
            'spread': 'Truffle Cream Cheese',
            'extras': ['Sautéed Mushrooms'],
        },

        # 520: The Lexington Omelette
        520: {
            'item_type': 'omelette',
            'egg_style': 'Egg White',
            'cheese': ['Swiss'],
            'veggies': ['Spinach'],
        },

        # 522: The Health Nut Omelette - "Three Egg Whites with Mushrooms, Spinach, Green & Red Peppers, and Tomatoes"
        522: {
            'item_type': 'omelette',
            'egg_style': 'Egg White',
            'veggies': ['Mushrooms', 'Spinach', 'Peppers', 'Tomatoes'],
        },

        # 524: The Delancey Omelette - "corned beef, potato latke, sauteed onions and Swiss cheese"
        524: {
            'item_type': 'omelette',
            'protein': ['Corned Beef'],
            'cheese': ['Swiss'],
            'extras': ['Potato Latke', 'Sautéed Onions'],
        },

        # 525: The Mulberry Omelette - "Espositos Sausage, Green & Red Peppers, and Sauteed Onions"
        525: {
            'item_type': 'omelette',
            'protein': ['Esposito'],
            'veggies': ['Peppers'],
            'extras': ['Sautéed Onions'],
        },

        # 526: Bacon and Cheddar Omelette
        526: {
            'item_type': 'omelette',
            'protein': ['Applewood Smoked Bacon'],
            'cheese': ['Cheddar'],
        },
    }

    # Clear existing attribute values for these items
    item_ids = list(MAPPINGS.keys())
    print(f'Clearing existing attributes for {len(item_ids)} menu items...')
    conn.execute(text('''
        DELETE FROM menu_item_attribute_values
        WHERE menu_item_id = ANY(:ids)
    '''), {'ids': item_ids})
    conn.execute(text('''
        DELETE FROM menu_item_attribute_selections
        WHERE menu_item_id = ANY(:ids)
    '''), {'ids': item_ids})

    # Insert new values
    value_inserts = []  # For single_select, boolean, text
    selection_inserts = []  # For multi_select
    now = datetime.now(timezone.utc)

    for menu_item_id, mapping in MAPPINGS.items():
        item_type = mapping['item_type']

        for attr_slug, values in mapping.items():
            if attr_slug == 'item_type':
                continue

            attr_id = get_attr_id(item_type, attr_slug)
            attr_type = get_attr_type(item_type, attr_slug)
            if not attr_id:
                print(f'  WARNING: Attribute {item_type}.{attr_slug} not found')
                continue

            # Handle boolean
            if isinstance(values, bool):
                value_inserts.append({
                    'menu_item_id': menu_item_id,
                    'attribute_id': attr_id,
                    'option_id': None,
                    'value_boolean': values,
                    'still_ask': False,
                    'created_at': now,
                    'updated_at': now,
                })
            # Handle single_select (string)
            elif isinstance(values, str):
                opt_id = find_opt(item_type, attr_slug, values)
                if opt_id:
                    value_inserts.append({
                        'menu_item_id': menu_item_id,
                        'attribute_id': attr_id,
                        'option_id': opt_id,
                        'value_boolean': None,
                        'still_ask': False,
                        'created_at': now,
                        'updated_at': now,
                    })
                else:
                    print(f'  WARNING: Option {item_type}.{attr_slug}="{values}" not found for item {menu_item_id}')
            # Handle multi_select (list) - uses selections table
            elif isinstance(values, list):
                # For multi_select, we need to insert into selections table
                # AND create a placeholder row in values table (for still_ask tracking)
                if attr_type == 'multi_select':
                    # Create placeholder value row
                    value_inserts.append({
                        'menu_item_id': menu_item_id,
                        'attribute_id': attr_id,
                        'option_id': None,
                        'value_boolean': None,
                        'still_ask': False,
                        'created_at': now,
                        'updated_at': now,
                    })
                    # Add selections
                    for val in values:
                        opt_id = find_opt(item_type, attr_slug, val)
                        if opt_id:
                            selection_inserts.append({
                                'menu_item_id': menu_item_id,
                                'attribute_id': attr_id,
                                'option_id': opt_id,
                                'created_at': now,
                            })
                        else:
                            print(f'  WARNING: Option {item_type}.{attr_slug}="{val}" not found for item {menu_item_id}')
                else:
                    # It's a list but attribute is not multi_select - treat first item as single select
                    opt_id = find_opt(item_type, attr_slug, values[0])
                    if opt_id:
                        value_inserts.append({
                            'menu_item_id': menu_item_id,
                            'attribute_id': attr_id,
                            'option_id': opt_id,
                            'value_boolean': None,
                            'still_ask': False,
                            'created_at': now,
                            'updated_at': now,
                        })
                    else:
                        print(f'  WARNING: Option {item_type}.{attr_slug}="{values[0]}" not found for item {menu_item_id}')

    # Insert values
    print(f'\nInserting {len(value_inserts)} attribute values...')
    for ins in value_inserts:
        conn.execute(text('''
            INSERT INTO menu_item_attribute_values
            (menu_item_id, attribute_id, option_id, value_boolean, still_ask, created_at, updated_at)
            VALUES (:menu_item_id, :attribute_id, :option_id, :value_boolean, :still_ask, :created_at, :updated_at)
        '''), ins)

    # Insert selections
    print(f'Inserting {len(selection_inserts)} attribute selections...')
    for ins in selection_inserts:
        conn.execute(text('''
            INSERT INTO menu_item_attribute_selections
            (menu_item_id, attribute_id, option_id, created_at)
            VALUES (:menu_item_id, :attribute_id, :option_id, :created_at)
        '''), ins)

    conn.commit()
    print('Done!')

    # Verify - count values
    result = conn.execute(text('''
        SELECT mi.name, COUNT(*) as attr_count
        FROM menu_item_attribute_values miav
        JOIN menu_items mi ON miav.menu_item_id = mi.id
        WHERE miav.menu_item_id = ANY(:ids)
        GROUP BY mi.name
        ORDER BY mi.name
    '''), {'ids': item_ids})
    print('\n=== ATTRIBUTE VALUES ===')
    for r in result:
        print(f'  {r.name}: {r.attr_count} attributes')

    # Verify - count selections
    result = conn.execute(text('''
        SELECT mi.name, COUNT(*) as sel_count
        FROM menu_item_attribute_selections mias
        JOIN menu_items mi ON mias.menu_item_id = mi.id
        WHERE mias.menu_item_id = ANY(:ids)
        GROUP BY mi.name
        ORDER BY mi.name
    '''), {'ids': item_ids})
    print('\n=== ATTRIBUTE SELECTIONS (multi-select) ===')
    for r in result:
        print(f'  {r.name}: {r.sel_count} selections')
