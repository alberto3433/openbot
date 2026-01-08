"""
Consolidate Espresso Milk, Sweetener, and Syrup attributes into one Drink Modifier.

This script:
1. Creates a new 'drink_modifier' attribute for the Espresso item type
2. Moves all options from milk, sweetener, and syrup to the new attribute
3. Deletes the old milk, sweetener, and syrup attributes

Run with: python scripts/consolidate_espresso_modifiers.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sandwich_bot.db import SessionLocal
from sandwich_bot.models import ItemType, ItemTypeAttribute, AttributeOption


def main():
    db = SessionLocal()

    try:
        # Find Espresso item type
        espresso = db.query(ItemType).filter(ItemType.slug == "espresso").first()
        if not espresso:
            print("ERROR: Espresso item type not found")
            return

        print(f"Found Espresso item type: id={espresso.id}")

        # Find the attributes to merge
        milk_attr = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == espresso.id,
            ItemTypeAttribute.slug == "milk"
        ).first()

        sweetener_attr = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == espresso.id,
            ItemTypeAttribute.slug == "sweetener"
        ).first()

        syrup_attr = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == espresso.id,
            ItemTypeAttribute.slug == "syrup"
        ).first()

        if not all([milk_attr, sweetener_attr, syrup_attr]):
            print("ERROR: Could not find all 3 attributes (milk, sweetener, syrup)")
            print(f"  milk: {milk_attr}")
            print(f"  sweetener: {sweetener_attr}")
            print(f"  syrup: {syrup_attr}")
            return

        print(f"Found attributes to merge:")
        print(f"  - milk (id={milk_attr.id})")
        print(f"  - sweetener (id={sweetener_attr.id})")
        print(f"  - syrup (id={syrup_attr.id})")

        # Check if drink_modifier already exists
        existing = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == espresso.id,
            ItemTypeAttribute.slug == "drink_modifier"
        ).first()

        if existing:
            print(f"\nWARNING: drink_modifier attribute already exists (id={existing.id})")
            print("Aborting to prevent duplicate. Delete it first if you want to re-run.")
            return

        # Get all options from the 3 attributes
        milk_options = db.query(AttributeOption).filter(
            AttributeOption.item_type_attribute_id == milk_attr.id
        ).all()

        sweetener_options = db.query(AttributeOption).filter(
            AttributeOption.item_type_attribute_id == sweetener_attr.id
        ).all()

        syrup_options = db.query(AttributeOption).filter(
            AttributeOption.item_type_attribute_id == syrup_attr.id
        ).all()

        print(f"\nOptions to merge:")
        print(f"  - milk: {[o.slug for o in milk_options]}")
        print(f"  - sweetener: {[o.slug for o in sweetener_options]}")
        print(f"  - syrup: {[o.slug for o in syrup_options]}")

        # Create the new consolidated attribute
        # Use the lowest display_order from the 3 attributes
        min_order = min(milk_attr.display_order, sweetener_attr.display_order, syrup_attr.display_order)

        drink_modifier = ItemTypeAttribute(
            item_type_id=espresso.id,
            slug="drink_modifier",
            display_name="Drink Modifier",
            input_type="multi_select",  # Allow multiple selections
            is_required=False,
            allow_none=True,
            min_selections=None,
            max_selections=None,  # No limit
            display_order=min_order,
            ask_in_conversation=True,
            question_text="Any milk, sweetener, or syrup?",
        )
        db.add(drink_modifier)
        db.flush()  # Get the ID

        print(f"\nCreated drink_modifier attribute (id={drink_modifier.id})")

        # Move options to new attribute with category prefixes for clarity
        display_order = 0

        # Add milk options (group 1)
        for opt in milk_options:
            new_opt = AttributeOption(
                item_type_attribute_id=drink_modifier.id,
                slug=opt.slug,
                display_name=opt.display_name,
                price_modifier=opt.price_modifier,
                is_default=opt.is_default,
                is_available=opt.is_available,
                display_order=display_order,
            )
            db.add(new_opt)
            display_order += 1
            print(f"  Added milk option: {opt.slug}")

        # Add sweetener options (group 2)
        for opt in sweetener_options:
            new_opt = AttributeOption(
                item_type_attribute_id=drink_modifier.id,
                slug=opt.slug,
                display_name=opt.display_name,
                price_modifier=opt.price_modifier,
                is_default=opt.is_default,
                is_available=opt.is_available,
                display_order=display_order,
            )
            db.add(new_opt)
            display_order += 1
            print(f"  Added sweetener option: {opt.slug}")

        # Add syrup options (group 3)
        for opt in syrup_options:
            new_opt = AttributeOption(
                item_type_attribute_id=drink_modifier.id,
                slug=opt.slug,
                display_name=opt.display_name,
                price_modifier=opt.price_modifier,
                is_default=opt.is_default,
                is_available=opt.is_available,
                display_order=display_order,
            )
            db.add(new_opt)
            display_order += 1
            print(f"  Added syrup option: {opt.slug}")

        # Delete old options first (due to foreign key constraints)
        for opt in milk_options:
            db.delete(opt)
        for opt in sweetener_options:
            db.delete(opt)
        for opt in syrup_options:
            db.delete(opt)

        # Delete old attributes
        db.delete(milk_attr)
        db.delete(sweetener_attr)
        db.delete(syrup_attr)

        print(f"\nDeleted old attributes: milk, sweetener, syrup")

        # Commit all changes
        db.commit()

        print(f"\nSUCCESS: Consolidated into drink_modifier (id={drink_modifier.id})")
        print(f"  Total options: {display_order}")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
