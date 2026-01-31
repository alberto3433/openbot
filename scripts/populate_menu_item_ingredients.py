"""
Script to parse menu item descriptions and populate menu_item_ingredients table.

Parses ingredients from descriptions like:
- "Two Eggs, Applewood Smoked Bacon, and Cheddar"
- "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes"

Handles:
- Quantity words (Two, Three, etc.)
- Ingredient matching via aliases
- Compound ingredients (Green & Red Peppers -> Green Pepper + Red Pepper)
"""

import os
import re
from dotenv import load_dotenv

load_dotenv()

from orderbot.db import SessionLocal
from orderbot.db.models import MenuItem, Ingredient, IngredientAlias, MenuItemIngredient

# Word to number mapping
WORD_TO_NUM = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'a': 1, 'an': 1,
}

# Manual mappings for tricky cases that aliases don't cover
MANUAL_MAPPINGS = {
    'cheddar': 'Cheddar Cheese',
    'swiss': 'Swiss Cheese',
    'havarti': 'Havarti Cheese',
    'pepper jack': 'Pepper Jack Cheese',
    'mozzarella': 'Mozzarella Cheese',
    'swiss cheese': 'Swiss Cheese',
    'tomato sauce': None,  # Skip - not in our ingredients
    'choice of pepperoni': None,  # Skip - user choice
    'romaine': 'Lettuce',  # Map romaine to lettuce
    'dijon mayo': 'Mayo',  # Map to mayo
    'basil mayo': 'Mayo',
    'cracked black peppers': 'Black Pepper',
    'cracked black pepper': 'Black Pepper',
    'beefsteak tomatoes': 'Beefsteak Tomatoes',
    'sauteed onions': 'Sauteed Onions',
    'sauteed mushrooms': 'Sauteed Mushrooms',
    'smoked bacon': 'Applewood Smoked Bacon',
    'green peppers': 'Green Pepper',
    'red peppers': 'Red Pepper',
    'green pepper': 'Green Pepper',
    'red pepper': 'Red Pepper',
    'jalapeno-honey': None,  # Skip - specialty sauce
    'lemon everything seeds': 'Everything Seeds',
    'salt and pepper': None,  # Skip - too generic, would need both
    'fresh avocado': 'Avocado',
    'espositos sausage': "Esposito's Sausage",
    "esposito's sausage": "Esposito's Sausage",
    'russian dressing': 'Russian Dressing',
    'roast turkey': 'Turkey',
    'grilled chicken': None,  # Not in ingredients - skip for now
    'diced tomatoes': 'Tomato',
    'crushed avocado': 'Avocado',
    'our fresh tuna salad': 'Tuna Salad',
    'fresh carved roast beef': 'Roast Beef',
    '2 fried eggs': 'Egg',
    'melted swiss': 'Swiss Cheese',
    'truffle cream cheese': 'Truffle Cream Cheese',
    'chipotle cream cheese': 'Chipotle Cream Cheese',
    'plain cream cheese': 'Plain Cream Cheese',
    'scallion cream cheese': 'Scallion Cream Cheese',
    'cream cheese': 'Cream Cheese',
    # Additional mappings for unmatched items
    'horseradish': 'Horseradish',
    'onion pepper relish': 'Onion, Pepper & Caper Relish',
    'onion pepper & caper relish': 'Onion, Pepper & Caper Relish',
    'caper relish': None,  # Part of compound, already covered by Onion, Pepper & Caper Relish
    'smoked nova scotia salmon': 'Nova Scotia Salmon',
    'tuna': 'Tuna Salad',
    'green': 'Green Pepper',  # From "green and red peppers"
    'jalapeno-honey': 'Jalapeno-Honey',
    'grilled chicken': 'Grilled Chicken',
}

# Compound descriptions that need special handling - maps to list of (qty, ingredient_name)
COMPOUND_DESCRIPTIONS = {
    'crushed avocado with diced tomatoes': [(1, 'Avocado'), (1, 'Tomato')],
    'egg whites with mushrooms': [(3, 'Egg White'), (1, 'Mushrooms')],
    'smoked whitefish salad with beefsteak tomatoes': [(1, 'Whitefish Salad'), (1, 'Beefsteak Tomatoes')],
    'or roast turkey with sauerkraut': [(1, 'Turkey'), (1, 'Sauerkraut')],
}


def build_ingredient_lookup(db):
    """Build a lookup dict from lowercase name/alias -> Ingredient."""
    lookup = {}

    ingredients = db.query(Ingredient).all()
    for ing in ingredients:
        # Add canonical name
        lookup[ing.name.lower()] = ing

    aliases = db.query(IngredientAlias).all()
    for alias in aliases:
        ing = db.query(Ingredient).filter(Ingredient.id == alias.ingredient_id).first()
        if ing:
            lookup[alias.alias.lower()] = ing

    return lookup


def parse_quantity(text):
    """Extract quantity from text like 'Two Eggs' -> (2, 'Eggs')."""
    text = text.strip()

    # Check for digit at start
    match = re.match(r'^(\d+)\s+(.+)$', text)
    if match:
        return int(match.group(1)), match.group(2)

    # Check for word at start
    words = text.split()
    if words and words[0].lower() in WORD_TO_NUM:
        qty = WORD_TO_NUM[words[0].lower()]
        remainder = ' '.join(words[1:])
        return qty, remainder

    return 1, text


