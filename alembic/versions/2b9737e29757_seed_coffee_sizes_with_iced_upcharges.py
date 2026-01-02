"""seed_coffee_sizes_with_iced_upcharges

Revision ID: 2b9737e29757
Revises: j3k4l5m6n7o8
Create Date: 2026-01-01 17:26:45.529262

This migration creates the sized_beverage item type with size options
and sets the iced price modifiers for each size:
- Small: base $3.45, iced upcharge $1.65 = $5.10
- Large: base $4.35, iced upcharge $1.10 = $5.45
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '2b9737e29757'
down_revision: Union[str, Sequence[str], None] = 'j3k4l5m6n7o8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed sized_beverage item type with coffee sizes and iced upcharges."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Check if sized_beverage item type exists
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
    ).fetchone()

    if result:
        item_type_id = result[0]
    else:
        # Create sized_beverage item type
        session.execute(
            sa.text("""
                INSERT INTO item_types (slug, display_name, is_configurable, skip_config)
                VALUES ('sized_beverage', 'Sized Beverage', 1, 0)
            """)
        )
        result = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
        ).fetchone()
        item_type_id = result[0]

    # Check if size attribute definition exists for this item type
    attr_result = session.execute(
        sa.text("""
            SELECT id FROM attribute_definitions
            WHERE item_type_id = :item_type_id AND slug = 'size'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if attr_result:
        attr_def_id = attr_result[0]
    else:
        # Create size attribute definition
        session.execute(
            sa.text("""
                INSERT INTO attribute_definitions
                (item_type_id, slug, display_name, input_type, is_required, allow_none, display_order)
                VALUES (:item_type_id, 'size', 'Size', 'single_select', 1, 0, 1)
            """),
            {"item_type_id": item_type_id}
        )
        attr_result = session.execute(
            sa.text("""
                SELECT id FROM attribute_definitions
                WHERE item_type_id = :item_type_id AND slug = 'size'
            """),
            {"item_type_id": item_type_id}
        ).fetchone()
        attr_def_id = attr_result[0]

    # Size options with pricing:
    # Small: base price, no size upcharge, iced upcharge $1.65
    # Large: +$0.90 size upcharge, iced upcharge $1.10
    size_options = [
        {
            "slug": "small",
            "display_name": "Small",
            "price_modifier": 0.0,  # Base price for small
            "iced_price_modifier": 1.65,  # Small iced: $3.45 + $1.65 = $5.10
            "is_default": True,
            "display_order": 1,
        },
        {
            "slug": "large",
            "display_name": "Large",
            "price_modifier": 0.90,  # Large is +$0.90 over small ($3.45 + $0.90 = $4.35)
            "iced_price_modifier": 1.10,  # Large iced: $4.35 + $1.10 = $5.45
            "is_default": False,
            "display_order": 2,
        },
    ]

    for opt in size_options:
        # Check if option exists
        existing = session.execute(
            sa.text("""
                SELECT id FROM attribute_options
                WHERE attribute_definition_id = :attr_def_id AND slug = :slug
            """),
            {"attr_def_id": attr_def_id, "slug": opt["slug"]}
        ).fetchone()

        if existing:
            # Update existing option
            session.execute(
                sa.text("""
                    UPDATE attribute_options
                    SET price_modifier = :price_modifier,
                        iced_price_modifier = :iced_price_modifier,
                        is_default = :is_default,
                        display_order = :display_order
                    WHERE id = :id
                """),
                {
                    "id": existing[0],
                    "price_modifier": opt["price_modifier"],
                    "iced_price_modifier": opt["iced_price_modifier"],
                    "is_default": opt["is_default"],
                    "display_order": opt["display_order"],
                }
            )
        else:
            # Insert new option
            session.execute(
                sa.text("""
                    INSERT INTO attribute_options
                    (attribute_definition_id, slug, display_name, price_modifier, iced_price_modifier, is_default, display_order, is_available)
                    VALUES (:attr_def_id, :slug, :display_name, :price_modifier, :iced_price_modifier, :is_default, :display_order, 1)
                """),
                {
                    "attr_def_id": attr_def_id,
                    "slug": opt["slug"],
                    "display_name": opt["display_name"],
                    "price_modifier": opt["price_modifier"],
                    "iced_price_modifier": opt["iced_price_modifier"],
                    "is_default": opt["is_default"],
                    "display_order": opt["display_order"],
                }
            )

    session.commit()


def downgrade() -> None:
    """Remove the sized_beverage item type and related data."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get the item type id
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
    ).fetchone()

    if result:
        item_type_id = result[0]

        # Get attribute definition id
        attr_result = session.execute(
            sa.text("""
                SELECT id FROM attribute_definitions
                WHERE item_type_id = :item_type_id AND slug = 'size'
            """),
            {"item_type_id": item_type_id}
        ).fetchone()

        if attr_result:
            attr_def_id = attr_result[0]

            # Delete attribute options
            session.execute(
                sa.text("DELETE FROM attribute_options WHERE attribute_definition_id = :attr_def_id"),
                {"attr_def_id": attr_def_id}
            )

            # Delete attribute definition
            session.execute(
                sa.text("DELETE FROM attribute_definitions WHERE id = :attr_def_id"),
                {"attr_def_id": attr_def_id}
            )

        # Delete item type
        session.execute(
            sa.text("DELETE FROM item_types WHERE id = :item_type_id"),
            {"item_type_id": item_type_id}
        )

    session.commit()
