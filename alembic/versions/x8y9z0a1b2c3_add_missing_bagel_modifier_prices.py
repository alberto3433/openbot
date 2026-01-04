"""Add missing bagel modifier prices to attribute_options.

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2025-01-04 18:00:00.000000

This migration adds pricing for bagel modifiers that were missing from attribute_options:
- Egg Whites (protein) - $1.00 upcharge
- Spinach (topping) - $0.50
- Mushrooms (topping) - $0.50
- Green Pepper (topping) - $0.50
- Red Pepper (topping) - $0.50
- Lettuce (topping) - $0.00

Prices sourced from Zucker's Bagels menu (https://www.menuxp.com/zuckers-bagels-menu)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "x8y9z0a1b2c3"
down_revision: Union[str, None] = "w7x8y9z0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New protein options to add (with upcharge prices)
# Note: slug is "egg_white" (singular) to match parser normalization in constants.py
NEW_PROTEINS = [
    {"slug": "egg_white", "display_name": "Egg White", "price_modifier": 1.00},
]

# New topping options to add (with upcharge prices)
NEW_TOPPINGS = [
    {"slug": "spinach", "display_name": "Spinach", "price_modifier": 0.50},
    {"slug": "mushrooms", "display_name": "Mushrooms", "price_modifier": 0.50},
    {"slug": "green_pepper", "display_name": "Green Pepper", "price_modifier": 0.50},
    {"slug": "red_pepper", "display_name": "Red Pepper", "price_modifier": 0.50},
    {"slug": "lettuce", "display_name": "Lettuce", "price_modifier": 0.00},
    {"slug": "cucumber", "display_name": "Cucumber", "price_modifier": 0.25},
    {"slug": "pickles", "display_name": "Pickles", "price_modifier": 0.25},
]


def create_option_if_not_exists(
    session,
    attr_def_id: int,
    slug: str,
    display_name: str,
    price_modifier: float,
    display_order: int,
) -> None:
    """Create an attribute option if it doesn't already exist."""
    existing = session.execute(
        sa.text("""
            SELECT id FROM attribute_options
            WHERE attribute_definition_id = :attr_def_id AND slug = :slug
        """),
        {"attr_def_id": attr_def_id, "slug": slug}
    ).fetchone()

    if existing:
        # Update price if exists
        session.execute(
            sa.text("""
                UPDATE attribute_options
                SET price_modifier = :price_modifier,
                    display_name = :display_name
                WHERE id = :id
            """),
            {
                "id": existing[0],
                "price_modifier": price_modifier,
                "display_name": display_name,
            }
        )
    else:
        # Insert new option
        session.execute(
            sa.text("""
                INSERT INTO attribute_options
                (attribute_definition_id, slug, display_name, price_modifier, iced_price_modifier, is_default, display_order, is_available)
                VALUES (:attr_def_id, :slug, :display_name, :price_modifier, 0.0, FALSE, :display_order, TRUE)
            """),
            {
                "attr_def_id": attr_def_id,
                "slug": slug,
                "display_name": display_name,
                "price_modifier": price_modifier,
                "display_order": display_order,
            }
        )


def upgrade() -> None:
    """Add missing bagel modifier prices."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get bagel item type ID
    bagel_result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()

    if not bagel_result:
        print("Warning: bagel item type not found, skipping migration")
        return

    bagel_type_id = bagel_result[0]

    # Get protein attribute definition for bagels
    protein_attr = session.execute(
        sa.text("""
            SELECT id FROM attribute_definitions
            WHERE item_type_id = :item_type_id AND slug = 'protein'
        """),
        {"item_type_id": bagel_type_id}
    ).fetchone()

    if protein_attr:
        protein_attr_id = protein_attr[0]
        # Get current max display_order
        max_order = session.execute(
            sa.text("""
                SELECT COALESCE(MAX(display_order), 0) FROM attribute_options
                WHERE attribute_definition_id = :attr_def_id
            """),
            {"attr_def_id": protein_attr_id}
        ).scalar()

        for i, opt in enumerate(NEW_PROTEINS):
            create_option_if_not_exists(
                session, protein_attr_id, opt["slug"], opt["display_name"],
                opt["price_modifier"], max_order + i + 1
            )

    # Get topping attribute definition for bagels
    topping_attr = session.execute(
        sa.text("""
            SELECT id FROM attribute_definitions
            WHERE item_type_id = :item_type_id AND slug = 'topping'
        """),
        {"item_type_id": bagel_type_id}
    ).fetchone()

    if topping_attr:
        topping_attr_id = topping_attr[0]
        # Get current max display_order
        max_order = session.execute(
            sa.text("""
                SELECT COALESCE(MAX(display_order), 0) FROM attribute_options
                WHERE attribute_definition_id = :attr_def_id
            """),
            {"attr_def_id": topping_attr_id}
        ).scalar()

        for i, opt in enumerate(NEW_TOPPINGS):
            create_option_if_not_exists(
                session, topping_attr_id, opt["slug"], opt["display_name"],
                opt["price_modifier"], max_order + i + 1
            )

    # Also add to sandwich item type for consistency
    sandwich_result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'sandwich'")
    ).fetchone()

    if sandwich_result:
        sandwich_type_id = sandwich_result[0]

        # Sandwich protein
        sandwich_protein = session.execute(
            sa.text("""
                SELECT id FROM attribute_definitions
                WHERE item_type_id = :item_type_id AND slug = 'protein'
            """),
            {"item_type_id": sandwich_type_id}
        ).fetchone()

        if sandwich_protein:
            protein_attr_id = sandwich_protein[0]
            max_order = session.execute(
                sa.text("""
                    SELECT COALESCE(MAX(display_order), 0) FROM attribute_options
                    WHERE attribute_definition_id = :attr_def_id
                """),
                {"attr_def_id": protein_attr_id}
            ).scalar()

            for i, opt in enumerate(NEW_PROTEINS):
                create_option_if_not_exists(
                    session, protein_attr_id, opt["slug"], opt["display_name"],
                    opt["price_modifier"], max_order + i + 1
                )

        # Sandwich topping
        sandwich_topping = session.execute(
            sa.text("""
                SELECT id FROM attribute_definitions
                WHERE item_type_id = :item_type_id AND slug = 'topping'
            """),
            {"item_type_id": sandwich_type_id}
        ).fetchone()

        if sandwich_topping:
            topping_attr_id = sandwich_topping[0]
            max_order = session.execute(
                sa.text("""
                    SELECT COALESCE(MAX(display_order), 0) FROM attribute_options
                    WHERE attribute_definition_id = :attr_def_id
                """),
                {"attr_def_id": topping_attr_id}
            ).scalar()

            for i, opt in enumerate(NEW_TOPPINGS):
                create_option_if_not_exists(
                    session, topping_attr_id, opt["slug"], opt["display_name"],
                    opt["price_modifier"], max_order + i + 1
                )

    session.commit()


def downgrade() -> None:
    """Remove the added modifier options."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Remove new protein options
    for opt in NEW_PROTEINS:
        session.execute(
            sa.text("DELETE FROM attribute_options WHERE slug = :slug"),
            {"slug": opt["slug"]}
        )

    # Remove new topping options
    for opt in NEW_TOPPINGS:
        session.execute(
            sa.text("DELETE FROM attribute_options WHERE slug = :slug"),
            {"slug": opt["slug"]}
        )

    session.commit()
