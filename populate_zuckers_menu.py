"""
Populate Zucker's Bagels menu items in the database.

This script adds essential bagel items to the database including:
- Bagel types
- Cream cheese schmears
- Egg sandwiches
- Signature sandwiches
- Drinks and sides
"""
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from sqlalchemy.orm import Session
from sandwich_bot.db import SessionLocal, engine
from sandwich_bot.models import (
    Base, MenuItem, ItemType, Ingredient, Company, Store,
    AttributeDefinition, AttributeOption,
    ItemTypeAttribute, MenuItemAttributeValue, MenuItemAttributeSelection
)


def clear_existing_menu(db: Session):
    """Clear existing menu items (optional - use with caution)."""
    count = db.query(MenuItem).delete()
    db.commit()
    print(f"Deleted {count} existing menu items")


# =============================================================================
# Attribute Configuration: Define attributes and still_ask defaults per item type
# =============================================================================

# Format: {item_type_slug: {attr_slug: {'display_name': str, 'input_type': str, 'is_required': bool, 'still_ask': bool}}}
ITEM_TYPE_ATTRIBUTE_CONFIG = {
    'egg_sandwich': {
        'bread': {'display_name': 'Bread Choice', 'input_type': 'single_select', 'is_required': True, 'still_ask': True},
        'toasted': {'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': False, 'still_ask': True},
        'scooped': {'display_name': 'Scooped Out', 'input_type': 'boolean', 'is_required': False, 'still_ask': False, 'default': False},
        'egg_style': {'display_name': 'Egg Preparation', 'input_type': 'single_select', 'is_required': False, 'still_ask': True},
        'protein': {'display_name': 'Breakfast Protein', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'cheese': {'display_name': 'Cheese', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'spread': {'display_name': 'Cream Cheese / Tofu', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'toppings': {'display_name': 'Breakfast Toppings', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
    },
    'signature_sandwich': {
        'bread': {'display_name': 'Bread', 'input_type': 'single_select', 'is_required': True, 'still_ask': True},
        'protein': {'display_name': 'Protein', 'input_type': 'single_select', 'is_required': False, 'still_ask': False},
        'cheese': {'display_name': 'Cheese', 'input_type': 'single_select', 'is_required': False, 'still_ask': False},
        'extras': {'display_name': 'Extras', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'toasted': {'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': True, 'still_ask': True},
    },
    'fish_sandwich': {
        'fish': {'display_name': 'Fish', 'input_type': 'single_select', 'is_required': True, 'still_ask': False},
        'spread': {'display_name': 'Spread', 'input_type': 'single_select', 'is_required': False, 'still_ask': False},
        'extras': {'display_name': 'Extras', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'toasted': {'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': True, 'still_ask': True},
    },
    'salad_sandwich': {
        'salad': {'display_name': 'Salad Type', 'input_type': 'single_select', 'is_required': True, 'still_ask': False},
    },
    'spread_sandwich': {
        'spread': {'display_name': 'Spread', 'input_type': 'single_select', 'is_required': True, 'still_ask': False},
    },
    'omelette': {
        'eggs': {'display_name': 'Eggs', 'input_type': 'single_select', 'is_required': False, 'still_ask': False},
        'protein': {'display_name': 'Protein', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'cheese': {'display_name': 'Cheese', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'spread': {'display_name': 'Spread', 'input_type': 'single_select', 'is_required': False, 'still_ask': False},
        'extras': {'display_name': 'Extras', 'input_type': 'multi_select', 'is_required': False, 'still_ask': False},
        'includes_side_choice': {'display_name': 'Includes Side', 'input_type': 'boolean', 'is_required': False, 'still_ask': False},
        'side_options': {'display_name': 'Side Options', 'input_type': 'text', 'is_required': False, 'still_ask': False},
    },
}


def normalize_option_slug(value: str) -> str:
    """Normalize a value to a slug format."""
    return value.lower().strip().replace(' ', '_').replace('-', '_').replace("'", '').replace('"', '')


def get_or_create_item_type_attribute(db: Session, item_type_id: int, slug: str, config: dict) -> ItemTypeAttribute:
    """Get or create an ItemTypeAttribute for the given item type and slug."""
    attr = db.query(ItemTypeAttribute).filter(
        ItemTypeAttribute.item_type_id == item_type_id,
        ItemTypeAttribute.slug == slug
    ).first()

    if not attr:
        attr = ItemTypeAttribute(
            item_type_id=item_type_id,
            slug=slug,
            display_name=config.get('display_name', slug.title()),
            input_type=config.get('input_type', 'single_select'),
            is_required=config.get('is_required', False),
            allow_none=not config.get('is_required', False),
            ask_in_conversation=True,
        )
        db.add(attr)
        db.flush()

    return attr


def get_or_create_attribute_option(db: Session, item_type_attribute_id: int, item_type_id: int, value: str) -> AttributeOption:
    """Get or create an AttributeOption for the given attribute and value."""
    slug = normalize_option_slug(value)
    display_name = value if value != value.lower() else value.title()

    # First check by item_type_attribute_id
    option = db.query(AttributeOption).filter(
        AttributeOption.item_type_attribute_id == item_type_attribute_id,
        AttributeOption.slug == slug
    ).first()

    if option:
        return option

    # Need to create a new option - first find or create placeholder attribute_definition for FK
    attr_def = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == item_type_id
    ).first()

    if not attr_def:
        # Create a placeholder attribute_definition
        attr_def = AttributeDefinition(
            item_type_id=item_type_id,
            slug=f'_placeholder_{item_type_id}',
            display_name='Placeholder',
            input_type='single_select',
            is_required=False,
            allow_none=True,
        )
        db.add(attr_def)
        db.flush()

    # Check if option exists with this attr_def and slug
    option = db.query(AttributeOption).filter(
        AttributeOption.attribute_definition_id == attr_def.id,
        AttributeOption.slug == slug
    ).first()

    if option:
        # Update to also reference our item_type_attribute
        if option.item_type_attribute_id is None:
            option.item_type_attribute_id = item_type_attribute_id
        return option

    # Create new option
    option = AttributeOption(
        attribute_definition_id=attr_def.id,
        item_type_attribute_id=item_type_attribute_id,
        slug=slug,
        display_name=display_name,
        price_modifier=0.0,
        is_available=True,
    )
    db.add(option)
    db.flush()
    return option


def create_relational_attribute_values(db: Session, menu_item: MenuItem, config: dict):
    """
    Create relational MenuItemAttributeValue and MenuItemAttributeSelection records
    for a menu item's default_config.

    This creates the relational representation that replaces the JSON default_config.
    Both the JSON and relational representations coexist during the transition period.
    """
    if not menu_item.item_type_id:
        return

    # Get item type slug
    item_type = db.query(ItemType).filter(ItemType.id == menu_item.item_type_id).first()
    if not item_type:
        return

    item_type_slug = item_type.slug
    attr_config = ITEM_TYPE_ATTRIBUTE_CONFIG.get(item_type_slug, {})

    for key, value in config.items():
        if value is None:
            continue

        # Get attribute configuration
        attr_settings = attr_config.get(key, {
            'display_name': key.title().replace('_', ' '),
            'input_type': 'multi_select' if isinstance(value, list) else ('boolean' if isinstance(value, bool) else 'single_select'),
            'is_required': False,
            'still_ask': False,
        })

        # Get or create the item_type_attribute
        attr = get_or_create_item_type_attribute(db, menu_item.item_type_id, key, attr_settings)
        still_ask = attr_settings.get('still_ask', False)

        if isinstance(value, list):
            # Multi-select: create MenuItemAttributeSelection entries
            # First check/create MenuItemAttributeValue for still_ask
            existing_value = db.query(MenuItemAttributeValue).filter(
                MenuItemAttributeValue.menu_item_id == menu_item.id,
                MenuItemAttributeValue.attribute_id == attr.id
            ).first()

            if not existing_value:
                existing_value = MenuItemAttributeValue(
                    menu_item_id=menu_item.id,
                    attribute_id=attr.id,
                    still_ask=still_ask,
                )
                db.add(existing_value)
                db.flush()

            # Create selection entries for each value
            for v in value:
                option = get_or_create_attribute_option(db, attr.id, menu_item.item_type_id, str(v))
                existing_selection = db.query(MenuItemAttributeSelection).filter(
                    MenuItemAttributeSelection.menu_item_id == menu_item.id,
                    MenuItemAttributeSelection.attribute_id == attr.id,
                    MenuItemAttributeSelection.option_id == option.id
                ).first()

                if not existing_selection:
                    selection = MenuItemAttributeSelection(
                        menu_item_id=menu_item.id,
                        attribute_id=attr.id,
                        option_id=option.id,
                    )
                    db.add(selection)

        elif isinstance(value, bool):
            # Boolean value
            existing = db.query(MenuItemAttributeValue).filter(
                MenuItemAttributeValue.menu_item_id == menu_item.id,
                MenuItemAttributeValue.attribute_id == attr.id
            ).first()

            if not existing:
                db.add(MenuItemAttributeValue(
                    menu_item_id=menu_item.id,
                    attribute_id=attr.id,
                    value_boolean=value,
                    still_ask=still_ask,
                ))

        else:
            # Single select: create option and reference it
            option = get_or_create_attribute_option(db, attr.id, menu_item.item_type_id, str(value))
            existing = db.query(MenuItemAttributeValue).filter(
                MenuItemAttributeValue.menu_item_id == menu_item.id,
                MenuItemAttributeValue.attribute_id == attr.id
            ).first()

            if not existing:
                db.add(MenuItemAttributeValue(
                    menu_item_id=menu_item.id,
                    attribute_id=attr.id,
                    option_id=option.id,
                    still_ask=still_ask,
                ))


def ensure_company_and_stores(db: Session):
    """Ensure Zucker's company and stores exist."""
    company = db.query(Company).first()
    if not company:
        company = Company(
            name="Zucker's Bagels",
            bot_persona_name="Zara",
            tagline="NYC's Favorite Bagels!",
            website="https://www.zuckersbagels.com",
        )
        db.add(company)
        db.commit()
        print("Created Zucker's company record")
    elif company.name != "Zucker's Bagels":
        company.name = "Zucker's Bagels"
        company.bot_persona_name = "Zara"
        company.tagline = "NYC's Favorite Bagels!"
        db.commit()
        print("Updated company to Zucker's Bagels")

    # Check for stores
    store_count = db.query(Store).count()
    if store_count == 0:
        stores = [
            {"store_id": "zuckers_tribeca", "name": "Zucker's - Tribeca", "address": "143 Chambers Street", "city": "New York", "state": "NY", "zip_code": "10007", "phone": "(212) 608-5844"},
            {"store_id": "zuckers_uws", "name": "Zucker's - Upper West Side", "address": "273 Columbus Ave", "city": "New York", "state": "NY", "zip_code": "10023", "phone": "(212) 712-2227"},
            {"store_id": "zuckers_grandcentral", "name": "Zucker's - Grand Central", "address": "370 Lexington Ave", "city": "New York", "state": "NY", "zip_code": "10017", "phone": "(212) 867-5151"},
        ]
        for s in stores:
            db.add(Store(**s))
        db.commit()
        print(f"Created {len(stores)} stores")


def ensure_item_types(db: Session):
    """Ensure bagel item types exist."""
    # Check for bagel item type
    bagel_type = db.query(ItemType).filter(ItemType.slug == "bagel").first()
    if not bagel_type:
        bagel_type = ItemType(
            slug="bagel",
            display_name="Bagel",
            is_configurable=True,
        )
        db.add(bagel_type)
        db.commit()
        print("Created 'bagel' item type")

    # Check for signature_sandwich item type
    sandwich_type = db.query(ItemType).filter(ItemType.slug == "signature_sandwich").first()
    if not sandwich_type:
        sandwich_type = ItemType(
            slug="signature_sandwich",
            display_name="Signature Sandwich",
            is_configurable=True,
        )
        db.add(sandwich_type)
        db.commit()
        print("Created 'signature_sandwich' item type")

    # Check for omelette item type
    omelette_type = db.query(ItemType).filter(ItemType.slug == "omelette").first()
    if not omelette_type:
        omelette_type = ItemType(
            slug="omelette",
            display_name="Omelette",
            is_configurable=True,
        )
        db.add(omelette_type)
        db.commit()
        print("Created 'omelette' item type")

    # Check for spread sandwich item type (cream cheese, butter, etc.)
    spread_sandwich_type = db.query(ItemType).filter(ItemType.slug == "spread_sandwich").first()
    if not spread_sandwich_type:
        spread_sandwich_type = ItemType(
            slug="spread_sandwich",
            display_name="Spread Sandwich",
            is_configurable=True,
        )
        db.add(spread_sandwich_type)
        db.commit()
        print("Created 'spread_sandwich' item type")

    # Check for salad sandwich item type (whitefish, tuna, egg salad, etc.)
    salad_sandwich_type = db.query(ItemType).filter(ItemType.slug == "salad_sandwich").first()
    if not salad_sandwich_type:
        salad_sandwich_type = ItemType(
            slug="salad_sandwich",
            display_name="Salad Sandwich",
            is_configurable=True,
        )
        db.add(salad_sandwich_type)
        db.commit()
        print("Created 'salad_sandwich' item type")

    # Check for sized_beverage item type (for drinks that need hot/iced/size config)
    sized_beverage_type = db.query(ItemType).filter(ItemType.slug == "sized_beverage").first()
    if not sized_beverage_type:
        sized_beverage_type = ItemType(
            slug="sized_beverage",
            display_name="Coffee and Tea",
            is_configurable=True,
        )
        db.add(sized_beverage_type)
        db.commit()
        print("Created 'sized_beverage' item type")

    # Check for beverage item type (cold drinks that don't need hot/iced config)
    beverage_type = db.query(ItemType).filter(ItemType.slug == "beverage").first()
    if not beverage_type:
        beverage_type = ItemType(
            slug="beverage",
            display_name="Cold Beverage",
            is_configurable=False,
            skip_config=True,
        )
        db.add(beverage_type)
        db.commit()
        print("Created 'beverage' item type")

    # Check for fish_sandwich item type
    fish_sandwich_type = db.query(ItemType).filter(ItemType.slug == "fish_sandwich").first()
    if not fish_sandwich_type:
        fish_sandwich_type = ItemType(
            slug="fish_sandwich",
            display_name="Fish Sandwich",
            is_configurable=True,
        )
        db.add(fish_sandwich_type)
        db.commit()
        print("Created 'fish_sandwich' item type")

    # Check for by_the_lb item type
    by_the_lb_type = db.query(ItemType).filter(ItemType.slug == "by_the_lb").first()
    if not by_the_lb_type:
        by_the_lb_type = ItemType(
            slug="by_the_lb",
            display_name="By the Pound",
            is_configurable=False,
            skip_config=True,
        )
        db.add(by_the_lb_type)
        db.commit()
        print("Created 'by_the_lb' item type")

    # Check for cream_cheese item type
    cream_cheese_type = db.query(ItemType).filter(ItemType.slug == "cream_cheese").first()
    if not cream_cheese_type:
        cream_cheese_type = ItemType(
            slug="cream_cheese",
            display_name="Cream Cheese",
            is_configurable=False,
            skip_config=True,
        )
        db.add(cream_cheese_type)
        db.commit()
        print("Created 'cream_cheese' item type")

    # Check for snack item type
    snack_type = db.query(ItemType).filter(ItemType.slug == "snack").first()
    if not snack_type:
        snack_type = ItemType(
            slug="snack",
            display_name="Snack",
            is_configurable=False,
            skip_config=True,
        )
        db.add(snack_type)
        db.commit()
        print("Created 'snack' item type")

    # Check for pastry item type (Desserts & Pastries category)
    pastry_type = db.query(ItemType).filter(ItemType.slug == "pastry").first()
    if not pastry_type:
        pastry_type = ItemType(
            slug="pastry",
            display_name="Desserts & Pastries",
            is_configurable=False,
            skip_config=True,
        )
        db.add(pastry_type)
        db.commit()
        print("Created 'pastry' item type")

    # Check for side item type
    side_type = db.query(ItemType).filter(ItemType.slug == "side").first()
    if not side_type:
        side_type = ItemType(
            slug="side",
            display_name="Side",
            is_configurable=False,
            skip_config=True,
        )
        db.add(side_type)
        db.commit()
        print("Created 'side' item type")

    # Check for breakfast item type
    breakfast_type = db.query(ItemType).filter(ItemType.slug == "breakfast").first()
    if not breakfast_type:
        breakfast_type = ItemType(
            slug="breakfast",
            display_name="Breakfast",
            is_configurable=False,
            skip_config=True,
        )
        db.add(breakfast_type)
        db.commit()
        print("Created 'breakfast' item type")

    # Check for deli_classic item type
    deli_classic_type = db.query(ItemType).filter(ItemType.slug == "deli_classic").first()
    if not deli_classic_type:
        deli_classic_type = ItemType(
            slug="deli_classic",
            display_name="Deli Classic",
            is_configurable=True,
        )
        db.add(deli_classic_type)
        db.commit()
        print("Created 'deli_classic' item type")

    # Check for egg_sandwich item type
    egg_sandwich_type = db.query(ItemType).filter(ItemType.slug == "egg_sandwich").first()
    if not egg_sandwich_type:
        egg_sandwich_type = ItemType(
            slug="egg_sandwich",
            display_name="Egg Sandwich",
            is_configurable=True,
        )
        db.add(egg_sandwich_type)
        db.commit()
        print("Created 'egg_sandwich' item type")

    # Check for espresso item type
    espresso_type = db.query(ItemType).filter(ItemType.slug == "espresso").first()
    if not espresso_type:
        espresso_type = ItemType(
            slug="espresso",
            display_name="Espresso",
            is_configurable=True,
        )
        db.add(espresso_type)
        db.commit()
        print("Created 'espresso' item type")

    # Check for salad item type
    salad_type = db.query(ItemType).filter(ItemType.slug == "salad").first()
    if not salad_type:
        salad_type = ItemType(
            slug="salad",
            display_name="Salad",
            is_configurable=False,
            skip_config=True,
        )
        db.add(salad_type)
        db.commit()
        print("Created 'salad' item type")

    # Check for soup item type
    soup_type = db.query(ItemType).filter(ItemType.slug == "soup").first()
    if not soup_type:
        soup_type = ItemType(
            slug="soup",
            display_name="Soup",
            is_configurable=False,
            skip_config=True,
        )
        db.add(soup_type)
        db.commit()
        print("Created 'soup' item type")

    return (bagel_type, sandwich_type, omelette_type, spread_sandwich_type,
            salad_sandwich_type, sized_beverage_type, beverage_type,
            fish_sandwich_type, by_the_lb_type, cream_cheese_type, snack_type,
            pastry_type, side_type, breakfast_type, deli_classic_type,
            egg_sandwich_type, espresso_type, salad_type, soup_type)


def ensure_bread_ingredients(db: Session):
    """Ensure bagel bread types exist as ingredients.

    Based on Zucker's Bagels official menu: https://www.zuckersbagels.com/menu/
    Prices based on Zucker's online ordering and delivery platforms.
    """
    # (name, price) - Regular bagels are $2.20, specialty/gluten-free are $3.00
    bagel_types = [
        # Standard bagels ($2.20)
        ("Plain Bagel", 2.20),
        ("Everything Bagel", 2.20),
        ("Sesame Bagel", 2.20),
        ("Poppy Bagel", 2.20),
        ("Onion Bagel", 2.20),
        ("Pumpernickel Bagel", 2.20),
        ("Salt Bagel", 2.20),
        ("Cinnamon Raisin Bagel", 2.20),
        ("Garlic Bagel", 2.20),
        ("Whole Wheat Bagel", 2.20),
        ("Everything Wheat Bagel", 2.20),
        ("Bialy", 2.20),
        # Specialty bagels ($2.50)
        ("Wheat Flatz", 2.50),
        ("Wheat Everything Flatz", 2.50),
        # Gluten-free vegan options ($3.00)
        ("Gluten Free Bagel", 3.00),
        ("Gluten Free Everything Bagel", 3.00),
    ]

    for name, price in bagel_types:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if existing:
            # Update price if it changed
            if existing.base_price != price:
                existing.base_price = price
        else:
            db.add(Ingredient(name=name, category="bread", unit="each", is_available=True, base_price=price))

    db.commit()
    print(f"Ensured {len(bagel_types)} bagel bread types exist with prices")


def ensure_schmear_ingredients(db: Session):
    """Ensure cream cheese schmears exist as ingredients.

    Based on Zucker's Bagels official menu: https://www.zuckersbagels.com/menu/
    """
    # Cream cheese flavors from Zucker's menu (category="cheese")
    cream_cheeses = [
        # Regular cream cheeses
        ("Plain Cream Cheese", 3.00),
        ("Scallion Cream Cheese", 3.50),
        ("Vegetable Cream Cheese", 3.50),
        ("Sun-Dried Tomato Cream Cheese", 3.75),
        ("Strawberry Cream Cheese", 3.50),
        ("Blueberry Cream Cheese", 3.50),
        ("Kalamata Olive Cream Cheese", 3.75),
        ("Maple Raisin Walnut Cream Cheese", 4.00),
        ("Jalapeño Cream Cheese", 3.50),
        ("Nova Scotia Cream Cheese", 4.50),
        ("Truffle Cream Cheese", 5.00),
        ("Lox Spread", 4.50),
        ("Honey Walnut Cream Cheese", 4.00),
        # Tofu spreads (vegan options)
        ("Tofu Cream Cheese", 3.50),
        ("Tofu Scallion Cream Cheese", 3.75),
        ("Tofu Vegetable Cream Cheese", 3.75),
        ("Tofu Nova Cream Cheese", 4.25),
    ]

    # Other spreads (category="spread") - these are NOT cream cheese
    other_spreads = [
        ("Butter", 1.00),
        ("Peanut Butter", 2.00),
        ("Nutella", 2.50),
        ("Hummus", 3.00),
        ("Avocado Spread", 4.00),
    ]

    for name, price in cream_cheeses:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if not existing:
            db.add(Ingredient(name=name, category="cheese", unit="portion", is_available=True, base_price=price))
        else:
            existing.base_price = price
            existing.category = "cheese"

    for name, price in other_spreads:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if not existing:
            db.add(Ingredient(name=name, category="spread", unit="portion", is_available=True, base_price=price))
        else:
            existing.base_price = price
            existing.category = "spread"

    db.commit()
    print(f"Ensured {len(cream_cheeses)} cream cheese schmears and {len(other_spreads)} other spreads exist")


def ensure_protein_ingredients(db: Session):
    """Ensure proteins exist as ingredients."""
    proteins = [
        ("Nova Scotia Salmon", 8.00),
        ("Baked Salmon", 7.00),
        ("Whitefish Salad", 7.00),
        ("Tuna Salad", 5.00),
        ("Egg Salad", 4.00),
        ("Bacon", 3.00),
        ("Turkey", 5.00),
        ("Pastrami", 6.00),
        ("Corned Beef", 6.00),
        ("Ham", 4.00),
        ("Egg", 2.00),
        ("Egg White", 2.50),
        ("Scrambled Eggs", 3.00),
        ("Avocado", 3.00),
    ]

    for name, price in proteins:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if not existing:
            db.add(Ingredient(name=name, category="protein", unit="portion", is_available=True, base_price=price))
        else:
            existing.base_price = price
            existing.category = "protein"

    db.commit()
    print(f"Ensured {len(proteins)} protein ingredients exist")


def ensure_topping_ingredients(db: Session):
    """Ensure toppings exist as ingredients."""
    toppings = [
        ("Tomato", 0.75),
        ("Onion", 0.50),
        ("Red Onion", 0.50),
        ("Capers", 1.00),
        ("Lettuce", 0.50),
        ("Cucumber", 0.75),
        ("Pickles", 0.50),
        ("Sauerkraut", 1.00),
        ("Sprouts", 0.75),
        ("Everything Seeds", 0.50),
    ]

    for name, price in toppings:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if not existing:
            db.add(Ingredient(name=name, category="topping", unit="portion", is_available=True, base_price=price))
        else:
            existing.base_price = price
            existing.category = "topping"

    db.commit()
    print(f"Ensured {len(toppings)} topping ingredients exist")


def ensure_sauce_ingredients(db: Session):
    """Ensure sauces/condiments exist as ingredients."""
    sauces = [
        ("Mayo", 0.00),
        ("Mustard", 0.00),
        ("Russian Dressing", 0.50),
        ("Hot Sauce", 0.00),
        ("Olive Oil", 0.50),
    ]

    for name, price in sauces:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if not existing:
            db.add(Ingredient(name=name, category="sauce", unit="portion", is_available=True, base_price=price))
        else:
            existing.base_price = price
            existing.category = "sauce"

    db.commit()
    print(f"Ensured {len(sauces)} sauce ingredients exist")


def ensure_spread_sandwich_attributes(db: Session, spread_sandwich_type: ItemType):
    """Set up attribute definitions for spread sandwiches."""
    if not spread_sandwich_type:
        return

    # Bread choice
    bread_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == spread_sandwich_type.id,
        AttributeDefinition.slug == "bread"
    ).first()
    if not bread_attr:
        bread_attr = AttributeDefinition(
            item_type_id=spread_sandwich_type.id,
            slug="bread",
            display_name="Bagel Type",
            input_type="single_select",
            is_required=True,
            display_order=1,
        )
        db.add(bread_attr)
        db.commit()
        print("Created 'bread' attribute for spread_sandwich")

    # Add bagel options for bread
    bagel_options = [
        ("plain", "Plain Bagel", 0.0, True),
        ("everything", "Everything Bagel", 0.0, False),
        ("sesame", "Sesame Bagel", 0.0, False),
        ("poppy", "Poppy Bagel", 0.0, False),
        ("onion", "Onion Bagel", 0.0, False),
        ("cinnamon_raisin", "Cinnamon Raisin Bagel", 0.25, False),
        ("pumpernickel", "Pumpernickel Bagel", 0.0, False),
        ("salt", "Salt Bagel", 0.0, False),
        ("garlic", "Garlic Bagel", 0.0, False),
        ("whole_wheat", "Whole Wheat Bagel", 0.25, False),
        ("bialy", "Bialy", 0.0, False),
        ("wrap", "Wrap", 0.0, False),
        ("artisan_bread", "Artisan Bread", 0.50, False),
    ]
    for slug, display_name, price_mod, is_default in bagel_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == bread_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=bread_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
                is_default=is_default,
            ))
    db.commit()
    print(f"Ensured {len(bagel_options)} bread options for spread_sandwich")

    # Toasted option
    toasted_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == spread_sandwich_type.id,
        AttributeDefinition.slug == "toasted"
    ).first()
    if not toasted_attr:
        toasted_attr = AttributeDefinition(
            item_type_id=spread_sandwich_type.id,
            slug="toasted",
            display_name="Toasted",
            input_type="boolean",
            is_required=False,
            display_order=2,
        )
        db.add(toasted_attr)
        db.commit()
        print("Created 'toasted' attribute for spread_sandwich")

    # Extra spread option
    extra_spread_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == spread_sandwich_type.id,
        AttributeDefinition.slug == "extra_spread"
    ).first()
    if not extra_spread_attr:
        extra_spread_attr = AttributeDefinition(
            item_type_id=spread_sandwich_type.id,
            slug="extra_spread",
            display_name="Extra Spread",
            input_type="boolean",
            is_required=False,
            display_order=3,
        )
        db.add(extra_spread_attr)
        db.commit()
        print("Created 'extra_spread' attribute for spread_sandwich")


def ensure_salad_sandwich_attributes(db: Session, salad_sandwich_type: ItemType):
    """Set up attribute definitions for salad sandwiches."""
    if not salad_sandwich_type:
        return

    # Bread choice
    bread_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == salad_sandwich_type.id,
        AttributeDefinition.slug == "bread"
    ).first()
    if not bread_attr:
        bread_attr = AttributeDefinition(
            item_type_id=salad_sandwich_type.id,
            slug="bread",
            display_name="Bagel Type",
            input_type="single_select",
            is_required=True,
            display_order=1,
        )
        db.add(bread_attr)
        db.commit()
        print("Created 'bread' attribute for salad_sandwich")

    # Add bagel options for bread
    bagel_options = [
        ("plain", "Plain Bagel", 0.0, True),
        ("everything", "Everything Bagel", 0.0, False),
        ("sesame", "Sesame Bagel", 0.0, False),
        ("poppy", "Poppy Bagel", 0.0, False),
        ("onion", "Onion Bagel", 0.0, False),
        ("cinnamon_raisin", "Cinnamon Raisin Bagel", 0.25, False),
        ("pumpernickel", "Pumpernickel Bagel", 0.0, False),
        ("salt", "Salt Bagel", 0.0, False),
        ("garlic", "Garlic Bagel", 0.0, False),
        ("whole_wheat", "Whole Wheat Bagel", 0.25, False),
        ("bialy", "Bialy", 0.0, False),
        ("wrap", "Wrap", 0.0, False),
        ("artisan_bread", "Artisan Bread", 0.50, False),
    ]
    for slug, display_name, price_mod, is_default in bagel_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == bread_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=bread_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
                is_default=is_default,
            ))
    db.commit()
    print(f"Ensured {len(bagel_options)} bread options for salad_sandwich")

    # Toasted option
    toasted_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == salad_sandwich_type.id,
        AttributeDefinition.slug == "toasted"
    ).first()
    if not toasted_attr:
        toasted_attr = AttributeDefinition(
            item_type_id=salad_sandwich_type.id,
            slug="toasted",
            display_name="Toasted",
            input_type="boolean",
            is_required=False,
            display_order=2,
        )
        db.add(toasted_attr)
        db.commit()
        print("Created 'toasted' attribute for salad_sandwich")

    # Extras (toppings)
    extras_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == salad_sandwich_type.id,
        AttributeDefinition.slug == "extras"
    ).first()
    if not extras_attr:
        extras_attr = AttributeDefinition(
            item_type_id=salad_sandwich_type.id,
            slug="extras",
            display_name="Extras",
            input_type="multi_select",
            is_required=False,
            allow_none=True,
            display_order=3,
        )
        db.add(extras_attr)
        db.commit()
        print("Created 'extras' attribute for salad_sandwich")

    # Add extras options
    extras_options = [
        ("tomato", "Tomato", 0.75),
        ("onion", "Onion", 0.50),
        ("red_onion", "Red Onion", 0.50),
        ("capers", "Capers", 1.00),
        ("lettuce", "Lettuce", 0.50),
        ("cucumber", "Cucumber", 0.75),
    ]
    for slug, display_name, price_mod in extras_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == extras_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=extras_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
            ))
    db.commit()
    print(f"Ensured {len(extras_options)} extras options for salad_sandwich")


