#!/usr/bin/env python
"""
Cleanup script to remove duplicate MenuItem records from the database.

For each duplicate name, keeps the oldest MenuItem (lowest ID) and deletes the rest.

Usage:
    # Dry run (default) - shows what would be deleted
    python scripts/cleanup_duplicate_menu_items.py

    # Actually delete duplicates
    python scripts/cleanup_duplicate_menu_items.py --execute
"""
import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from sandwich_bot.models import Base, MenuItem


def get_database_url():
    """Get database URL from environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    return url


def find_duplicates(session):
    """Find all menu items with duplicate names."""
    duplicates = (
        session.query(MenuItem.name, func.count(MenuItem.id).label("count"))
        .group_by(MenuItem.name)
        .having(func.count(MenuItem.id) > 1)
        .all()
    )
    return duplicates


def get_items_to_delete(session, name):
    """Get all but the oldest MenuItem with the given name."""
    items = (
        session.query(MenuItem)
        .filter(MenuItem.name == name)
        .order_by(MenuItem.id.asc())
        .all()
    )
    # Keep the first (oldest), return the rest for deletion
    return items[0], items[1:]


def cleanup_duplicates(execute=False):
    """Find and optionally delete duplicate menu items."""
    database_url = get_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        duplicates = find_duplicates(session)

        if not duplicates:
            print("No duplicate menu items found.")
            return

        print(f"Found {len(duplicates)} menu item names with duplicates:\n")

        total_to_delete = 0
        deletion_plan = []

        for name, count in duplicates:
            keeper, to_delete = get_items_to_delete(session, name)
            total_to_delete += len(to_delete)

            deletion_plan.append({
                "name": name,
                "total_count": count,
                "keep_id": keeper.id,
                "delete_ids": [item.id for item in to_delete],
            })

            print(f"  '{name}':")
            print(f"    Total copies: {count}")
            print(f"    Keep: ID {keeper.id} (category={keeper.category})")
            print(f"    Delete: {len(to_delete)} copies (IDs: {[i.id for i in to_delete][:5]}{'...' if len(to_delete) > 5 else ''})")
            print()

        print(f"Summary: {total_to_delete} menu items will be deleted")
        print()

        if not execute:
            print("DRY RUN - No changes made.")
            print("Run with --execute to actually delete duplicates.")
            return

        # Actually delete
        print("Executing deletion...")
        deleted_count = 0

        for plan in deletion_plan:
            for item_id in plan["delete_ids"]:
                item = session.query(MenuItem).filter(MenuItem.id == item_id).first()
                if item:
                    session.delete(item)
                    deleted_count += 1

        session.commit()
        print(f"Successfully deleted {deleted_count} duplicate menu items.")

        # Verify
        remaining_duplicates = find_duplicates(session)
        if remaining_duplicates:
            print(f"WARNING: {len(remaining_duplicates)} duplicate names still exist!")
        else:
            print("Verification: No duplicates remain.")

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup duplicate MenuItem records from the database."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete duplicates (default is dry-run)",
    )
    args = parser.parse_args()

    cleanup_duplicates(execute=args.execute)


if __name__ == "__main__":
    main()
