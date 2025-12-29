"""
Chat Schemas for Sandwich Bot
=============================

This module defines Pydantic models for the chat API endpoints, which handle
real-time customer conversations for ordering food. These schemas validate
incoming requests and structure outgoing responses.

Endpoint Coverage:
------------------
- POST /chat/start: Start a new chat session
- POST /chat/message: Send a message and receive a response
- POST /chat/message/stream: Streaming version of message endpoint
- POST /chat/abandon: Log an abandoned session for analytics

Key Concepts:
-------------
1. **Sessions**: Each conversation is identified by a session_id (UUID).
   Sessions persist conversation history and order state.

2. **Actions**: The bot's response includes "actions" that describe what
   operations were performed (add_item, remove_item, confirm_order, etc.).
   This structured data allows the frontend to update the UI accordingly.

3. **Returning Customers**: When a caller_id (phone number) is provided,
   the system looks up previous orders to personalize the experience.

4. **Order State**: The current state of the customer's order is returned
   with each response, including items, totals, and customer info.

Validation:
-----------
- Message length is constrained by MAX_MESSAGE_LENGTH (default: 2000 chars)
  to prevent excessive LLM token usage and potential abuse.
- Session IDs must be valid UUIDs.
- All required fields are enforced by Pydantic.

Usage:
------
These schemas are used as type annotations on route functions:

    @router.post("/message", response_model=ChatMessageResponse)
    def chat_message(req: ChatMessageRequest, db: Session = Depends(get_db)):
        # req is automatically validated
        # response is automatically serialized
        return ChatMessageResponse(...)
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..config import MAX_MESSAGE_LENGTH


class ReturningCustomerInfo(BaseModel):
    """
    Information about a returning customer identified by caller ID.

    When a customer calls from a phone number that matches a previous order,
    this data is used to personalize the greeting and offer repeat orders.

    Attributes:
        name: Customer's name from their last order
        phone: Phone number used for identification
        order_count: Total number of previous orders
        last_order_items: Items from their most recent order (for "usual" feature)
        last_order_date: ISO format date of last order
    """
    name: Optional[str] = None
    phone: Optional[str] = None
    order_count: int = 0
    last_order_items: List[Dict[str, Any]] = []
    last_order_date: Optional[str] = None


class ChatStartResponse(BaseModel):
    """
    Response from starting a new chat session.

    Returned by POST /chat/start. Contains the session identifier and
    initial greeting message, plus optional returning customer info.

    Attributes:
        session_id: UUID for this chat session (use in subsequent requests)
        message: Initial greeting from the bot (personalized for returning customers)
        returning_customer: Present if caller_id matched a previous customer
    """
    session_id: str
    message: str
    returning_customer: Optional[ReturningCustomerInfo] = None


class ChatMessageRequest(BaseModel):
    """
    Request body for sending a chat message.

    Used by POST /chat/message and POST /chat/message/stream.

    Attributes:
        session_id: UUID of the current chat session
        message: Customer's message text (1-2000 characters)

    Validation:
        - message must be at least 1 character
        - message cannot exceed MAX_MESSAGE_LENGTH (prevents LLM token abuse)
    """
    session_id: str
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)


class ActionOut(BaseModel):
    """
    A single action performed by the bot on the order.

    Actions represent structured operations that the bot performed in response
    to a customer message. The frontend uses these to update the cart UI.

    Common intents:
        - add_sandwich, add_pizza, add_bagel: Add item to order
        - add_coffee, add_drink: Add beverage to order
        - remove_item: Remove item from order
        - modify_item: Change an existing item
        - set_pickup_time: Customer specified pickup time
        - collect_customer_info: Got customer name/phone
        - confirm_order: Order was confirmed
        - request_payment_link: Customer wants payment link

    Attributes:
        intent: The type of action (see common intents above)
        slots: Key-value pairs with action details (varies by intent)
    """
    intent: str
    slots: Dict[str, Any]


class ChatMessageResponse(BaseModel):
    """
    Response from sending a chat message.

    Contains the bot's reply, updated order state, and structured actions.
    The frontend uses this to display the response and update the cart.

    Attributes:
        reply: Bot's natural language response to display
        order_state: Complete current order (items, customer, totals)
        actions: List of structured actions performed (for UI updates)
        intent: Primary intent (deprecated, use actions[0].intent)
        slots: Primary slots (deprecated, use actions[0].slots)

    Deprecation Note:
        The `intent` and `slots` fields are maintained for backward
        compatibility with older frontend versions. New code should
        use the `actions` list which supports multiple actions per turn.
    """
    reply: str
    order_state: Dict[str, Any]
    actions: List[ActionOut] = Field(
        default_factory=list,
        description="List of actions performed"
    )
    # Deprecated fields for backward compatibility
    intent: Optional[str] = Field(
        None,
        description="Primary intent (deprecated, use actions)"
    )
    slots: Optional[Dict[str, Any]] = Field(
        None,
        description="Primary slots (deprecated, use actions)"
    )


class AbandonedSessionRequest(BaseModel):
    """
    Request body for logging an abandoned session.

    Called by the frontend when a user closes the browser, navigates away,
    or the session times out. Used for analytics to understand abandonment
    patterns and improve the ordering experience.

    Attributes:
        session_id: UUID of the abandoned session
        message_count: Number of messages exchanged
        had_items_in_cart: Whether cart had items when abandoned
        item_count: Number of items in cart
        cart_total: Total value of abandoned cart
        order_status: Status when abandoned (usually "pending")
        last_bot_message: Last message from bot (truncated for storage)
        last_user_message: Last message from user (truncated for storage)
        reason: Why session was abandoned (browser_close, refresh, navigation)
        session_duration_seconds: How long session was active
        conversation_history: Full conversation for analysis
        store_id: Store identifier for per-store analytics
    """
    session_id: str
    message_count: int = 0
    had_items_in_cart: bool = False
    item_count: int = 0
    cart_total: float = 0.0
    order_status: str = "pending"
    last_bot_message: Optional[str] = None
    last_user_message: Optional[str] = None
    reason: str = "browser_close"  # browser_close, refresh, navigation
    session_duration_seconds: Optional[int] = None
    conversation_history: Optional[List[Dict[str, str]]] = None
    store_id: Optional[str] = None
