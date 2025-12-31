"""
Update Zucker's menu from CSV file.
Handles items with Small/Large variants by creating configurable item types.

Requires DATABASE_URL environment variable to be set to a PostgreSQL connection URL.
"""
import csv
import os
import re
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sandwich_bot.models import (
    Base, MenuItem, ItemType, AttributeDefinition, AttributeOption,
    Ingredient, AttributeOptionIngredient
)

# Require DATABASE_URL environment variable (PostgreSQL)
DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is required")

CSV_PATH = r"C:\Users\alber\Downloads\zuckers_menu_items_complete_v3.csv"


def parse_csv(csv_path):
    """Parse the CSV file and return list of items."""
    items = []
    # Try different encodings
    for encoding in ['utf-8', 'cp1252', 'latin-1']:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('item') and row.get('price'):
                        # Clean up the item name (fix encoding issues like Café)
                        name = row['item'].strip()
                        # Handle various encodings of é
                        name = name.replace('\xe9', 'é')  # Latin-1 é
                        name = name.replace('�', 'é')  # Replacement character
                        items.append({
                            'name': name,
                            'price': float(row['price']),
                            'category': row.get('category', '').strip(),
                        })
            print(f"  (Using {encoding} encoding)")
            return items
        except UnicodeDecodeError:
            items = []
            continue
    raise ValueError("Could not decode CSV file with any supported encoding")


def identify_size_variants(items):
    """
    Identify items that have Small/Large variants.
    Returns dict: {base_name: {'small': price, 'large': price}}
    """
    size_items = {}
    regular_items = []

    # Patterns for size variants
    small_pattern = re.compile(r'^Small\s+(.+)$', re.IGNORECASE)
    large_pattern = re.compile(r'^Large\s+(.+)$', re.IGNORECASE)

    # Special handling for Fresh OJ (different naming convention)
    fresh_oj_small = re.compile(r'^Small Fresh OJ.*$', re.IGNORECASE)
    fresh_oj_large = re.compile(r'^Large Fresh OJ.*$', re.IGNORECASE)

    for item in items:
        name = item['name']

        # Special handling for Fresh OJ (10 oz and 16 oz)
        if fresh_oj_small.match(name):
            base_name = "Fresh Orange Juice"
            if base_name not in size_items:
                size_items[base_name] = {'category': item['category']}
            size_items[base_name]['small'] = item['price']
            continue
        elif fresh_oj_large.match(name):
            base_name = "Fresh Orange Juice"
            if base_name not in size_items:
                size_items[base_name] = {'category': item['category']}
            size_items[base_name]['large'] = item['price']
            continue

        small_match = small_pattern.match(name)
        large_match = large_pattern.match(name)

        if small_match:
            base_name = small_match.group(1)
            if base_name not in size_items:
                size_items[base_name] = {'category': item['category']}
            size_items[base_name]['small'] = item['price']
        elif large_match:
            base_name = large_match.group(1)
            if base_name not in size_items:
                size_items[base_name] = {'category': item['category']}
            size_items[base_name]['large'] = item['price']
        else:
            regular_items.append(item)

    # Also handle special size variants like Poland Spring, San Pellegrino
    special_size_items = {}
    remaining_regular = []

    for item in regular_items:
        name = item['name']

        # Poland Spring
        if 'Poland Spring - Large' in name:
            if 'Poland Spring' not in special_size_items:
                special_size_items['Poland Spring'] = {'category': item['category']}
            special_size_items['Poland Spring']['large'] = item['price']
        elif 'Poland Spring - Small' in name:
            if 'Poland Spring' not in special_size_items:
                special_size_items['Poland Spring'] = {'category': item['category']}
            special_size_items['Poland Spring']['small'] = item['price']
        # San Pellegrino
        elif 'San Pellegrino - Large' in name:
            if 'San Pellegrino' not in special_size_items:
                special_size_items['San Pellegrino'] = {'category': item['category']}
            special_size_items['San Pellegrino']['large'] = item['price']
        elif 'San Pellegrino - Small' in name:
            if 'San Pellegrino' not in special_size_items:
                special_size_items['San Pellegrino'] = {'category': item['category']}
            special_size_items['San Pellegrino']['small'] = item['price']
        else:
            remaining_regular.append(item)

    # Merge special size items into size_items
    size_items.update(special_size_items)

    return size_items, remaining_regular


def clear_existing_menu(session):
    """Clear existing menu-related data."""
    print("Clearing existing menu data...")

    # Delete in correct order to respect foreign keys
    session.query(AttributeOptionIngredient).delete()
    session.query(AttributeOption).delete()
    session.query(AttributeDefinition).delete()
    session.query(MenuItem).delete()
    session.query(ItemType).delete()
    session.query(Ingredient).delete()
    session.commit()
    print("  Cleared all menu data")


