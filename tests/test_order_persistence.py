from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sandwich_bot.models import Base, MenuItem, Order, OrderItem
from sandwich_bot.main import persist_confirmed_order


def test_persist_confirmed_order_creates_order_and_items():
    """Test that persist_confirmed_order creates Order and OrderItem records."""
    # In-memory SQLite shared connection
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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

    # There should be one persisted Order and one OrderItem
    orders = db.query(Order).all()
    assert len(orders) == 1
    assert orders[0].total_price == 16.0
    assert orders[0].customer_name == "Alice"

    items = db.query(OrderItem).all()
    assert len(items) == 1
    assert items[0].menu_item_name == "Turkey Club"
    assert items[0].quantity == 2
    assert items[0].line_total == 16.0

    # And the order_state should now have the db_order_id
    assert "db_order_id" in order_state
    assert order_state["db_order_id"] == orders[0].id

    db.close()
