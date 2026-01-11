import json
from sandwich_bot.db import SessionLocal
from sandwich_bot.models import (
    MenuItem,
    Ingredient,
    ItemType,
    ItemTypeAttribute,
    AttributeOption,
    AttributeOptionIngredient,
)


def seed_menu():
    # Note: Tables should be created via Alembic migrations.
    # Run `alembic upgrade head` before seeding if database is empty.

    db = SessionLocal()
    try:
        existing = db.query(MenuItem).count()
        if existing > 0:
            print(f"Menu already has {existing} items. Not seeding again.")
            return

        signature_default = lambda bread, protein, cheese, toppings, sauces: {
            "default_config": {
                "bread": bread,
                "size": '6"',
                "protein": protein,
                "cheese": cheese,
                "toppings": toppings,
                "sauces": sauces,
                "toasted": True,
            }
        }

        items = [
            # Signature sandwiches
            MenuItem(
                name="Turkey Club",
                category="signature",
                is_signature=True,
                base_price=8.99,
                available_qty=10,
                extra_metadata=json.dumps(
                    signature_default(
                        bread="wheat",
                        protein="turkey",
                        cheese="cheddar",
                        toppings=["lettuce", "tomato", "onion"],
                        sauces=["mayo"],
                    )
                ),
            ),
            MenuItem(
                name="Italian Stallion",
                category="signature",
                is_signature=True,
                base_price=9.49,
                available_qty=10,
                extra_metadata=json.dumps(
                    signature_default(
                        bread="white",
                        protein="salami",
                        cheese="provolone",
                        toppings=["lettuce", "tomato", "red onion", "banana peppers"],
                        sauces=["oil", "vinegar"],
                    )
                ),
            ),
            MenuItem(
                name="Veggie Delight",
                category="signature",
                is_signature=True,
                base_price=7.99,
                available_qty=10,
                extra_metadata=json.dumps(
                    signature_default(
                        bread="multigrain",
                        protein="none",
                        cheese="swiss",
                        toppings=[
                            "lettuce",
                            "tomato",
                            "cucumber",
                            "green pepper",
                            "olive",
                        ],
                        sauces=["vinaigrette"],
                    )
                ),
            ),
            MenuItem(
                name="Chicken Bacon Ranch",
                category="signature",
                is_signature=True,
                base_price=9.99,
                available_qty=10,
                extra_metadata=json.dumps(
                    signature_default(
                        bread="white",
                        protein="chicken",
                        cheese="cheddar",
                        toppings=["lettuce", "tomato", "bacon"],
                        sauces=["ranch"],
                    )
                ),
            ),
            MenuItem(
                name="Meatball Marinara",
                category="signature",
                is_signature=True,
                base_price=8.49,
                available_qty=10,
                extra_metadata=json.dumps(
                    signature_default(
                        bread="italian",
                        protein="meatball",
                        cheese="mozzarella",
                        toppings=[],
                        sauces=["marinara"],
                    )
                ),
            ),
            # Custom Sandwich (Build Your Own)
            MenuItem(
                name="Custom Sandwich",
                category="sandwich",
                is_signature=False,
                base_price=5.99,  # Base price before protein/extras
                available_qty=100,
                extra_metadata=json.dumps({
                    "description": "Build your own sandwich with your choice of protein, bread, cheese, toppings, and sauces",
                    "is_custom": True,
                }),
            ),
            # Drinks
            MenuItem(
                name="Coke",
                category="drink",
                is_signature=False,
                base_price=2.29,
                available_qty=50,
                extra_metadata=json.dumps({"type": "soda", "size": "20oz"}),
            ),
            MenuItem(
                name="Diet Coke",
                category="drink",
                is_signature=False,
                base_price=2.29,
                available_qty=50,
                extra_metadata=json.dumps({"type": "soda", "size": "20oz"}),
            ),
            MenuItem(
                name="Coke Zero",
                category="drink",
                is_signature=False,
                base_price=2.29,
                available_qty=50,
                extra_metadata=json.dumps({"type": "soda", "size": "20oz"}),
            ),
            MenuItem(
                name="Sprite",
                category="drink",
                is_signature=False,
                base_price=2.29,
                available_qty=50,
                extra_metadata=json.dumps({"type": "soda", "size": "20oz"}),
            ),
            MenuItem(
                name="Orange Fanta",
                category="drink",
                is_signature=False,
                base_price=2.29,
                available_qty=50,
                extra_metadata=json.dumps({"type": "soda", "size": "20oz"}),
            ),
            MenuItem(
                name="Bottled Water",
                category="drink",
                is_signature=False,
                base_price=1.49,
                available_qty=50,
                extra_metadata=json.dumps({}),
            ),
            # Sides
            MenuItem(
                name="Chips",
                category="side",
                is_signature=False,
                base_price=1.29,
                available_qty=40,
                extra_metadata=json.dumps({"flavors": ["bbq", "sea salt", "sour cream & onion"]}),
            ),
            MenuItem(
                name="Chocolate Chip Cookie",
                category="dessert",
                is_signature=False,
                base_price=1.79,
                available_qty=30,
            ),
        ]

        db.add_all(items)
        db.commit()
        print(f"Seeded {len(items)} menu items.")
    finally:
        db.close()


