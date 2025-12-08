from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    category = Column(String, nullable=False)  # 'sandwich', 'drink', 'side'
    is_signature = Column(Boolean, default=False, nullable=False)
    base_price = Column(Float, nullable=False)
    available_qty = Column(Integer, default=0, nullable=False)
    # Use a different attribute name; underlying column is actually called "metadata"
    extra_metadata = Column("metadata", JSON, default=dict)

    # Optional: backref from OrderItem
    order_items = relationship("OrderItem", back_populates="menu_item", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default="confirmed")  # e.g., draft/confirmed/cancelled
    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    pickup_time = Column(String, nullable=True)
    total_price = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)

    menu_item_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    line_total = Column(Float, nullable=False)

    # Store sandwich configuration (size, bread, toppings, sauces, etc.)
    extra = Column(JSON, default=dict)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")