def parse_description(description):
    """
    Parse a description into ingredient parts.

    Returns list of (quantity, ingredient_text) tuples.
    """
    if not description:
        return []

    # Normalize
    desc = description.strip()

    # Skip non-ingredient descriptions
    skip_patterns = [
        'create your own',
        'choice of',
    ]
    if any(p in desc.lower() for p in skip_patterns):
        return []

    # Split by comma and 'and'
    # First replace " and " with comma
    desc = re.sub(r'\s+and\s+', ', ', desc, flags=re.IGNORECASE)

    # Split by comma
    parts = [p.strip() for p in desc.split(',') if p.strip()]

    results = []
    for part in parts:
        # Handle "Green & Red Peppers" -> ["Green Peppers", "Red Peppers"]
        if ' & ' in part:
            # Check if it's a compound like "Green & Red Peppers"
            match = re.match(r'^(.+?)\s*&\s*(.+?)(\s+\w+)$', part)
            if match:
                prefix1, prefix2, suffix = match.groups()
                results.append(parse_quantity(prefix1 + suffix))
                results.append(parse_quantity(prefix2 + suffix))
                continue

        # Handle "or" alternatives - take the first one
        if ' or ' in part.lower():
            part = re.split(r'\s+or\s+', part, flags=re.IGNORECASE)[0]

        results.append(parse_quantity(part))

    return results


def match_ingredient(text, lookup):
    """
    Try to match text to an ingredient.

    Returns (Ingredient, matched_name) or (None, None).
    """
    text_lower = text.lower().strip()

    # Remove trailing period
    text_lower = text_lower.rstrip('.')

    # Check compound descriptions first - returns special marker
    if text_lower in COMPOUND_DESCRIPTIONS:
        return 'COMPOUND', text_lower

    # Check manual mappings first
    if text_lower in MANUAL_MAPPINGS:
        mapped = MANUAL_MAPPINGS[text_lower]
        if mapped is None:
            return None, None  # Explicitly skip
        if mapped.lower() in lookup:
            return lookup[mapped.lower()], mapped

    # Direct lookup
    if text_lower in lookup:
        return lookup[text_lower], text

    # Try singular/plural variations
    if text_lower.endswith('s'):
        singular = text_lower[:-1]
        if singular in lookup:
            return lookup[singular], text
    else:
        plural = text_lower + 's'
        if plural in lookup:
            return lookup[plural], text

    # Try adding common suffixes
    for suffix in [' cheese', ' cream cheese']:
        if text_lower + suffix in lookup:
            return lookup[text_lower + suffix], text

    return None, None


def get_existing_ingredients(db, menu_item_id):
    """Get set of ingredient IDs already linked to this menu item."""
    existing = db.query(MenuItemIngredient).filter(
        MenuItemIngredient.menu_item_id == menu_item_id
    ).all()
    return {e.ingredient_id for e in existing}


def main():
    db = SessionLocal()

    try:
        # Build lookup
        print("Building ingredient lookup...")
        lookup = build_ingredient_lookup(db)
        print(f"Loaded {len(lookup)} ingredient names/aliases")

        # Get all menu items with descriptions
        items = db.query(MenuItem).filter(
            MenuItem.description != None,
            MenuItem.description != ''
        ).order_by(MenuItem.name).all()

        print(f"\nProcessing {len(items)} menu items with descriptions...\n")

        unmatched = []
        added_count = 0
        skipped_count = 0

        for item in items:
            print(f"\n{'='*60}")
            print(f"ITEM: {item.name}")
            print(f"DESC: {item.description}")

            existing_ids = get_existing_ingredients(db, item.id)
            print(f"Existing ingredients: {len(existing_ids)}")

            parsed = parse_description(item.description)
            if not parsed:
                print("  -> No ingredients parsed")
                continue

            for qty, ingredient_text in parsed:
                ing, matched_name = match_ingredient(ingredient_text, lookup)

                if ing is None:
                    print(f"  [!] UNMATCHED: '{ingredient_text}'")
                    unmatched.append((item.name, ingredient_text))
                    continue

                # Handle compound descriptions
                if ing == 'COMPOUND':
                    compound_key = matched_name
                    compound_items = COMPOUND_DESCRIPTIONS[compound_key]
                    print(f"  [*] COMPOUND: '{ingredient_text}' -> {len(compound_items)} items")
                    for c_qty, c_name in compound_items:
                        c_ing = lookup.get(c_name.lower())
                        if c_ing is None:
                            print(f"      [!] COMPOUND UNMATCHED: '{c_name}'")
                            unmatched.append((item.name, c_name))
                            continue
                        if c_ing.id in existing_ids:
                            print(f"      [=] ALREADY EXISTS: {c_ing.name} (qty={c_qty})")
                            skipped_count += 1
                            continue
                        print(f"      [+] ADDING: {c_ing.name} (qty={c_qty})")
                        link = MenuItemIngredient(
                            menu_item_id=item.id,
                            ingredient_id=c_ing.id,
                            quantity=c_qty,
                        )
                        db.add(link)
                        existing_ids.add(c_ing.id)
                        added_count += 1
                    continue

                if ing.id in existing_ids:
                    print(f"  [=] ALREADY EXISTS: {ing.name} (qty={qty})")
                    skipped_count += 1
                    continue

                print(f"  [+] ADDING: {ing.name} (qty={qty}) [matched from '{ingredient_text}']")

                # Add to database
                link = MenuItemIngredient(
                    menu_item_id=item.id,
                    ingredient_id=ing.id,
                    quantity=qty,
                )
                db.add(link)
                existing_ids.add(ing.id)
                added_count += 1

        # Commit all changes
        db.commit()

        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Added: {added_count} ingredient links")
        print(f"Skipped (already exist): {skipped_count}")
        print(f"Unmatched: {len(unmatched)}")

        if unmatched:
            print(f"\n--- UNMATCHED INGREDIENTS ---")
            for item_name, ing_text in unmatched:
                print(f"  {item_name}: '{ing_text}'")

    finally:
        db.close()


if __name__ == "__main__":
    main()