def ensure_egg_sandwich_attributes(db: Session, egg_sandwich_type: ItemType):
    """Set up attribute definitions and options for egg sandwiches.

    Based on Zucker's website egg sandwich configuration page.
    """
    if not egg_sandwich_type:
        return

    # 1. Bread choice
    bread_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "bread"
    ).first()
    if not bread_attr:
        bread_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="bread",
            display_name="Bread Choice",
            input_type="single_select",
            is_required=True,
            display_order=1,
        )
        db.add(bread_attr)
        db.commit()
        print("Created 'bread' attribute for egg_sandwich")

    # Bread options from Zucker's website (slug, display_name, price_modifier, is_default)
    bread_options = [
        ("plain_bagel", "Plain Bagel", 0.0, True),
        ("everything_bagel", "Everything Bagel", 0.0, False),
        ("sesame_bagel", "Sesame Bagel", 0.0, False),
        ("poppy_bagel", "Poppy Bagel", 0.0, False),
        ("onion_bagel", "Onion Bagel", 0.0, False),
        ("salt_bagel", "Salt Bagel", 0.0, False),
        ("garlic_bagel", "Garlic Bagel", 0.0, False),
        ("pumpernickel_bagel", "Pumpernickel Bagel", 0.0, False),
        ("whole_wheat_bagel", "Whole Wheat Bagel", 0.0, False),
        ("egg_bagel", "Egg Bagel", 0.0, False),
        ("rainbow_bagel", "Rainbow Bagel", 0.0, False),
        ("french_toast_bagel", "French Toast Bagel", 0.0, False),
        ("sun_dried_tomato_bagel", "Sun Dried Tomato Bagel", 0.0, False),
        ("multigrain_bagel", "Multigrain Bagel", 0.0, False),
        ("cinnamon_raisin_bagel", "Cinnamon Raisin Bagel", 0.0, False),
        ("asiago_bagel", "Asiago Bagel", 0.0, False),
        ("jalapeno_cheddar_bagel", "Jalapeno Cheddar Bagel", 0.0, False),
        ("bialy", "Bialy", 0.0, False),
        ("flagel", "Flagel", 0.0, False),
        # GF options with upcharge
        ("gf_plain_bagel", "Gluten Free Plain Bagel", 1.85, False),
        ("gf_everything_bagel", "Gluten Free Everything Bagel", 1.85, False),
        ("gf_sesame_bagel", "Gluten Free Sesame Bagel", 1.85, False),
        ("gf_cinnamon_raisin_bagel", "Gluten Free Cinnamon Raisin Bagel", 1.85, False),
        # Other breads
        ("croissant", "Croissant", 1.80, False),
        ("wrap", "Wrap", 0.0, False),
        ("gf_wrap", "Gluten Free Wrap", 1.00, False),
        ("no_bread", "No Bread (in a bowl)", 2.00, False),
    ]
    for slug, display_name, price_mod, is_default in bread_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == bread_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=bread_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
                is_default=is_default,
            ))
        else:
            # Update price if changed
            existing.price_modifier = price_mod
    db.commit()
    print(f"Ensured {len(bread_options)} bread options for egg_sandwich")

    # 2. Toasted option
    toasted_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "toasted"
    ).first()
    if not toasted_attr:
        toasted_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="toasted",
            display_name="Toasted",
            input_type="boolean",
            is_required=False,
            display_order=2,
        )
        db.add(toasted_attr)
        db.commit()
        print("Created 'toasted' attribute for egg_sandwich")

    # 3. Scooped option
    scooped_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "scooped"
    ).first()
    if not scooped_attr:
        scooped_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="scooped",
            display_name="Scooped Out",
            input_type="boolean",
            is_required=False,
            display_order=3,
        )
        db.add(scooped_attr)
        db.commit()
        print("Created 'scooped' attribute for egg_sandwich")

    # 4. Egg style (preparation)
    egg_style_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "egg_style"
    ).first()
    if not egg_style_attr:
        egg_style_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="egg_style",
            display_name="Egg Preparation",
            input_type="single_select",
            is_required=False,
            display_order=4,
        )
        db.add(egg_style_attr)
        db.commit()
        print("Created 'egg_style' attribute for egg_sandwich")

    # Egg style options
    egg_style_options = [
        ("scrambled", "Scrambled", 0.0, True),
        ("fried", "Fried", 0.0, False),
        ("over_easy", "Over Easy", 0.0, False),
        ("over_medium", "Over Medium", 0.0, False),
        ("over_hard", "Over Hard", 0.0, False),
        ("egg_whites", "Substitute Egg Whites", 2.05, False),
    ]
    for slug, display_name, price_mod, is_default in egg_style_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == egg_style_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=egg_style_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
                is_default=is_default,
            ))
        else:
            existing.price_modifier = price_mod
    db.commit()
    print(f"Ensured {len(egg_style_options)} egg_style options for egg_sandwich")

    # 5. Protein (multi-select)
    protein_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "protein"
    ).first()
    if not protein_attr:
        protein_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="protein",
            display_name="Breakfast Protein",
            input_type="multi_select",
            is_required=False,
            allow_none=True,
            display_order=5,
        )
        db.add(protein_attr)
        db.commit()
        print("Created 'protein' attribute for egg_sandwich")

    # Protein options from Zucker's website (slug, display_name, price_modifier)
    protein_options = [
        ("applewood_bacon", "Applewood Smoked Bacon", 2.50),
        ("turkey_bacon", "Turkey Bacon", 2.95),
        ("sausage", "Sausage Patty", 2.75),
        ("chicken_sausage", "Chicken Sausage", 2.95),
        ("smoked_turkey", "Smoked Turkey", 3.45),
        ("ham", "Ham", 2.50),
        ("pastrami", "Pastrami", 3.45),
        ("corned_beef", "Corned Beef", 3.45),
        ("roast_beef", "Roast Beef", 3.45),
    ]
    for slug, display_name, price_mod in protein_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == protein_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=protein_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
            ))
        else:
            existing.price_modifier = price_mod
    db.commit()
    print(f"Ensured {len(protein_options)} protein options for egg_sandwich")

    # 6. Cheese (hard cheeses only, multi-select)
    cheese_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "cheese"
    ).first()
    if not cheese_attr:
        cheese_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="cheese",
            display_name="Cheese",
            input_type="multi_select",
            is_required=False,
            allow_none=True,
            display_order=6,
        )
        db.add(cheese_attr)
        db.commit()
        print("Created 'cheese' attribute for egg_sandwich")

    # Hard cheese options - all $1.50 upcharge
    cheese_options = [
        ("american", "American Cheese", 1.50),
        ("cheddar", "Cheddar", 1.50),
        ("fresh_mozzarella", "Fresh Mozzarella", 1.50),
        ("havarti", "Havarti", 1.50),
        ("muenster", "Muenster", 1.50),
        ("pepper_jack", "Pepper Jack", 1.50),
        ("swiss", "Swiss", 1.50),
        ("provolone", "Provolone", 1.50),
    ]
    for slug, display_name, price_mod in cheese_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == cheese_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=cheese_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
            ))
        else:
            existing.price_modifier = price_mod
    db.commit()
    print(f"Ensured {len(cheese_options)} cheese options for egg_sandwich")

    # 7. Spread (cream cheese + tofu, multi-select)
    spread_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "spread"
    ).first()
    if not spread_attr:
        spread_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="spread",
            display_name="Cream Cheese / Tofu",
            input_type="multi_select",
            is_required=False,
            allow_none=True,
            display_order=7,
        )
        db.add(spread_attr)
        db.commit()
        print("Created 'spread' attribute for egg_sandwich")

    # Cream cheese and tofu options
    spread_options = [
        ("plain_cc", "Plain Cream Cheese", 0.80),
        ("scallion_cc", "Scallion Cream Cheese", 0.90),
        ("veggie_cc", "Veggie Cream Cheese", 0.90),
        ("lox_cc", "Lox Cream Cheese", 0.90),
        ("walnut_raisin_cc", "Walnut Raisin Cream Cheese", 0.90),
        ("jalapeno_cc", "Jalapeno Cream Cheese", 0.90),
        ("honey_walnut_cc", "Honey Walnut Cream Cheese", 0.90),
        ("strawberry_cc", "Strawberry Cream Cheese", 0.90),
        ("blueberry_cc", "Blueberry Cream Cheese", 0.90),
        ("olive_pimento_cc", "Olive Pimento Cream Cheese", 0.90),
        # Premium cream cheeses
        ("nova_scotia_cc", "Nova Scotia Cream Cheese", 1.85),
        ("chipotle_cc", "Chipotle Cream Cheese", 1.85),
        ("truffle_cc", "Truffle Cream Cheese", 1.85),
        # Tofu
        ("plain_tofu", "Plain Tofu", 0.90),
        ("scallion_tofu", "Scallion Tofu", 0.90),
        ("veggie_tofu", "Veggie Tofu", 0.90),
    ]
    for slug, display_name, price_mod in spread_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == spread_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=spread_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
            ))
        else:
            existing.price_modifier = price_mod
    db.commit()
    print(f"Ensured {len(spread_options)} spread options for egg_sandwich")

    # 8. Toppings (multi-select)
    toppings_attr = db.query(AttributeDefinition).filter(
        AttributeDefinition.item_type_id == egg_sandwich_type.id,
        AttributeDefinition.slug == "toppings"
    ).first()
    if not toppings_attr:
        toppings_attr = AttributeDefinition(
            item_type_id=egg_sandwich_type.id,
            slug="toppings",
            display_name="Breakfast Toppings",
            input_type="multi_select",
            is_required=False,
            allow_none=True,
            display_order=8,
        )
        db.add(toppings_attr)
        db.commit()
        print("Created 'toppings' attribute for egg_sandwich")

    # Toppings options from Zucker's website
    toppings_options = [
        ("butter", "Butter", 0.55),
        ("tomatoes", "Tomatoes", 1.00),
        ("lettuce", "Lettuce", 0.60),
        ("onions", "Onions", 0.75),
        ("red_onions", "Red Onions", 0.75),
        ("capers", "Capers", 1.00),
        ("spinach", "Spinach", 1.00),
        ("roasted_peppers", "Roasted Peppers", 1.00),
        ("jalapenos", "Jalapenos", 0.75),
        ("pickles", "Pickles", 0.75),
        ("cucumber", "Cucumber", 0.75),
        ("sauteed_mushrooms", "Sauteed Mushrooms", 1.50),
        ("sauteed_onions", "Sauteed Onions", 1.00),
        ("hash_browns", "Hash Browns", 2.50),
        ("latke", "Breakfast Potato Latke", 2.80),
        ("avocado", "Avocado", 3.50),
        ("extra_egg", "Extra Egg", 2.05),
        ("hot_sauce", "Hot Sauce", 0.0),
    ]
    for slug, display_name, price_mod in toppings_options:
        existing = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == toppings_attr.id,
            AttributeOption.slug == slug
        ).first()
        if not existing:
            db.add(AttributeOption(
                attribute_definition_id=toppings_attr.id,
                slug=slug,
                display_name=display_name,
                price_modifier=price_mod,
            ))
        else:
            existing.price_modifier = price_mod
    db.commit()
    print(f"Ensured {len(toppings_options)} toppings options for egg_sandwich")


