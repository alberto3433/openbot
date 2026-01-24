"""Add global_attribute_option_aliases table

Revision ID: add_global_attr_option_aliases
Revises: create_ingredient_units
Create Date: 2026-01-23

Adds a child table for global attribute option aliases.

This allows options like 'double_shot' to have aliases like '2 shots', 'two shots', etc.
without requiring a linked ingredient. The cache loader merges both option aliases
and linked ingredient aliases.

Aliases are globally unique across all alias tables (ItemTypeAlias, MenuItemAlias,
IngredientAlias, ModifierCategoryAlias, GlobalAttributeOptionAlias) to prevent
ambiguous lookups during parsing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_global_attr_option_aliases'
down_revision: Union[str, Sequence[str], None] = 'create_ingredient_units'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Shot option aliases: (option_slug, [list of aliases])
SHOT_ALIASES = [
    ("extra_shot", ["extra shot", "1 extra", "one extra", "an extra shot"]),
    ("double_shot", ["2 shots", "two shots", "double"]),
    ("triple_shot", ["3 shots", "three shots", "triple"]),
    ("quadruple_shot", ["4 shots", "four shots", "quad", "quadruple"]),
]


def upgrade() -> None:
    """Add global_attribute_option_aliases table and seed shot aliases."""
    # Create the table
    op.create_table(
        "global_attribute_option_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "global_attribute_option_id",
            sa.Integer(),
            sa.ForeignKey("global_attribute_options.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("alias", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # Seed shot aliases
    bind = op.get_bind()

    # Get the shots attribute ID first
    global_attrs_table = sa.table(
        "global_attributes",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
    )

    shots_attr = bind.execute(
        sa.select(global_attrs_table.c.id).where(global_attrs_table.c.slug == "shots")
    ).fetchone()

    if not shots_attr:
        # No shots attribute, skip seeding
        return

    shots_attr_id = shots_attr[0]

    # Get option IDs by slug within the shots attribute
    options_table = sa.table(
        "global_attribute_options",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
        sa.column("global_attribute_id", sa.Integer),
    )

    aliases_table = sa.table(
        "global_attribute_option_aliases",
        sa.column("id", sa.Integer),
        sa.column("global_attribute_option_id", sa.Integer),
        sa.column("alias", sa.String),
    )

    for option_slug, aliases in SHOT_ALIASES:
        # Get option ID for this slug within the shots attribute
        result = bind.execute(
            sa.select(options_table.c.id).where(
                sa.and_(
                    options_table.c.slug == option_slug,
                    options_table.c.global_attribute_id == shots_attr_id
                )
            )
        ).fetchone()

        if result:
            option_id = result[0]
            for alias in aliases:
                try:
                    bind.execute(
                        aliases_table.insert().values(
                            global_attribute_option_id=option_id,
                            alias=alias,
                        )
                    )
                except Exception:
                    # Skip if alias already exists (shouldn't happen with unique constraint)
                    pass


def downgrade() -> None:
    """Drop global_attribute_option_aliases table."""
    op.drop_table("global_attribute_option_aliases")
