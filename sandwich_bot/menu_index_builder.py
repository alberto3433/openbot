from typing import Dict, Any
from sqlalchemy.orm import Session

from .models import MenuItem


def build_menu_index(db: Session) -> Dict[str, Dict[str, Any]]:
    """Build a mapping of menu item name -> details, for pricing and LLM context."""
    idx: Dict[str, Dict[str, Any]] = {}
    for m in db.query(MenuItem).all():
        idx[m.name] = {
            "id": m.id,
            "category": m.category,
            "is_signature": m.is_signature,
            "base_price": float(m.base_price),
            "available_qty": m.available_qty,
            "metadata": m.extra_metadata or {},
        }
    return idx
