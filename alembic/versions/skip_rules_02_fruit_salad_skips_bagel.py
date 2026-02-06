"""Add skip rule: fruit_salad -> skip bagel_choice

When user selects fruit_salad as side_choice for an omelette,
skip asking about bagel_choice since they're not getting a bagel.

Note: cheese is NOT skipped because it's for the omelette's cheese filling,
not the bagel's cheese. The omelette can still have cheese regardless of side choice.

Revision ID: skip_rules_02
Revises: skip_rules_01
Create Date: 2026-02-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "skip_rules_02"
down_revision = "skip_rules_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add skip rule for fruit_salad -> bagel/bagel_choice."""
    # Insert skip rule: fruit_salad option -> skip bagel_choice attribute
    # Include both 'bagel' and 'bagel_choice' slugs to handle both naming conventions
    # Note: Do NOT skip 'cheese' - it's for the omelette filling, not the bagel
    op.execute("""
        INSERT INTO global_attribute_option_skips (triggering_option_id, skipped_attribute_id)
        SELECT opt.id, attr.id
        FROM global_attribute_options opt
        CROSS JOIN global_attributes attr
        WHERE opt.slug = 'fruit_salad'
        AND attr.slug IN ('bagel', 'bagel_choice')
        AND NOT EXISTS (
            SELECT 1 FROM global_attribute_option_skips
            WHERE triggering_option_id = opt.id
            AND skipped_attribute_id = attr.id
        )
    """)


def downgrade() -> None:
    """Remove fruit_salad skip rules."""
    op.execute("""
        DELETE FROM global_attribute_option_skips
        WHERE triggering_option_id IN (
            SELECT id FROM global_attribute_options WHERE slug = 'fruit_salad'
        )
        AND skipped_attribute_id IN (
            SELECT id FROM global_attributes WHERE slug IN ('bagel', 'bagel_choice')
        )
    """)
