"""Add alias for package_variety custom option and update package_contents question

Revision ID: a1b2c3d4e5f6
Revises: z5a6b7c8d9e0
Create Date: 2026-02-20

Adds "choose your bagel types" as an alias for the custom option of
package_variety so the frontend can linkify it in the question text.

Also simplifies the package_contents question to "What types would you like?"
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f8'
down_revision: Union[str, Sequence[str], None] = 'z5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add alias and update question text."""
    bind = op.get_bind()

    # --- Table references ---
    item_types = sa.table(
        "item_types",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
    )
    global_attrs = sa.table(
        "global_attributes",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
        sa.column("item_type_id", sa.Integer),
        sa.column("question_text", sa.String),
    )
    global_opts = sa.table(
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

    # --- Find bagel_package item type ---
    row = bind.execute(
        sa.select(item_types.c.id).where(item_types.c.slug == "bagel_package")
    ).fetchone()
    if not row:
        return
    bagel_package_id = row[0]

    # --- 1. Add alias for the custom option of package_variety ---
    variety_attr = bind.execute(
        sa.select(global_attrs.c.id).where(
            sa.and_(
                global_attrs.c.slug == "package_variety",
                global_attrs.c.item_type_id == bagel_package_id,
            )
        )
    ).fetchone()

    if variety_attr:
        custom_opt = bind.execute(
            sa.select(global_opts.c.id).where(
                sa.and_(
                    global_opts.c.slug == "custom",
                    global_opts.c.global_attribute_id == variety_attr[0],
                )
            )
        ).fetchone()

        if custom_opt:
            # Check alias doesn't already exist before inserting
            existing = bind.execute(
                sa.select(aliases_table.c.id).where(
                    aliases_table.c.alias == "choose your bagel types"
                )
            ).fetchone()
            if not existing:
                bind.execute(
                    aliases_table.insert().values(
                        global_attribute_option_id=custom_opt[0],
                        alias="choose your bagel types",
                    )
                )

    # --- 2. Update package_contents question text ---
    bind.execute(
        global_attrs.update()
        .where(
            sa.and_(
                global_attrs.c.slug == "package_contents",
                global_attrs.c.item_type_id == bagel_package_id,
            )
        )
        .values(question_text="What types would you like?")
    )


def downgrade() -> None:
    """Remove alias and restore original question text."""
    bind = op.get_bind()

    # --- Table references ---
    item_types = sa.table(
        "item_types",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
    )
    global_attrs = sa.table(
        "global_attributes",
        sa.column("id", sa.Integer),
        sa.column("slug", sa.String),
        sa.column("item_type_id", sa.Integer),
        sa.column("question_text", sa.String),
    )
    aliases_table = sa.table(
        "global_attribute_option_aliases",
        sa.column("id", sa.Integer),
        sa.column("alias", sa.String),
    )

    # Remove the alias
    bind.execute(
        aliases_table.delete().where(
            aliases_table.c.alias == "choose your bagel types"
        )
    )

    # Restore original question text
    row = bind.execute(
        sa.select(item_types.c.id).where(item_types.c.slug == "bagel_package")
    ).fetchone()
    if row:
        bind.execute(
            global_attrs.update()
            .where(
                sa.and_(
                    global_attrs.c.slug == "package_contents",
                    global_attrs.c.item_type_id == row[0],
                )
            )
            .values(question_text="What types of bagels would you like in your package? You can say things like '6 plain, 3 everything, 3 sesame'.")
        )
