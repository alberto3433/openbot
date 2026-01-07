"""add_company_payment_dietary_catering_fields

Revision ID: 3374fb4828b2
Revises: 3c21925714be
Create Date: 2026-01-07 10:44:42.585439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3374fb4828b2'
down_revision: Union[str, Sequence[str], None] = '3c21925714be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add payment methods, dietary/certification, amenities, and catering fields to company."""
    # Payment Methods
    op.add_column('company', sa.Column('accepts_credit_cards', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('company', sa.Column('accepts_debit_cards', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('company', sa.Column('accepts_cash', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('company', sa.Column('accepts_apple_pay', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('accepts_google_pay', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('accepts_venmo', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('accepts_paypal', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # Dietary & Certification Info
    op.add_column('company', sa.Column('is_kosher', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('kosher_certification', sa.String(), nullable=True))
    op.add_column('company', sa.Column('is_halal', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('has_vegetarian_options', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('company', sa.Column('has_vegan_options', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('company', sa.Column('has_gluten_free_options', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # Amenities
    op.add_column('company', sa.Column('wifi_available', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('wheelchair_accessible', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('company', sa.Column('outdoor_seating', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # Catering
    op.add_column('company', sa.Column('offers_catering', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('company', sa.Column('catering_minimum_order', sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column('company', sa.Column('catering_advance_notice_hours', sa.Integer(), nullable=True))
    op.add_column('company', sa.Column('catering_phone', sa.String(), nullable=True))
    op.add_column('company', sa.Column('catering_email', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove payment methods, dietary/certification, amenities, and catering fields from company."""
    # Catering
    op.drop_column('company', 'catering_email')
    op.drop_column('company', 'catering_phone')
    op.drop_column('company', 'catering_advance_notice_hours')
    op.drop_column('company', 'catering_minimum_order')
    op.drop_column('company', 'offers_catering')

    # Amenities
    op.drop_column('company', 'outdoor_seating')
    op.drop_column('company', 'wheelchair_accessible')
    op.drop_column('company', 'wifi_available')

    # Dietary & Certification Info
    op.drop_column('company', 'has_gluten_free_options')
    op.drop_column('company', 'has_vegan_options')
    op.drop_column('company', 'has_vegetarian_options')
    op.drop_column('company', 'is_halal')
    op.drop_column('company', 'kosher_certification')
    op.drop_column('company', 'is_kosher')

    # Payment Methods
    op.drop_column('company', 'accepts_paypal')
    op.drop_column('company', 'accepts_venmo')
    op.drop_column('company', 'accepts_google_pay')
    op.drop_column('company', 'accepts_apple_pay')
    op.drop_column('company', 'accepts_cash')
    op.drop_column('company', 'accepts_debit_cards')
    op.drop_column('company', 'accepts_credit_cards')
