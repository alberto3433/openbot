"""
Add Zucker's Omelette modifiers to the database.

This script adds:
- Omelette item type with is_configurable=True
- Attribute definitions for omelette customization:
  - Side Choice (bagel or fruit salad)
  - Bagel Choice (all bagel types)
  - Egg Style (regular or egg whites)
  - Fillings (cheese, veggies, meats)
  - Extras (extra cheese, extra protein, etc.)
"""
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from sqlalchemy.orm import Session
from sandwich_bot.db import SessionLocal
from sandwich_bot.models import (
    ItemType, AttributeDefinition, AttributeOption
)


def create_omelette_item_type(db: Session) -> ItemType:
    """Create or get the omelette item type."""
    omelette_type = db.query(ItemType).filter(ItemType.slug == "omelette").first()
    if not omelette_type:
        omelette_type = ItemType(
            slug="omelette",
            display_name="Omelette",
            is_configurable=True,
        )
        db.add(omelette_type)
        db.commit()
        db.refresh(omelette_type)
        print("Created 'omelette' item type")
    else:
        # Ensure is_configurable is True for existing omelette type
        if not omelette_type.is_configurable:
            omelette_type.is_configurable = True
            db.commit()
            print("Updated 'omelette' item type to is_configurable=True")
        else:
            print("Omelette item type already exists and is configurable")
    return omelette_type


def add_attribute_definition(
    db: Session,
    item_type_id: int,
    slug: str,
    display_name: str,
    input_type: str = "single_select",
    is_required: bool = True,
    allow_none: bool = False,
    display_order: int = 0,
    min_selections: int = None,
    max_selections: int = None,
) -> AttributeDefinition:
    """Create or get an attribute definition."""
    attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == item_type_id,
        AttributeDefinition.slug == slug,
    ).first()

    if not attr:
        attr = AttributeDefinition(
            item_type_id=item_type_id,
            slug=slug,
            display_name=display_name,
            input_type=input_type,
            is_required=is_required,
            allow_none=allow_none,
            display_order=display_order,
            min_selections=min_selections,
            max_selections=max_selections,
        )
        db.add(attr)
        db.commit()
        db.refresh(attr)
        print(f"  Created attribute: {display_name}")
    else:
        print(f"  Attribute '{display_name}' already exists")
    return attr


def add_attribute_option(
    db: Session,
    attribute_id: int,
    slug: str,
    display_name: str,
    price_modifier: float = 0.0,
    is_default: bool = False,
    display_order: int = 0,
) -> AttributeOption:
    """Create or update an attribute option."""
    opt = db.query(AttributeOption).filter(
        AttributeOption.attribute_definition_id == attribute_id,
        AttributeOption.slug == slug,
    ).first()

    if not opt:
        opt = AttributeOption(
            attribute_definition_id=attribute_id,
            slug=slug,
            display_name=display_name,
            price_modifier=price_modifier,
            is_default=is_default,
            is_available=True,
            display_order=display_order,
        )
        db.add(opt)
        db.commit()
        print(f"    Added option: {display_name}" + (f" (+${price_modifier:.2f})" if price_modifier > 0 else ""))
    else:
        # Update existing
        opt.display_name = display_name
        opt.price_modifier = price_modifier
        opt.is_default = is_default
        opt.display_order = display_order
        db.commit()
    return opt


