"""
Migrate data from local Zucker's SQLite database to Neon PostgreSQL.
"""
import os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sandwich_bot.models import (
    Base, Company, Store, MenuItem, ItemType, AttributeDefinition,
    AttributeOption, Ingredient, Recipe, RecipeIngredient,
    RecipeChoiceGroup, RecipeChoiceItem, AttributeOptionIngredient
)

SOURCE_DB = "sqlite:///./data/zuckers.db"
TARGET_DB = os.environ["DATABASE_URL"]

def clear_target_database(session):
    """Clear all data from target database in correct order."""
    print("Clearing existing data from Neon...")

    # Delete in reverse dependency order
    tables = [
        "order_items", "orders", "chat_sessions", "session_analytics",
        "menu_item_store_availability", "ingredient_store_availability",
        "recipe_choice_items", "recipe_choice_groups", "recipe_ingredients",
        "attribute_option_ingredients", "attribute_options", "attribute_definitions",
        "menu_items", "recipes", "ingredients", "item_types", "stores", "company"
    ]

    for table in tables:
        try:
            session.execute(text(f"DELETE FROM {table}"))
            print(f"  Cleared {table}")
        except Exception as e:
            print(f"  Skipped {table}: {e}")

    session.commit()
    print("Done clearing data.\n")


def migrate_data(source_session, target_session):
    """Copy all data from source to target."""

    # 1. Company
    print("Migrating company...")
    companies = source_session.query(Company).all()
    for c in companies:
        new_c = Company(
            name=c.name,
            bot_persona_name=c.bot_persona_name,
            tagline=c.tagline,
            website=c.website,
            signature_item_label=getattr(c, 'signature_item_label', None),
        )
        target_session.add(new_c)
    target_session.commit()
    print(f"  Migrated {len(companies)} company records")

    # 2. Stores
    print("Migrating stores...")
    stores = source_session.query(Store).all()
    for s in stores:
        new_s = Store(
            store_id=s.store_id,
            name=s.name,
            address=s.address,
            city=s.city,
            state=s.state,
            zip_code=s.zip_code,
            phone=s.phone,
            hours=s.hours,
            timezone=getattr(s, 'timezone', 'America/New_York'),
            status=s.status,
            payment_methods=s.payment_methods,
        )
        target_session.add(new_s)
    target_session.commit()
    print(f"  Migrated {len(stores)} stores")

    # 3. ItemTypes
    print("Migrating item types...")
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
    print(f"  Migrated {len(item_types)} item types")

    # 4. AttributeDefinitions
    print("Migrating attribute definitions...")
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
    print(f"  Migrated {len(attr_defs)} attribute definitions")

    # 5. Ingredients
    print("Migrating ingredients...")
    ingredients = source_session.query(Ingredient).all()
    id_map_ingredients = {}
    for ing in ingredients:
        new_ing = Ingredient(
            name=ing.name,
            category=ing.category,
            unit=ing.unit,
            track_inventory=ing.track_inventory,
            base_price=getattr(ing, 'base_price', 0.0),
            is_available=getattr(ing, 'is_available', True),
        )
        target_session.add(new_ing)
        target_session.flush()
        id_map_ingredients[ing.id] = new_ing.id
    target_session.commit()
    print(f"  Migrated {len(ingredients)} ingredients")

    # 6. AttributeOptions
    print("Migrating attribute options...")
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
    print(f"  Migrated {len(attr_opts)} attribute options")

    # 7. AttributeOptionIngredients
    print("Migrating attribute option ingredients...")
    attr_opt_ings = source_session.query(AttributeOptionIngredient).all()
    for aoi in attr_opt_ings:
        new_aoi = AttributeOptionIngredient(
            attribute_option_id=id_map_attr_opts.get(aoi.attribute_option_id),
            ingredient_id=id_map_ingredients.get(aoi.ingredient_id),
        )
        target_session.add(new_aoi)
    target_session.commit()
    print(f"  Migrated {len(attr_opt_ings)} attribute option ingredients")

    # 8. Recipes
    print("Migrating recipes...")
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
    print(f"  Migrated {len(recipes)} recipes")

    # 9. RecipeIngredients
    print("Migrating recipe ingredients...")
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
    print(f"  Migrated {len(recipe_ings)} recipe ingredients")

    # 10. RecipeChoiceGroups
    print("Migrating recipe choice groups...")
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
    print(f"  Migrated {len(choice_groups)} recipe choice groups")

    # 11. RecipeChoiceItems
    print("Migrating recipe choice items...")
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
    print(f"  Migrated {len(choice_items)} recipe choice items")

    # 12. MenuItems
    print("Migrating menu items...")
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
    print(f"  Migrated {len(menu_items)} menu items")


def main():
    print("="*50)
    print("Migrating Zucker's data to Neon PostgreSQL")
    print("="*50)
    print(f"\nSource: {SOURCE_DB}")
    print(f"Target: Neon PostgreSQL\n")

    # Create engines and sessions
    source_engine = create_engine(SOURCE_DB)
    target_engine = create_engine(TARGET_DB)

    SourceSession = sessionmaker(bind=source_engine)
    TargetSession = sessionmaker(bind=target_engine)

    source_session = SourceSession()
    target_session = TargetSession()

    try:
        # Clear existing data
        clear_target_database(target_session)

        # Migrate data
        migrate_data(source_session, target_session)

        print("\n" + "="*50)
        print("Migration complete!")
        print("="*50)

    except Exception as e:
        print(f"\nError: {e}")
        target_session.rollback()
        raise
    finally:
        source_session.close()
        target_session.close()


if __name__ == "__main__":
    main()