def seed_ingredients():
    """Seed initial ingredients (breads, cheeses, proteins, toppings, sauces)."""
    db = SessionLocal()
    try:
        existing = db.query(Ingredient).count()
        if existing > 0:
            print(f"Ingredients table already has {existing} items. Not seeding again.")
            return

        ingredients = [
            # Breads (base_price for premium breads)
            Ingredient(name="White", category="bread", unit="piece", track_inventory=False, base_price=0.0),
            Ingredient(name="Wheat", category="bread", unit="piece", track_inventory=False, base_price=0.0),
            Ingredient(name="Italian", category="bread", unit="piece", track_inventory=False, base_price=0.0),
            Ingredient(name="Multigrain", category="bread", unit="piece", track_inventory=False, base_price=0.50),
            Ingredient(name="Ciabatta", category="bread", unit="piece", track_inventory=False, base_price=1.00),
            Ingredient(name="Sourdough", category="bread", unit="piece", track_inventory=False, base_price=0.50),
            # Cheeses
            Ingredient(name="Cheddar", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Swiss", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Provolone", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Pepper Jack", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Mozzarella", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="American", category="cheese", unit="slice", track_inventory=False),
            # Proteins (base_price used for custom sandwich pricing)
            Ingredient(name="Turkey", category="protein", unit="oz", track_inventory=False, base_price=2.50),
            Ingredient(name="Ham", category="protein", unit="oz", track_inventory=False, base_price=2.50),
            Ingredient(name="Roast Beef", category="protein", unit="oz", track_inventory=False, base_price=3.50),
            Ingredient(name="Chicken", category="protein", unit="oz", track_inventory=False, base_price=3.00),
            Ingredient(name="Salami", category="protein", unit="oz", track_inventory=False, base_price=2.50),
            Ingredient(name="Bacon", category="protein", unit="strip", track_inventory=False, base_price=2.00),
            Ingredient(name="Meatball", category="protein", unit="piece", track_inventory=False, base_price=3.00),
            Ingredient(name="Tuna Salad", category="protein", unit="scoop", track_inventory=False, base_price=2.50),
            Ingredient(name="Steak", category="protein", unit="oz", track_inventory=False, base_price=4.00),
            # Toppings
            Ingredient(name="Lettuce", category="topping", unit="portion", track_inventory=False),
            Ingredient(name="Tomato", category="topping", unit="slice", track_inventory=False),
            Ingredient(name="Red Onion", category="topping", unit="portion", track_inventory=False),
            Ingredient(name="Pickles", category="topping", unit="slice", track_inventory=False),
            Ingredient(name="Cucumber", category="topping", unit="slice", track_inventory=False),
            Ingredient(name="Olives", category="topping", unit="portion", track_inventory=False),
            Ingredient(name="Banana Peppers", category="topping", unit="portion", track_inventory=False),
            Ingredient(name="Jalapenos", category="topping", unit="portion", track_inventory=False),
            Ingredient(name="Green Peppers", category="topping", unit="portion", track_inventory=False),
            # Sauces
            Ingredient(name="Mayo", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Mustard", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Ranch", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Italian Vinaigrette", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Oil & Vinegar", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Marinara", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Pesto", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Buffalo", category="sauce", unit="portion", track_inventory=False),
            Ingredient(name="Honey Mustard", category="sauce", unit="portion", track_inventory=False),
        ]

        db.add_all(ingredients)
        db.commit()
        print(f"Seeded {len(ingredients)} ingredients.")
    finally:
        db.close()


def seed_item_types():
    """Seed the generic item type system with sandwich-specific configuration."""
    db = SessionLocal()
    try:
        # Check if already seeded
        existing = db.query(ItemType).count()
        if existing > 0:
            print(f"ItemType table already has {existing} items. Not seeding again.")
            return

        # Create item types
        item_types = [
            ItemType(slug="sandwich", display_name="Sandwich", is_configurable=True),
            ItemType(slug="side", display_name="Side", is_configurable=False),
            ItemType(slug="drink", display_name="Drink", is_configurable=False),
            ItemType(slug="dessert", display_name="Dessert", is_configurable=False),
        ]
        db.add_all(item_types)
        db.flush()  # Get IDs

        sandwich_type = db.query(ItemType).filter(ItemType.slug == "sandwich").first()

        # Create attribute definitions for sandwich
        attr_defs = [
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="size",
                display_name="Size",
                input_type="single_select",
                is_required=True,
                allow_none=False,
                display_order=1,
            ),
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="bread",
                display_name="Bread",
                input_type="single_select",
                is_required=True,
                allow_none=False,
                display_order=2,
            ),
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="protein",
                display_name="Protein",
                input_type="single_select",
                is_required=False,
                allow_none=True,  # Can have no protein (veggie)
                display_order=3,
            ),
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="cheese",
                display_name="Cheese",
                input_type="single_select",
                is_required=False,
                allow_none=True,  # Can have no cheese
                display_order=4,
            ),
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="toppings",
                display_name="Toppings",
                input_type="multi_select",
                is_required=False,
                allow_none=True,
                min_selections=0,
                max_selections=10,
                display_order=5,
            ),
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="sauces",
                display_name="Sauces",
                input_type="multi_select",
                is_required=False,
                allow_none=True,
                min_selections=0,
                max_selections=5,
                display_order=6,
            ),
            ItemTypeAttribute(
                item_type_id=sandwich_type.id,
                slug="toasted",
                display_name="Toasted",
                input_type="boolean",
                is_required=False,
                allow_none=False,
                display_order=7,
            ),
        ]
        db.add_all(attr_defs)
        db.flush()

        # Get attribute definitions for option creation
        size_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "size"
        ).first()
        bread_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "bread"
        ).first()
        protein_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "protein"
        ).first()
        cheese_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "cheese"
        ).first()
        toppings_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "toppings"
        ).first()
        sauces_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "sauces"
        ).first()
        toasted_def = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == sandwich_type.id,
            ItemTypeAttribute.slug == "toasted"
        ).first()

        # Create size options (no ingredient link needed)
        size_options = [
            AttributeOption(
                item_type_attribute_id=size_def.id,
                slug="6inch",
                display_name='6"',
                price_modifier=0.0,
                is_default=True,
                display_order=1,
            ),
            AttributeOption(
                item_type_attribute_id=size_def.id,
                slug="12inch",
                display_name='12"',
                price_modifier=4.00,
                is_default=False,
                display_order=2,
            ),
        ]
        db.add_all(size_options)

        # Create toasted options (no ingredient link needed)
        toasted_options = [
            AttributeOption(
                item_type_attribute_id=toasted_def.id,
                slug="yes",
                display_name="Yes",
                price_modifier=0.0,
                is_default=False,
                display_order=1,
            ),
            AttributeOption(
                item_type_attribute_id=toasted_def.id,
                slug="no",
                display_name="No",
                price_modifier=0.0,
                is_default=True,
                display_order=2,
            ),
        ]
        db.add_all(toasted_options)

        # Create options linked to ingredients
        # Get all ingredients by category
        breads = db.query(Ingredient).filter(Ingredient.category == "bread").all()
        proteins = db.query(Ingredient).filter(Ingredient.category == "protein").all()
        cheeses = db.query(Ingredient).filter(Ingredient.category == "cheese").all()
        toppings = db.query(Ingredient).filter(Ingredient.category == "topping").all()
        sauces = db.query(Ingredient).filter(Ingredient.category == "sauce").all()

        # Helper to create option + ingredient link
        def create_option_with_ingredient(attr_def_id, ingredient, display_order, is_default=False):
            slug = ingredient.name.lower().replace(" ", "_").replace("&", "and")
            option = AttributeOption(
                item_type_attribute_id=attr_def_id,
                slug=slug,
                display_name=ingredient.name,
                price_modifier=ingredient.base_price,
                is_default=is_default,
                display_order=display_order,
            )
            db.add(option)
            db.flush()
            # Link to ingredient
            link = AttributeOptionIngredient(
                attribute_option_id=option.id,
                ingredient_id=ingredient.id,
                quantity=1.0,
            )
            db.add(link)
            return option

        # Create bread options
        for i, bread in enumerate(breads):
            create_option_with_ingredient(bread_def.id, bread, i + 1, is_default=(bread.name == "White"))

        # Create protein options (with "none" option)
        none_protein = AttributeOption(
            item_type_attribute_id=protein_def.id,
            slug="none",
            display_name="No Protein",
            price_modifier=0.0,
            is_default=False,
            display_order=0,
        )
        db.add(none_protein)
        for i, protein in enumerate(proteins):
            create_option_with_ingredient(protein_def.id, protein, i + 1, is_default=(protein.name == "Turkey"))

        # Create cheese options (with "none" option)
        none_cheese = AttributeOption(
            item_type_attribute_id=cheese_def.id,
            slug="none",
            display_name="No Cheese",
            price_modifier=0.0,
            is_default=False,
            display_order=0,
        )
        db.add(none_cheese)
        for i, cheese in enumerate(cheeses):
            create_option_with_ingredient(cheese_def.id, cheese, i + 1)

        # Create topping options
        for i, topping in enumerate(toppings):
            create_option_with_ingredient(toppings_def.id, topping, i + 1)

        # Create sauce options
        for i, sauce in enumerate(sauces):
            create_option_with_ingredient(sauces_def.id, sauce, i + 1)

        db.commit()
        print("Seeded generic item type system successfully.")
        print(f"  - {len(item_types)} item types")
        print(f"  - {len(attr_defs)} attribute definitions")
        print(f"  - {len(size_options) + len(toasted_options) + len(breads) + len(proteins) + 1 + len(cheeses) + 1 + len(toppings) + len(sauces)} attribute options")

    finally:
        db.close()


