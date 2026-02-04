"""Add attribute_inquiry_keywords table.

Maps inquiry keywords to attribute slugs for data-driven attribute inquiry parsing.
When user asks "what bagel types do you have?", the word "types" is matched
against this table to determine which attribute's options to show.

Revision ID: attr_inq_01
Revises: 56d472767269
Create Date: 2026-02-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "attr_inq_01"
down_revision: Union[str, Sequence[str], None] = "56d472767269"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed data for attribute inquiry keywords
# Format: (keyword, item_type_slug, attribute_slug)
ATTRIBUTE_INQUIRY_KEYWORDS = [
    # Bagel types/flavors -> bread attribute
    ("type", "bagel", "bread"),
    ("types", "bagel", "bread"),
    ("flavor", "bagel", "bread"),
    ("flavors", "bagel", "bread"),
    ("kind", "bagel", "bread"),
    ("kinds", "bagel", "bread"),
    ("variety", "bagel", "bread"),
    ("varieties", "bagel", "bread"),

    # Beverage sizes (works for any item type with size attribute)
    ("size", None, "size"),
    ("sizes", None, "size"),

    # Coffee temperature
    ("temperature", None, "temperature"),
    ("temperatures", None, "temperature"),

    # Generic "options" -> primary attribute (context-dependent)
    # For bagel, "options" means bread types
    ("option", "bagel", "bread"),
    ("options", "bagel", "bread"),
    ("choice", "bagel", "bread"),
    ("choices", "bagel", "bread"),

    # For sized_beverage, "options" means size
    ("option", "sized_beverage", "size"),
    ("options", "sized_beverage", "size"),
]


def upgrade() -> None:
    # Create the attribute_inquiry_keywords table
    op.create_table(
        "attribute_inquiry_keywords",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(50), nullable=False),
        sa.Column("item_type_slug", sa.String(50), nullable=True),
        sa.Column("attribute_slug", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("keyword", "item_type_slug", name="uq_attr_inquiry_keyword_item_type"),
    )
    op.create_index(op.f("ix_attribute_inquiry_keywords_id"), "attribute_inquiry_keywords", ["id"], unique=False)
    op.create_index(op.f("ix_attribute_inquiry_keywords_keyword"), "attribute_inquiry_keywords", ["keyword"], unique=False)
    op.create_index("idx_attr_inquiry_keyword_lookup", "attribute_inquiry_keywords", ["keyword", "item_type_slug"], unique=False)

    # Seed the data
    conn = op.get_bind()
    for keyword, item_type_slug, attribute_slug in ATTRIBUTE_INQUIRY_KEYWORDS:
        conn.execute(
            sa.text("""
                INSERT INTO attribute_inquiry_keywords (keyword, item_type_slug, attribute_slug)
                VALUES (:keyword, :item_type_slug, :attribute_slug)
            """),
            {
                "keyword": keyword,
                "item_type_slug": item_type_slug,
                "attribute_slug": attribute_slug,
            }
        )
        print(f"Created attribute inquiry keyword: {keyword} -> {attribute_slug} (item_type={item_type_slug})")


def downgrade() -> None:
    op.drop_index("idx_attr_inquiry_keyword_lookup", table_name="attribute_inquiry_keywords")
    op.drop_index(op.f("ix_attribute_inquiry_keywords_keyword"), table_name="attribute_inquiry_keywords")
    op.drop_index(op.f("ix_attribute_inquiry_keywords_id"), table_name="attribute_inquiry_keywords")
    op.drop_table("attribute_inquiry_keywords")
