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
    AttributeDefinition, AttributeOption
)


def clear_existing_menu(db: Session):
    """Clear existing menu items (optional - use with caution)."""
    count = db.query(MenuItem).delete()
    db.commit()
    print(f"Deleted {count} existing menu items")


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
            display_name="Beverage",
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

    return (bagel_type, sandwich_type, omelette_type, spread_sandwich_type,
            salad_sandwich_type, sized_beverage_type, beverage_type,
            fish_sandwich_type, by_the_lb_type, cream_cheese_type, snack_type, pastry_type, side_type)


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
    # Cream cheese flavors from Zucker's menu
    schmears = [
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
        # Other spreads
        ("Butter", 1.00),
        ("Peanut Butter", 2.00),
        ("Nutella", 2.50),
        ("Hummus", 3.00),
        ("Avocado Spread", 4.00),
    ]

    for name, price in schmears:
        existing = db.query(Ingredient).filter(Ingredient.name == name).first()
        if not existing:
            db.add(Ingredient(name=name, category="cheese", unit="portion", is_available=True, base_price=price))
        else:
            existing.base_price = price
            existing.category = "cheese"

    db.commit()
    print(f"Ensured {len(schmears)} cream cheese schmears exist")


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


def populate_menu_items(db: Session):
    """Populate the menu with Zucker's items."""
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

    # Define menu items
    items = [
        # Plain Bagels (category: bagel)
        {"name": "Plain Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Everything Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Sesame Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Poppy Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Onion Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Cinnamon Raisin Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Pumpernickel Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Salt Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Garlic Bagel", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Whole Wheat Bagel", "category": "bagel", "base_price": 2.75, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Bialy", "category": "bagel", "base_price": 2.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},

        # Bagel with cream cheese
        {"name": "Bagel with Cream Cheese", "category": "bagel", "base_price": 5.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},
        {"name": "Bagel with Butter", "category": "bagel", "base_price": 3.50, "is_signature": False, "item_type_id": bagel_type.id if bagel_type else None},

        # Egg Sandwiches (Signature)
        {"name": "The Classic BEC", "category": "signature", "base_price": 9.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Everything Bagel", "protein": "Bacon", "cheese": "American", "extras": ["Egg"]}},
        {"name": "The Leo", "category": "signature", "base_price": 14.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Nova Scotia Salmon", "extras": ["Scrambled Eggs", "Onion"]}},
        {"name": "The Avocado Toast", "category": "signature", "base_price": 12.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Everything Bagel", "extras": ["Avocado", "Egg", "Everything Seeds"]}},
        {"name": "The Delancey", "category": "signature", "base_price": 11.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Bialy", "protein": "Pastrami", "extras": ["Scrambled Eggs", "Mustard"]}},
        {"name": "The Health Nut", "category": "signature", "base_price": 10.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Whole Wheat Bagel", "extras": ["Egg White", "Avocado", "Tomato"]}},

        # Lox & Smoked Fish
        {"name": "Nova Scotia Salmon on Bagel", "category": "signature", "base_price": 16.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Nova Scotia Salmon", "extras": ["Cream Cheese", "Tomato", "Onion", "Capers"]}},
        {"name": "The Zucker's Traditional", "category": "signature", "base_price": 18.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Nova Scotia Salmon", "extras": ["Cream Cheese", "Tomato", "Onion", "Capers"]}},

        # Deli Sandwiches
        {"name": "Hot Pastrami Sandwich", "category": "signature", "base_price": 18.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "New York Rye", "protein": "Pastrami", "extras": ["Mustard"]}},
        {"name": "The Reuben", "category": "signature", "base_price": 19.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "New York Rye", "protein": "Corned Beef", "cheese": "Swiss", "extras": ["Sauerkraut", "Russian Dressing"]}},
        {"name": "Turkey Club", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Turkey", "extras": ["Bacon", "Lettuce", "Tomato", "Mayo"]}},

        # Club & Deli Sandwiches
        {"name": "The Chelsea Club", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Chicken Salad", "cheese": "Cheddar", "extras": ["Bacon", "Tomato", "Lettuce", "Red Onion"]}},
        {"name": "The Grand Central", "category": "signature", "base_price": 16.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Grilled Chicken", "extras": ["Bacon", "Tomato", "Lettuce", "Dijon Mayo"]}},
        {"name": "The Tribeca", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Turkey", "cheese": "Havarti", "extras": ["Tomato", "Lettuce", "Basil Mayo"]}},
        {"name": "The Natural", "category": "signature", "base_price": 15.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Whole Wheat Bagel", "protein": "Smoked Turkey", "cheese": "Brie", "extras": ["Tomato", "Lettuce", "Dijon Dill Sauce"]}},
        {"name": "The BLT", "category": "signature", "base_price": 12.95, "is_signature": True, "item_type_id": signature_sandwich_type.id if signature_sandwich_type else None,
         "default_config": {"bread": "Plain Bagel", "protein": "Bacon", "extras": ["Lettuce", "Tomato", "Mayo"]}},

        # ===========================================
        # SIZED BEVERAGES - Hot/Iced options (La Colombe Coffee Bar)
        # ===========================================
        {"name": "Coffee", "category": "drink", "base_price": 3.25, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Decaf Coffee", "category": "drink", "base_price": 3.25, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Iced Coffee", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Cold Brew", "category": "drink", "base_price": 4.75, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Americano", "category": "drink", "base_price": 4.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Cappuccino", "category": "drink", "base_price": 5.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Iced Cappuccino", "category": "drink", "base_price": 5.75, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Latte", "category": "drink", "base_price": 5.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Iced Latte", "category": "drink", "base_price": 5.75, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Cafe au Lait", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Espresso", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Double Espresso", "category": "drink", "base_price": 4.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Macchiato", "category": "drink", "base_price": 4.25, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Hot Chocolate", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        # Harney & Sons Tea
        {"name": "Hot Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Earl Grey Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Chamomile Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Green Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "English Breakfast Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Peppermint Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Chai Tea", "category": "drink", "base_price": 4.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Iced Tea", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},
        {"name": "Iced Chai Tea", "category": "drink", "base_price": 5.00, "is_signature": False, "item_type_id": sized_beverage_type.id if sized_beverage_type else None},

        # ===========================================
        # BEVERAGES - Cold only (cannot be heated)
        # ===========================================
        # Sodas
        {"name": "Coca-Cola", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Diet Coke", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Sprite", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Ginger Ale", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # Dr. Brown's
        {"name": "Dr. Brown's Cream Soda", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Dr. Brown's Black Cherry", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Dr. Brown's Cel-Ray", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # Boylan's
        {"name": "Boylan's Root Beer", "category": "drink", "base_price": 3.25, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Boylan's Ginger Ale", "category": "drink", "base_price": 3.25, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # Snapple
        {"name": "Snapple Iced Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Snapple Lemonade", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Snapple Peach Tea", "category": "drink", "base_price": 3.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # Water & Sparkling
        {"name": "Bottled Water", "category": "drink", "base_price": 2.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "San Pellegrino", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Poland Spring", "category": "drink", "base_price": 2.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # Juices
        {"name": "Fresh Squeezed Orange Juice", "category": "drink", "base_price": 6.95, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Apple Juice", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Cranberry Juice", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Tropicana Orange Juice 46 oz", "category": "drink", "base_price": 7.60, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        {"name": "Tropicana No Pulp", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # ITO EN
        {"name": "ITO EN Green Tea", "category": "drink", "base_price": 3.50, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},
        # Ronnybrook Milk
        {"name": "Chocolate Milk", "category": "drink", "base_price": 4.00, "is_signature": False, "item_type_id": beverage_type.id if beverage_type else None},

        # Sides
        {"name": "Latkes", "category": "side", "base_price": 5.95, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Bacon", "category": "side", "base_price": 4.50, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Fruit Cup", "category": "side", "base_price": 6.95, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Bagel Chips", "category": "side", "base_price": 3.50, "is_signature": False, "item_type_id": side_type.id if side_type else None},
        {"name": "Fruit Salad", "category": "side", "base_price": 7.95, "is_signature": False, "item_type_id": side_type.id if side_type else None},

        # Omelettes (come with choice of bagel or fruit salad)
        # All omelettes are 3 eggs unless noted as egg whites
        {"name": "The Truffled Egg Omelette", "category": "omelette", "base_price": 15.50, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"cheese": "Swiss", "spread": "Truffle Cream Cheese", "extras": ["Sautéed Mushrooms"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Chipotle Egg Omelette", "category": "omelette", "base_price": 15.50, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"cheese": "Pepper Jack", "spread": "Chipotle Cream Cheese", "extras": ["Avocado", "Pico de Gallo"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Lexington Omelette", "category": "omelette", "base_price": 11.95, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"eggs": "Egg Whites", "cheese": "Swiss", "extras": ["Spinach"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Columbus Omelette", "category": "omelette", "base_price": 13.50, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"eggs": "Egg Whites", "protein": "Turkey Bacon", "cheese": "Swiss", "extras": ["Avocado"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Health Nut Omelette", "category": "omelette", "base_price": 11.75, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"eggs": "Egg Whites", "extras": ["Mushrooms", "Spinach", "Green Peppers", "Red Peppers", "Tomatoes"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Nova Omelette", "category": "omelette", "base_price": 14.95, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"protein": "Nova Scotia Salmon", "extras": ["Sautéed Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Delancey Omelette", "category": "omelette", "base_price": 15.25, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"protein": "Corned Beef", "cheese": "Swiss", "extras": ["Potato Latke", "Sautéed Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "The Mulberry Omelette", "category": "omelette", "base_price": 13.65, "is_signature": True, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"protein": "Esposito's Sausage", "extras": ["Green Peppers", "Red Peppers", "Sautéed Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "Bacon and Cheddar Omelette", "category": "omelette", "base_price": 13.50, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"protein": "Applewood Smoked Bacon", "cheese": "Cheddar", "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "Cheese Omelette", "category": "omelette", "base_price": 12.95, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"cheese": "American", "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "Western Omelette", "category": "omelette", "base_price": 14.95, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"protein": "Ham", "extras": ["Green Peppers", "Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "Veggie Omelette", "category": "omelette", "base_price": 13.95, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"extras": ["Mushrooms", "Spinach", "Tomatoes", "Onions"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},
        {"name": "Spinach & Feta Omelette", "category": "omelette", "base_price": 14.50, "is_signature": False, "item_type_id": omelette_type.id if omelette_type else None,
         "default_config": {"cheese": "Feta", "extras": ["Spinach"], "includes_side_choice": True, "side_options": ["bagel", "fruit_salad"]}},

        # Spread Sandwiches (cream cheese, butter, etc.)
        {"name": "Plain Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.25, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Plain Cream Cheese"}},
        {"name": "Scallion Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Scallion Cream Cheese"}},
        {"name": "Vegetable Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Vegetable Cream Cheese"}},
        {"name": "Sun-Dried Tomato Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Sun-Dried Tomato Cream Cheese"}},
        {"name": "Strawberry Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Strawberry Cream Cheese"}},
        {"name": "Blueberry Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Blueberry Cream Cheese"}},
        {"name": "Kalamata Olive Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Kalamata Olive Cream Cheese"}},
        {"name": "Maple Raisin Walnut Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 6.25, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Maple Raisin Walnut Cream Cheese"}},
        {"name": "Jalapeno Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Jalapeno Cream Cheese"}},
        {"name": "Nova Scotia Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 6.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Nova Scotia Cream Cheese"}},
        {"name": "Truffle Cream Cheese Sandwich", "category": "spread_sandwich", "base_price": 7.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Truffle Cream Cheese"}},
        {"name": "Butter Sandwich", "category": "spread_sandwich", "base_price": 3.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Butter"}},
        {"name": "Peanut Butter Sandwich", "category": "spread_sandwich", "base_price": 4.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Peanut Butter"}},
        {"name": "Nutella Sandwich", "category": "spread_sandwich", "base_price": 4.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Nutella"}},
        {"name": "Hummus Sandwich", "category": "spread_sandwich", "base_price": 5.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Hummus"}},
        {"name": "Avocado Spread Sandwich", "category": "spread_sandwich", "base_price": 6.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Avocado Spread"}},
        {"name": "Tofu Plain Sandwich", "category": "spread_sandwich", "base_price": 5.75, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Tofu Plain"}},
        {"name": "Tofu Scallion Sandwich", "category": "spread_sandwich", "base_price": 5.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Tofu Scallion"}},
        {"name": "Tofu Vegetable Sandwich", "category": "spread_sandwich", "base_price": 5.95, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Tofu Vegetable"}},
        {"name": "Tofu Nova Sandwich", "category": "spread_sandwich", "base_price": 6.50, "is_signature": False, "item_type_id": spread_sandwich_type.id if spread_sandwich_type else None,
         "default_config": {"spread": "Tofu Nova"}},

        # Salad Sandwiches (whitefish, tuna, egg salad, etc.)
        {"name": "Tuna Salad Sandwich", "category": "salad_sandwich", "base_price": 13.15, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Tuna Salad"}},
        {"name": "Whitefish Salad Sandwich", "category": "salad_sandwich", "base_price": 15.13, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Whitefish Salad"}},
        {"name": "Baked Salmon Salad Sandwich", "category": "salad_sandwich", "base_price": 14.50, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Baked Salmon Salad"}},
        {"name": "Egg Salad Sandwich", "category": "salad_sandwich", "base_price": 9.95, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Egg Salad"}},
        {"name": "Chicken Salad Sandwich", "category": "salad_sandwich", "base_price": 13.50, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Chicken Salad"}},
        {"name": "Cranberry Pecan Chicken Salad Sandwich", "category": "salad_sandwich", "base_price": 14.50, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Cranberry Pecan Chicken Salad"}},
        {"name": "Lemon Chicken Salad Sandwich", "category": "salad_sandwich", "base_price": 14.25, "is_signature": False, "item_type_id": salad_sandwich_type.id if salad_sandwich_type else None,
         "default_config": {"salad": "Lemon Chicken Salad"}},

        # ===========================================
        # FISH SANDWICHES - Smoked fish on bagel
        # ===========================================
        {"name": "The Zucker's Traditional", "category": "fish_sandwich", "base_price": 18.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Nova Scotia Salmon", "spread": "Plain Cream Cheese", "extras": ["Tomato", "Red Onion", "Capers"]}},
        {"name": "The Flatiron", "category": "fish_sandwich", "base_price": 19.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Everything Seeded Salmon", "spread": "Scallion Cream Cheese", "extras": ["Avocado"]}},
        {"name": "The Alton Brown", "category": "fish_sandwich", "base_price": 21.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Smoked Trout", "spread": "Plain Cream Cheese", "extras": ["Avocado Horseradish", "Tobiko"]}},
        {"name": "The Max Zucker", "category": "fish_sandwich", "base_price": 17.95, "is_signature": True, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Whitefish Salad", "extras": ["Tomato", "Red Onion"]}},
        {"name": "Nova Scotia Salmon Sandwich", "category": "fish_sandwich", "base_price": 16.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Nova Scotia Salmon"}},
        {"name": "Gravlax Sandwich", "category": "fish_sandwich", "base_price": 18.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Gravlax"}},
        {"name": "Sable Sandwich", "category": "fish_sandwich", "base_price": 24.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Sable"}},
        {"name": "Sturgeon Sandwich", "category": "fish_sandwich", "base_price": 29.95, "is_signature": False, "item_type_id": fish_sandwich_type.id if fish_sandwich_type else None,
         "default_config": {"fish": "Lake Sturgeon"}},

        # ===========================================
        # BY THE POUND - Smoked fish & spreads sold by weight
        # ===========================================
        # Smoked Fish (prices per 1/4 lb)
        {"name": "Nova Scotia Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 12.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Nova Scotia Salmon (1 lb)", "category": "by_the_lb", "base_price": 44.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Gravlax (1/4 lb)", "category": "by_the_lb", "base_price": 14.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Gravlax (1 lb)", "category": "by_the_lb", "base_price": 52.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Belly Lox (1/4 lb)", "category": "by_the_lb", "base_price": 12.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Belly Lox (1 lb)", "category": "by_the_lb", "base_price": 44.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Everything Seed Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 13.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Everything Seed Salmon (1 lb)", "category": "by_the_lb", "base_price": 48.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Pastrami Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 14.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Pastrami Salmon (1 lb)", "category": "by_the_lb", "base_price": 52.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Scottish Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 15.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Scottish Salmon (1 lb)", "category": "by_the_lb", "base_price": 56.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Wild Pacific Salmon (1/4 lb)", "category": "by_the_lb", "base_price": 14.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Wild Pacific Salmon (1 lb)", "category": "by_the_lb", "base_price": 52.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Smoked Trout (1/4 lb)", "category": "by_the_lb", "base_price": 11.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Smoked Trout (1 lb)", "category": "by_the_lb", "base_price": 40.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Sable (1/4 lb)", "category": "by_the_lb", "base_price": 18.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Sable (1 lb)", "category": "by_the_lb", "base_price": 68.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Lake Sturgeon (1/4 lb)", "category": "by_the_lb", "base_price": 22.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Lake Sturgeon (1 lb)", "category": "by_the_lb", "base_price": 84.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Whitefish (Whole)", "category": "by_the_lb", "base_price": 28.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Whitefish Salad (1/4 lb)", "category": "by_the_lb", "base_price": 9.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},
        {"name": "Whitefish Salad (1 lb)", "category": "by_the_lb", "base_price": 32.00, "is_signature": False, "item_type_id": by_the_lb_type.id if by_the_lb_type else None},

        # ===========================================
        # CREAM CHEESE BY THE POUND - Sold by weight
        # ===========================================
        {"name": "Plain Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 4.50, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Plain Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 16.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Scallion Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Scallion Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Vegetable Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Vegetable Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Sun-Dried Tomato Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.50, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Sun-Dried Tomato Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 20.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Strawberry Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Strawberry Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Blueberry Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Blueberry Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Kalamata Olive Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.50, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Kalamata Olive Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 20.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Maple Raisin Walnut Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 6.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Maple Raisin Walnut Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 22.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Jalapeno Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Jalapeno Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Nova Scotia Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 7.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Nova Scotia Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 26.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Truffle Cream Cheese (1/4 lb)", "category": "cream_cheese", "base_price": 8.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Truffle Cream Cheese (1 lb)", "category": "cream_cheese", "base_price": 30.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Tofu Plain (1/4 lb)", "category": "cream_cheese", "base_price": 5.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},
        {"name": "Tofu Plain (1 lb)", "category": "cream_cheese", "base_price": 18.00, "is_signature": False, "item_type_id": cream_cheese_type.id if cream_cheese_type else None},

        # ===========================================
        # SNACKS - Chips and small bites
        # ===========================================
        {"name": "Potato Chips", "category": "snack", "base_price": 2.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Bagel Chips - Salt", "category": "snack", "base_price": 3.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Bagel Chips - BBQ", "category": "snack", "base_price": 3.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Bagel Chips - Sea Salt & Vinegar", "category": "snack", "base_price": 3.50, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},
        {"name": "Kettle Chips", "category": "snack", "base_price": 2.75, "is_signature": False, "item_type_id": snack_type.id if snack_type else None},

        # ===========================================
        # DESSERTS & PASTRIES - Baked goods and sweets
        # Prices from Zucker's Fall 2023 menu and SinglePlatform (2024-2025)
        # https://www.zuckersbagels.com/menu/
        # ===========================================

        # MUFFINS - Baked In-House ($3.95 each)
        {"name": "Corn Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Blueberry Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Lemon Poppy Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Banana Walnut Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Cranberry Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Chocolate Chip Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Morning Glory Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Apple Cinnamon Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Double-Chocolate Muffin", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},

        # COOKIES - Large, Homemade ($3.95 each)
        {"name": "Chocolate Chip Cookie", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Peanut Butter Cookie", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Oatmeal Raisin Cookie", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Black & White Cookie", "category": "pastry", "base_price": 4.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Black & White Cookie Minis (3-Pack)", "category": "pastry", "base_price": 4.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},

        # SPECIALTY PASTRIES
        {"name": "Rugelach (3-Pack)", "category": "pastry", "base_price": 4.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Chocolate-Dipped Macaroons (3-Pack)", "category": "pastry", "base_price": 4.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Brownie", "category": "pastry", "base_price": 4.50, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Danish", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Babka - Chocolate", "category": "pastry", "base_price": 14.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Babka - Cinnamon", "category": "pastry", "base_price": 14.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},

        # CAKES & BARS
        {"name": "Russian Coffee Cake", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Rice Krispy Treat", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Pound Cake", "category": "pastry", "base_price": 3.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Blondie Square", "category": "pastry", "base_price": 3.95, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Pecan Pie Square", "category": "pastry", "base_price": 3.75, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Jelly Rings (3-Pack)", "category": "pastry", "base_price": 1.25, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
        {"name": "Halvah Bar", "category": "pastry", "base_price": 1.25, "is_signature": False, "item_type_id": pastry_type.id if pastry_type else None},
    ]

    added = 0
    for item_data in items:
        existing = db.query(MenuItem).filter(MenuItem.name == item_data["name"]).first()
        if not existing:
            db.add(MenuItem(**item_data))
            added += 1
        else:
            # Update existing item
            for key, value in item_data.items():
                setattr(existing, key, value)

    db.commit()
    print(f"Added/updated {len(items)} menu items ({added} new)")


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
         fish_sandwich_type, by_the_lb_type, cream_cheese_type, snack_type, pastry_type, side_type) = ensure_item_types(db)
        ensure_bread_ingredients(db)
        ensure_schmear_ingredients(db)
        ensure_protein_ingredients(db)
        ensure_topping_ingredients(db)
        ensure_sauce_ingredients(db)

        # Set up attributes for the new sandwich types
        ensure_spread_sandwich_attributes(db, spread_sandwich_type)
        ensure_salad_sandwich_attributes(db, salad_sandwich_type)

        populate_menu_items(db)

        print("\nMenu population complete!")
        print("\nMenu summary:")
        for cat in ["bagel", "signature", "omelette", "drink", "side", "spread_sandwich", "salad_sandwich", "fish_sandwich", "by_the_lb", "cream_cheese", "snack", "pastry"]:
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
