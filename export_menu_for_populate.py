"""
Export current menu items from the database to update populate_zuckers_menu.py.

This script reads all menu items from the Neon database and outputs them
in the format needed for the populate script.

Run with: python export_menu_for_populate.py
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sandwich_bot.models import MenuItem, ItemType, Ingredient, Recipe, RecipeIngredient

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    exit(1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

def export_menu_items():
    """Export all menu items grouped by category."""

    # Get all item types for reference
    item_types = {it.id: it.slug for it in db.query(ItemType).all()}

    # Get all menu items
    items = db.query(MenuItem).order_by(MenuItem.category, MenuItem.name).all()

    print("=" * 80)
    print("MENU ITEMS EXPORT")
    print("=" * 80)

    current_category = None

    for item in items:
        if item.category != current_category:
            current_category = item.category
            print(f"\n# --- {current_category.upper()} ---")

        item_type_slug = item_types.get(item.item_type_id, "None")

        # Build the dict representation
        item_dict = {
            "name": item.name,
            "category": item.category,
            "base_price": float(item.base_price) if item.base_price else 0,
            "is_signature": item.is_signature or False,
        }

        if item.item_type_id:
            item_dict["item_type_id"] = f"{item_type_slug}_type.id"

        if item.default_config:
            item_dict["default_config"] = item.default_config

        if item.description:
            item_dict["description"] = item.description

        if item.aliases:
            item_dict["aliases"] = item.aliases

        # Pretty print
        print(f'        {json.dumps(item_dict, indent=None)},')


def export_signature_sandwiches_detail():
    """Export detailed info about signature sandwiches to understand where ingredients come from."""

    print("\n" + "=" * 80)
    print("SIGNATURE SANDWICH DETAILS")
    print("=" * 80)

    signature_items = db.query(MenuItem).filter(MenuItem.is_signature == True).all()

    for item in signature_items:
        print(f"\n--- {item.name} ---")
        print(f"  ID: {item.id}")
        print(f"  Category: {item.category}")
        print(f"  Base Price: {item.base_price}")
        print(f"  Description: {item.description}")
        print(f"  Default Config: {json.dumps(item.default_config, indent=2) if item.default_config else 'None'}")
        print(f"  Aliases: {item.aliases}")
        print(f"  Recipe ID: {item.recipe_id}")

        # If there's a recipe, show its ingredients
        if item.recipe_id:
            recipe = db.query(Recipe).filter(Recipe.id == item.recipe_id).first()
            if recipe:
                print(f"  Recipe Name: {recipe.name}")
                print(f"  Recipe Description: {recipe.description}")

                recipe_ingredients = db.query(RecipeIngredient).filter(
                    RecipeIngredient.recipe_id == recipe.id
                ).all()

                if recipe_ingredients:
                    print("  Recipe Ingredients:")
                    for ri in recipe_ingredients:
                        ingredient = db.query(Ingredient).filter(Ingredient.id == ri.ingredient_id).first()
                        if ingredient:
                            print(f"    - {ingredient.name} (qty: {ri.quantity})")


def check_lexington():
    """Specifically check The Lexington to find where ingredients come from."""

    print("\n" + "=" * 80)
    print("THE LEXINGTON - DETAILED INVESTIGATION")
    print("=" * 80)

    lexington = db.query(MenuItem).filter(MenuItem.name == "The Lexington").first()

    if not lexington:
        print("'The Lexington' not found in database!")
        return

    print(f"Name: {lexington.name}")
    print(f"ID: {lexington.id}")
    print(f"Category: {lexington.category}")
    print(f"Base Price: {lexington.base_price}")
    print(f"Is Signature: {lexington.is_signature}")
    print(f"Item Type ID: {lexington.item_type_id}")
    print(f"Description: {lexington.description}")
    print(f"Default Config: {json.dumps(lexington.default_config, indent=2) if lexington.default_config else 'None'}")
    print(f"Extra Metadata: {lexington.extra_metadata}")
    print(f"Aliases: {lexington.aliases}")
    print(f"Recipe ID: {lexington.recipe_id}")

    # Check all columns
    print("\nAll column values:")
    for column in lexington.__table__.columns:
        value = getattr(lexington, column.name)
        if value is not None:
            print(f"  {column.name}: {value}")


if __name__ == "__main__":
    print("Connecting to database...")
    print(f"DATABASE_URL: {DATABASE_URL[:50]}...")

    check_lexington()
    export_signature_sandwiches_detail()
    # export_menu_items()  # Uncomment for full export

    db.close()
