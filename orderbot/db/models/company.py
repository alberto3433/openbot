"""Company and store models.

Contains: Store, NeighborhoodZipCode, Company, MenuItemSizeCategory,
MenuItemSize, MenuItemSizePrice.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class Store(Base):
    """
    Represents a physical store location.
    Stores are managed via the admin interface and used for:
    - Store selection in customer chat
    - Per-store ingredient/menu item availability (86 system)
    - Order attribution
    """
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, unique=True, nullable=False, index=True)  # e.g., "store_eb_001"
    name = Column(String, nullable=False)  # e.g., "Sammy's Subs - East Brunswick"
    address = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String(2), nullable=False)  # e.g., "NJ"
    zip_code = Column(String(10), nullable=False)
    phone = Column(String, nullable=False)
    hours = Column(Text, nullable=True)  # Store hours description
    timezone = Column(String, nullable=False, default="America/New_York")  # IANA timezone, e.g., "America/Los_Angeles"
    status = Column(String, nullable=False, default="open")  # "open" or "closed"
    payment_methods = Column(JSON, nullable=False, default=list)  # ["cash", "credit", "bitcoin"]

    # Tax rates (stored as decimals, e.g., 0.04 for 4%)
    city_tax_rate = Column(Float, nullable=False, default=0.0)  # City/local tax rate
    state_tax_rate = Column(Float, nullable=False, default=0.0)  # State tax rate

    # Delivery configuration
    delivery_zip_codes = Column(JSON, nullable=False, default=list)  # List of zip codes for delivery
    delivery_fee = Column(Float, nullable=False, default=2.99)  # Delivery fee in dollars

    # Square POS integration
    square_location_id = Column(String, nullable=True)  # Square location ID for this store

    # Soft delete support
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class NeighborhoodZipCode(Base):
    """
    Maps neighborhood names to their zip codes.
    Used for delivery zone lookups when customers specify a neighborhood.
    """
    __tablename__ = "neighborhood_zip_codes"

    id = Column(Integer, primary_key=True, index=True)
    neighborhood = Column(String(100), unique=True, nullable=False, index=True)
    zip_codes = Column(JSON, nullable=False, default=list)  # List of zip codes
    borough = Column(String(50), nullable=True)  # Manhattan, Brooklyn, Queens, Bronx


class Company(Base):
    """
    Stores company-level settings such as name, contact info, branding.
    This is a single-row table - there should only be one company record.
    """
    __tablename__ = "company"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="Sammy's Subs")  # Company name shown to customers
    bot_persona_name = Column(String, nullable=False, default="Sammy")  # Bot's name/persona
    tagline = Column(String, nullable=True)  # e.g., "The best subs in town!"
    signature_item_label = Column(String, nullable=True)  # Custom label for signature items (e.g., "speed menu bagel")

    # Contact info
    headquarters_address = Column(String, nullable=True)
    corporate_phone = Column(String, nullable=True)
    corporate_email = Column(String, nullable=True)
    website = Column(String, nullable=True)

    # Social media & feedbackt
    instagram_handle = Column(String, nullable=True)  # e.g., "@zuckersbagels"
    feedback_form_url = Column(String, nullable=True)  # URL to customer feedback form

    # Branding
    logo_url = Column(String, nullable=True)  # URL to company logo

    # Business hours (JSON for structured format)
    business_hours = Column(JSON, nullable=True)  # e.g., {"mon": "9-5", "tue": "9-5", ...}

    # Online Payment Provider
    payment_provider = Column(String, nullable=False, default="stripe")  # "stripe" or "square"

    # Payment Methods
    accepts_credit_cards = Column(Boolean, nullable=False, default=True)
    accepts_debit_cards = Column(Boolean, nullable=False, default=True)
    accepts_cash = Column(Boolean, nullable=False, default=True)
    accepts_apple_pay = Column(Boolean, nullable=False, default=False)
    accepts_google_pay = Column(Boolean, nullable=False, default=False)
    accepts_venmo = Column(Boolean, nullable=False, default=False)
    accepts_paypal = Column(Boolean, nullable=False, default=False)

    # Dietary & Certification Info
    is_kosher = Column(Boolean, nullable=False, default=False)
    kosher_certification = Column(String, nullable=True)  # e.g., "Tablet K", "OU", "OK"
    is_halal = Column(Boolean, nullable=False, default=False)
    has_vegetarian_options = Column(Boolean, nullable=False, default=True)
    has_vegan_options = Column(Boolean, nullable=False, default=True)
    has_gluten_free_options = Column(Boolean, nullable=False, default=False)

    # Amenities
    wifi_available = Column(Boolean, nullable=False, default=False)
    wheelchair_accessible = Column(Boolean, nullable=False, default=True)
    outdoor_seating = Column(Boolean, nullable=False, default=False)

    # Catering
    offers_catering = Column(Boolean, nullable=False, default=False)
    catering_minimum_order = Column(Numeric(10, 2), nullable=True)  # e.g., 50.00
    catering_advance_notice_hours = Column(Integer, nullable=True)  # e.g., 24
    catering_phone = Column(String, nullable=True)
    catering_email = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    size_categories = relationship("MenuItemSizeCategory", back_populates="company", cascade="all, delete-orphan")
    sizes = relationship("MenuItemSize", back_populates="company", cascade="all, delete-orphan")


class MenuItemSizeCategory(Base):
    """
    Categories for menu item sizes (e.g., 'size', 'weight', 'quantity').

    Each category has a question_text used when asking customers to choose
    (e.g., "What size?" for size, "How much would you like?" for weight).

    Categories are company-scoped to allow customization per deployment.
    """
    __tablename__ = "menu_item_size_categories"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String(50), nullable=False)  # e.g., "size", "weight", "quantity"
    name = Column(String(100), nullable=False)  # Display name: "Size", "Weight", "Quantity"
    question_text = Column(String(200), nullable=True)  # e.g., "What size?", "How much would you like?"
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "slug", name="uix_size_category_company_slug"),
    )

    # Relationships
    company = relationship("Company", back_populates="size_categories")
    sizes = relationship("MenuItemSize", back_populates="category", cascade="all, delete-orphan")
    menu_items = relationship("MenuItem", back_populates="size_category")


class MenuItemSize(Base):
    """
    Individual size options within a category (e.g., 'small', 'large', '1/4 lb', 'each').

    Sizes are company-scoped and belong to a category. The display_order
    controls how sizes are presented to customers.
    """
    __tablename__ = "menu_item_sizes"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("company.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("menu_item_size_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # e.g., "small", "large", "1/4 lb", "each"
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("category_id", "name", name="uix_size_category_name"),
    )

    # Relationships
    company = relationship("Company", back_populates="sizes")
    category = relationship("MenuItemSizeCategory", back_populates="sizes")
    price_entries = relationship("MenuItemSizePrice", back_populates="size", cascade="all, delete-orphan")


class MenuItemSizePrice(Base):
    """
    Explicit price for a menu item at a specific size.

    This replaces the base_price + upcharge model for items with size variants.
    Each menu item must have at least one size_price entry.

    Examples:
        - Hot Coffee (small): $3.45
        - Hot Coffee (large): $4.35
        - Nova Lox (1/4 lb): $9.00
        - Cookie (each): $2.50
    """
    __tablename__ = "menu_item_size_prices"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False, index=True)
    size_id = Column(Integer, ForeignKey("menu_item_sizes.id", ondelete="CASCADE"), nullable=False, index=True)
    price = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("menu_item_id", "size_id", name="uix_menu_item_size_price"),
    )

    # Relationships
    menu_item = relationship("MenuItem", back_populates="size_prices")
    size = relationship("MenuItemSize", back_populates="price_entries")
