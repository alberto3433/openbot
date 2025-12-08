import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sandwich_bot.models import Base, MenuItem
from sandwich_bot.inventory import apply_inventory_decrement_on_confirm, OutOfStockError

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    item = MenuItem(name="Turkey Club", category="sandwich", base_price=8.0, available_qty=5)
    s.add(item); s.commit()
    yield s
    s.close()

def test_inventory_decrement_success(db):
    order = {"status":"confirmed","items":[{"menu_item_name":"Turkey Club","quantity":2}]}
    apply_inventory_decrement_on_confirm(db, order)
    it = db.query(MenuItem).filter_by(name="Turkey Club").one()
    assert it.available_qty == 3

def test_inventory_decrement_fail(db):
    order = {"status":"confirmed","items":[{"menu_item_name":"Turkey Club","quantity":10}]}
    with pytest.raises(OutOfStockError):
        apply_inventory_decrement_on_confirm(db, order)
