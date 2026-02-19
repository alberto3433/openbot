"""Add unrecognized_ingredient_suggestions table with seed data.

Revision ID: unrecognized_ingredient_01
Revises: unrecognized_rename_01
Create Date: 2026-02-18

Stores common ingredient requests not on the menu (e.g., "honey") along with
alternative ingredients we actually carry. Used to detect and suggest
alternatives during order parsing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'unrecognized_ingredient_01'
down_revision: Union[str, Sequence[str], None] = 'unrecognized_rename_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the suggestions table
    op.create_table(
        "unrecognized_ingredient_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("input_pattern", sa.String(100), nullable=False, index=True),
        sa.Column("match_type", sa.String(20), nullable=False, server_default="exact"),
        sa.Column("suggested_display_name", sa.String(100), nullable=False),
        sa.Column("modifier_category", sa.String(50), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_unrecognized_ingredient_suggestions_id"),
        "unrecognized_ingredient_suggestions",
        ["id"],
    )

    # Create junction table for alternative ingredients
    op.create_table(
        "unrecognized_ingredient_suggestion_alternatives",
        sa.Column("suggestion_id", sa.Integer(), sa.ForeignKey("unrecognized_ingredient_suggestions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True),
    )

    # Seed data: "honey" with sweetener alternatives
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        # Insert the honey suggestion
        session.execute(
            sa.text(
                "INSERT INTO unrecognized_ingredient_suggestions "
                "(input_pattern, match_type, suggested_display_name, modifier_category, hit_count, is_active) "
                "VALUES (:pattern, :match_type, :display, :category, 0, true)"
            ),
            {"pattern": "honey", "match_type": "exact", "display": "Honey", "category": "sweetener"},
        )

        # Get the suggestion id
        result = session.execute(
            sa.text("SELECT id FROM unrecognized_ingredient_suggestions WHERE input_pattern = 'honey'")
        )
        suggestion_id = result.scalar()

        # Find sweetener ingredient IDs by name
        sweetener_names = ["Domino Sugar", "Sugar in the Raw", "Splenda", "Equal", "Sweet N Low"]
        for name in sweetener_names:
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
    op.drop_table("unrecognized_ingredient_suggestion_alternatives")
    op.drop_table("unrecognized_ingredient_suggestions")
