"""Add weight option aliases for data-driven weight matching.

Revision ID: weight_alias_01
Revises: (will be set by alembic)
Create Date: 2025-02-07

This migration adds aliases to global_attribute_options for weight values,
replacing hardcoded weight variation generation in config_modification_handler.py
and config_change_handler.py.

After this migration, weight normalization like "pound" -> "1 lb" is handled
by the standard resolve_option_by_alias() lookup instead of hardcoded functions.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "weight_alias_01"
down_revision: Union[str, None] = "drop_iti_table_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Weight option aliases to add
# Format: (option_slug, list_of_aliases)
WEIGHT_ALIASES = [
    # 1 lb option - all the ways users might say "one pound"
    ("one_pound", [
        "pound",
        "lb",
        "pounds",
        "lbs",
        "1 pound",
        "one pound",
        "a pound",
        "1lb",
    ]),
    # 1/4 lb option - all the ways users might say "quarter pound"
    ("quarter_pound", [
        "quarter",
        "quarter pound",
        "quarter lb",
        "1/4 pound",
        "a quarter pound",
        "a quarter",
    ]),
]


def upgrade() -> None:
    conn = op.get_bind()

    for option_slug, aliases in WEIGHT_ALIASES:
        # Get the option ID
        result = conn.execute(
            sa.text("""
                SELECT gao.id
                FROM global_attribute_options gao
                JOIN global_attributes ga ON gao.global_attribute_id = ga.id
                WHERE ga.slug = 'weight' AND gao.slug = :slug
            """),
            {"slug": option_slug}
        )
        row = result.fetchone()

        if not row:
            print(f"Warning: Weight option '{option_slug}' not found")
            continue

        option_id = row[0]

        # Insert each alias (skip if already exists due to unique constraint)
        for alias in aliases:
            try:
                conn.execute(
                    sa.text("""
                        INSERT INTO global_attribute_option_aliases
                        (global_attribute_option_id, alias)
                        VALUES (:option_id, :alias)
                        ON CONFLICT (alias) DO NOTHING
                    """),
                    {"option_id": option_id, "alias": alias}
                )
                print(f"Added alias '{alias}' for {option_slug}")
            except Exception as e:
                print(f"Skipping alias '{alias}': {e}")

    conn.commit()


def downgrade() -> None:
    conn = op.get_bind()

    # Remove the aliases we added
    all_aliases = []
    for _, aliases in WEIGHT_ALIASES:
        all_aliases.extend(aliases)

    conn.execute(
        sa.text("""
            DELETE FROM global_attribute_option_aliases
            WHERE alias = ANY(:aliases)
        """),
        {"aliases": all_aliases}
    )
    conn.commit()