def link_menu_items_to_item_types():
    """Update existing menu items to link to the generic item type system."""
    db = SessionLocal()
    try:
        # Get item types
        sandwich_type = db.query(ItemType).filter(ItemType.slug == "sandwich").first()
        side_type = db.query(ItemType).filter(ItemType.slug == "side").first()
        drink_type = db.query(ItemType).filter(ItemType.slug == "drink").first()
        dessert_type = db.query(ItemType).filter(ItemType.slug == "dessert").first()

        if not sandwich_type:
            print("Item types not seeded yet. Run seed_item_types() first.")
            return

        # Map category to item type
        category_to_type = {
            "signature": sandwich_type,
            "sandwich": sandwich_type,
            "side": side_type,
            "drink": drink_type,
            "dessert": dessert_type,
        }

        # Update all menu items
        menu_items = db.query(MenuItem).all()
        updated = 0
        for item in menu_items:
            if item.item_type_id is None:
                item_type = category_to_type.get(item.category)
                if item_type:
                    item.item_type_id = item_type.id

                    # Migrate extra_metadata to default_config for sandwiches
                    if item_type.slug == "sandwich" and item.extra_metadata:
                        try:
                            metadata = json.loads(item.extra_metadata)
                            if "default_config" in metadata:
                                item.default_config = metadata["default_config"]
                        except (json.JSONDecodeError, TypeError):
                            pass

                    updated += 1

        db.commit()
        print(f"Linked {updated} menu items to item types.")

    finally:
        db.close()


if __name__ == "__main__":
    seed_menu()
    seed_ingredients()
    seed_item_types()
    link_menu_items_to_item_types()
