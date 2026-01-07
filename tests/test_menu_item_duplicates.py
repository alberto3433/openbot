"""
Tests to detect duplicate menu items in the database.

These tests help catch when duplicate MenuItem records are being created,
which can cause issues with order processing and menu display.
"""
import os
import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from sandwich_bot.models import Base, MenuItem


# Use TEST_DATABASE_URL or derive from DATABASE_URL
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture
def db_session():
    """Create a PostgreSQL database session for testing."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL required for this test")

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    yield session
    session.close()


class TestMenuItemDuplicates:
    """Tests to detect duplicate menu items."""

    def test_no_duplicate_menu_item_names(self, db_session):
        """Fail if duplicate menu item names exist in the database.

        This test catches issues where menu items are being inserted multiple
        times with the same name, which can cause order processing issues.
        """
        duplicates = (
            db_session.query(MenuItem.name, func.count(MenuItem.id).label("count"))
            .group_by(MenuItem.name)
            .having(func.count(MenuItem.id) > 1)
            .all()
        )

        if duplicates:
            dup_details = []
            for name, count in duplicates:
                # Get IDs and categories of duplicates for debugging
                items = db_session.query(MenuItem.id, MenuItem.category).filter(
                    MenuItem.name == name
                ).all()
                dup_details.append(
                    f"  '{name}': {count} copies (IDs: {[i.id for i in items]}, "
                    f"categories: {[i.category for i in items]})"
                )

            pytest.fail(
                f"Found {len(duplicates)} menu items with duplicate names:\n"
                + "\n".join(dup_details)
                + "\n\nTo debug, enable MENU_ITEM_INSERT_LOGGING=1 and re-run tests."
            )

    def test_no_duplicate_menu_items_by_name_and_category(self, db_session):
        """Fail if duplicate menu items exist with same name AND category.

        This is a stricter check - same name in different categories might be
        intentional (e.g., "Small" in drinks vs sides), but same name+category
        is definitely a bug.
        """
        duplicates = (
            db_session.query(
                MenuItem.name,
                MenuItem.category,
                func.count(MenuItem.id).label("count"),
            )
            .group_by(MenuItem.name, MenuItem.category)
            .having(func.count(MenuItem.id) > 1)
            .all()
        )

        if duplicates:
            dup_details = []
            for name, category, count in duplicates:
                items = db_session.query(MenuItem.id).filter(
                    MenuItem.name == name,
                    MenuItem.category == category,
                ).all()
                dup_details.append(
                    f"  '{name}' (category='{category}'): {count} copies (IDs: {[i.id for i in items]})"
                )

            pytest.fail(
                f"Found {len(duplicates)} menu items with duplicate name+category:\n"
                + "\n".join(dup_details)
                + "\n\nTo debug, enable MENU_ITEM_INSERT_LOGGING=1 and re-run tests."
            )

    def test_report_total_menu_item_count(self, db_session):
        """Report total menu item count for monitoring growth over time."""
        total = db_session.query(MenuItem).count()
        unique_names = db_session.query(MenuItem.name).distinct().count()

        print(f"\n[Menu Stats] Total items: {total}, Unique names: {unique_names}")

        # This test always passes - it's just for reporting
        # If total >> unique_names, there might be duplicates
        if total > unique_names:
            print(f"  WARNING: {total - unique_names} potential duplicates detected")
