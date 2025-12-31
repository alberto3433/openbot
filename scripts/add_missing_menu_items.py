"""
Add Missing Menu Items to Database
===================================
This script adds all missing menu items identified in the menu discrepancy report.
Prices are based on current 2024/2025 Zucker's pricing from MenuPages/Grubhub.
"""

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
import os

db_url = os.environ.get('DATABASE_URL')
engine = create_engine(db_url)

def execute_sql(sql, params=None):
    """Execute SQL and commit."""
    with engine.connect() as conn:
        if params:
            result = conn.execute(text(sql), params)
        else:
            result = conn.execute(text(sql))
        conn.commit()
        return result

def get_item_type_id(slug):
    """Get item_type_id by slug."""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id FROM item_types WHERE slug = :slug"), {"slug": slug})
        row = result.fetchone()
        return row[0] if row else None

def create_item_type(slug, display_name, is_configurable=False, skip_config=True):
    """Create a new item type if it doesn't exist."""
    existing = get_item_type_id(slug)
    if existing:
        print(f"  Item type '{slug}' already exists (id={existing})")
        return existing

    execute_sql("""
        INSERT INTO item_types (slug, display_name, is_configurable, skip_config)
        VALUES (:slug, :display_name, :is_configurable, :skip_config)
    """, {
        "slug": slug,
        "display_name": display_name,
        "is_configurable": is_configurable,
        "skip_config": skip_config
    })

    new_id = get_item_type_id(slug)
    print(f"  Created item type '{slug}' (id={new_id})")
    return new_id

