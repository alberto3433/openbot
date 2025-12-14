import json
from sandwich_bot.db import SessionLocal
from sandwich_bot.models import MenuItem, Ingredient


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
                name="Cookie",
                category="dessert",
                is_signature=False,
                base_price=1.79,
                available_qty=30,
                extra_metadata=json.dumps({"types": ["chocolate chip", "oatmeal raisin"]}),
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
            # Breads
            Ingredient(name="White", category="bread", unit="piece", track_inventory=False),
            Ingredient(name="Wheat", category="bread", unit="piece", track_inventory=False),
            Ingredient(name="Italian", category="bread", unit="piece", track_inventory=False),
            Ingredient(name="Multigrain", category="bread", unit="piece", track_inventory=False),
            Ingredient(name="Ciabatta", category="bread", unit="piece", track_inventory=False),
            Ingredient(name="Sourdough", category="bread", unit="piece", track_inventory=False),
            # Cheeses
            Ingredient(name="Cheddar", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Swiss", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Provolone", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Pepper Jack", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="Mozzarella", category="cheese", unit="slice", track_inventory=False),
            Ingredient(name="American", category="cheese", unit="slice", track_inventory=False),
            # Proteins
            Ingredient(name="Turkey", category="protein", unit="oz", track_inventory=False),
            Ingredient(name="Ham", category="protein", unit="oz", track_inventory=False),
            Ingredient(name="Roast Beef", category="protein", unit="oz", track_inventory=False),
            Ingredient(name="Chicken", category="protein", unit="oz", track_inventory=False),
            Ingredient(name="Salami", category="protein", unit="oz", track_inventory=False),
            Ingredient(name="Bacon", category="protein", unit="strip", track_inventory=False),
            Ingredient(name="Meatball", category="protein", unit="piece", track_inventory=False),
            Ingredient(name="Tuna Salad", category="protein", unit="scoop", track_inventory=False),
            # Toppings
            Ingredient(name="Lettuce", category="topping", unit="portion", track_inventory=False),
            Ingredient(name="Tomato", category="topping", unit="slice", track_inventory=False),
            Ingredient(name="Onion", category="topping", unit="portion", track_inventory=False),
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


if __name__ == "__main__":
    seed_menu()
    seed_ingredients()
