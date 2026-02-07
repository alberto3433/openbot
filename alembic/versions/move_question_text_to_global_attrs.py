"""Move question_text from ItemTypeGlobalAttribute to GlobalAttribute

Moves the question_text column from the junction table (item_type_global_attributes)
to the global attributes table (global_attributes). This means each attribute has
one question shared across all item types.

For attributes with different questions per item type, the most common question
is preserved.

Revision ID: move_question_text_01
Revises: display_name_chars_01
Create Date: 2026-02-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'move_question_text_01'
down_revision: Union[str, None] = 'display_name_chars_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add question_text column to global_attributes
    op.add_column(
        'global_attributes',
        sa.Column('question_text', sa.Text(), nullable=True)
    )

    # 2. Migrate data: copy most common question_text per attribute
    # For each global attribute, pick the question_text that appears most often
    # across the item_type_global_attributes links
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE global_attributes ga
        SET question_text = subq.question_text
        FROM (
            SELECT DISTINCT ON (global_attribute_id)
                global_attribute_id,
                question_text
            FROM (
                SELECT
                    global_attribute_id,
                    question_text,
                    COUNT(*) as cnt
                FROM item_type_global_attributes
                WHERE question_text IS NOT NULL
                GROUP BY global_attribute_id, question_text
                ORDER BY global_attribute_id, cnt DESC
            ) ranked
        ) subq
        WHERE ga.id = subq.global_attribute_id
    """))

    # 3. Drop question_text column from item_type_global_attributes
    op.drop_column('item_type_global_attributes', 'question_text')


def downgrade() -> None:
    # 1. Add question_text back to item_type_global_attributes
    op.add_column(
        'item_type_global_attributes',
        sa.Column('question_text', sa.Text(), nullable=True)
    )

    # 2. Copy question_text from global_attributes to all links
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE item_type_global_attributes itga
        SET question_text = ga.question_text
        FROM global_attributes ga
        WHERE itga.global_attribute_id = ga.id
          AND ga.question_text IS NOT NULL
    """))

    # 3. Drop question_text from global_attributes
    op.drop_column('global_attributes', 'question_text')