def create_item_types(session):
    """Create item types for Zucker's menu."""
    item_types = {}

    # Create a configurable "sized_beverage" type for drinks with Small/Large options
    sized_bev = ItemType(
        slug="sized_beverage",
        display_name="Coffee and Tea",
        is_configurable=True,
    )
    session.add(sized_bev)
    session.flush()
    item_types['sized_beverage'] = sized_bev

    # Add size attribute
    size_attr = AttributeDefinition(
        item_type_id=sized_bev.id,
        slug="size",
        display_name="Size",
        input_type="single_select",
        is_required=True,
        allow_none=False,
        display_order=0,
    )
    session.add(size_attr)
    session.flush()

    # Size options will be added per-item since prices vary
    # We'll use a standard small/large with modifier = 0 for small
    small_opt = AttributeOption(
        attribute_definition_id=size_attr.id,
        slug="small",
        display_name="Small",
        price_modifier=0.0,
        is_default=True,
        is_available=True,
        display_order=0,
    )
    large_opt = AttributeOption(
        attribute_definition_id=size_attr.id,
        slug="large",
        display_name="Large",
        price_modifier=1.0,  # Will be overridden per item
        is_default=False,
        is_available=True,
        display_order=1,
    )
    session.add(small_opt)
    session.add(large_opt)

    # Create simple item types
    for slug, name in [
        ('bagel', 'Bagel'),
        ('beverage', 'Beverage'),
        ('by_the_lb', 'Food by the Pound'),
        ('cream_cheese', 'Cream Cheese'),
        ('egg_sandwich', 'Egg Sandwich'),
        ('fish_sandwich', 'Fish Sandwich'),
        ('omelette', 'Omelette'),
        ('sandwich', 'Sandwich'),
        ('side', 'Side'),
        ('signature_sandwich', 'Signature Sandwich'),
        ('snack', 'Snack'),
    ]:
        it = ItemType(slug=slug, display_name=name, is_configurable=False)
        session.add(it)
        session.flush()
        item_types[slug] = it

    session.commit()
    print(f"Created {len(item_types)} item types")
    return item_types


def get_item_type_for_category(category, item_types):
    """Map CSV category to item type."""
    mapping = {
        'Bagels': 'bagel',
        'Beverages': 'beverage',
        'By the lb': 'by_the_lb',
        'Cream Cheese': 'cream_cheese',
        'Egg Sandwiches': 'egg_sandwich',
        'Fish Sandwiches': 'fish_sandwich',
        'Omelettes': 'omelette',
        'Sandwiches': 'sandwich',
        'Sides': 'side',
        'Signature Sandwiches': 'signature_sandwich',
        'Snacks & Candy': 'snack',
    }
    slug = mapping.get(category, 'beverage')
    return item_types.get(slug)


def add_menu_items(session, size_items, regular_items, item_types):
    """Add all menu items to the database."""

    # Add sized beverages (items with Small/Large variants)
    print(f"Adding {len(size_items)} sized beverages...")
    sized_bev_type = item_types['sized_beverage']

    for base_name, data in size_items.items():
        small_price = data.get('small', 0)
        large_price = data.get('large', 0)

        # Use small price as base, calculate modifier for large
        base_price = small_price if small_price else large_price
        large_modifier = round(large_price - small_price, 2) if small_price and large_price else 0

        # Store the large modifier in the default_config
        default_config = {
            'size_modifiers': {
                'small': 0,
                'large': large_modifier
            }
        }

        menu_item = MenuItem(
            name=base_name,
            category=data.get('category', 'Beverages'),
            is_signature=False,
            base_price=base_price,
            available_qty=0,
            item_type_id=sized_bev_type.id,
            default_config=default_config,
        )
        session.add(menu_item)

    # Add regular items
    print(f"Adding {len(regular_items)} regular items...")
    for item in regular_items:
        item_type = get_item_type_for_category(item['category'], item_types)

        menu_item = MenuItem(
            name=item['name'],
            category=item['category'],
            is_signature='Signature' in item['category'],
            base_price=item['price'],
            available_qty=0,
            item_type_id=item_type.id if item_type else None,
        )
        session.add(menu_item)

    session.commit()
    total = len(size_items) + len(regular_items)
    print(f"Added {total} menu items total")


def main():
    print("Updating Zucker's menu from CSV...")
    print(f"CSV file: {CSV_PATH}\n")

    # Parse CSV
    items = parse_csv(CSV_PATH)
    print(f"Parsed {len(items)} items from CSV")

    # Identify size variants
    size_items, regular_items = identify_size_variants(items)
    print(f"Found {len(size_items)} items with Small/Large variants")
    print(f"Found {len(regular_items)} regular items")

    # Show size items
    print("\nSized beverages:")
    for name, data in sorted(size_items.items()):
        small = data.get('small', 'N/A')
        large = data.get('large', 'N/A')
        print(f"  {name}: Small=${small}, Large=${large}")

    # Connect to database
    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Clear existing menu
        clear_existing_menu(session)

        # Create item types
        item_types = create_item_types(session)

        # Add menu items
        add_menu_items(session, size_items, regular_items, item_types)

        print("\n" + "="*50)
        print("Zucker's menu updated successfully!")
        print("="*50)

    except Exception as e:
        print(f"\nError: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
