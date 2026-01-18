"""remove_bagel_suffix_from_bread_slugs

Revision ID: 61205c36fc16
Revises: c5f34cd2963b
Create Date: 2026-01-18

This migration removes the redundant '_bagel' suffix from bread attribute option
slugs. For example:
- 'plain_bagel' -> 'plain'
- 'everything_bagel' -> 'everything'
- 'gf_plain_bagel' -> 'gf_plain'

This is part of making the codebase data-driven by eliminating the need for
the _normalize_bread_value() function in the parser.

Note: Compound bread types like 'french_toast_bagel', '*_sourdough_bagel' are
kept as-is because "bagel" is part of the bread type name (French Toast Bagel,
Sourdough Bagel).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '61205c36fc16'
down_revision = 'c5f34cd2963b'
branch_labels = None
depends_on = None


# Slugs to rename: old_slug -> new_slug
# Only core bagel types where '_bagel' is a redundant suffix
SLUG_RENAMES = {
    # Core bagel types
    'plain_bagel': 'plain',
    'sesame_bagel': 'sesame',
    'poppy_bagel': 'poppy',
    'onion_bagel': 'onion',
    'salt_bagel': 'salt',
    'garlic_bagel': 'garlic',
    'egg_bagel': 'egg',
    'rainbow_bagel': 'rainbow',
    'everything_bagel': 'everything',
    'sun_dried_tomato_bagel': 'sun_dried_tomato',
    'multigrain_bagel': 'multigrain',
    'cinnamon_raisin_bagel': 'cinnamon_raisin',
    'asiago_bagel': 'asiago',
    'jalapeno_cheddar_bagel': 'jalapeno_cheddar',
    'whole_wheat_bagel': 'whole_wheat',
    'pumpernickel_bagel': 'pumpernickel',
    # Gluten-free variants
    'gf_plain_bagel': 'gf_plain',
    'gf_everything_bagel': 'gf_everything',
    'gf_sesame_bagel': 'gf_sesame',
    'gf_cinnamon_raisin_bagel': 'gf_cinnamon_raisin',
}

# Slug to delete: generic 'bagel' that causes false positives
SLUG_TO_DELETE = 'bagel'


def upgrade():
    # Rename slugs
    for old_slug, new_slug in SLUG_RENAMES.items():
        op.execute(
            sa.text(
                "UPDATE global_attribute_options SET slug = :new_slug WHERE slug = :old_slug"
            ).bindparams(old_slug=old_slug, new_slug=new_slug)
        )

    # Delete the generic 'bagel' option that causes false positives
    op.execute(
        sa.text(
            "DELETE FROM global_attribute_options WHERE slug = :slug"
        ).bindparams(slug=SLUG_TO_DELETE)
    )


def downgrade():
    # Restore the generic 'bagel' option
    # Note: We need to get the global_attribute_id for 'bread'
    op.execute(
        sa.text("""
            INSERT INTO global_attribute_options
            (global_attribute_id, slug, display_name, price_modifier, is_default, is_available, display_order)
            SELECT id, 'bagel', 'Bagel', 0.0, false, true, 0
            FROM global_attributes WHERE slug = 'bread'
        """)
    )

    # Reverse the renames
    for old_slug, new_slug in SLUG_RENAMES.items():
        op.execute(
            sa.text(
                "UPDATE global_attribute_options SET slug = :old_slug WHERE slug = :new_slug"
            ).bindparams(old_slug=old_slug, new_slug=new_slug)
        )
