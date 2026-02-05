"""merge skip_rules and display_grp branches

Revision ID: 7508fc64a9f6
Revises: display_grp_03, skip_rules_02
Create Date: 2026-02-05 17:30:49.385503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7508fc64a9f6'
down_revision: Union[str, Sequence[str], None] = ('display_grp_03', 'skip_rules_02')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