def ensure_egg_sandwich_type_attributes(db: Session, egg_sandwich_type: ItemType):
    """Update item_type_attributes table for egg_sandwich with new schema.

    This is the consolidated schema that menu_index_builder reads from first.
    """
    if not egg_sandwich_type:
        return

    # Define the new attribute configuration
    egg_sandwich_attrs = [
        {
            "slug": "bread",
            "display_name": "Bread Choice",
            "input_type": "single_select",
            "is_required": True,
            "ask_in_conversation": True,
            "display_order": 1,
            "question_text": "What kind of bread would you like?",
        },
        {
            "slug": "toasted",
            "display_name": "Toasted",
            "input_type": "boolean",
            "is_required": False,
            "ask_in_conversation": True,
            "display_order": 2,
            "question_text": "Would you like it toasted?",
        },
        {
            "slug": "scooped",
            "display_name": "Scooped Out",
            "input_type": "boolean",
            "is_required": False,
            "ask_in_conversation": False,
            "display_order": 3,
            "question_text": None,
        },
        {
            "slug": "egg_style",
            "display_name": "Egg Preparation",
            "input_type": "single_select",
            "is_required": False,
            "ask_in_conversation": True,
            "display_order": 4,
            "question_text": "How would you like your eggs?",
        },
        {
            "slug": "protein",
            "display_name": "Breakfast Protein",
            "input_type": "multi_select",
            "is_required": False,
            "ask_in_conversation": False,
            "display_order": 5,
            "question_text": None,
        },
        {
            "slug": "cheese",
            "display_name": "Cheese",
            "input_type": "multi_select",
            "is_required": False,
            "ask_in_conversation": False,
            "display_order": 6,
            "question_text": None,
        },
        {
            "slug": "spread",
            "display_name": "Cream Cheese / Tofu",
            "input_type": "multi_select",
            "is_required": False,
            "ask_in_conversation": False,
            "display_order": 7,
            "question_text": None,
        },
        {
            "slug": "toppings",
            "display_name": "Breakfast Toppings",
            "input_type": "multi_select",
            "is_required": False,
            "ask_in_conversation": False,
            "display_order": 8,
            "question_text": None,
        },
    ]

    # Remove old attributes that are no longer needed
    old_slugs_to_remove = ["extras", "_placeholder_6"]
    for old_slug in old_slugs_to_remove:
        old_attr = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == egg_sandwich_type.id,
            ItemTypeAttribute.slug == old_slug
        ).first()
        if old_attr:
            db.delete(old_attr)
            print(f"Removed old '{old_slug}' attribute from egg_sandwich item_type_attributes")

    # Create/update attributes
    for attr_config in egg_sandwich_attrs:
        existing = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == egg_sandwich_type.id,
            ItemTypeAttribute.slug == attr_config["slug"]
        ).first()

        if existing:
            # Update existing attribute
            existing.display_name = attr_config["display_name"]
            existing.input_type = attr_config["input_type"]
            existing.is_required = attr_config["is_required"]
            existing.ask_in_conversation = attr_config["ask_in_conversation"]
            existing.display_order = attr_config["display_order"]
            existing.question_text = attr_config["question_text"]
        else:
            # Create new attribute
            new_attr = ItemTypeAttribute(
                item_type_id=egg_sandwich_type.id,
                slug=attr_config["slug"],
                display_name=attr_config["display_name"],
                input_type=attr_config["input_type"],
                is_required=attr_config["is_required"],
                ask_in_conversation=attr_config["ask_in_conversation"],
                display_order=attr_config["display_order"],
                question_text=attr_config["question_text"],
            )
            db.add(new_attr)
            print(f"Created '{attr_config['slug']}' in item_type_attributes for egg_sandwich")

    db.commit()
    print(f"Ensured {len(egg_sandwich_attrs)} item_type_attributes for egg_sandwich")

    # Now link AttributeOptions to the ItemTypeAttribute records
    for attr_config in egg_sandwich_attrs:
        # Get the ItemTypeAttribute record
        ita = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == egg_sandwich_type.id,
            ItemTypeAttribute.slug == attr_config["slug"]
        ).first()

        if not ita:
            continue

        # Get the corresponding AttributeDefinition record
        ad = db.query(AttributeDefinition).filter(
            AttributeDefinition.item_type_id == egg_sandwich_type.id,
            AttributeDefinition.slug == attr_config["slug"]
        ).first()

        if not ad:
            continue

        # Link the options from attribute_definitions to item_type_attributes
        options = db.query(AttributeOption).filter(
            AttributeOption.attribute_definition_id == ad.id
        ).all()

        linked_count = 0
        for opt in options:
            if opt.item_type_attribute_id != ita.id:
                opt.item_type_attribute_id = ita.id
                linked_count += 1

        if linked_count > 0:
            db.commit()
            print(f"Linked {linked_count} options to '{attr_config['slug']}' item_type_attribute")


