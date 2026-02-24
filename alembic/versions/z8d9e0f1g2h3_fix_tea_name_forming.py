"""Remove is_name_forming from tea ingredient category

Tea flavor should not replace the menu item name "Hot Tea" — unlike bread
(where "Everything" replaces "Bagel"), tea flavor is a customization detail.

Revision ID: z8d9e0f1g2h3
Revises: z7c8d9e0f1g2
Create Date: 2026-02-24
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "z8d9e0f1g2h3"
down_revision = "z7c8d9e0f1g2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE ingredient_categories SET is_name_forming = false WHERE slug = 'tea'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ingredient_categories SET is_name_forming = true WHERE slug = 'tea'"
    )
