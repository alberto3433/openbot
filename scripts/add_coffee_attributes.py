"""
Script to add coffee attributes to the item_type_attributes table.

This adds the following attributes for the sized_beverage item type:
- size: small, medium (default), large
- preparation: hot, iced
- milk: none, whole, skim, 2%, oat, almond, coconut, soy, half & half, cream
- sweetener: sugar, raw sugar, splenda, stevia, equal, sweet'n low, honey
- syrup: vanilla, caramel, hazelnut, mocha, pumpkin spice, cinnamon, lavender, almond

Run with: DATABASE_URL="postgresql://..." python scripts/add_coffee_attributes.py
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sandwich_bot.db import SessionLocal
from sandwich_bot.models import ItemType, ItemTypeAttribute, AttributeOption


def main():
    db = SessionLocal()

    try:
        # Find the sized_beverage item type
        coffee_type = db.query(ItemType).filter(ItemType.slug == "sized_beverage").first()
        if not coffee_type:
            print("ERROR: sized_beverage item type not found!")
            return 1

        print(f"Found item type: {coffee_type.slug} (id={coffee_type.id})")

        # Define coffee attributes and their options
        coffee_attributes = [
            {
                "slug": "size",
                "display_name": "Size",
                "input_type": "single_select",
                "is_required": True,
                "ask_in_conversation": True,
                "question_text": "What size would you like?",
                "display_order": 1,
                "options": [
                    {"slug": "small", "display_name": "Small", "display_order": 1},
                    {"slug": "medium", "display_name": "Medium", "is_default": True, "display_order": 2},
                    {"slug": "large", "display_name": "Large", "display_order": 3},
                ],
            },
            {
                "slug": "preparation",
                "display_name": "Preparation",
                "input_type": "single_select",
                "is_required": True,
                "ask_in_conversation": True,
                "question_text": "Would you like that hot or iced?",
                "display_order": 2,
                "options": [
                    {"slug": "hot", "display_name": "Hot", "display_order": 1},
                    {"slug": "iced", "display_name": "Iced", "display_order": 2},
                ],
            },
            {
                "slug": "milk",
                "display_name": "Milk",
                "input_type": "single_select",
                "is_required": False,
                "allow_none": True,
                "ask_in_conversation": False,
                "question_text": "What kind of milk would you like?",
                "display_order": 3,
                "options": [
                    {"slug": "none", "display_name": "None (Black)", "display_order": 0},
                    {"slug": "whole", "display_name": "Whole Milk", "display_order": 1},
                    {"slug": "skim", "display_name": "Skim Milk", "display_order": 2},
                    {"slug": "2_percent", "display_name": "2% Milk", "display_order": 3},
                    {"slug": "oat", "display_name": "Oat Milk", "price_modifier": 0.80, "display_order": 4},
                    {"slug": "almond", "display_name": "Almond Milk", "price_modifier": 0.80, "display_order": 5},
                    {"slug": "coconut", "display_name": "Coconut Milk", "price_modifier": 0.80, "display_order": 6},
                    {"slug": "soy", "display_name": "Soy Milk", "price_modifier": 0.80, "display_order": 7},
                    {"slug": "half_and_half", "display_name": "Half & Half", "display_order": 8},
                    {"slug": "cream", "display_name": "Cream", "display_order": 9},
                ],
            },
            {
                "slug": "sweetener",
                "display_name": "Sweetener",
                "input_type": "multi_select",
                "is_required": False,
                "allow_none": True,
                "ask_in_conversation": False,
                "question_text": "Would you like any sweetener?",
                "display_order": 4,
                "options": [
                    {"slug": "sugar", "display_name": "Sugar", "display_order": 1},
                    {"slug": "raw_sugar", "display_name": "Raw Sugar", "display_order": 2},
                    {"slug": "splenda", "display_name": "Splenda", "display_order": 3},
                    {"slug": "stevia", "display_name": "Stevia", "display_order": 4},
                    {"slug": "equal", "display_name": "Equal", "display_order": 5},
                    {"slug": "sweet_n_low", "display_name": "Sweet'N Low", "display_order": 6},
                    {"slug": "honey", "display_name": "Honey", "display_order": 7},
                ],
            },
            {
                "slug": "syrup",
                "display_name": "Flavor Syrup",
                "input_type": "multi_select",
                "is_required": False,
                "allow_none": True,
                "ask_in_conversation": False,
                "question_text": "Would you like any flavor syrup?",
                "display_order": 5,
                "options": [
                    {"slug": "vanilla", "display_name": "Vanilla", "price_modifier": 0.75, "display_order": 1},
                    {"slug": "caramel", "display_name": "Caramel", "price_modifier": 0.75, "display_order": 2},
                    {"slug": "hazelnut", "display_name": "Hazelnut", "price_modifier": 0.75, "display_order": 3},
                    {"slug": "mocha", "display_name": "Mocha", "price_modifier": 0.75, "display_order": 4},
                    {"slug": "pumpkin_spice", "display_name": "Pumpkin Spice", "price_modifier": 0.75, "display_order": 5},
                    {"slug": "cinnamon", "display_name": "Cinnamon", "price_modifier": 0.75, "display_order": 6},
                    {"slug": "lavender", "display_name": "Lavender", "price_modifier": 0.75, "display_order": 7},
                    {"slug": "almond", "display_name": "Almond", "price_modifier": 0.75, "display_order": 8},
                ],
            },
        ]

        # Create attributes and options
        for attr_data in coffee_attributes:
            options_data = attr_data.pop("options", [])

            # Check if attribute already exists
            existing = db.query(ItemTypeAttribute).filter(
                ItemTypeAttribute.item_type_id == coffee_type.id,
                ItemTypeAttribute.slug == attr_data["slug"],
            ).first()

            if existing:
                print(f'  Attribute {attr_data["slug"]} already exists, skipping')
                continue

            # Create attribute
            attr = ItemTypeAttribute(item_type_id=coffee_type.id, **attr_data)
            db.add(attr)
            db.flush()  # Get the ID

            print(f"  Created attribute: {attr.slug} (id={attr.id})")

            # Create options
            for opt_data in options_data:
                option = AttributeOption(
                    item_type_attribute_id=attr.id,
                    slug=opt_data["slug"],
                    display_name=opt_data.get("display_name", opt_data["slug"].replace("_", " ").title()),
                    price_modifier=opt_data.get("price_modifier", 0.0),
                    is_default=opt_data.get("is_default", False),
                    is_available=True,
                    display_order=opt_data.get("display_order", 0),
                )
                db.add(option)
                print(f"    - Option: {option.slug}")

        db.commit()
        print("\nDone! Coffee attributes created successfully.")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