def populate_omelette_modifiers(db: Session):
    """Add all omelette modifiers."""
    omelette_type = create_omelette_item_type(db)
    item_type_id = omelette_type.id

    print("\nAdding omelette attribute definitions and options...")

    # 1. Side Choice - bagel or fruit salad (comes with omelette)
    side_attr = add_attribute_definition(
        db, item_type_id,
        slug="side_choice",
        display_name="Side Choice",
        input_type="single_select",
        is_required=True,
        display_order=1,
    )
    side_options = [
        ("bagel", "Bagel", 0.0, True),
        ("fruit_salad", "Small Fruit Salad", 0.0, False),
    ]
    for i, (slug, name, price, is_default) in enumerate(side_options):
        add_attribute_option(db, side_attr.id, slug, name, price, is_default, i)

    # 2. Bagel Choice - which bagel they want (if they chose bagel as side)
    bagel_attr = add_attribute_definition(
        db, item_type_id,
        slug="bagel_choice",
        display_name="Bagel Choice",
        input_type="single_select",
        is_required=False,  # Only required if side_choice is bagel
        display_order=2,
    )
    bagel_options = [
        ("plain", "Plain Bagel", 0.0, True),
        ("everything", "Everything Bagel", 0.0, False),
        ("sesame", "Sesame Bagel", 0.0, False),
        ("poppy", "Poppy Bagel", 0.0, False),
        ("onion", "Onion Bagel", 0.0, False),
        ("salt", "Salt Bagel", 0.0, False),
        ("garlic", "Garlic Bagel", 0.0, False),
        ("pumpernickel", "Pumpernickel Bagel", 0.0, False),
        ("cinnamon_raisin", "Cinnamon Raisin Bagel", 0.0, False),
        ("whole_wheat", "Whole Wheat Bagel", 0.0, False),
        ("everything_wheat", "Everything Wheat Bagel", 0.0, False),
        ("bialy", "Bialy", 0.0, False),
    ]
    for i, (slug, name, price, is_default) in enumerate(bagel_options):
        add_attribute_option(db, bagel_attr.id, slug, name, price, is_default, i)

    # 3. Egg Style
    egg_attr = add_attribute_definition(
        db, item_type_id,
        slug="egg_style",
        display_name="Egg Style",
        input_type="single_select",
        is_required=True,
        display_order=3,
    )
    egg_options = [
        ("regular", "Regular Eggs", 0.0, True),
        ("egg_whites", "Egg Whites", 1.50, False),
    ]
    for i, (slug, name, price, is_default) in enumerate(egg_options):
        add_attribute_option(db, egg_attr.id, slug, name, price, is_default, i)

    # 4. Omelette Fillings - signature omelette styles or build your own
    filling_attr = add_attribute_definition(
        db, item_type_id,
        slug="filling",
        display_name="Omelette Filling",
        input_type="multi_select",
        is_required=True,
        allow_none=False,
        min_selections=1,
        max_selections=5,
        display_order=4,
    )
    # Based on Zucker's signature omelettes and available fillings
    filling_options = [
        # Cheese options
        ("american_cheese", "American Cheese", 0.0, True),
        ("cheddar", "Cheddar Cheese", 0.0, False),
        ("swiss", "Swiss Cheese", 0.0, False),
        ("muenster", "Muenster Cheese", 0.0, False),
        # Proteins
        ("bacon", "Bacon", 2.00, False),
        ("turkey_bacon", "Turkey Bacon", 2.00, False),
        ("sausage", "Sausage", 2.00, False),
        ("nova_salmon", "Nova Salmon", 4.00, False),
        ("corned_beef", "Corned Beef", 3.00, False),
        ("pastrami", "Pastrami", 3.00, False),
        ("ham", "Ham", 2.00, False),
        # Veggies
        ("onion", "Onion", 0.0, False),
        ("peppers", "Peppers", 0.0, False),
        ("tomato", "Tomato", 0.0, False),
        ("mushroom", "Mushroom", 0.75, False),
        ("spinach", "Spinach", 0.75, False),
        ("avocado", "Avocado", 2.50, False),
        ("broccoli", "Broccoli", 0.75, False),
    ]
    for i, (slug, name, price, is_default) in enumerate(filling_options):
        add_attribute_option(db, filling_attr.id, slug, name, price, is_default, i)

    # 5. Extras - add-ons
    extras_attr = add_attribute_definition(
        db, item_type_id,
        slug="extras",
        display_name="Extras",
        input_type="multi_select",
        is_required=False,
        allow_none=True,
        min_selections=0,
        max_selections=5,
        display_order=5,
    )
    extras_options = [
        ("extra_cheese", "Extra Cheese", 1.50, False),
        ("extra_bacon", "Extra Bacon", 2.50, False),
        ("extra_avocado", "Extra Avocado", 2.50, False),
        ("cream_cheese_side", "Side of Cream Cheese", 2.00, False),
        ("hot_sauce", "Hot Sauce", 0.0, False),
        ("salsa", "Salsa", 0.50, False),
        ("sour_cream", "Sour Cream", 0.75, False),
    ]
    for i, (slug, name, price, is_default) in enumerate(extras_options):
        add_attribute_option(db, extras_attr.id, slug, name, price, is_default, i)

    print("\nOmelette modifiers population complete!")


def main():
    print("Adding Zucker's Omelette modifiers...")
    print(f"Database: {os.getenv('DATABASE_URL', 'Not set')[:50]}...")

    db = SessionLocal()

    try:
        populate_omelette_modifiers(db)

        # Print summary
        omelette_type = db.query(ItemType).filter(ItemType.slug == "omelette").first()
        if omelette_type:
            attrs = db.query(AttributeDefinition).filter(
                AttributeDefinition.item_type_id == omelette_type.id
            ).all()
            print(f"\nOmelette modifiers summary:")
            for attr in attrs:
                options = db.query(AttributeOption).filter(
                    AttributeOption.attribute_definition_id == attr.id
                ).count()
                print(f"  {attr.display_name}: {options} options")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
