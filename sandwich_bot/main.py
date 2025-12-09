from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid
import random  # NEW

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import engine, get_db
from .models import Base, MenuItem, Order, OrderItem
from .llm_client import call_sandwich_bot
from .order_logic import apply_intent_to_order_state
from .menu_index_builder import build_menu_index
from .inventory import apply_inventory_decrement_on_confirm, OutOfStockError

# Create tables on startup (for local dev / simple deployment)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sandwich Bot API")

# Allow local static HTML and JS to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store for MVP
SESSIONS: Dict[str, Dict[str, Any]] = {}

# Mount static files (chat UI, admin UI)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------- Pydantic models for chat / menu ----------

class ChatStartResponse(BaseModel):
    session_id: str
    message: str  # NEW: initial greeting from Sammy


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str


class ChatMessageResponse(BaseModel):
    reply: str
    order_state: Dict[str, Any]
    intent: str
    slots: Dict[str, Any]


class MenuItemOut(BaseModel):
    id: int
    name: str
    category: str
    is_signature: bool
    base_price: float
    available_qty: int
    metadata: Dict[str, Any]

    class Config:
        orm_mode = True


# ---------- Pydantic models for orders admin UI ----------

class OrderSummaryOut(BaseModel):
    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    pickup_time: Optional[str] = None
    total_price: float

    class Config:
        orm_mode = True


class OrderItemOut(BaseModel):
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
    quantity: int
    unit_price: float
    line_total: float

    class Config:
        orm_mode = True


class OrderDetailOut(BaseModel):
    id: int
    status: str
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    pickup_time: Optional[str] = None
    total_price: float
    created_at: str
    items: List[OrderItemOut]

    class Config:
        orm_mode = True


class OrderListResponse(BaseModel):
    items: List[OrderSummaryOut]
    page: int
    page_size: int
    total: int
    has_next: bool


# ---------- Health ----------

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


# ---------- Chat endpoints ----------


@app.post("/chat/start", response_model=ChatStartResponse)
def chat_start() -> ChatStartResponse:
    session_id = str(uuid.uuid4())
    # Initialize order state
    SESSIONS[session_id] = {
        "history": [],
        "order": {
            "status": "pending",
            "items": [],
            "customer": {
                "name": None,
                "phone": None,
                "pickup_time": None,
            },
            "total_price": 0.0,
        },
    }

    # Sammy starts the conversation
    greetings = [
        "Hello, how can I help you?",
        "Hi! Would you like to try one of our signature sandwiches or build your own?",
    ]
    welcome = random.choice(greetings)

    # Store initial assistant message in history
    SESSIONS[session_id]["history"].append(
        {"role": "assistant", "content": welcome}
    )

    return ChatStartResponse(session_id=session_id, message=welcome)


@app.post("/chat/message", response_model=ChatMessageResponse)
def chat_message(
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    session = SESSIONS.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Invalid session_id")

    history: List[Dict[str, str]] = session["history"]
    order_state: Dict[str, Any] = session["order"]

    # Build menu index for LLM
    menu_index = build_menu_index(db)

    # Call OpenAI (LLM)
    llm_result = call_sandwich_bot(
        history,
        order_state,
        menu_index,
        req.message,
    )

    intent = llm_result.get("intent", "unknown")
    slots = llm_result.get("slots", {})
    reply = llm_result.get("reply", "")

    # Apply deterministic business logic
    try:
        updated_order_state = apply_intent_to_order_state(order_state, intent, slots, menu_index)
    except OutOfStockError as e:
        reply = str(e)
    else:
        # If confirming order, decrement inventory and persist
        if intent == "confirm_order" and updated_order_state.get("status") == "confirmed":
            apply_inventory_decrement_on_confirm(db, updated_order_state)
            persist_confirmed_order(db, updated_order_state)
        session["order"] = updated_order_state

    # Update history
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    return ChatMessageResponse(
        reply=reply,
        order_state=session["order"],
        intent=intent,
        slots=slots,
    )


# ---------- Persist confirmed orders ----------

def persist_confirmed_order(db: Session, order_state: Dict[str, Any]) -> Order:
    """
    Persist a confirmed order + its items to the database.
    """
    if order_state.get("status") != "confirmed":
        return None  # nothing to persist

    customer = order_state.get("customer", {}) or {}
    items = order_state.get("items", []) or []

    order = Order(
        status="confirmed",
        customer_name=customer.get("name"),
        phone=customer.get("phone"),
        pickup_time=customer.get("pickup_time"),
        total_price=order_state.get("total_price", 0.0),
        created_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()  # assign order.id

    for it in items:
        oi = OrderItem(
            order_id=order.id,
            menu_item_name=it.get("menu_item_name") or it.get("name"),
            item_type=it.get("item_type"),
            size=it.get("size"),
            bread=it.get("bread"),
            protein=it.get("protein"),
            cheese=it.get("cheese"),
            toppings=it.get("toppings") or [],
            sauces=it.get("sauces") or [],
            toasted=it.get("toasted"),
            quantity=it.get("quantity", 1),
            unit_price=it.get("unit_price", 0.0),
            line_total=it.get("line_total", 0.0),
        )
        db.add(oi)

    db.commit()
    db.refresh(order)
    return order


# ---------- Admin menu endpoint ----------

@app.get("/admin/menu", response_model=List[MenuItemOut])
def admin_menu(db: Session = Depends(get_db)) -> List[MenuItemOut]:
    items = db.query(MenuItem).all()
    return [
        MenuItemOut(
            id=m.id,
            name=m.name,
            category=m.category,
            is_signature=m.is_signature,
            base_price=m.base_price,
            available_qty=m.available_qty,
            metadata=m.metadata or {},
        )
        for m in items
    ]


# ---------- Admin orders endpoints (for UI) ----------

@app.get("/admin/orders", response_model=OrderListResponse)
def list_orders(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(
        None,
        description="Filter by status: pending, confirmed, or leave empty for all",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> OrderListResponse:
    """
    Return a paginated list of orders.
    """
    query = db.query(Order)

    if status in ("pending", "confirmed"):
        query = query.filter(Order.status == status)

    total = query.count()
    offset = (page - 1) * page_size

    orders = (
        query.order_by(Order.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items = [
        OrderSummaryOut(
            id=o.id,
            status=o.status,
            customer_name=o.customer_name,
            phone=o.phone,
            pickup_time=o.pickup_time,
            total_price=o.total_price,
        )
        for o in orders
    ]

    has_next = offset + len(items) < total

    return OrderListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=has_next,
    )


@app.get("/admin/orders/{order_id}", response_model=OrderDetailOut)
def get_order_detail(order_id: int, db: Session = Depends(get_db)) -> OrderDetailOut:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items_out = [OrderItemOut.from_orm(item) for item in order.items]

    created_at_str = ""
    if getattr(order, "created_at", None):
        created_at_str = order.created_at.isoformat()

    return OrderDetailOut(
        id=order.id,
        status=order.status,
        customer_name=order.customer_name,
        phone=order.phone,
        pickup_time=order.pickup_time,
        total_price=order.total_price,
        created_at=created_at_str,
        items=items_out,
    )
