"""Seed common unrecognized ingredient suggestions.

Revision ID: unrecognized_ingredient_02
Revises: unrecognized_ingredient_01
Create Date: 2026-02-18

Adds 10 common ingredient requests that aren't on the menu, with
appropriate alternatives we actually carry.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'unrecognized_ingredient_02'
down_revision: Union[str, Sequence[str], None] = 'unrecognized_ingredient_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (input_pattern, match_type, display_name, modifier_category, [alternative ingredient names])
SEED_DATA = [
    ("cream", "exact", "Cream", "milk", [
        "Half N Half", "Whole Milk", "Oat Milk",
    ]),
    ("asparagus", "exact", "Asparagus", "topping", [
        "Broccoli", "Spinach", "Sauteed Peppers",
    ]),
    ("stevia", "exact", "Stevia", "sweetener", [
        "Splenda", "Equal", "Sweet N Low",
    ]),
    ("agave", "exact", "Agave", "sweetener", [
        "Domino Sugar", "Sugar in the Raw", "Splenda",
    ]),
    ("coconut milk", "exact", "Coconut Milk", "milk", [
        "Oat Milk", "Almond Milk", "Soy Milk",
    ]),
    ("ranch", "exact", "Ranch", "condiment", [
        "Mayo", "Dijon Mayo", "Russian Dressing",
    ]),
    ("sriracha", "exact", "Sriracha", "condiment", [
        "Hot Sauce", "Jalapeno-Honey", "Salsa",
    ]),
    ("guacamole", "exact", "Guacamole", "spread", [
        "Avocado Spread", "Avocado", "Pico de Gallo",
    ]),
    ("jam", "exact", "Jam", "spread", [
        "Grape Jelly", "Strawberry Jelly",
    ]),
    ("maple syrup", "exact", "Maple Syrup", "syrup", [
        "Vanilla Syrup", "Caramel Syrup", "Hazelnut Syrup",
    ]),
]


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        for pattern, match_type, display, category, alt_names in SEED_DATA:
            # Insert suggestion
            session.execute(
                sa.text(
                    "INSERT INTO unrecognized_ingredient_suggestions "
                    "(input_pattern, match_type, suggested_display_name, modifier_category, hit_count, is_active) "
                    "VALUES (:pattern, :match_type, :display, :category, 0, true)"
                ),
                {"pattern": pattern, "match_type": match_type, "display": display, "category": category},
            )

            # Get the suggestion id
            result = session.execute(
                sa.text(
                    "SELECT id FROM unrecognized_ingredient_suggestions "
                    "WHERE input_pattern = :pattern AND match_type = :match_type"
                ),
                {"pattern": pattern, "match_type": match_type},
            )
            suggestion_id = result.scalar()

            # Link alternative ingredients
            for name in alt_names:
                result = session.execute(
                    sa.text("SELECT id FROM ingredients WHERE name = :name"),
                    {"name": name},
                )
                ingredient_id = result.scalar()
                if ingredient_id:
                    session.execute(
                        sa.text(
                            "INSERT INTO unrecognized_ingredient_suggestion_alternatives "
                            "(suggestion_id, ingredient_id) VALUES (:sid, :iid)"
                        ),
                        {"sid": suggestion_id, "iid": ingredient_id},
                    )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        patterns = [row[0] for row in SEED_DATA]
        for pattern in patterns:
            # Delete alternatives first (cascade should handle this, but be explicit)
            session.execute(
                sa.text(
                    "DELETE FROM unrecognized_ingredient_suggestion_alternatives "
                    "WHERE suggestion_id IN ("
                    "  SELECT id FROM unrecognized_ingredient_suggestions "
                    "  WHERE input_pattern = :pattern"
                    ")"
                ),
                {"pattern": pattern},
            )
            session.execute(
                sa.text(
                    "DELETE FROM unrecognized_ingredient_suggestions "
                    "WHERE input_pattern = :pattern"
                ),
                {"pattern": pattern},
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
