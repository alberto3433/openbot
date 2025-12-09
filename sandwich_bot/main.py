import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .db import get_db, engine
from .models import Base, MenuItem
from .menu_index_builder import build_menu_index
from .order_logic import apply_intent_to_order_state
from .inventory import apply_inventory_decrement_on_confirm, OutOfStockError
from .llm_client import call_sandwich_bot

# Ensure tables exist (menu_items at least)
Base.metadata.create_all(bind=engine)

# Base paths for static files
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Sandwich Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (for the web chat UI)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_root():
    """
    Serve the chat UI at the root path.
    Expects static/index.html to exist under the project root.
    """
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(index_file))


# Simple in-memory session storage for MVP
SESSIONS: Dict[str, Dict[str, Any]] = {}


class ChatStartResponse(BaseModel):
    session_id: str
    reply: str
    order_state: Dict[str, Any]


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str


class ChatMessageResponse(BaseModel):
    session_id: str
    reply: str
    intent: str
    slots: Dict[str, Any]
    order_state: Dict[str, Any]


class MenuItemOut(BaseModel):
    id: int
    name: str
    category: str
    base_price: float
    available_qty: int

    class Config:
        orm_mode = True


def _initial_order_state() -> Dict[str, Any]:
    return {
        "status": "draft",
        "items": [],
        "customer": {
            "name": None,
            "phone": None,
            "pickup_time": None,
        },
        "total_price": None,
    }


@app.post("/chat/start", response_model=ChatStartResponse)
def chat_start(db: Session = Depends(get_db)) -> ChatStartResponse:  # db kept for future use
    session_id = str(uuid.uuid4())

    order_state = _initial_order_state()
    history: List[Dict[str, str]] = []

    SESSIONS[session_id] = {
        "order": order_state,
        "history": history,
    }

    reply = "Hi! Welcome to Sandwich Central. Would you like a signature sandwich or build your own?"

    return ChatStartResponse(
        session_id=session_id,
        reply=reply,
        order_state=order_state,
    )


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

    menu_index = build_menu_index(db)

    llm_result = call_sandwich_bot(
        conversation_history=history,
        current_order_state=order_state,
        menu_json=menu_index,
        user_message=req.message,
    )

    reply = llm_result["reply"]
    intent = llm_result["intent"]
    slots = llm_result["slots"]

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})

    updated_order_state = apply_intent_to_order_state(
        order_state,
        intent,
        slots,
        menu_index=menu_index,
    )

    if updated_order_state.get("status") == "confirmed":
        try:
            apply_inventory_decrement_on_confirm(db, updated_order_state)
        except OutOfStockError as e:
            updated_order_state["status"] = "inventory_failed"
            SESSIONS[req.session_id]["order"] = updated_order_state
            return ChatMessageResponse(
                session_id=req.session_id,
                reply=str(e),
                intent=intent,
                slots=slots,
                order_state=updated_order_state,
            )

    session["order"] = updated_order_state
    session["history"] = history

    return ChatMessageResponse(
        session_id=req.session_id,
        reply=reply,
        intent=intent,
        slots=slots,
        order_state=updated_order_state,
    )


@app.get("/admin/menu", response_model=list[MenuItemOut])
def get_menu(db: Session = Depends(get_db)) -> list[MenuItemOut]:
    items = db.query(MenuItem).all()
    return items
