"""Toast POS integration models.

Contains: ToastGuidMap — maps local entities to Toast GUIDs.
"""

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func

from .base import Base


class ToastGuidMap(Base):
    """Maps local entity IDs to Toast POS GUIDs.

    This generic mapping table supports any entity type (menu_item, ingredient,
    dining_option, etc.) and is store-scoped to support multi-location setups.
    """

    __tablename__ = "toast_guid_map"

    id = Column(Integer, primary_key=True, index=True)

    # What kind of entity: "menu_item", "ingredient", "dining_option", etc.
    entity_type = Column(String, nullable=False, index=True)

    # Our local ID (e.g. menu_items.id or ingredients.id)
    local_id = Column(Integer, nullable=False)

    # The corresponding Toast GUID
    toast_guid = Column(String, nullable=False)

    # Human-readable name from Toast (for admin UI display)
    toast_name = Column(String, nullable=True)

    # Store scope (nullable = applies to all stores)
    store_id = Column(String, nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "local_id", "store_id", name="uq_toast_guid_map"),
    )