def add_menu_item(name, category, base_price, item_type_id, is_signature=False, available_qty=100):
    """Add a menu item if it doesn't exist."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT id FROM menu_items WHERE LOWER(name) = LOWER(:name)"
        ), {"name": name})
        existing = result.fetchone()

        if existing:
            print(f"    Skipped (exists): {name}")
            return existing[0]

    execute_sql("""
        INSERT INTO menu_items (name, category, base_price, item_type_id, is_signature, available_qty)
        VALUES (:name, :category, :base_price, :item_type_id, :is_signature, :available_qty)
    """, {
        "name": name,
        "category": category,
        "base_price": base_price,
        "item_type_id": item_type_id,
        "is_signature": is_signature,
        "available_qty": available_qty
    })
    print(f"    Added: {name} (${base_price:.2f})")

def main():
    print("=" * 70)
    print("ADDING MISSING MENU ITEMS")
    print("=" * 70)

    # =========================================================================
    # STEP 1: Create missing item types
    # =========================================================================
    print("\n1. Creating new item types...")

    deli_classic_id = create_item_type("deli_classic", "Deli Classic", is_configurable=True, skip_config=False)
    soup_id = create_item_type("soup", "Soup", is_configurable=True, skip_config=False)
    salad_id = create_item_type("salad", "Fresh Salad", is_configurable=False, skip_config=True)
    pastry_id = create_item_type("pastry", "Pastry", is_configurable=False, skip_config=True)
    breakfast_id = create_item_type("breakfast", "Breakfast", is_configurable=False, skip_config=True)

    # Get existing type IDs
    bagel_id = get_item_type_id("bagel")
    egg_sandwich_id = get_item_type_id("egg_sandwich")
    fish_sandwich_id = get_item_type_id("fish_sandwich")
    omelette_id = get_item_type_id("omelette")
    side_id = get_item_type_id("side")
    beverage_id = get_item_type_id("beverage")
    signature_sandwich_id = get_item_type_id("signature_sandwich")

    print(f"\n  Using existing types: bagel={bagel_id}, egg_sandwich={egg_sandwich_id}, fish_sandwich={fish_sandwich_id}, omelette={omelette_id}, side={side_id}")

    # =========================================================================
    # STEP 2: Add Deli Classics (9 items)
    # =========================================================================
    print("\n2. Adding Deli Classics...")
    deli_classics = [
        ("Hot Corned Beef Sandwich", 16.95),
        ("Hot Pastrami Sandwich", 16.95),  # May already exist
        ("Kosher Beef Salami Sandwich", 12.50),
        ("Top Round Roast Beef Sandwich", 14.50),
        ("Homemade Roast Turkey Sandwich", 14.50),
        ("All-Natural Smoked Turkey Sandwich", 14.50),
        ("Black Forest Ham Sandwich", 14.50),
        ("Chicken Cutlet Sandwich", 13.50),
        ("Grilled Cheese", 8.95),
    ]
    for name, price in deli_classics:
        add_menu_item(name, "deli_classic", price, deli_classic_id)

    # =========================================================================
    # STEP 3: Add Fish Sandwiches (14 items) - Smoked fish on bagel
    # =========================================================================
    print("\n3. Adding Fish Sandwiches...")
    fish_sandwiches = [
        ("Nova Scotia Salmon Sandwich", 18.65),
        ("Gravlax Sandwich", 18.65),
        ("Belly Lox Sandwich", 18.65),
        ("Everything Seeded Salmon Sandwich", 18.98),
        ("Pastrami Salmon Sandwich", 19.95),
        ("Scottish Salmon Sandwich", 19.50),
        ("Wild Pacific Salmon Sandwich", 22.50),
        ("Wild Coho Salmon Sandwich", 22.50),
        ("Baked Kippered Salmon Sandwich", 18.65),
        ("Sable Sandwich", 22.00),
        ("Smoked Trout Sandwich", 18.65),
        ("Lake Sturgeon Sandwich", 22.50),
        ("Whitefish Sandwich", 16.50),
        ("Herring Tidbits on Bagel", 12.95),
    ]
    for name, price in fish_sandwiches:
        add_menu_item(name, "fish_sandwich", price, fish_sandwich_id)

    # =========================================================================
    # STEP 4: Add Breakfast Items (4 items)
    # =========================================================================
    print("\n4. Adding Breakfast Items...")
    breakfast_items = [
        ("Organic Steel-Cut Oatmeal", 5.95),
        ("Oatmeal", 4.95),  # Alias/smaller size
        ("Homemade Malted Pecan Granola", 6.95),
        ("Low Fat Yogurt Granola Parfait", 6.50),
        ("Yogurt Parfait", 6.50),  # Alias
        ("Fresh Seasonal Fruit Cup", 6.95),
    ]
    for name, price in breakfast_items:
        add_menu_item(name, "breakfast", price, breakfast_id)

    # =========================================================================
    # STEP 5: Add Missing Omelettes (8 items)
    # =========================================================================
    print("\n5. Adding Missing Omelettes...")
    omelettes = [
        ("Nova Omelette", 15.24),
        ("Lox and Onion Omelette", 15.24),  # Alias
        ("Corned Beef Omelette", 13.63),
        ("Pastrami Omelette", 13.63),
        ("Sausage Omelette", 13.63),
        ("Southwest Omelette", 15.53),
        ("Truffle Omelette", 14.72),
        ("Egg White Avocado Omelette", 14.72),
        ("Salami Omelette", 13.63),
        ("Turkey Omelette", 13.63),
    ]
    for name, price in omelettes:
        add_menu_item(name, "omelette", price, omelette_id)

    # =========================================================================
    # STEP 6: Add Missing Egg Sandwiches (4 items)
    # =========================================================================
    print("\n6. Adding Missing Egg Sandwiches...")
    egg_sandwiches = [
        ("The Truffled Egg", 21.95),
        ("The Latke BEC", 13.50),
        ("Two Scrambled Eggs on Bagel", 6.88),
        ("Scrambled Eggs on Bagel", 6.88),  # Alias
        ("The Health Nut Egg Sandwich", 12.50),
    ]
    for name, price in egg_sandwiches:
        add_menu_item(name, "egg_sandwich", price, egg_sandwich_id, is_signature=True)

    # =========================================================================
    # STEP 7: Add Missing Sides (12 items)
    # =========================================================================
    print("\n7. Adding Missing Sides...")
    sides = [
        ("Side of Sausage", 4.50),
        ("Sausage", 4.50),  # Alias
        ("Side of Ham", 4.50),
        ("Ham", 4.50),
        ("Turkey Bacon", 4.50),
        ("Applewood Chicken Sausage", 4.85),
        ("Kosher Beef Salami Side", 4.85),
        ("Two Hardboiled Eggs", 3.95),
        ("Hardboiled Eggs", 3.95),
        ("Two Deviled Eggs", 3.95),
        ("Deviled Eggs", 3.95),
        ("Cole Slaw", 3.50),
        ("Potato Salad", 3.50),
        ("Macaroni Salad", 3.50),
    ]
    for name, price in sides:
        add_menu_item(name, "side", price, side_id)

    # =========================================================================
    # STEP 8: Add Soups (3 items)
    # =========================================================================
    print("\n8. Adding Soups...")
    soups = [
        ("Chicken Noodle Soup", 7.50),
        ("Lentil Soup", 6.95),
        ("Soup of the Day", 7.50),
    ]
    for name, price in soups:
        add_menu_item(name, "soup", price, soup_id)

    # =========================================================================
    # STEP 9: Add Fresh Salads (2 items)
    # =========================================================================
    print("\n9. Adding Fresh Salads...")
    salads = [
        ("Caesar Salad", 9.95),
        ("The Caesar", 9.95),  # Alias
        ("Garden Salad", 8.95),
        ("The Garden", 8.95),  # Alias
    ]
    for name, price in salads:
        add_menu_item(name, "salad", price, salad_id)

    # =========================================================================
    # STEP 10: Add Pastries (8 items)
    # =========================================================================
    print("\n10. Adding Pastries...")
    pastries = [
        ("Assorted Muffin", 4.50),
        ("Muffin", 4.50),
        ("Rugelach", 4.50),
        ("Chocolate-Dipped Macaroons", 5.50),
        ("Macaroons", 5.50),
        ("Assorted Brownie", 5.25),
        ("Brownie", 5.25),
        ("Large Homemade Cookie", 4.50),
        ("Cookie", 4.50),
        ("Black and White Cookie", 4.95),
        ("Danish", 4.50),
    ]
    for name, price in pastries:
        add_menu_item(name, "pastry", price, pastry_id)

    # =========================================================================
    # STEP 11: Add Missing Bagel Types (9 items)
    # =========================================================================
    print("\n11. Adding Missing Bagel Types...")
    bagels = [
        ("Marble Rye Bagel", 2.75),
        ("Wheat Poppy Bagel", 2.75),
        ("Wheat Oat Bran Bagel", 2.75),
        ("Wheat Sesame Bagel", 2.75),
        ("Wheat Health Bagel", 2.75),
        ("Wheat Flatz", 2.75),
        ("Wheat Everything Flatz", 2.75),
        ("Gluten Free Plain Bagel", 4.50),
        ("Gluten Free Everything Bagel", 4.50),
        ("Egg Bagel", 2.75),
        ("Asiago Bagel", 2.75),
    ]
    for name, price in bagels:
        add_menu_item(name, "bagel", price, bagel_id)

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT t.slug, t.display_name, COUNT(m.id) as count
            FROM item_types t
            LEFT JOIN menu_items m ON m.item_type_id = t.id
            GROUP BY t.id, t.slug, t.display_name
            ORDER BY t.slug
        """))

        total = 0
        for row in result:
            print(f"  {row[1]}: {row[2]} items")
            total += row[2]

        print(f"\n  TOTAL: {total} menu items")

if __name__ == "__main__":
    main()
