"""
Order Schemas for Sandwich Bot
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
represents a single line item with its configuration (bread, toppings, etc.)
and calculated price.

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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class OrderItemOut(BaseModel):
    """
    Response model for an individual order line item.

    Represents one item in an order, including all customization details
    and the calculated price for that item.

    Attributes:
        id: Database primary key
        menu_item_name: Name of the menu item ordered
        item_type: Type category (sandwich, bagel, coffee, etc.)
        size: Size selection if applicable (small, medium, large)
        bread: Bread choice for sandwiches/bagels
        protein: Protein selection (turkey, ham, etc.)
        cheese: Cheese selection
        toppings: List of selected toppings
        sauces: List of selected sauces
        toasted: Whether the item should be toasted
        item_config: Additional config for drinks (style, milk, syrup, etc.)
        notes: Special instructions (e.g., "extra hot", "no ice")
        quantity: Number of this item ordered
        unit_price: Price per item before quantity multiplication
        line_total: Total price for this line (unit_price * quantity)
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_item_name: str
    item_type: Optional[str] = None
    size: Optional[str] = None
    bread: Optional[str] = None
    protein: Optional[str] = None
    cheese: Optional[str] = None
    toppings: Optional[List[str]] = None
    sauces: Optional[List[str]] = None
    toasted: Optional[bool] = None
    item_config: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    quantity: int
    unit_price: float
    line_total: float


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
    created_at: str
    items: List[OrderItemOut]


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
