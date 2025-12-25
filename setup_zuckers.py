"""
Setup script for Zucker's Bagels database.

Creates a new database with:
- Zucker's company info
- 7 NYC store locations
- Menu items copied from Sammy's
"""
import os
import sys

# Set up the database URL before importing anything from sandwich_bot
os.environ["DATABASE_URL"] = "sqlite:///./data/zuckers.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sandwich_bot.models import (
    Base, Company, Store, MenuItem, ItemType, AttributeDefinition,
    AttributeOption, Ingredient, Recipe, RecipeIngredient,
    RecipeChoiceGroup, RecipeChoiceItem, AttributeOptionIngredient
)

# Source database (Sammy's)
SOURCE_DB = "sqlite:///./data/sammys.db"
TARGET_DB = "sqlite:///./data/zuckers.db"


def create_zuckers_stores(db):
    """Create the 7 Zucker's store locations."""
    stores = [
        {
            "store_id": "zuckers_tribeca",
            "name": "Zucker's - Tribeca",
            "address": "143 Chambers Street",
            "city": "New York",
            "state": "NY",
            "zip_code": "10007",
            "phone": "212-608-5844",
            "hours": "Mon-Fri 7:00am-5:30pm, Sat-Sun 7:00am-2:30pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "zuckers_uws",
            "name": "Zucker's - Upper West Side",
            "address": "273 Columbus Ave",
            "city": "New York",
            "state": "NY",
            "zip_code": "10023",
            "phone": "212-874-2800",
            "hours": "Mon-Fri 7:00am-5:30pm, Sat-Sun 7:00am-3:00pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "zuckers_grandcentral",
            "name": "Zucker's - Grand Central",
            "address": "370 Lexington Ave",
            "city": "New York",
            "state": "NY",
            "zip_code": "10017",
            "phone": "212-661-1080",
            "hours": "Mon-Fri 6:30am-5:30pm, Sat-Sun 7:00am-2:30pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "zuckers_flatiron",
            "name": "Zucker's - Flatiron",
            "address": "40 East 23rd Street",
            "city": "New York",
            "state": "NY",
            "zip_code": "10010",
            "phone": "212-228-5100",
            "hours": "Daily 7:00am-2:30pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "zuckers_chelsea",
            "name": "Zucker's - Chelsea",
            "address": "242 Eighth Avenue",
            "city": "New York",
            "state": "NY",
            "zip_code": "10011",
            "phone": "646-638-1335",
            "hours": "Daily 7:00am-2:30pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "zuckers_fidi",
            "name": "Zucker's - Financial District",
            "address": "125 Fulton Street",
            "city": "New York",
            "state": "NY",
            "zip_code": "10038",
            "phone": "212-361-9400",
            "hours": "Mon-Fri 7:00am-5:30pm, Sat-Sun 7:00am-2:30pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
        {
            "store_id": "zuckers_bryantpark",
            "name": "Zucker's - Bryant Park",
            "address": "1065 Sixth Avenue",
            "city": "New York",
            "state": "NY",
            "zip_code": "10018",
            "phone": "212-671-2400",
            "hours": "Mon-Fri 6:30am-5:30pm, Sat-Sun 7:00am-5:30pm",
            "timezone": "America/New_York",
            "status": "open",
            "payment_methods": ["cash", "credit"],
        },
    ]

    for store_data in stores:
        store = Store(**store_data)
        db.add(store)

    db.commit()
    print(f"Created {len(stores)} stores")


def create_zuckers_company(db):
    """Create the Zucker's company record."""
    company = Company(
        name="Zucker's Bagels",
        bot_persona_name="Zack",
        tagline="NYC's Favorite Bagels!",
        website="https://www.zuckersbagels.com",
    )
    db.add(company)
    db.commit()
    print("Created Zucker's company record")


def copy_menu_from_sammys(source_session, target_session):
    """Copy all menu-related data from Sammy's to Zucker's."""

    # 1. Copy ItemTypes
    print("Copying item types...")
    item_types = source_session.query(ItemType).all()
    id_map_item_types = {}
    for it in item_types:
        new_it = ItemType(
            slug=it.slug,
            display_name=it.display_name,
            is_configurable=it.is_configurable,
        )
        target_session.add(new_it)
        target_session.flush()
        id_map_item_types[it.id] = new_it.id
    target_session.commit()
    print(f"  Copied {len(item_types)} item types")

    # 2. Copy AttributeDefinitions
    print("Copying attribute definitions...")
    attr_defs = source_session.query(AttributeDefinition).all()
    id_map_attr_defs = {}
    for ad in attr_defs:
        new_ad = AttributeDefinition(
            item_type_id=id_map_item_types.get(ad.item_type_id),
            slug=ad.slug,
            display_name=ad.display_name,
            input_type=ad.input_type,
            is_required=ad.is_required,
            allow_none=ad.allow_none,
            min_selections=ad.min_selections,
            max_selections=ad.max_selections,
            display_order=ad.display_order,
        )
        target_session.add(new_ad)
        target_session.flush()
        id_map_attr_defs[ad.id] = new_ad.id
    target_session.commit()
    print(f"  Copied {len(attr_defs)} attribute definitions")

    # 3. Copy Ingredients
    print("Copying ingredients...")
    ingredients = source_session.query(Ingredient).all()
    id_map_ingredients = {}
    for ing in ingredients:
        new_ing = Ingredient(
            name=ing.name,
            category=ing.category,
            unit=ing.unit,
            track_inventory=ing.track_inventory,
            base_price=ing.base_price,
            is_available=ing.is_available,
        )
        target_session.add(new_ing)
        target_session.flush()
        id_map_ingredients[ing.id] = new_ing.id
    target_session.commit()
    print(f"  Copied {len(ingredients)} ingredients")

    # 4. Copy AttributeOptions
    print("Copying attribute options...")
    attr_opts = source_session.query(AttributeOption).all()
    id_map_attr_opts = {}
    for ao in attr_opts:
        new_ao = AttributeOption(
            attribute_definition_id=id_map_attr_defs.get(ao.attribute_definition_id),
            slug=ao.slug,
            display_name=ao.display_name,
            price_modifier=ao.price_modifier,
            is_default=ao.is_default,
            is_available=ao.is_available,
            display_order=ao.display_order,
        )
        target_session.add(new_ao)
        target_session.flush()
        id_map_attr_opts[ao.id] = new_ao.id
    target_session.commit()
    print(f"  Copied {len(attr_opts)} attribute options")

    # 5. Copy AttributeOptionIngredients (junction table)
    print("Copying attribute option ingredients...")
    attr_opt_ings = source_session.query(AttributeOptionIngredient).all()
    for aoi in attr_opt_ings:
        new_aoi = AttributeOptionIngredient(
            attribute_option_id=id_map_attr_opts.get(aoi.attribute_option_id),
            ingredient_id=id_map_ingredients.get(aoi.ingredient_id),
        )
        target_session.add(new_aoi)
    target_session.commit()
    print(f"  Copied {len(attr_opt_ings)} attribute option ingredients")

    # 6. Copy Recipes
    print("Copying recipes...")
    recipes = source_session.query(Recipe).all()
    id_map_recipes = {}
    for r in recipes:
        new_r = Recipe(
            name=r.name,
            description=r.description,
        )
        target_session.add(new_r)
        target_session.flush()
        id_map_recipes[r.id] = new_r.id
    target_session.commit()
    print(f"  Copied {len(recipes)} recipes")

    # 7. Copy RecipeIngredients
    print("Copying recipe ingredients...")
    recipe_ings = source_session.query(RecipeIngredient).all()
    for ri in recipe_ings:
        new_ri = RecipeIngredient(
            recipe_id=id_map_recipes.get(ri.recipe_id),
            ingredient_id=id_map_ingredients.get(ri.ingredient_id),
            quantity=ri.quantity,
            unit_override=ri.unit_override,
            is_required=ri.is_required,
        )
        target_session.add(new_ri)
    target_session.commit()
    print(f"  Copied {len(recipe_ings)} recipe ingredients")

    # 8. Copy RecipeChoiceGroups
    print("Copying recipe choice groups...")
    choice_groups = source_session.query(RecipeChoiceGroup).all()
    id_map_choice_groups = {}
    for cg in choice_groups:
        new_cg = RecipeChoiceGroup(
            recipe_id=id_map_recipes.get(cg.recipe_id),
            name=cg.name,
            min_choices=cg.min_choices,
            max_choices=cg.max_choices,
            is_required=cg.is_required,
        )
        target_session.add(new_cg)
        target_session.flush()
        id_map_choice_groups[cg.id] = new_cg.id
    target_session.commit()
    print(f"  Copied {len(choice_groups)} recipe choice groups")

    # 9. Copy RecipeChoiceItems
    print("Copying recipe choice items...")
    choice_items = source_session.query(RecipeChoiceItem).all()
    for ci in choice_items:
        new_ci = RecipeChoiceItem(
            choice_group_id=id_map_choice_groups.get(ci.choice_group_id),
            ingredient_id=id_map_ingredients.get(ci.ingredient_id),
            is_default=ci.is_default,
            extra_price=ci.extra_price,
        )
        target_session.add(new_ci)
    target_session.commit()
    print(f"  Copied {len(choice_items)} recipe choice items")

    # 10. Copy MenuItems
    print("Copying menu items...")
    menu_items = source_session.query(MenuItem).all()
    for mi in menu_items:
        new_mi = MenuItem(
            name=mi.name,
            category=mi.category,
            is_signature=mi.is_signature,
            base_price=mi.base_price,
            available_qty=mi.available_qty,
            extra_metadata=mi.extra_metadata,
            item_type_id=id_map_item_types.get(mi.item_type_id) if mi.item_type_id else None,
            default_config=mi.default_config,
            recipe_id=id_map_recipes.get(mi.recipe_id) if mi.recipe_id else None,
        )
        target_session.add(new_mi)
    target_session.commit()
    print(f"  Copied {len(menu_items)} menu items")


def main():
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)

    # Check if Zucker's database already exists
    if os.path.exists("data/zuckers.db"):
        response = input("Zucker's database already exists. Delete and recreate? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            return
        os.remove("data/zuckers.db")
        print("Deleted existing database.")

    # Create target database engine and tables
    print("\nCreating Zucker's database...")
    target_engine = create_engine(TARGET_DB)
    Base.metadata.create_all(target_engine)
    TargetSession = sessionmaker(bind=target_engine)
    target_session = TargetSession()

    # Create source database session
    source_engine = create_engine(SOURCE_DB)
    SourceSession = sessionmaker(bind=source_engine)
    source_session = SourceSession()

    try:
        # Create Zucker's company and stores
        print("\nSetting up Zucker's company...")
        create_zuckers_company(target_session)

        print("\nCreating Zucker's store locations...")
        create_zuckers_stores(target_session)

        # Copy menu from Sammy's
        print("\nCopying menu from Sammy's...")
        copy_menu_from_sammys(source_session, target_session)

        print("\n" + "="*50)
        print("Zucker's database setup complete!")
        print("="*50)
        print("\nTo start Zucker's server, run:")
        print("  start_zuckers.cmd")
        print("\nThe server will be available at http://localhost:8006")

    except Exception as e:
        print(f"\nError: {e}")
        target_session.rollback()
        raise
    finally:
        source_session.close()
        target_session.close()


if __name__ == "__main__":
    main()
