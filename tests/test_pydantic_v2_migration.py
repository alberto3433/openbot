"""
Tests to verify Pydantic v2 migration is correctly implemented.

These tests ensure:
1. Models use ConfigDict with from_attributes=True (not deprecated orm_mode)
2. model_validate() works correctly with ORM objects (not deprecated from_orm())
3. No Pydantic v1 deprecation warnings are raised
"""
import warnings
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sandwich_bot.models import Base, MenuItem, Order, OrderItem
from sandwich_bot.main import (
    MenuItemOut,
    OrderSummaryOut,
    OrderItemOut,
    OrderDetailOut,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    yield session
    session.close()


class TestPydanticV2ConfigDict:
    """Test that models use Pydantic v2 ConfigDict correctly."""

    def test_menu_item_out_has_from_attributes(self):
        """MenuItemOut should use from_attributes=True in model_config."""
        config = MenuItemOut.model_config
        assert config.get("from_attributes") is True, (
            "MenuItemOut should have from_attributes=True in model_config"
        )

    def test_order_summary_out_has_from_attributes(self):
        """OrderSummaryOut should use from_attributes=True in model_config."""
        config = OrderSummaryOut.model_config
        assert config.get("from_attributes") is True, (
            "OrderSummaryOut should have from_attributes=True in model_config"
        )

    def test_order_item_out_has_from_attributes(self):
        """OrderItemOut should use from_attributes=True in model_config."""
        config = OrderItemOut.model_config
        assert config.get("from_attributes") is True, (
            "OrderItemOut should have from_attributes=True in model_config"
        )

    def test_order_detail_out_has_from_attributes(self):
        """OrderDetailOut should use from_attributes=True in model_config."""
        config = OrderDetailOut.model_config
        assert config.get("from_attributes") is True, (
            "OrderDetailOut should have from_attributes=True in model_config"
        )


class TestPydanticV2ModelValidate:
    """Test that model_validate works with ORM objects."""

    def test_menu_item_out_model_validate(self, db_session):
        """MenuItemOut.model_validate should work with MenuItem ORM object."""
        # Create a MenuItem in the database
        menu_item = MenuItem(
            name="Test Sandwich",
            category="sandwich",
            is_signature=True,
            base_price=9.99,
            available_qty=10,
            extra_metadata="{}",
        )
        db_session.add(menu_item)
        db_session.commit()
        db_session.refresh(menu_item)

        # model_validate should work without warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # We use the serialize function since MenuItemOut has custom metadata handling
            from sandwich_bot.main import serialize_menu_item
            result = serialize_menu_item(menu_item)

            # Check no Pydantic deprecation warnings
            pydantic_warnings = [
                warning for warning in w
                if "pydantic" in str(warning.category).lower()
                or "orm_mode" in str(warning.message).lower()
            ]
            assert len(pydantic_warnings) == 0, (
                f"Pydantic deprecation warnings found: {pydantic_warnings}"
            )

        assert result.id == menu_item.id
        assert result.name == "Test Sandwich"
        assert result.category == "sandwich"
        assert result.base_price == 9.99

    def test_order_item_out_model_validate(self, db_session):
        """OrderItemOut.model_validate should work with OrderItem ORM object."""
        # Create an Order first (required for foreign key)
        order = Order(
            status="confirmed",
            customer_name="Test Customer",
            phone="555-0000",
            total_price=9.99,
        )
        db_session.add(order)
        db_session.commit()
        db_session.refresh(order)

        # Create an OrderItem
        order_item = OrderItem(
            order_id=order.id,
            menu_item_name="Test Sandwich",
            item_config={"item_type": "sandwich", "bread": "wheat", "toasted": True},
            quantity=1,
            unit_price=9.99,
            line_total=9.99,
        )
        db_session.add(order_item)
        db_session.commit()
        db_session.refresh(order_item)

        # model_validate should work without warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = OrderItemOut.model_validate(order_item)

            # Check no Pydantic deprecation warnings
            pydantic_warnings = [
                warning for warning in w
                if "pydantic" in str(warning.category).lower()
                or "orm_mode" in str(warning.message).lower()
            ]
            assert len(pydantic_warnings) == 0, (
                f"Pydantic deprecation warnings found: {pydantic_warnings}"
            )

        assert result.id == order_item.id
        assert result.menu_item_name == "Test Sandwich"
        assert result.quantity == 1
        assert result.line_total == 9.99

    def test_order_summary_out_model_validate(self, db_session):
        """OrderSummaryOut.model_validate should work with Order ORM object."""
        order = Order(
            status="confirmed",
            customer_name="Test Customer",
            phone="555-1234",
            pickup_time="12:00 PM",
            total_price=25.50,
        )
        db_session.add(order)
        db_session.commit()
        db_session.refresh(order)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = OrderSummaryOut.model_validate(order)

            pydantic_warnings = [
                warning for warning in w
                if "pydantic" in str(warning.category).lower()
                or "orm_mode" in str(warning.message).lower()
            ]
            assert len(pydantic_warnings) == 0, (
                f"Pydantic deprecation warnings found: {pydantic_warnings}"
            )

        assert result.id == order.id
        assert result.status == "confirmed"
        assert result.customer_name == "Test Customer"
        assert result.total_price == 25.50


class TestNoDeprecationWarnings:
    """Ensure no Pydantic v1 deprecation warnings when importing models."""

    def test_no_orm_mode_warning_on_import(self):
        """Importing models should not trigger orm_mode deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Re-import to trigger any warnings
            from importlib import reload
            import sandwich_bot.main
            reload(sandwich_bot.main)

            # Filter for orm_mode warnings
            orm_mode_warnings = [
                warning for warning in w
                if "orm_mode" in str(warning.message).lower()
            ]

            assert len(orm_mode_warnings) == 0, (
                f"orm_mode deprecation warnings found: {[str(w.message) for w in orm_mode_warnings]}"
            )