def populate_menu_items(db: Session):
    """Populate the menu with Zucker's items.

    Data exported from Neon production database - 271 unique items.
    """
    # Load all item types
    bagel_type = db.query(ItemType).filter(ItemType.slug == "bagel").first()
    signature_sandwich_type = db.query(ItemType).filter(ItemType.slug == "signature_sandwich").first()
    omelette_type = db.query(ItemType).filter(ItemType.slug == "omelette").first()
    spread_sandwich_type = db.query(ItemType).filter(ItemType.slug == "spread_sandwich").first()
    salad_sandwich_type = db.query(ItemType).filter(ItemType.slug == "salad_sandwich").first()
    sized_beverage_type = db.query(ItemType).filter(ItemType.slug == "sized_beverage").first()
    beverage_type = db.query(ItemType).filter(ItemType.slug == "beverage").first()
    fish_sandwich_type = db.query(ItemType).filter(ItemType.slug == "fish_sandwich").first()
    by_the_lb_type = db.query(ItemType).filter(ItemType.slug == "by_the_lb").first()
    cream_cheese_type = db.query(ItemType).filter(ItemType.slug == "cream_cheese").first()
    snack_type = db.query(ItemType).filter(ItemType.slug == "snack").first()
    pastry_type = db.query(ItemType).filter(ItemType.slug == "pastry").first()
    side_type = db.query(ItemType).filter(ItemType.slug == "side").first()
    # New item types from database export
    breakfast_type = db.query(ItemType).filter(ItemType.slug == "breakfast").first()
    deli_classic_type = db.query(ItemType).filter(ItemType.slug == "deli_classic").first()
    egg_sandwich_type = db.query(ItemType).filter(ItemType.slug == "egg_sandwich").first()
    espresso_type = db.query(ItemType).filter(ItemType.slug == "espresso").first()
    salad_type = db.query(ItemType).filter(ItemType.slug == "salad").first()
    soup_type = db.query(ItemType).filter(ItemType.slug == "soup").first()

    # =========================================================================
    # MENU ITEMS - Exported from Neon production database (271 unique items)
    # Last synced: 2026-01-06
    # =========================================================================
    items = [
        # === BAGEL ===
        {"name": "Asiago Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Bagel with Butter", "category": "bagel", "base_price": 3.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Bagel with Cream Cheese", "category": "bagel", "base_price": 5.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Bialy", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Cinnamon Raisin Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Egg Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Everything Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Garlic Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Gluten Free Everything Bagel", "category": "bagel", "base_price": 4.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Gluten Free Plain Bagel", "category": "bagel", "base_price": 4.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Marble Rye Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Onion Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Plain Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Poppy Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Pumpernickel Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Salt Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Sesame Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Wheat Everything Flatz", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Wheat Flatz", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Wheat Health Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Wheat Oat Bran Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Wheat Poppy Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Wheat Sesame Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Whole Wheat Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},

        # === BREAKFAST ===
        {"name": "Fresh Seasonal Fruit Cup", "category": "breakfast", "base_price": 6.95, "is_signature": False, "item_type_id": breakfast_type.id if breakfast_type else None},
        {"name": "Homemade Malted Pecan Granola", "category": "breakfast", "base_price": 6.95, "is_signature": False, "item_type_id": breakfast_type.id if breakfast_type else None},
        {"name": "Low Fat Yogurt Granola Parfait", "category": "breakfast", "base_price": 6.50, "is_signature": False, "item_type_id": breakfast_type.id if breakfast_type else None, "aliases": "low fat yogurt granola parfait"},
        {"name": "Oatmeal", "category": "breakfast", "base_price": 4.95, "is_signature": False, "item_type_id": breakfast_type.id if breakfast_type else None, "aliases": "oatmeal"},
        {"name": "Organic Steel-Cut Oatmeal", "category": "breakfast", "base_price": 5.95, "is_signature": False, "item_type_id": breakfast_type.id if breakfast_type else None, "aliases": "organic steel-cut oatmeal, steel cut oatmeal"},
        {"name": "Yogurt Parfait", "category": "breakfast", "base_price": 6.50, "is_signature": False, "item_type_id": breakfast_type.id if breakfast_type else None, "aliases": "yogurt, yogurt parfait"},

        # === BY_THE_LB ===
        {"name": "Belly Lox (1 lb)", "category": "by_the_lb", "base_price": 44.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "belly, belly salmon"},
        {"name": "Belly Lox (1/4 lb)", "category": "by_the_lb", "base_price": 12.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "belly, belly salmon"},
        {"name": "Everything Seed Salmon (1 lb)", "category": "by_the_lb", "base_price": 48.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Everything Seed Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 13.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Gravlax (1 lb)", "category": "by_the_lb", "base_price": 52.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "cured salmon"},
        {"name": "Gravlax (1/4 lb)", "category": "by_the_lb", "base_price": 14.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "cured salmon"},
        {"name": "Lake Sturgeon (1 lb)", "category": "by_the_lb", "base_price": 84.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "sturgeon, smoked sturgeon"},
        {"name": "Lake Sturgeon (1/4 lb)", "category": "by_the_lb", "base_price": 22.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "sturgeon, smoked sturgeon"},
        {"name": "Nova Scotia Salmon (1 lb)", "category": "by_the_lb", "base_price": 44.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "nova, lox, nova lox, nova scotia salmon (lox), smoked salmon"},
        {"name": "Nova Scotia Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 12.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "nova, lox, nova lox, nova scotia salmon (lox), smoked salmon"},
        {"name": "Pastrami Salmon (1 lb)", "category": "by_the_lb", "base_price": 52.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Pastrami Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 14.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Sable (1 lb)", "category": "by_the_lb", "base_price": 68.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "sable fish, sablefish"},
        {"name": "Sable (1/4 lb)", "category": "by_the_lb", "base_price": 18.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "sable fish, sablefish"},
        {"name": "Scottish Salmon (1 lb)", "category": "by_the_lb", "base_price": 56.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Scottish Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 15.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Smoked Trout (1 lb)", "category": "by_the_lb", "base_price": 40.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "trout"},
        {"name": "Smoked Trout (1/4 lb)", "category": "by_the_lb", "base_price": 11.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "trout"},
        {"name": "Whitefish (Whole)", "category": "by_the_lb", "base_price": 28.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "whole whitefish"},
        {"name": "Whitefish Salad (1 lb)", "category": "by_the_lb", "base_price": 32.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "whitefish"},
        {"name": "Whitefish Salad (1/4 lb)", "category": "by_the_lb", "base_price": 9.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None, "aliases": "whitefish"},
        {"name": "Wild Pacific Salmon (1 lb)", "category": "by_the_lb", "base_price": 52.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Wild Pacific Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 14.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},

        # === CREAM_CHEESE ===
        {"name": "Blueberry Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "blueberry cc"},
        {"name": "Blueberry Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "blueberry cc"},
        {"name": "Jalapeno Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "jalapeno cc, spicy cream cheese"},
        {"name": "Jalapeno Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "jalapeno cc, spicy cream cheese"},
        {"name": "Kalamata Olive Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 20.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "olive cc, olive cream cheese"},
        {"name": "Kalamata Olive Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.50, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "olive cc, olive cream cheese"},
        {"name": "Maple Raisin Walnut Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 22.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "maple walnut cc, maple raisin cc"},
        {"name": "Maple Raisin Walnut Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 6.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "maple walnut cc, maple raisin cc"},
        {"name": "Nova Scotia Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 26.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "lox spread, nova cc, nova spread"},
        {"name": "Nova Scotia Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 7.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "lox spread, nova cc, nova spread"},
        {"name": "Plain Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 16.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "plain cc, regular cream cheese, regular cc"},
        {"name": "Plain Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 4.50, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "plain cc, regular cream cheese, regular cc"},
        {"name": "Scallion Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "scallion cc, chive cream cheese, chive cc"},
        {"name": "Scallion Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "scallion cc, chive cream cheese, chive cc"},
        {"name": "Strawberry Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "strawberry cc"},
        {"name": "Strawberry Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "strawberry cc"},
        {"name": "Sun-Dried Tomato Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 20.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "sun dried tomato cc, tomato cc"},
        {"name": "Sun-Dried Tomato Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.50, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "sun dried tomato cc, tomato cc"},
        {"name": "Tofu Plain (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Tofu Plain (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Truffle Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 30.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "truffle cc"},
        {"name": "Truffle Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 8.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "truffle cc"},
        {"name": "Vegetable Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "veggie cream cheese, veggie cc, vegetable cc"},
        {"name": "Vegetable Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None, "aliases": "veggie cream cheese, veggie cc, vegetable cc"},

        # === DELI_CLASSIC ===
        {"name": "All-Natural Smoked Turkey Sandwich", "category": "deli_classic", "base_price": 14.50, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},
        {"name": "Black Forest Ham Sandwich", "category": "deli_classic", "base_price": 14.50, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},
        {"name": "Chicken Cutlet Sandwich", "category": "deli_classic", "base_price": 13.50, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},
        {"name": "Grilled Cheese", "category": "deli_classic", "base_price": 8.95, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None, "aliases": "grilled cheese, grilled cheese sandwich"},
        {"name": "Homemade Roast Turkey Sandwich", "category": "deli_classic", "base_price": 14.50, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},
        {"name": "Hot Corned Beef Sandwich", "category": "deli_classic", "base_price": 16.95, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},
        {"name": "Kosher Beef Salami Sandwich", "category": "deli_classic", "base_price": 12.50, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},
        {"name": "Top Round Roast Beef Sandwich", "category": "deli_classic", "base_price": 14.50, "is_signature": False, "item_type_id": deli_classic_type.id if deli_classic_type else None},

        # === DRINK ===
        {"name": "Americano", "category": "drink", "base_price": 4.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "amercano, americano"},
        {"name": "Apple Juice", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "apple juice"},
        {"name": "Bottled Water", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "water, bottled water"},
        {"name": "Boylan's Ginger Ale", "category": "drink", "base_price": 3.25, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "boylans ginger ale, boylan ginger ale"},
        {"name": "Boylan's Root Beer", "category": "drink", "base_price": 3.25, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "root beer, boylans root beer, boylan root beer"},
        {"name": "Cafe au Lait", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "cafe au lait, au lait"},
        {"name": "Cappuccino", "category": "drink", "base_price": 5.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "appuccino, cappuccinno, cappuccino, cappucino, capuccino, capuchino"},
        {"name": "Chai Tea", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "chai, iced chai, iced chai tea"},
        {"name": "Chamomile Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "chamomile"},
        {"name": "Chocolate Milk", "category": "drink", "base_price": 4.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "choc milk, chocolate milk, chocolate milks"},
        {"name": "Coca-Cola", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "coca cola, coca-cola, coke"},
        {"name": "Coffee", "category": "drink", "base_price": 3.45, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "drip, drip coffee, regular coffee"},
        {"name": "Cold Brew", "category": "drink", "base_price": 4.75, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "cold brew, coldbrew"},
        {"name": "Cranberry Juice", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "cranberry juice, cran juice"},
        {"name": "Diet Coke", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "diet coca cola, diet coca-cola, diet coke"},
        {"name": "Dr. Brown's Black Cherry", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "dr brown's black cherry, dr browns black cherry, dr. browns black cherry"},
        {"name": "Dr. Brown's Cel-Ray", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "cel-ray, celray, dr brown's cel-ray, dr browns cel-ray, dr. browns cel-ray"},
        {"name": "Dr. Brown's Cream Soda", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "dr brown's, dr brown's cream soda, dr browns, dr browns cream soda, dr. brown's, dr. browns, dr. browns cream soda"},
        {"name": "Earl Grey Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "earl grey"},
        {"name": "English Breakfast Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "english breakfast"},
        {"name": "Espresso", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": espresso_type.id if espresso_type else None, "aliases": "espresso, esspresso, expreso, expresso"},
        {"name": "Fresh Squeezed Orange Juice", "category": "drink", "base_price": 6.95, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "fresh oj, fresh squeezed orange juice, oj, orange juice"},
        {"name": "Ginger Ale", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "ginger ale"},
        {"name": "Green Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "green tea"},
        {"name": "Hot Chocolate", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "hot cocoa, cocoa"},
        {"name": "Hot Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "hot tea, tea"},
        {"name": "ITO EN Green Tea", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "ito en, itoen, ito en green tea"},
        {"name": "Iced Tea", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "iced tea"},
        {"name": "Latte", "category": "drink", "base_price": 5.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "late, latte, lattee"},
        {"name": "Macchiato", "category": "drink", "base_price": 4.25, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "macchiato, machato, machiato"},
        {"name": "Peppermint Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None, "aliases": "peppermint"},
        {"name": "Poland Spring", "category": "drink", "base_price": 2.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "poland spring"},
        {"name": "San Pellegrino", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "pellegrino, san pellegrino, sparkling water, seltzer"},
        {"name": "Snapple Iced Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "snapple iced tea, snapple tea"},
        {"name": "Snapple Lemonade", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "snapple lemonade"},
        {"name": "Snapple Peach Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "snapple peach, snapple peach tea"},
        {"name": "Sprite", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "sprite"},
        {"name": "Tropicana Orange Juice 46 oz", "category": "drink", "base_price": 7.60, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "large tropicana, tropicana 46, tropicana 46 oz, tropicana orange juice, tropicana orange juice 46 oz"},
        {"name": "Tropicana Orange Juice No Pulp", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None, "aliases": "tropicana, tropicana no pulp, tropicana oj, tropicana orange juice"},

        # === EGG_SANDWICH ===
        {"name": "Scrambled Eggs on Bagel", "category": "egg_sandwich", "base_price": 6.88, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "aliases": "scrambled eggs on bagel, scrambled egg bagel, scrambled eggs bagel"},
        {"name": "The Chelsea", "category": "egg_sandwich", "base_price": 10.95, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "default_config": {"bread": "Whole Wheat Bagel", "toppings": ["Egg White", "Avocado", "Tomato"]}, "aliases": "the chelsea, chelsea"},
        {"name": "The Columbus", "category": "egg_sandwich", "base_price": 10.95, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "description": "Three Egg Whites, Turkey Bacon, Avocado, and Swiss Cheese", "default_config": {"bread": "Everything Bagel", "protein": "Sausage", "cheese": "American", "toppings": ["Egg"]}, "aliases": "the columbus, columbus"},
        {"name": "The Health Nut Egg Sandwich", "category": "egg_sandwich", "base_price": 12.50, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "aliases": "the health nut egg sandwich, health nut egg sandwich, health nut egg"},
        {"name": "The Hudson", "category": "egg_sandwich", "base_price": 11.95, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "default_config": {"bread": "Bagel", "protein": "Nova Scotia Salmon", "toppings": ["Scrambled Eggs", "Onion"]}, "aliases": "the hudson, hudson"},
        {"name": "The Latke BEC", "category": "egg_sandwich", "base_price": 13.50, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "description": "Two Eggs, Applewood Smoked Bacon, Cheddar, and a Breakfast Potato Latke", "aliases": "latke bec, the latke bec"},
        {"name": "The Lexington", "category": "egg_sandwich", "base_price": 9.25, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "description": "Egg Whites, Swiss, and Spinach", "default_config": {"bread": "Bagel", "protein": "Egg White", "cheese": "Swiss", "toppings": ["Spinach"]}, "aliases": "the lexington, lexington"},
        {"name": "The Midtown", "category": "egg_sandwich", "base_price": 10.50, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "default_config": {"bread": "Bagel", "protein": "Bacon", "cheese": "Cheddar", "toppings": ["Egg", "Jalapeño"]}, "aliases": "the midtown, midtown"},
        {"name": "The Truffled Egg", "category": "egg_sandwich", "base_price": 21.95, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "description": "Two Eggs, Swiss, Truffle Cream Cheese, and Sauteed Mushrooms", "aliases": "the truffled egg, truffled egg, truffled egg sandwich"},
        {"name": "The Wall Street", "category": "egg_sandwich", "base_price": 10.95, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "default_config": {"bread": "Everything Bagel", "protein": "Turkey Bacon", "cheese": "Swiss", "toppings": ["Egg White"]}, "aliases": "the wall street, wall street"},
        {"name": "Two Scrambled Eggs on Bagel", "category": "egg_sandwich", "base_price": 6.88, "is_signature": True, "item_type_id": egg_sandwich_type.id if egg_sandwich_type else None, "aliases": "two scrambled eggs on bagel, 2 scrambled eggs on bagel"},

        # === FISH_SANDWICH ===
        {"name": "Gravlax Sandwich", "category": "fish_sandwich", "base_price": 18.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "default_config": {"fish": "Gravlax"}, "aliases": "cured salmon, gravlax, gravlax on bagel, gravlax sandwich"},
        {"name": "Nova Scotia Salmon Sandwich", "category": "fish_sandwich", "base_price": 16.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "default_config": {"fish": "Nova Scotia Salmon"}, "aliases": "lox, lox sandwich, nova, nova lox, nova lox sandwich, nova on bagel, nova sandwich, nova scotia salmon (lox), smoked salmon"},
        {"name": "Sable Sandwich", "category": "fish_sandwich", "base_price": 24.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "default_config": {"fish": "Sable"}, "aliases": "sable fish, sablefish"},
        {"name": "Sturgeon Sandwich", "category": "fish_sandwich", "base_price": 29.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "default_config": {"fish": "Lake Sturgeon"}},
        {"name": "The Alton Brown", "category": "fish_sandwich", "base_price": 21.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "description": "Smoked Trout with Plain Cream Cheese, Avocado Horseradish, and Tobiko", "default_config": {"fish": "Smoked Trout", "spread": "Plain Cream Cheese", "extras": ["Avocado Horseradish", "Tobiko"]}, "aliases": "the alton brown, alton brown"},
        {"name": "The Flatiron", "category": "fish_sandwich", "base_price": 19.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "description": "Everything-seeded Salmon with Scallion Cream Cheese and Fresh Avocado", "default_config": {"fish": "Everything Seeded Salmon", "spread": "Scallion Cream Cheese", "extras": ["Avocado"]}, "aliases": "the flatiron, flatiron, the flatiron traditional, flatiron traditional"},
        {"name": "The Max Zucker", "category": "fish_sandwich", "base_price": 17.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "description": "Smoked Whitefish Salad with Beefsteak Tomatoes and Red Onions", "default_config": {"fish": "Whitefish Salad", "extras": ["Tomato", "Red Onion"]}, "aliases": "the max zucker, max zucker"},
        {"name": "The Zucker's Traditional", "category": "fish_sandwich", "base_price": 18.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "description": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers", "default_config": {"fish": "Nova Scotia Salmon", "spread": "Plain Cream Cheese", "extras": ["Tomato", "Red Onion", "Capers"]}, "aliases": "the traditional, traditional, the zucker's traditional, zucker's traditional, zuckers traditional, the zuckers traditional"},

        # === OMELETTE ===
        {"name": "Bacon and Cheddar Omelette", "category": "omelette", "base_price": 13.50, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"protein": "Applewood Smoked Bacon", "cheese": "Cheddar", "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "bacon and cheddar omelette, bacon cheddar omelette"},
        {"name": "Cheese Omelette", "category": "omelette", "base_price": 12.95, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"cheese": "American", "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "cheese omelet, cheese omelette"},
        {"name": "Corned Beef Omelette", "category": "omelette", "base_price": 13.63, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "corned beef omelet, corned beef omelette"},
        {"name": "Egg White Avocado Omelette", "category": "omelette", "base_price": 14.72, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "avocado omelet, avocado omelette, egg white avocado omelet, egg white avocado omelette"},
        {"name": "Pastrami Omelette", "category": "omelette", "base_price": 13.63, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "pastrami omelet, pastrami omelette"},
        {"name": "Salami Omelette", "category": "omelette", "base_price": 13.63, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "salami omelet, salami omelette"},
        {"name": "Sausage Omelette", "category": "omelette", "base_price": 13.63, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "sausage omelet, sausage omelette"},
        {"name": "Southwest Omelette", "category": "omelette", "base_price": 15.53, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "southwest omelet, southwest omelette"},
        {"name": "Spinach & Feta Omelette", "category": "omelette", "base_price": 14.50, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"cheese": "Feta", "extras": ["Spinach"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "spinach & feta omelet, spinach and feta omelet, spinach and feta omelette, spinach feta omelet, spinach feta omelette"},
        {"name": "The Chipotle Egg Omelette", "category": "omelette", "base_price": 15.50, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "description": "Three Eggs with Pepper Jack Cheese, Jalapenos, and Chipotle Cream Cheese", "default_config": {"cheese": "Pepper Jack", "spread": "Chipotle Cream Cheese", "extras": ["Avocado", "Pico de Gallo"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "the chipotle egg omelette, chipotle egg omelette, chipotle omelette"},
        {"name": "The Columbus Omelette", "category": "omelette", "base_price": 13.50, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"eggs": "Egg Whites", "protein": "Turkey Bacon", "cheese": "Swiss", "extras": ["Avocado"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "the columbus omelette, columbus omelette"},
        {"name": "The Delancey Omelette", "category": "omelette", "base_price": 15.25, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "description": "Three Eggs with Corned Beef or Pastrami, Onions, and Swiss Cheese", "default_config": {"protein": "Corned Beef", "cheese": "Swiss", "extras": ["Potato Latke", "Sautéed Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "the delancey omelette, delancey omelette"},
        {"name": "The Health Nut Omelette", "category": "omelette", "base_price": 11.75, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "description": "Three Egg Whites with Mushrooms, Spinach, Green & Red Peppers, and Tomatoes", "default_config": {"eggs": "Egg Whites", "extras": ["Mushrooms", "Spinach", "Green Peppers", "Red Peppers", "Tomatoes"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "the health nut omelette, health nut omelette"},
        {"name": "The Lexington Omelette", "category": "omelette", "base_price": 11.95, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"eggs": "Egg Whites", "cheese": "Swiss", "extras": ["Spinach"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "the lexington omelette, lexington omelette"},
        {"name": "The Mulberry Omelette", "category": "omelette", "base_price": 13.65, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "description": "Two Eggs, Espositos Sausage, Green & Red Peppers, and Sauteed Onions", "default_config": {"protein": "Esposito's Sausage", "extras": ["Green Peppers", "Red Peppers", "Sautéed Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "mulberry, mulberry omelette, the mulberry, the mulberry omelette"},
        {"name": "The Nova Omelette", "category": "omelette", "base_price": 14.95, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"protein": "Nova Scotia Salmon", "extras": ["Sautéed Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "nova omelette, the nova omelette"},
        {"name": "The Truffled Egg Omelette", "category": "omelette", "base_price": 15.50, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"cheese": "Swiss", "spread": "Truffle Cream Cheese", "extras": ["Sautéed Mushrooms"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "the truffled egg omelette, truffled egg omelette"},
        {"name": "Truffle Omelette", "category": "omelette", "base_price": 14.72, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "truffle omelet, truffle omelette"},
        {"name": "Turkey Omelette", "category": "omelette", "base_price": 13.63, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "aliases": "turkey omelet, turkey omelette"},
        {"name": "Veggie Omelette", "category": "omelette", "base_price": 13.95, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"extras": ["Mushrooms", "Spinach", "Tomatoes", "Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "veggie omelet, veggie omelette"},
        {"name": "Western Omelette", "category": "omelette", "base_price": 14.95, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None, "default_config": {"protein": "Ham", "extras": ["Green Peppers", "Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}, "aliases": "western omelet, western omelette"},

        # === PASTRY ===
        {"name": "Apple Cinnamon Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Babka - Chocolate", "category": "pastry", "base_price": 14.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Babka - Cinnamon", "category": "pastry", "base_price": 14.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Banana Walnut Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Black & White Cookie", "category": "pastry", "base_price": 4.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Black & White Cookie Minis (3-Pack)", "category": "pastry", "base_price": 4.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Blondie Square", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Blueberry Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Brownie", "category": "pastry", "base_price": 4.50, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Chocolate Chip Cookie", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Chocolate Chip Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Chocolate-Dipped Macaroons (3-Pack)", "category": "pastry", "base_price": 4.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Corn Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Cranberry Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Danish", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Double-Chocolate Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Halvah Bar", "category": "pastry", "base_price": 1.25, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Jelly Rings (3-Pack)", "category": "pastry", "base_price": 1.25, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Lemon Poppy Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Morning Glory Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Oatmeal Raisin Cookie", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Peanut Butter Cookie", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Pecan Pie Square", "category": "pastry", "base_price": 3.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Pound Cake", "category": "pastry", "base_price": 3.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Rice Krispy Treat", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Rugelach (3-Pack)", "category": "pastry", "base_price": 4.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Russian Coffee Cake", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},

        # === SALAD ===
        {"name": "The Caesar", "category": "salad", "base_price": 9.95, "is_signature": False, "item_type_id": salad_type.id if salad_type else None},
        {"name": "The Garden", "category": "salad", "base_price": 8.95, "is_signature": False, "item_type_id": salad_type.id if salad_type else None},

        # === SALAD_SANDWICH ===
        {"name": "Baked Salmon Salad Sandwich", "category": "salad_sandwich", "base_price": 14.50, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Baked Salmon Salad"}, "aliases": "baked salmon salad, salmon salad sandwich"},
        {"name": "Chicken Salad Sandwich", "category": "salad_sandwich", "base_price": 13.50, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Chicken Salad"}, "aliases": "chicken salad"},
        {"name": "Cranberry Pecan Chicken Salad Sandwich", "category": "salad_sandwich", "base_price": 14.50, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Cranberry Pecan Chicken Salad"}, "aliases": "cranberry chicken salad, cranberry pecan chicken salad"},
        {"name": "Egg Salad Sandwich", "category": "salad_sandwich", "base_price": 9.95, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Egg Salad"}, "aliases": "egg salad"},
        {"name": "Lemon Chicken Salad Sandwich", "category": "salad_sandwich", "base_price": 14.25, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Lemon Chicken Salad"}, "aliases": "lemon chicken salad"},
        {"name": "Tuna Salad Sandwich", "category": "salad_sandwich", "base_price": 13.15, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Tuna Salad"}, "aliases": "tuna salad, tuna sandwich"},
        {"name": "Whitefish Salad Sandwich", "category": "salad_sandwich", "base_price": 15.13, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None, "default_config": {"salad": "Whitefish Salad"}, "aliases": "whitefish, whitefish salad, whitefish sandwich"},

        # === SANDWICH ===
        {"name": "Italian Stallion", "category": "sandwich", "base_price": 9.49, "is_signature": True},

        # === SIDE ===
        {"name": "Applewood Chicken Sausage", "category": "side", "base_price": 4.85, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Bacon", "category": "side", "base_price": 4.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "bacon, side of bacon"},
        {"name": "Bagel Chips", "category": "side", "base_price": 3.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "bagel chips"},
        {"name": "Cole Slaw", "category": "side", "base_price": 3.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "cole slaw, coleslaw"},
        {"name": "Fruit Cup", "category": "side", "base_price": 6.95, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "fruit cup"},
        {"name": "Fruit Salad", "category": "side", "base_price": 7.95, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "fruit salad"},
        {"name": "Kosher Beef Salami Side", "category": "side", "base_price": 4.85, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Latkes", "category": "side", "base_price": 5.95, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "latkes, potato latkes"},
        {"name": "Macaroni Salad", "category": "side", "base_price": 3.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "macaroni salad"},
        {"name": "Potato Salad", "category": "side", "base_price": 3.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "potato salad"},
        {"name": "Side of Ham", "category": "side", "base_price": 4.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "ham, side ham"},
        {"name": "Side of Sausage", "category": "side", "base_price": 4.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "esposito's sausage, espositos sausage, sausage, side of sausage"},
        {"name": "Turkey Bacon", "category": "side", "base_price": 4.50, "is_signature": False, "item_type_id": side_type.id if side_type else None, "aliases": "side of turkey bacon, turkey bacon"},
        {"name": "Two Deviled Eggs", "category": "side", "base_price": 3.95, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Two Hardboiled Eggs", "category": "side", "base_price": 3.95, "is_signature": False, "item_type_id": side_type.id if side_type else None},

        # === SIGNATURE ===
        {"name": "HEC", "category": "signature", "base_price": 9.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "default_config": {"bread": "Everything Bagel", "protein": "Ham", "cheese": "American", "extras": ["Egg"]}, "aliases": "hec, h.e.c., h.e.c, ham egg and cheese bagel, ham egg and cheese, ham egg cheese, ham eggs and cheese, ham eggs cheese, ham and egg and cheese, egg ham and cheese, egg and ham and cheese, egg ham cheese"},
        {"name": "Hot Pastrami Sandwich", "category": "signature", "base_price": 18.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "default_config": {"bread": "New York Rye", "protein": "Pastrami", "extras": ["Mustard"]}, "aliases": "hot pastrami, hot pastrami sandwich, pastrami sandwich"},
        {"name": "Nova Scotia Salmon on Bagel", "category": "signature", "base_price": 16.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "default_config": {"bread": "Plain Bagel", "protein": "Nova Scotia Salmon", "extras": ["Cream Cheese", "Tomato", "Onion", "Capers"]}, "aliases": "nova scotia salmon, nova salmon, nova on bagel, lox on bagel"},
        {"name": "SEC", "category": "signature", "base_price": 9.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "default_config": {"bread": "Everything Bagel", "protein": "Sausage", "cheese": "American", "extras": ["Egg"]}, "aliases": "sec, s.e.c., s.e.c, sausage egg and cheese bagel, sausage egg and cheese, sausage egg cheese, sausage eggs and cheese, sausage eggs cheese, sausage and egg and cheese, egg sausage and cheese, egg and sausage and cheese, egg sausage cheese"},
        {"name": "The Avocado Toast", "category": "signature", "base_price": 12.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Crushed Avocado with Diced Tomatoes, Lemon Everything Seeds, Salt and Pepper", "default_config": {"bread": "Everything Bagel", "extras": ["Avocado", "Egg", "Everything Seeds"]}, "aliases": "the avocado toast, avocado toast"},
        {"name": "The BLT", "category": "signature", "base_price": 12.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Applewood Smoked Bacon, Lettuce, Beefsteak Tomatoes, and Mayo", "default_config": {"bread": "Plain Bagel", "protein": "Bacon", "extras": ["Lettuce", "Tomato", "Mayo"]}, "aliases": "b.l.t, b.l.t., blt, the blt"},
        {"name": "The Chelsea Club", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Chicken Salad, Cheddar, Smoked Bacon, Beefsteak Tomatoes, Lettuce, and Red Onions", "default_config": {"bread": "Plain Bagel", "protein": "Chicken Salad", "cheese": "Cheddar", "extras": ["Bacon", "Tomato", "Lettuce", "Red Onion"]}, "aliases": "chelsea club, the chelsea club"},
        {"name": "The Classic BEC", "category": "signature", "base_price": 9.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Two Eggs, Applewood Smoked Bacon, and Cheddar", "default_config": {"bread": "Everything Bagel", "protein": "Bacon", "cheese": "American", "extras": ["Egg"]}, "aliases": "the classic bec, classic bec, bec, b.e.c., b.e.c, bacon egg and cheese, bacon egg cheese, bacon and egg and cheese, bacon eggs and cheese, bacon eggs cheese, egg bacon and cheese, egg and bacon and cheese, egg bacon cheese, bacon n egg n cheese, bacon n egg and cheese, the classic, classic"},
        {"name": "The Delancey", "category": "signature", "base_price": 11.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Two Eggs, Corned Beef or Pastrami, Breakfast Potato Latke, Sauteed Onions, and Swiss", "default_config": {"bread": "Bialy", "protein": "Pastrami", "extras": ["Scrambled Eggs", "Mustard"]}, "aliases": "the delancey, delancey"},
        {"name": "The Grand Central", "category": "signature", "base_price": 16.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Grilled Chicken, Smoked Bacon, Beefsteak Tomatoes, Romaine, and Dijon Mayo", "default_config": {"bread": "Plain Bagel", "protein": "Grilled Chicken", "extras": ["Bacon", "Tomato", "Lettuce", "Dijon Mayo"]}, "aliases": "the grand central, grand central"},
        {"name": "The Health Nut", "category": "signature", "base_price": 10.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes", "default_config": {"bread": "Whole Wheat Bagel", "extras": ["Egg White", "Avocado", "Tomato"]}, "aliases": "the health nut, health nut"},
        {"name": "The Leo", "category": "signature", "base_price": 14.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Smoked Nova Scotia Salmon, Eggs, and Sauteed Onions", "default_config": {"bread": "Plain Bagel", "protein": "Nova Scotia Salmon", "extras": ["Scrambled Eggs", "Onion"]}, "aliases": "the leo, leo"},
        {"name": "The Natural", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Smoked Turkey, Brie, Beefsteak Tomatoes, Lettuce, and Dijon Dill Sauce", "default_config": {"bread": "Whole Wheat Bagel", "protein": "Smoked Turkey", "cheese": "Brie", "extras": ["Tomato", "Lettuce", "Dijon Dill Sauce"]}, "aliases": "natural, the natural"},
        {"name": "The Reuben", "category": "signature", "base_price": 19.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Corned Beef, Pastrami, or Roast Turkey with Sauerkraut, Swiss Cheese, and Russian Dressing", "default_config": {"bread": "New York Rye", "protein": "Corned Beef", "cheese": "Swiss", "extras": ["Sauerkraut", "Russian Dressing"]}, "aliases": "the reuben, reuben"},
        {"name": "The Tribeca", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "description": "Roast Turkey, Havarti, Romaine, Beefsteak Tomatoes, Basil Mayo, and Cracked Black Pepper", "default_config": {"bread": "Plain Bagel", "protein": "Turkey", "cheese": "Havarti", "extras": ["Tomato", "Lettuce", "Basil Mayo"]}, "aliases": "the tribeca, tribeca"},
        {"name": "Turkey Club", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None, "default_config": {"bread": "Plain Bagel", "protein": "Turkey", "extras": ["Bacon", "Lettuce", "Tomato", "Mayo"]}, "aliases": "the turkey club, turkey club"},

        # === SMOKED_FISH_SANDWICH ===
        {"name": "Baked Kippered Salmon Sandwich", "category": "smoked_fish_sandwich", "base_price": 18.65, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Belly Lox Sandwich", "category": "smoked_fish_sandwich", "base_price": 18.65, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "aliases": "belly, belly lox, belly lox on bagel, belly lox sandwich, belly salmon, lox"},
        {"name": "Everything Seeded Salmon Sandwich", "category": "smoked_fish_sandwich", "base_price": 18.98, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Herring Tidbits on Bagel", "category": "smoked_fish_sandwich", "base_price": 12.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Lake Sturgeon Sandwich", "category": "smoked_fish_sandwich", "base_price": 22.50, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "aliases": "sturgeon, smoked sturgeon"},
        {"name": "Pastrami Salmon Sandwich", "category": "smoked_fish_sandwich", "base_price": 19.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Scottish Salmon Sandwich", "category": "smoked_fish_sandwich", "base_price": 19.50, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Smoked Trout Sandwich", "category": "smoked_fish_sandwich", "base_price": 18.65, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None, "aliases": "trout"},
        {"name": "Whitefish Sandwich", "category": "smoked_fish_sandwich", "base_price": 16.50, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Wild Coho Salmon Sandwich", "category": "smoked_fish_sandwich", "base_price": 22.50, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},
        {"name": "Wild Pacific Salmon Sandwich", "category": "smoked_fish_sandwich", "base_price": 22.50, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None},

        # === SNACK ===
        {"name": "Bagel Chips - BBQ", "category": "snack", "base_price": 3.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Bagel Chips - Salt", "category": "snack", "base_price": 3.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Bagel Chips - Sea Salt & Vinegar", "category": "snack", "base_price": 3.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Kettle Chips", "category": "snack", "base_price": 2.75, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Potato Chips", "category": "snack", "base_price": 2.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},

        # === SOUP ===
        {"name": "Chicken Noodle Soup", "category": "soup", "base_price": 7.50, "is_signature": False, "item_type_id": soup_type.id if soup_type else None},
        {"name": "Lentil Soup", "category": "soup", "base_price": 6.95, "is_signature": False, "item_type_id": soup_type.id if soup_type else None},
        {"name": "Soup of the Day", "category": "soup", "base_price": 7.50, "is_signature": False, "item_type_id": soup_type.id if soup_type else None},

        # === SPREAD_SANDWICH ===
        {"name": "Avocado Spread Sandwich", "category": "spread_sandwich", "base_price": 6.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Avocado Spread"}, "aliases": "avocado spread"},
        {"name": "Blueberry Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Blueberry Cream Cheese"}, "aliases": "blueberry cc, blueberry cream cheese"},
        {"name": "Butter Sandwich", "category": "spread_sandwich", "base_price": 3.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Butter"}, "aliases": "bagel with butter"},
        {"name": "Hummus Sandwich", "category": "spread_sandwich", "base_price": 5.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Hummus"}, "aliases": "hummus, hummus bagel"},
        {"name": "Jalapeno Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Jalapeno Cream Cheese"}, "aliases": "jalapeno cc, jalapeno cream cheese, spicy cream cheese"},
        {"name": "Kalamata Olive Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Kalamata Olive Cream Cheese"}, "aliases": "olive cc, olive cream cheese"},
        {"name": "Maple Raisin Walnut Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 6.25, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Maple Raisin Walnut Cream Cheese"}, "aliases": "maple raisin cc, maple raisin walnut, maple walnut cc, maple walnut cream cheese"},
        {"name": "Nova Scotia Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 6.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Nova Scotia Cream Cheese"}, "aliases": "lox spread, lox spread sandwich, nova cc, nova cream cheese, nova spread"},
        {"name": "Nutella Sandwich", "category": "spread_sandwich", "base_price": 4.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Nutella"}, "aliases": "nutella bagel"},
        {"name": "Peanut Butter Sandwich", "category": "spread_sandwich", "base_price": 4.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Peanut Butter"}, "aliases": "peanut butter bagel"},
        {"name": "Plain Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.25, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Plain Cream Cheese"}, "aliases": "plain cc, plain cream cheese, regular cc, regular cream cheese"},
        {"name": "Scallion Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Scallion Cream Cheese"}, "aliases": "chive cc, chive cream cheese, scallion cc, scallion cream cheese"},
        {"name": "Strawberry Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Strawberry Cream Cheese"}, "aliases": "strawberry cc, strawberry cream cheese"},
        {"name": "Sun-Dried Tomato Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Sun-Dried Tomato Cream Cheese"}, "aliases": "sun dried tomato cc, sun dried tomato cream cheese, tomato cc"},
        {"name": "Tofu Nova Sandwich", "category": "spread_sandwich", "base_price": 6.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Tofu Nova"}, "aliases": "nova tofu, tofu nova"},
        {"name": "Tofu Plain Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Tofu Plain"}, "aliases": "plain tofu, tofu plain"},
        {"name": "Tofu Scallion Sandwich", "category": "spread_sandwich", "base_price": 5.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Tofu Scallion"}, "aliases": "scallion tofu, tofu scallion"},
        {"name": "Tofu Vegetable Sandwich", "category": "spread_sandwich", "base_price": 5.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Tofu Vegetable"}, "aliases": "tofu vegetable, tofu veggie, veggie tofu"},
        {"name": "Truffle Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 7.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Truffle Cream Cheese"}, "aliases": "truffle cc, truffle cream cheese"},
        {"name": "Vegetable Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None, "default_config": {"spread": "Vegetable Cream Cheese"}, "aliases": "vegetable cc, vegetable cream cheese, veggie cc, veggie cream cheese"},
    ]

    added = 0
    relational_created = 0
    for item_data in items:
        existing = db.query(MenuItem).filter(MenuItem.name == item_data["name"]).first()
        if not existing:
            menu_item = MenuItem(**item_data)
            db.add(menu_item)
            db.flush()  # Get ID for relational records
            added += 1
        else:
            # Update existing item
            for key, value in item_data.items():
                setattr(existing, key, value)
            menu_item = existing

        # Create relational attribute values if default_config exists
        config = item_data.get("default_config")
        if config and menu_item.item_type_id:
            create_relational_attribute_values(db, menu_item, config)
            relational_created += 1

    db.commit()
    print(f"Added/updated {len(items)} menu items ({added} new)")
    print(f"Created relational attribute values for {relational_created} items")


def main():
    print("Populating Zucker's Bagels menu...")
    print(f"Database: {os.getenv('DATABASE_URL', 'Not set')[:50]}...")

    db = SessionLocal()

    try:
        # NOTE: Skipping clear_existing_menu to preserve order_items foreign key references
        # clear_existing_menu(db)

        ensure_company_and_stores(db)
        (bagel_type, sandwich_type, omelette_type, spread_sandwich_type,
         salad_sandwich_type, sized_beverage_type, beverage_type,
         fish_sandwich_type, by_the_lb_type, cream_cheese_type, snack_type,
         pastry_type, side_type, breakfast_type, deli_classic_type,
         egg_sandwich_type, espresso_type, salad_type, soup_type) = ensure_item_types(db)
        ensure_bread_ingredients(db)
        ensure_schmear_ingredients(db)
        ensure_protein_ingredients(db)
        ensure_topping_ingredients(db)
        ensure_sauce_ingredients(db)

        # Set up attributes for the new sandwich types
        ensure_spread_sandwich_attributes(db, spread_sandwich_type)
        ensure_salad_sandwich_attributes(db, salad_sandwich_type)
        ensure_egg_sandwich_attributes(db, egg_sandwich_type)

        # Update consolidated item_type_attributes table
        ensure_egg_sandwich_type_attributes(db, egg_sandwich_type)

        populate_menu_items(db)

        print("\nMenu population complete!")
        print("\nMenu summary:")
        for cat in ["bagel", "signature", "omelette", "drink", "side", "spread_sandwich",
                    "salad_sandwich", "fish_sandwich", "by_the_lb", "cream_cheese", "snack",
                    "pastry", "breakfast", "deli_classic", "egg_sandwich", "salad",
                    "smoked_fish_sandwich", "soup", "sandwich"]:
            count = db.query(MenuItem).filter(MenuItem.category == cat).count()
            if count > 0:
                print(f"  {cat}: {count} items")

        print("\nIngredient summary:")
        for cat in ["bread", "cheese", "protein", "topping", "sauce"]:
            count = db.query(Ingredient).filter(Ingredient.category == cat).count()
            print(f"  {cat}: {count} ingredients")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
