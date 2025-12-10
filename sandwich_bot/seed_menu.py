import json
from sandwich_bot.db import SessionLocal, engine
from sandwich_bot.models import Base, MenuItem


def seed_menu():
    # Make sure tables exist
    Base.metadata.create_all(bind=engine)

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
                name="Fountain Soda",
                category="drink",
                is_signature=False,
                base_price=1.99,
                available_qty=50,
                extra_metadata=json.dumps({"sizes": ["small", "medium", "large"]}),
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


if __name__ == "__main__":
    seed_menu()
