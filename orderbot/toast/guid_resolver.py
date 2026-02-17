"""
Toast GUID Resolver
========================

Looks up Toast GUIDs from the toast_guid_map table for local entity IDs.
Provides request-scoped caching to avoid repeated DB queries within a
single order submission.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..db.models.toast import ToastGuidMap

logger = logging.getLogger(__name__)


class GuidResolver:
    """Resolves local entity IDs to Toast GUIDs with caching.

    Create one per order submission request; the internal cache avoids
    repeated DB lookups for the same entity.

    Args:
        db: SQLAlchemy session
        store_id: Optional store scope (falls back to store_id=NULL mappings)
    """

    def __init__(self, db: Session, store_id: str | None = None):
        self._db = db
        self._store_id = store_id
        self._cache: dict[str, str | None] = {}

    def _cache_key(self, entity_type: str, local_id: int) -> str:
        return f"{entity_type}:{local_id}"

    def resolve(self, entity_type: str, local_id: int) -> str | None:
        """Resolve a local entity ID to a Toast GUID.

        Checks store-specific mapping first, then falls back to global (store_id=NULL).

        Args:
            entity_type: Entity type ("menu_item", "ingredient", "dining_option")
            local_id: Our local database ID

        Returns:
            Toast GUID string, or None if not mapped.
        """
        key = self._cache_key(entity_type, local_id)
        if key in self._cache:
            return self._cache[key]

        # Try store-specific first, then global
        mapping = None
        if self._store_id:
            mapping = (
                self._db.query(ToastGuidMap)
                .filter(
                    ToastGuidMap.entity_type == entity_type,
                    ToastGuidMap.local_id == local_id,
                    ToastGuidMap.store_id == self._store_id,
                )
                .first()
            )

        if not mapping:
            mapping = (
                self._db.query(ToastGuidMap)
                .filter(
                    ToastGuidMap.entity_type == entity_type,
                    ToastGuidMap.local_id == local_id,
                    ToastGuidMap.store_id.is_(None),
                )
                .first()
            )

        guid = mapping.toast_guid if mapping else None
        self._cache[key] = guid
        return guid

    def resolve_menu_item(self, menu_item_id: int) -> str | None:
        """Resolve a menu item ID to a Toast GUID."""
        return self.resolve("menu_item", menu_item_id)

    def resolve_ingredient(self, ingredient_id: int) -> str | None:
        """Resolve an ingredient ID to a Toast GUID."""
        return self.resolve("ingredient", ingredient_id)

    def resolve_dining_option(self, dining_option_id: int) -> str | None:
        """Resolve a dining option ID to a Toast GUID."""
        return self.resolve("dining_option", dining_option_id)

    def get_unmapped_items(self, order_state: dict[str, Any]) -> list[str]:
        """Return names of items in the order that lack Toast GUID mappings.

        Useful for admin warnings and partial-order diagnostics.

        Args:
            order_state: Internal order state dict

        Returns:
            List of unmapped item display names
        """
        unmapped = []
        items = order_state.get("items", [])

        for item in items:
            menu_item_id = item.get("menu_item_id")
            if menu_item_id and not self.resolve_menu_item(menu_item_id):
                name = (
                    item.get("display_name")
                    or item.get("menu_item_name")
                    or f"item #{menu_item_id}"
                )
                unmapped.append(name)

        return unmapped
