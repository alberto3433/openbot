import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sandwich_bot.models import Base, MenuItem, Order, OrderItem
from sandwich_bot.main import persist_confirmed_order

# Use TEST_DATABASE_URL or derive from DATABASE_URL
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def test_persist_confirmed_order_creates_order_and_items():
    """Test that persist_confirmed_order creates Order and OrderItem records."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL required for this test")

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    # Seed one menu item
    m = MenuItem(
        name="Turkey Club",
        category="sandwich",
        is_signature=True,
        base_price=8.0,
        available_qty=5,
        extra_metadata="{}",
    )
    db.add(m)
    db.commit()

    # Build a confirmed order_state with 2 of that item
    order_state = {
        "status": "confirmed",
        "customer": {
            "name": "Alice",
            "phone": "555-1234",
            "pickup_time": "ASAP",
        },
        "total_price": 16.0,
        "items": [
            {
                "menu_item_name": "Turkey Club",
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
    persist_confirmed_order(db, order_state)

    # The order_state should now have the db_order_id
    assert "db_order_id" in order_state
    order_id = order_state["db_order_id"]

    # Verify the persisted Order
    order = db.query(Order).filter(Order.id == order_id).first()
    assert order is not None
    assert order.total_price == 16.0
    assert order.customer_name == "Alice"

    # Verify the OrderItem was created for this order
    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    assert len(items) == 1
    assert items[0].menu_item_name == "Turkey Club"
    assert items[0].quantity == 2
    assert items[0].line_total == 16.0

    db.close()
