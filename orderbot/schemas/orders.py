"""
Order Schemas for Orderbot
==============================

This module defines Pydantic models for order management in the admin interface.
Orders represent completed or pending customer purchases, including all items,
customer information, and payment details.

Endpoint Coverage:
------------------
- GET /admin/orders: List orders with pagination and filtering
- GET /admin/orders/{id}: Get detailed order information

Order Lifecycle:
----------------
1. **Pending**: Customer is still building their order in chat
2. **Confirmed**: Customer confirmed the order, awaiting payment/pickup
3. **Completed**: Order has been fulfilled
4. **Cancelled**: Order was cancelled

Order Types:
------------
- **Pickup**: Customer will pick up at the store
- **Delivery**: Order will be delivered to customer's address

Tax Calculation:
----------------
Orders include separate city and state tax fields to support different
tax jurisdictions. Tax rates are configured per-store. The total_price
includes subtotal + taxes + delivery fee (if applicable).

Data Model:
-----------
Orders have a one-to-many relationship with OrderItems. Each OrderItem
represents a single line item with its modifiers and calculated price.

Usage:
------
    # List recent orders
    orders = OrderListResponse(
        items=[OrderSummaryOut.model_validate(order) for order in db_orders],
        page=1,
        page_size=20,
        total=100,
        has_next=True
    )

    # Get order with items
    detail = OrderDetailOut.model_validate(order)
    for item in detail.items:
        print(f"{item.menu_item_name}: ${item.line_total}")
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, model_validator


class OrderItemOut(BaseModel):
    """
    Response model for an individual order line item.

    Data-driven schema that works with any item type. All customizations
    are represented generically in the modifiers list.

    Attributes:
        id: Database primary key
        menu_item_name: Name of the menu item ordered (e.g., "Latte", "Everything Bagel")
        display_name: Full display name built by converter
        item_type: Item type slug from database (e.g., "sized_beverage", "bagel")
        modifiers: List of all customizations as {name: str, price: float}
        base_price: Base price before modifiers
        notes: Special instructions (e.g., "extra hot", "no ice")
        quantity: Number of this item ordered
        unit_price: Price per item (base + modifiers)
        line_total: Total price for this line (unit_price * quantity)
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_item_name: str
    display_name: Optional[str] = None
    item_type: Optional[str] = None
    modifiers: Optional[List[Dict[str, Any]]] = None
    base_price: Optional[float] = None
    notes: Optional[str] = None
    quantity: int
    unit_price: float
    line_total: float

    @model_validator(mode='before')
    @classmethod
    def extract_from_item_config(cls, data):
        """Extract generic fields from item_config JSON column."""
        # Handle ORM objects with from_attributes=True
        if hasattr(data, '__dict__'):
            obj_dict = {
                'id': getattr(data, 'id', None),
                'menu_item_name': getattr(data, 'menu_item_name', None),
                'quantity': getattr(data, 'quantity', None),
                'unit_price': getattr(data, 'unit_price', None),
                'line_total': getattr(data, 'line_total', None),
                'notes': getattr(data, 'notes', None),
            }
            # Extract generic fields from item_config
            item_config = getattr(data, 'item_config', None) or {}
            if isinstance(item_config, dict):
                obj_dict['item_type'] = item_config.get('item_type')
                obj_dict['display_name'] = item_config.get('display_name')
                obj_dict['modifiers'] = item_config.get('modifiers')
                obj_dict['base_price'] = item_config.get('base_price')
            return obj_dict
        return data


class OrderSummaryOut(BaseModel):
    """
    Response model for order list/summary view.

    Contains key order information without the full item details.
    Used for order listing endpoints where full details aren't needed.

    Attributes:
        id: Database primary key (order number)
        status: Current order status (pending, confirmed, completed, cancelled)
        customer_name: Customer's name
        phone: Customer's phone number
        customer_email: Customer's email address
        pickup_time: Requested pickup/delivery time
        subtotal: Sum of all item prices before tax
        city_tax: City/local tax amount
        state_tax: State tax amount
        delivery_fee: Delivery fee if applicable
        total_price: Final total (subtotal + taxes + delivery)
        store_id: Which store location this order is for
        order_type: "pickup" or "delivery"
        delivery_address: Delivery address if order_type is "delivery"
        payment_status: Payment state (pending, paid, refunded)
        payment_method: How customer will/did pay (cash, credit, etc.)
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    customer_email: Optional[str] = None
    pickup_time: Optional[str] = None
    subtotal: Optional[float] = None
    city_tax: Optional[float] = None
    state_tax: Optional[float] = None
    delivery_fee: Optional[float] = None
    total_price: float
    store_id: Optional[str] = None
    order_type: Optional[str] = None
    delivery_address: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    estimated_ready_at: Optional[Union[str, datetime]] = None
    staff_notes: Optional[str] = None
    created_at: Optional[Union[str, datetime]] = None


class OrderDetailOut(BaseModel):
    """
    Response model for detailed order view.

    Includes all order information plus the full list of items.
    Used when viewing a specific order's complete details.

    Attributes:
        (All fields from OrderSummaryOut, plus:)
        created_at: ISO timestamp when order was created
        items: List of all items in the order with full details
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    customer_email: Optional[str] = None
    pickup_time: Optional[str] = None
    subtotal: Optional[float] = None
    city_tax: Optional[float] = None
    state_tax: Optional[float] = None
    delivery_fee: Optional[float] = None
    total_price: float
    store_id: Optional[str] = None
    order_type: Optional[str] = None
    delivery_address: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    estimated_ready_at: Optional[Union[str, datetime]] = None
    ready_at: Optional[Union[str, datetime]] = None
    completed_at: Optional[Union[str, datetime]] = None
    cancelled_at: Optional[Union[str, datetime]] = None
    cancellation_reason: Optional[str] = None
    staff_notes: Optional[str] = None
    created_at: Union[str, datetime]
    updated_at: Optional[Union[str, datetime]] = None
    items: List[OrderItemOut]


class OrderStatusUpdateIn(BaseModel):
    """Request body for updating an order's status."""
    status: str
    note: Optional[str] = None
    cancellation_reason: Optional[str] = None


class OrderEstimatedTimeIn(BaseModel):
    """Request body for setting estimated ready time."""
    estimated_minutes: int  # Minutes from now


class OrderNotesIn(BaseModel):
    """Request body for updating staff notes."""
    staff_notes: str


class OrderStatusHistoryOut(BaseModel):
    """Response model for a single status history entry."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_status: Optional[str] = None
    to_status: str
    changed_by: Optional[str] = None
    note: Optional[str] = None
    created_at: Union[str, datetime]


class OrderListResponse(BaseModel):
    """
    Paginated response for order listing.

    Wraps a list of orders with pagination metadata for efficient
    navigation through large order histories.

    Attributes:
        items: List of orders for the current page
        page: Current page number (1-indexed)
        page_size: Number of items per page
        total: Total number of orders matching the query
        has_next: Whether there are more pages after this one

    Example:
        {
            "items": [...],
            "page": 1,
            "page_size": 20,
            "total": 157,
            "has_next": true
        }
    """
    items: List[OrderSummaryOut]
    page: int
    page_size: int
    total: int
    has_next: bool
