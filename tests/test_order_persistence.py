import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from orderbot.db.models import Base, MenuItem, Order, OrderItem
from orderbot.services.order import persist_confirmed_order

# Use TEST_DATABASE_URL or derive from DATABASE_URL
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

# Distinctive test data names for easy cleanup
TEST_MENU_ITEM_NAME = "TEST OrderPersistence Sandwich"
TEST_CUSTOMER_NAME = "TEST_OrderPersistence_Customer"


def _cleanup_test_data(session):
    """Clean up test data created by order persistence tests."""
    try:
        # Delete in correct order (respect FK constraints)
        # 1. OrderItems referencing our test menu item
        session.query(OrderItem).filter(
            OrderItem.menu_item_name == TEST_MENU_ITEM_NAME
        ).delete(synchronize_session=False)

        # 2. Orders with our test customer
        session.query(Order).filter(
            Order.customer_name == TEST_CUSTOMER_NAME
        ).delete(synchronize_session=False)

        # 3. Our test MenuItem
        session.query(MenuItem).filter(
            MenuItem.name == TEST_MENU_ITEM_NAME
        ).delete(synchronize_session=False)

        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Warning: Failed to clean up order persistence test data: {e}")


@pytest.fixture
def db_session():
    """Create a PostgreSQL database session for testing with cleanup."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL required for this test")

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        _cleanup_test_data(session)
        session.close()


def test_persist_confirmed_order_creates_order_and_items(db_session):
    """Test that persist_confirmed_order creates Order and OrderItem records."""
    # Seed one menu item (get-or-create to handle existing items)
    m = db_session.query(MenuItem).filter(MenuItem.name == TEST_MENU_ITEM_NAME).first()
    if not m:
        m = MenuItem(
            name=TEST_MENU_ITEM_NAME,
            is_signature=True,
            available_qty=5,
        )
        db_session.add(m)
        db_session.commit()

    # Build a confirmed order_state with 2 of that item
    order_state = {
        "status": "confirmed",
        "customer": {
            "name": TEST_CUSTOMER_NAME,
            "phone": "555-1234",
            "pickup_time": "ASAP",
        },
        "total_price": 16.0,
        "items": [
            {
                "menu_item_name": TEST_MENU_ITEM_NAME,
                "quantity": 2,
                "unit_price": 8.0,
                "line_total": 16.0,
                "size": '6"',
                "bread": "wheat",
                "protein": "turkey",
                "cheese": "cheddar",
                "toppings": [],
                "sauces": [],
                "toasted": True,
            }
        ],
    }

    # persist_confirmed_order is what creates Order and OrderItem records
    persist_confirmed_order(db_session, order_state)

    # The order_state should now have the db_order_id
    assert "db_order_id" in order_state
    order_id = order_state["db_order_id"]

    # Verify the persisted Order
    order = db_session.query(Order).filter(Order.id == order_id).first()
    assert order is not None
    assert order.total_price == 16.0
    assert order.customer_name == TEST_CUSTOMER_NAME

    # Verify the OrderItem was created for this order
    items = db_session.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    assert len(items) == 1
    assert items[0].menu_item_name == TEST_MENU_ITEM_NAME
    assert items[0].quantity == 2
    assert items[0].line_total == 16.0
