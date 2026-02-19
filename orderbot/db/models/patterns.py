"""Response pattern and attribute inquiry keyword models."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from .base import Base


class ResponsePattern(Base):
    """
    Stores patterns for recognizing user response types.

    This table enables data-driven response classification for:
    - Affirmative responses (yes, yeah, yep, sure, ok, etc.)
    - Negative responses (no, nope, nah, no thanks, etc.)
    - Cancel responses (cancel, never mind, forget it, etc.)
    - Done responses (that's all, that's it, nothing else, etc.)

    Patterns are matched case-insensitively against normalized user input.
    """
    __tablename__ = "response_pattern"

    id = Column(Integer, primary_key=True, index=True)
    pattern_type = Column(String(50), nullable=False, index=True)  # 'affirmative', 'negative', 'cancel', 'done', 'greeting'
    pattern = Column(String(100), nullable=False)  # The pattern to match (exact string or regex)
    is_regex = Column(Boolean, nullable=False, default=False)  # If True, pattern is treated as regex
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('pattern_type', 'pattern', name='uq_response_pattern_type_pattern'),
        Index('idx_response_pattern_type', 'pattern_type'),
    )


class AttributeInquiryKeyword(Base):
    """
    Maps inquiry keywords to global attributes for data-driven attribute inquiry parsing.

    When user asks "what bagel types do you have?", the word "types" (keyword)
    combined with the item type "bagel" is matched against this table to determine
    which attribute's options to show (e.g., "bread" attribute).

    Examples:
    - ("types", bagel_item_type_id) -> bread_global_attribute_id
    - ("sizes", None) -> size_global_attribute_id (None means any/no item type)
    - ("flavors", bagel_item_type_id) -> bread_global_attribute_id

    This replaces the hardcoded common_mappings dict in menu_options_inquiry_handler.py.
    """
    __tablename__ = "attribute_inquiry_keywords"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(50), nullable=False, index=True)  # e.g., "types", "sizes", "flavors"
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=True, index=True)
    global_attribute_id = Column(Integer, ForeignKey("global_attributes.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    item_type = relationship("ItemType")
    global_attribute = relationship("GlobalAttribute")

    __table_args__ = (
        UniqueConstraint('keyword', 'item_type_id', name='uq_attr_inquiry_keyword_item_type'),
        Index('idx_attr_inquiry_keyword_lookup', 'keyword', 'item_type_id'),
    )
