"""Run the consolidate_to_global_attributes migration directly with psycopg2.

This bypasses SQLAlchemy/alembic since psycopg2 works but SQLAlchemy import hangs.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import psycopg2
from urllib.parse import urlparse, parse_qs

url = os.getenv('DATABASE_URL')
if not url:
    print("ERROR: DATABASE_URL not set")
    exit(1)

# Parse connection params
parsed = urlparse(url)
params = {
    'host': parsed.hostname,
    'port': parsed.port or 5432,
    'user': parsed.username,
    'password': parsed.password,
    'dbname': parsed.path[1:],
    'connect_timeout': 30,
}
query = parse_qs(parsed.query)
if 'sslmode' in query:
    params['sslmode'] = query['sslmode'][0]

print("Connecting to database...")
conn = psycopg2.connect(**params)
conn.autocommit = False
cur = conn.cursor()

# Check current alembic version
cur.execute("SELECT version_num FROM alembic_version")
current = cur.fetchone()
print(f"Current alembic version: {current[0] if current else 'None'}")

# Check if migration already applied
if current and current[0] == 'consolidate_global_attrs':
    print("Migration already applied!")
    conn.close()
    exit(0)

# Check if we're at the expected predecessor
if current and current[0] != 'fix_syrup_price_01':
    print(f"WARNING: Expected version 'fix_syrup_price_01', got '{current[0]}'")
    print("Proceeding anyway...")

try:
    # ==========================================================================
    # PHASE 2: Create missing GlobalAttributes
    # ==========================================================================
    print("\nPhase 2: Creating missing GlobalAttributes...")

    missing_global_attrs = [
        ('condiments', 'Condiments', 'multi_select', 'Condiments like ketchup, mustard, mayo'),
        ('filling', 'Omelette Filling', 'multi_select', 'Fillings for omelettes'),
        ('proteins', 'Proteins', 'multi_select', 'Protein additions'),
        ('veggies', 'Veggies', 'multi_select', 'Vegetable additions'),
    ]

    for slug, display_name, input_type, description in missing_global_attrs:
        cur.execute("SELECT id FROM global_attributes WHERE slug = %s", (slug,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO global_attributes (slug, display_name, input_type, description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
            """, (slug, display_name, input_type, description))
            print(f"  Created GlobalAttribute: {slug}")
        else:
            print(f"  GlobalAttribute already exists: {slug}")

    # ==========================================================================
    # PHASE 3: Create missing ItemTypeGlobalAttribute links
    # ==========================================================================
    print("\nPhase 3: Creating missing ItemTypeGlobalAttribute links...")

    # Get all item type IDs
    cur.execute("SELECT id, slug FROM item_types")
    item_types = {row[1]: row[0] for row in cur.fetchall()}

    # Get all global attribute IDs
    cur.execute("SELECT id, slug FROM global_attributes")
    global_attrs = {row[1]: row[0] for row in cur.fetchall()}

    # Links to create: (item_type_slug, global_attr_slug, ask, required, question, display_order)
    links_to_create = [
        ('bagel', 'condiments', False, False, None, 100),
        ('deli_sandwich', 'condiments', False, False, None, 100),
        ('fish_sandwich', 'condiments', False, False, None, 100),
        ('omelette', 'filling', True, False, 'What would you like in your omelette?', 4),
        ('omelette', 'veggies', True, False, 'Any vegetables?', 10),
        ('spread_sandwich', 'proteins', False, False, None, 50),
        ('spread_sandwich', 'condiments', False, False, None, 100),
    ]

    for item_type_slug, attr_slug, ask, required, question, display_order in links_to_create:
        item_type_id = item_types.get(item_type_slug)
        global_attr_id = global_attrs.get(attr_slug)

        if not item_type_id:
            print(f"  WARNING: Item type not found: {item_type_slug}")
            continue
        if not global_attr_id:
            print(f"  WARNING: Global attribute not found: {attr_slug}")
            continue

        cur.execute("""
            SELECT id FROM item_type_global_attributes
            WHERE item_type_id = %s AND global_attribute_id = %s
        """, (item_type_id, global_attr_id))

        if not cur.fetchone():
            cur.execute("""
                INSERT INTO item_type_global_attributes
                (item_type_id, global_attribute_id, ask_in_conversation, is_required,
                 question_text, display_order, allow_none, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, true, NOW(), NOW())
            """, (item_type_id, global_attr_id, ask, required, question, display_order))
            print(f"  Created link: {item_type_slug} -> {attr_slug}")
        else:
            print(f"  Link already exists: {item_type_slug} -> {attr_slug}")

    # ==========================================================================
    # PHASE 4: Fix configuration conflicts
    # ==========================================================================
    print("\nPhase 4: Fixing configuration conflicts...")

    # Get sized_beverage and global attr IDs
    sized_bev_id = item_types.get('sized_beverage')
    size_attr_id = global_attrs.get('size')
    style_attr_id = global_attrs.get('style')
    temp_attr_id = global_attrs.get('temperature')

    # Fix sized_beverage.size
    if sized_bev_id and size_attr_id:
        cur.execute("""
            UPDATE item_type_global_attributes
            SET ask_in_conversation = true, question_text = 'What size?'
            WHERE item_type_id = %s AND global_attribute_id = %s
        """, (sized_bev_id, size_attr_id))
        print("  Fixed: sized_beverage.size -> ask=True")

    # Fix sized_beverage.style
    if sized_bev_id and style_attr_id:
        cur.execute("""
            UPDATE item_type_global_attributes
            SET ask_in_conversation = true
            WHERE item_type_id = %s AND global_attribute_id = %s
        """, (sized_bev_id, style_attr_id))
        print("  Fixed: sized_beverage.style -> ask=True")

    # Fix sized_beverage.temperature
    if sized_bev_id and temp_attr_id:
        cur.execute("""
            SELECT id FROM item_type_global_attributes
            WHERE item_type_id = %s AND global_attribute_id = %s
        """, (sized_bev_id, temp_attr_id))

        if cur.fetchone():
            cur.execute("""
                UPDATE item_type_global_attributes
                SET ask_in_conversation = true, question_text = 'Would you like that hot or iced?'
                WHERE item_type_id = %s AND global_attribute_id = %s
            """, (sized_bev_id, temp_attr_id))
            print("  Fixed: sized_beverage.temperature -> ask=True")
        else:
            cur.execute("""
                INSERT INTO item_type_global_attributes
                (item_type_id, global_attribute_id, ask_in_conversation, is_required,
                 question_text, display_order, allow_none, created_at, updated_at)
                VALUES (%s, %s, true, false, 'Would you like that hot or iced?', 3, true, NOW(), NOW())
            """, (sized_bev_id, temp_attr_id))
            print("  Created: sized_beverage.temperature link with ask=True")

    # Fix omelette.egg_style
    omelette_id = item_types.get('omelette')
    egg_style_id = global_attrs.get('egg_style')
    if omelette_id and egg_style_id:
        cur.execute("""
            UPDATE item_type_global_attributes
            SET ask_in_conversation = true
            WHERE item_type_id = %s AND global_attribute_id = %s
        """, (omelette_id, egg_style_id))
        print("  Fixed: omelette.egg_style -> ask=True")

    # ==========================================================================
    # PHASE 5: Create GlobalAttributeOptions from ingredients
    # ==========================================================================
    print("\nPhase 5: Ensuring GlobalAttributeOptions exist for new attributes...")

    attr_to_category = {
        'condiments': 'condiment',
        'filling': 'filling',
        'proteins': 'protein',
        'veggies': 'veggie',
    }

    for attr_slug, ing_category in attr_to_category.items():
        global_attr_id = global_attrs.get(attr_slug)
        if not global_attr_id:
            continue

        cur.execute("""
            SELECT i.id, i.slug, i.name
            FROM ingredients i
            WHERE i.category = %s
              AND NOT EXISTS (
                  SELECT 1 FROM global_attribute_options gao
                  WHERE gao.global_attribute_id = %s AND gao.ingredient_id = i.id
              )
        """, (ing_category, global_attr_id))

        ingredients = cur.fetchall()
        for i, (ing_id, ing_slug, ing_name) in enumerate(ingredients):
            cur.execute("""
                INSERT INTO global_attribute_options
                (global_attribute_id, slug, display_name, ingredient_id,
                 price_modifier, is_default, is_available, display_order, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 0, false, true, %s, NOW(), NOW())
            """, (global_attr_id, ing_slug, ing_name, ing_id, i))

        if ingredients:
            print(f"  Created {len(ingredients)} options for {attr_slug}")

    # ==========================================================================
    # PHASE 6: Drop item_type_attributes table
    # ==========================================================================
    print("\nPhase 6: Dropping item_type_attributes table...")

    # Check if table exists first
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'item_type_attributes'
        )
    """)
    if cur.fetchone()[0]:
        cur.execute("SELECT COUNT(*) FROM item_type_attributes")
        count = cur.fetchone()[0]
        print(f"  Rows in item_type_attributes before drop: {count}")

        cur.execute("DROP TABLE item_type_attributes CASCADE")
        print("  Dropped table: item_type_attributes")
    else:
        print("  Table item_type_attributes already dropped")

    # ==========================================================================
    # Update alembic_version
    # ==========================================================================
    print("\nUpdating alembic_version...")
    cur.execute("DELETE FROM alembic_version")
    cur.execute("INSERT INTO alembic_version (version_num) VALUES ('consolidate_global_attrs')")
    print("  Set version to: consolidate_global_attrs")

    # Commit all changes
    conn.commit()
    print("\n" + "=" * 50)
    print("Migration completed successfully!")
    print("=" * 50)

except Exception as e:
    conn.rollback()
    print(f"\nERROR: {e}")
    print("Transaction rolled back.")
    raise
finally:
    cur.close()
    conn.close()
