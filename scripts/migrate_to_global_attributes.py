"""
Migration script to populate GlobalAttribute tables from legacy ItemTypeAttribute data.

For each unique attribute slug:
1. Find the item type version with the most options
2. Create a GlobalAttribute from that "best" version
3. Copy all AttributeOption records to GlobalAttributeOption
4. Create ItemTypeGlobalAttribute links for all item types that had the attribute

Run with: python scripts/migrate_to_global_attributes.py
"""

import os
import sys
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sandwich_bot.db import SessionLocal
from sandwich_bot.models import (
    ItemTypeAttribute,
    AttributeOption,
    ItemType,
    GlobalAttribute,
    GlobalAttributeOption,
    ItemTypeGlobalAttribute,
)


def migrate_attributes():
    db = SessionLocal()

    try:
        # Check if global attributes already exist
        existing_count = db.query(GlobalAttribute).count()
        if existing_count > 0:
            print(f"WARNING: {existing_count} global attributes already exist.")
            response = input("Delete existing and re-migrate? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                return

            # Delete existing global attributes (cascades to options and links)
            db.query(ItemTypeGlobalAttribute).delete()
            db.query(GlobalAttributeOption).delete()
            db.query(GlobalAttribute).delete()
            db.commit()
            print("Deleted existing global attributes.")

        # Step 1: Collect all attributes grouped by slug
        print("\n=== Step 1: Analyzing legacy attributes ===")
        attr_by_slug = defaultdict(list)

        legacy_attrs = db.query(ItemTypeAttribute).all()
        for attr in legacy_attrs:
            item_type = db.query(ItemType).filter(ItemType.id == attr.item_type_id).first()
            option_count = db.query(AttributeOption).filter(
                AttributeOption.item_type_attribute_id == attr.id
            ).count()

            attr_by_slug[attr.slug].append({
                'legacy_attr': attr,
                'item_type': item_type,
                'option_count': option_count,
            })

        print(f"Found {len(attr_by_slug)} unique attribute slugs across {len(legacy_attrs)} total attributes")

        # Step 2: For each slug, pick the best version and create GlobalAttribute
        print("\n=== Step 2: Creating global attributes ===")
        slug_to_global = {}  # Maps slug -> GlobalAttribute

        for slug, versions in sorted(attr_by_slug.items()):
            # Sort by option count descending, pick the one with most options
            versions.sort(key=lambda x: -x['option_count'])
            best = versions[0]
            legacy_attr = best['legacy_attr']

            # Create GlobalAttribute
            # Note: loads_from_ingredients and ingredient_group are not part of GlobalAttribute
            # Global attributes are just the definition; linking to ingredients happens elsewhere
            global_attr = GlobalAttribute(
                slug=slug,
                display_name=legacy_attr.display_name or slug.replace('_', ' ').title(),
                input_type=legacy_attr.input_type,
                description=f"Migrated from {best['item_type'].slug if best['item_type'] else 'unknown'}" +
                           (f" [ingredient_group: {legacy_attr.ingredient_group}]" if legacy_attr.loads_from_ingredients else ""),
            )
            db.add(global_attr)
            db.flush()  # Get the ID

            slug_to_global[slug] = global_attr

            # Copy options from the best version
            options = db.query(AttributeOption).filter(
                AttributeOption.item_type_attribute_id == legacy_attr.id
            ).order_by(AttributeOption.display_order).all()

            for opt in options:
                global_opt = GlobalAttributeOption(
                    global_attribute_id=global_attr.id,
                    slug=opt.slug,
                    display_name=opt.display_name,
                    price_modifier=opt.price_modifier,
                    iced_price_modifier=opt.iced_price_modifier,
                    is_default=opt.is_default,
                    is_available=opt.is_available,
                    display_order=opt.display_order,
                )
                db.add(global_opt)

            source_item_type = best['item_type'].slug if best['item_type'] else 'unknown'
            print(f"  {slug}: created with {best['option_count']} options (from {source_item_type})")

        db.flush()

        # Step 3: Create links from item types to global attributes
        print("\n=== Step 3: Creating item type links ===")
        link_count = 0

        for slug, versions in attr_by_slug.items():
            global_attr = slug_to_global[slug]

            for v in versions:
                legacy_attr = v['legacy_attr']
                item_type = v['item_type']

                if not item_type:
                    continue

                # Create link with the per-item-type settings from the legacy attribute
                link = ItemTypeGlobalAttribute(
                    item_type_id=item_type.id,
                    global_attribute_id=global_attr.id,
                    display_order=legacy_attr.display_order,
                    is_required=legacy_attr.is_required,
                    allow_none=legacy_attr.allow_none,
                    min_selections=legacy_attr.min_selections,
                    max_selections=legacy_attr.max_selections,
                    ask_in_conversation=legacy_attr.ask_in_conversation,
                    question_text=legacy_attr.question_text,
                )
                db.add(link)
                link_count += 1

        db.commit()
        print(f"Created {link_count} item type -> global attribute links")

        # Summary
        print("\n=== Migration Complete ===")
        print(f"  Global Attributes: {db.query(GlobalAttribute).count()}")
        print(f"  Global Options: {db.query(GlobalAttributeOption).count()}")
        print(f"  Item Type Links: {db.query(ItemTypeGlobalAttribute).count()}")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_attributes()
