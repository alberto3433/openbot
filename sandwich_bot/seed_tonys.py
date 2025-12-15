"""
Seed data for Tony's Pizza - a pizza shop tenant.

This demonstrates the generic item type system working for a different
restaurant type (pizza instead of sandwiches).

Usage:
    DATABASE_URL="sqlite:///./data/tonys.db" python -m sandwich_bot.seed_tonys
"""

import json
from sandwich_bot.db import SessionLocal
from sandwich_bot.models import (
    MenuItem,
    Ingredient,
    ItemType,
    AttributeDefinition,
    AttributeOption,
    AttributeOptionIngredient,
    Company,
)


def seed_company():
    """Seed Tony's Pizza company settings."""
    db = SessionLocal()
    try:
        existing = db.query(Company).count()
        if existing > 0:
            print("Company already exists. Not seeding again.")
            return

        company = Company(
            name="Tony's Pizza",
            bot_persona_name="Tony",
            tagline="Authentic New York style pizza!",
            headquarters_address="123 Pizza Lane, Brooklyn, NY",
            corporate_phone="555-PIZZA",
            website="https://tonyspizza.example.com",
        )
        db.add(company)
        db.commit()
        print("Seeded company: Tony's Pizza")
    finally:
        db.close()


def seed_ingredients():
    """Seed pizza-specific ingredients."""
    db = SessionLocal()
    try:
        existing = db.query(Ingredient).count()
        if existing > 0:
            print(f"Ingredients table already has {existing} items. Not seeding again.")
            return

        ingredients = [
            # Crusts
            Ingredient(name="Thin Crust", category="crust", unit="piece", track_inventory=False, base_price=0.0),
            Ingredient(name="Hand Tossed", category="crust", unit="piece", track_inventory=False, base_price=0.0),
            Ingredient(name="Deep Dish", category="crust", unit="piece", track_inventory=False, base_price=2.00),
            Ingredient(name="Stuffed Crust", category="crust", unit="piece", track_inventory=False, base_price=3.00),
            Ingredient(name="Gluten Free", category="crust", unit="piece", track_inventory=False, base_price=3.00),

            # Sauces
            Ingredient(name="Marinara", category="sauce", unit="portion", track_inventory=False, base_price=0.0),
            Ingredient(name="White Garlic", category="sauce", unit="portion", track_inventory=False, base_price=0.0),
            Ingredient(name="BBQ", category="sauce", unit="portion", track_inventory=False, base_price=0.0),
            Ingredient(name="Buffalo", category="sauce", unit="portion", track_inventory=False, base_price=0.0),
            Ingredient(name="Pesto", category="sauce", unit="portion", track_inventory=False, base_price=1.00),

            # Cheeses
            Ingredient(name="Mozzarella", category="cheese", unit="portion", track_inventory=False, base_price=0.0),
            Ingredient(name="Extra Mozzarella", category="cheese", unit="portion", track_inventory=False, base_price=2.00),
            Ingredient(name="Parmesan", category="cheese", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Ricotta", category="cheese", unit="portion", track_inventory=False, base_price=1.50),
            Ingredient(name="Feta", category="cheese", unit="portion", track_inventory=False, base_price=1.50),
            Ingredient(name="Vegan Cheese", category="cheese", unit="portion", track_inventory=False, base_price=2.50),

            # Meat toppings
            Ingredient(name="Pepperoni", category="topping", unit="portion", track_inventory=False, base_price=1.50),
            Ingredient(name="Italian Sausage", category="topping", unit="portion", track_inventory=False, base_price=2.00),
            Ingredient(name="Bacon", category="topping", unit="portion", track_inventory=False, base_price=2.00),
            Ingredient(name="Ham", category="topping", unit="portion", track_inventory=False, base_price=1.50),
            Ingredient(name="Grilled Chicken", category="topping", unit="portion", track_inventory=False, base_price=2.50),
            Ingredient(name="Meatballs", category="topping", unit="portion", track_inventory=False, base_price=2.50),
            Ingredient(name="Anchovies", category="topping", unit="portion", track_inventory=False, base_price=2.00),

            # Veggie toppings
            Ingredient(name="Mushrooms", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Bell Peppers", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Onions", category="topping", unit="portion", track_inventory=False, base_price=0.75),
            Ingredient(name="Black Olives", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Green Olives", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Jalapenos", category="topping", unit="portion", track_inventory=False, base_price=0.75),
            Ingredient(name="Fresh Tomatoes", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Spinach", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Fresh Basil", category="topping", unit="portion", track_inventory=False, base_price=1.00),
            Ingredient(name="Roasted Garlic", category="topping", unit="portion", track_inventory=False, base_price=0.75),
            Ingredient(name="Sun-dried Tomatoes", category="topping", unit="portion", track_inventory=False, base_price=1.50),
            Ingredient(name="Artichoke Hearts", category="topping", unit="portion", track_inventory=False, base_price=1.50),
            Ingredient(name="Pineapple", category="topping", unit="portion", track_inventory=False, base_price=1.00),

            # Drinks
            Ingredient(name="Coke", category="drink", unit="bottle", track_inventory=True, base_price=2.50),
            Ingredient(name="Diet Coke", category="drink", unit="bottle", track_inventory=True, base_price=2.50),
            Ingredient(name="Sprite", category="drink", unit="bottle", track_inventory=True, base_price=2.50),
            Ingredient(name="Water", category="drink", unit="bottle", track_inventory=True, base_price=1.50),

            # Sides
            Ingredient(name="Garlic Bread", category="side", unit="piece", track_inventory=True, base_price=4.99),
            Ingredient(name="Breadsticks", category="side", unit="order", track_inventory=True, base_price=5.99),
            Ingredient(name="Wings", category="side", unit="order", track_inventory=True, base_price=9.99),
            Ingredient(name="Caesar Salad", category="side", unit="order", track_inventory=True, base_price=7.99),
        ]

        db.add_all(ingredients)
        db.commit()
        print(f"Seeded {len(ingredients)} ingredients.")
    finally:
        db.close()


def seed_item_types():
    """Seed the pizza item type with its attributes."""
    db = SessionLocal()
    try:
        existing = db.query(ItemType).count()
        if existing > 0:
            print(f"ItemType table already has {existing} items. Not seeding again.")
            return

        # Create item types
        item_types = [
            ItemType(slug="pizza", display_name="Pizza", is_configurable=True),
            ItemType(slug="side", display_name="Side", is_configurable=False),
            ItemType(slug="drink", display_name="Drink", is_configurable=False),
        ]
        db.add_all(item_types)
        db.flush()

        pizza_type = db.query(ItemType).filter(ItemType.slug == "pizza").first()

        # Create attribute definitions for pizza
        attr_defs = [
            AttributeDefinition(
                item_type_id=pizza_type.id,
                slug="size",
                display_name="Size",
                input_type="single_select",
                is_required=True,
                allow_none=False,
                display_order=1,
            ),
            AttributeDefinition(
                item_type_id=pizza_type.id,
                slug="crust",
                display_name="Crust",
                input_type="single_select",
                is_required=True,
                allow_none=False,
                display_order=2,
            ),
            AttributeDefinition(
                item_type_id=pizza_type.id,
                slug="sauce",
                display_name="Sauce",
                input_type="single_select",
                is_required=True,
                allow_none=True,
                display_order=3,
            ),
            AttributeDefinition(
                item_type_id=pizza_type.id,
                slug="cheese",
                display_name="Cheese",
                input_type="single_select",
                is_required=False,
                allow_none=True,
                display_order=4,
            ),
            AttributeDefinition(
                item_type_id=pizza_type.id,
                slug="toppings",
                display_name="Toppings",
                input_type="multi_select",
                is_required=False,
                allow_none=True,
                min_selections=0,
                max_selections=10,
                display_order=5,
            ),
        ]
        db.add_all(attr_defs)
        db.flush()

        # Get attribute definitions
        size_def = db.query(AttributeDefinition).filter(
            AttributeDefinition.item_type_id == pizza_type.id,
            AttributeDefinition.slug == "size"
        ).first()
        crust_def = db.query(AttributeDefinition).filter(
            AttributeDefinition.item_type_id == pizza_type.id,
            AttributeDefinition.slug == "crust"
        ).first()
        sauce_def = db.query(AttributeDefinition).filter(
            AttributeDefinition.item_type_id == pizza_type.id,
            AttributeDefinition.slug == "sauce"
        ).first()
        cheese_def = db.query(AttributeDefinition).filter(
            AttributeDefinition.item_type_id == pizza_type.id,
            AttributeDefinition.slug == "cheese"
        ).first()
        toppings_def = db.query(AttributeDefinition).filter(
            AttributeDefinition.item_type_id == pizza_type.id,
            AttributeDefinition.slug == "toppings"
        ).first()

        # Create size options (no ingredient link needed)
        size_options = [
            AttributeOption(
                attribute_definition_id=size_def.id,
                slug="small",
                display_name="Small (10\")",
                price_modifier=0.0,
                is_default=False,
                display_order=1,
            ),
            AttributeOption(
                attribute_definition_id=size_def.id,
                slug="medium",
                display_name="Medium (12\")",
                price_modifier=3.00,
                is_default=True,
                display_order=2,
            ),
            AttributeOption(
                attribute_definition_id=size_def.id,
                slug="large",
                display_name="Large (14\")",
                price_modifier=6.00,
                is_default=False,
                display_order=3,
            ),
            AttributeOption(
                attribute_definition_id=size_def.id,
                slug="xlarge",
                display_name="X-Large (16\")",
                price_modifier=9.00,
                is_default=False,
                display_order=4,
            ),
        ]
        db.add_all(size_options)

        # Helper to create option + ingredient link
        def create_option_with_ingredient(attr_def_id, ingredient, display_order, is_default=False):
            slug = ingredient.name.lower().replace(" ", "_").replace("-", "_")
            option = AttributeOption(
                attribute_definition_id=attr_def_id,
                slug=slug,
                display_name=ingredient.name,
                price_modifier=ingredient.base_price,
                is_default=is_default,
                display_order=display_order,
            )
            db.add(option)
            db.flush()
            link = AttributeOptionIngredient(
                attribute_option_id=option.id,
                ingredient_id=ingredient.id,
                quantity=1.0,
            )
            db.add(link)
            return option

        # Get ingredients by category
        crusts = db.query(Ingredient).filter(Ingredient.category == "crust").all()
        sauces = db.query(Ingredient).filter(Ingredient.category == "sauce").all()
        cheeses = db.query(Ingredient).filter(Ingredient.category == "cheese").all()
        toppings = db.query(Ingredient).filter(Ingredient.category == "topping").all()

        # Create crust options
        for i, crust in enumerate(crusts):
            create_option_with_ingredient(crust_def.id, crust, i + 1, is_default=(crust.name == "Hand Tossed"))

        # Create sauce options (with "none" option)
        none_sauce = AttributeOption(
            attribute_definition_id=sauce_def.id,
            slug="none",
            display_name="No Sauce",
            price_modifier=0.0,
            is_default=False,
            display_order=0,
        )
        db.add(none_sauce)
        for i, sauce in enumerate(sauces):
            create_option_with_ingredient(sauce_def.id, sauce, i + 1, is_default=(sauce.name == "Marinara"))

        # Create cheese options (with "none" option)
        none_cheese = AttributeOption(
            attribute_definition_id=cheese_def.id,
            slug="none",
            display_name="No Cheese",
            price_modifier=0.0,
            is_default=False,
            display_order=0,
        )
        db.add(none_cheese)
        for i, cheese in enumerate(cheeses):
            create_option_with_ingredient(cheese_def.id, cheese, i + 1, is_default=(cheese.name == "Mozzarella"))

        # Create topping options
        for i, topping in enumerate(toppings):
            create_option_with_ingredient(toppings_def.id, topping, i + 1)

        db.commit()
        print("Seeded pizza item type system successfully.")
        print(f"  - {len(item_types)} item types")
        print(f"  - {len(attr_defs)} attribute definitions")

    finally:
        db.close()


def seed_menu():
    """Seed pizza menu items."""
    db = SessionLocal()
    try:
        existing = db.query(MenuItem).count()
        if existing > 0:
            print(f"Menu already has {existing} items. Not seeding again.")
            return

        # Get pizza item type
        pizza_type = db.query(ItemType).filter(ItemType.slug == "pizza").first()
        side_type = db.query(ItemType).filter(ItemType.slug == "side").first()
        drink_type = db.query(ItemType).filter(ItemType.slug == "drink").first()

        items = [
            # Signature Pizzas
            MenuItem(
                name="Margherita",
                category="signature",
                is_signature=True,
                base_price=12.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Thin Crust",
                    "sauce": "Marinara",
                    "cheese": "Mozzarella",
                    "toppings": ["Fresh Tomatoes", "Fresh Basil"],
                },
            ),
            MenuItem(
                name="Pepperoni",
                category="signature",
                is_signature=True,
                base_price=13.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Hand Tossed",
                    "sauce": "Marinara",
                    "cheese": "Mozzarella",
                    "toppings": ["Pepperoni"],
                },
            ),
            MenuItem(
                name="Supreme",
                category="signature",
                is_signature=True,
                base_price=16.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Hand Tossed",
                    "sauce": "Marinara",
                    "cheese": "Mozzarella",
                    "toppings": ["Pepperoni", "Italian Sausage", "Mushrooms", "Bell Peppers", "Onions", "Black Olives"],
                },
            ),
            MenuItem(
                name="Meat Lovers",
                category="signature",
                is_signature=True,
                base_price=17.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Hand Tossed",
                    "sauce": "Marinara",
                    "cheese": "Extra Mozzarella",
                    "toppings": ["Pepperoni", "Italian Sausage", "Bacon", "Ham", "Meatballs"],
                },
            ),
            MenuItem(
                name="BBQ Chicken",
                category="signature",
                is_signature=True,
                base_price=15.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Hand Tossed",
                    "sauce": "BBQ",
                    "cheese": "Mozzarella",
                    "toppings": ["Grilled Chicken", "Onions", "Bacon"],
                },
            ),
            MenuItem(
                name="Veggie Garden",
                category="signature",
                is_signature=True,
                base_price=14.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Thin Crust",
                    "sauce": "Marinara",
                    "cheese": "Mozzarella",
                    "toppings": ["Mushrooms", "Bell Peppers", "Onions", "Black Olives", "Fresh Tomatoes", "Spinach"],
                },
            ),
            MenuItem(
                name="White Pizza",
                category="signature",
                is_signature=True,
                base_price=14.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Thin Crust",
                    "sauce": "White Garlic",
                    "cheese": "Ricotta",
                    "toppings": ["Spinach", "Roasted Garlic", "Fresh Tomatoes"],
                },
            ),
            MenuItem(
                name="Hawaiian",
                category="signature",
                is_signature=True,
                base_price=14.99,
                available_qty=50,
                item_type_id=pizza_type.id if pizza_type else None,
                default_config={
                    "size": "Medium (12\")",
                    "crust": "Hand Tossed",
                    "sauce": "Marinara",
                    "cheese": "Mozzarella",
                    "toppings": ["Ham", "Pineapple"],
                },
            ),
            # Build Your Own Pizza
            MenuItem(
                name="Build Your Own Pizza",
                category="pizza",
                is_signature=False,
                base_price=10.99,
                available_qty=100,
                item_type_id=pizza_type.id if pizza_type else None,
                extra_metadata=json.dumps({
                    "description": "Create your perfect pizza with your choice of crust, sauce, cheese, and toppings",
                    "is_custom": True,
                }),
            ),
            # Sides
            MenuItem(
                name="Garlic Bread",
                category="side",
                is_signature=False,
                base_price=4.99,
                available_qty=30,
                item_type_id=side_type.id if side_type else None,
            ),
            MenuItem(
                name="Breadsticks",
                category="side",
                is_signature=False,
                base_price=5.99,
                available_qty=30,
                item_type_id=side_type.id if side_type else None,
                extra_metadata=json.dumps({"pieces": 6, "includes": "marinara dipping sauce"}),
            ),
            MenuItem(
                name="Buffalo Wings",
                category="side",
                is_signature=False,
                base_price=9.99,
                available_qty=20,
                item_type_id=side_type.id if side_type else None,
                extra_metadata=json.dumps({"pieces": 8, "includes": "ranch or blue cheese"}),
            ),
            MenuItem(
                name="Caesar Salad",
                category="side",
                is_signature=False,
                base_price=7.99,
                available_qty=20,
                item_type_id=side_type.id if side_type else None,
            ),
            # Drinks
            MenuItem(
                name="Coke",
                category="drink",
                is_signature=False,
                base_price=2.50,
                available_qty=50,
                item_type_id=drink_type.id if drink_type else None,
            ),
            MenuItem(
                name="Diet Coke",
                category="drink",
                is_signature=False,
                base_price=2.50,
                available_qty=50,
                item_type_id=drink_type.id if drink_type else None,
            ),
            MenuItem(
                name="Sprite",
                category="drink",
                is_signature=False,
                base_price=2.50,
                available_qty=50,
                item_type_id=drink_type.id if drink_type else None,
            ),
            MenuItem(
                name="Bottled Water",
                category="drink",
                is_signature=False,
                base_price=1.50,
                available_qty=50,
                item_type_id=drink_type.id if drink_type else None,
            ),
        ]

        db.add_all(items)
        db.commit()
        print(f"Seeded {len(items)} menu items.")
    finally:
        db.close()


def seed_all():
    """Run all seed functions for Tony's Pizza."""
    print("\n" + "=" * 50)
    print("Seeding Tony's Pizza Database")
    print("=" * 50 + "\n")

    seed_company()
    seed_ingredients()
    seed_item_types()
    seed_menu()

    print("\n" + "=" * 50)
    print("Tony's Pizza seeding complete!")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    seed_all()
