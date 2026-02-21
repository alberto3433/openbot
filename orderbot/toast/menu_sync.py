"""
Toast Menu Sync
===================

Fetches the Toast restaurant menu and auto-matches items to our local
menu_items table by name similarity. Creates GUID mappings for confident
matches and reports ambiguous ones for manual resolution.
"""

import logging
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session

from ..cache.base import normalize_text
from ..db.models.menu import MenuItem
from ..db.models.toast import ToastGuidMap

logger = logging.getLogger(__name__)

# Minimum similarity ratio to auto-match (0.0 - 1.0)
AUTO_MATCH_THRESHOLD = 0.85

# Below this, don't even report as a candidate
MIN_CANDIDATE_THRESHOLD = 0.5


def sync_menus(db: Session) -> dict[str, Any]:
    """Fetch Toast menu and create mappings for matching items.

    Returns:
        Summary dict with counts of auto-matched, ambiguous, and unmatched items.
    """
    from .service import get_menus, is_toast_configured

    if not is_toast_configured():
        return {"error": "Toast is not configured. Set TOAST_CLIENT_ID, TOAST_CLIENT_SECRET, and TOAST_RESTAURANT_GUID."}

    toast_menus = get_menus()
    if toast_menus is None:
        return {"error": "Failed to fetch Toast menus. Check credentials and connectivity."}

    # Extract all Toast menu items (flatten menu -> groups -> items)
    toast_items = _extract_toast_items(toast_menus)
    if not toast_items:
        return {"error": "No items found in Toast menu."}

    # Load local menu items
    local_items = db.query(MenuItem).filter(MenuItem.is_available.is_(True)).all()

    # Get already-mapped local IDs to skip
    existing_mappings = {
        row.local_id
        for row in db.query(ToastGuidMap.local_id)
        .filter(ToastGuidMap.entity_type == "menu_item")
        .all()
    }

    auto_matched = []
    ambiguous = []
    unmatched = []

    for toast_item in toast_items:
        toast_name = toast_item.get("name", "")
        toast_guid = toast_item.get("guid", "")

        if not toast_name or not toast_guid:
            continue

        # Find best local match
        match, score = _find_best_match(toast_name, local_items)

        if match and match.id in existing_mappings:
            # Already mapped, skip
            continue

        if match and score >= AUTO_MATCH_THRESHOLD:
            # Auto-match: create mapping
            mapping = ToastGuidMap(
                entity_type="menu_item",
                local_id=match.id,
                toast_guid=toast_guid,
                toast_name=toast_name,
            )
            db.add(mapping)
            existing_mappings.add(match.id)
            auto_matched.append({
                "toast_name": toast_name,
                "local_name": match.name,
                "local_id": match.id,
                "score": round(score, 3),
            })
        elif match and score >= MIN_CANDIDATE_THRESHOLD:
            ambiguous.append({
                "toast_name": toast_name,
                "toast_guid": toast_guid,
                "best_local_name": match.name,
                "best_local_id": match.id,
                "score": round(score, 3),
            })
        else:
            unmatched.append({
                "toast_name": toast_name,
                "toast_guid": toast_guid,
            })

    db.commit()

    return {
        "auto_matched": auto_matched,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "summary": {
            "auto_matched": len(auto_matched),
            "ambiguous": len(ambiguous),
            "unmatched": len(unmatched),
            "toast_items_total": len(toast_items),
        },
    }


def _extract_toast_items(menus: list) -> list[dict[str, Any]]:
    """Flatten Toast menu structure into a list of {name, guid} dicts."""
    items = []

    for menu in menus:
        if not isinstance(menu, dict):
            continue
        for group in menu.get("groups", []):
            if not isinstance(group, dict):
                continue
            for item in group.get("items", []):
                if isinstance(item, dict) and item.get("name") and item.get("guid"):
                    items.append({
                        "name": item["name"],
                        "guid": item["guid"],
                    })

    return items


def _find_best_match(
    toast_name: str,
    local_items: list,
) -> tuple[Any, float]:
    """Find the local menu item most similar to a Toast item name.

    Uses SequenceMatcher for fuzzy string matching (case-insensitive).

    Returns:
        Tuple of (best_match_MenuItem_or_None, similarity_score)
    """
    best_match = None
    best_score = 0.0
    toast_lower = normalize_text(toast_name)

    for item in local_items:
        local_lower = normalize_text(item.name)
        score = SequenceMatcher(None, toast_lower, local_lower).ratio()

        if score > best_score:
            best_score = score
            best_match = item

    return best_match, best_score
