"""Drop attribute_options tables - consolidate to global_attribute_options

Revision ID: cleanup_02
Revises: cleanup_01
Create Date: 2026-01-15

This migration removes the attribute_options and attribute_option_ingredients
tables. All attribute options are now managed via global_attribute_options,
which is linked to item_types via item_type_global_attributes.

DROPPED TABLES:
- attribute_option_ingredients: Link table for inventory tracking (564 records)
- attribute_options: Per-item-type attribute options (564 records)

These tables were redundant because:
1. global_attribute_options already has the same options with ingredient_id links
2. item_type_global_attributes already controls which attributes each item type uses
3. Per-item-type option availability can be managed via data, not schema

All code should now use GlobalAttributeOption instead of AttributeOption.
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'cleanup_02'
down_revision = 'cleanup_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Get counts before dropping for logging
    ao_count = conn.execute(text("SELECT COUNT(*) FROM attribute_options")).scalar()
    aoi_count = conn.execute(text("SELECT COUNT(*) FROM attribute_option_ingredients")).scalar()

    print(f"Dropping attribute_option_ingredients table ({aoi_count} records)")
    op.drop_table('attribute_option_ingredients')

    print(f"Dropping attribute_options table ({ao_count} records)")
    op.drop_table('attribute_options')

    print("Tables dropped. All attribute options should now use global_attribute_options.")


def downgrade() -> None:
    """
    Downgrade recreates the tables but NOT the data.

    The data was redundant with global_attribute_options so it is not restored.
    If you need the original data, restore from a database backup.
    """
    # Recreate attribute_options table
    op.execute(text("""
        CREATE TABLE attribute_options (
            id SERIAL PRIMARY KEY,
            item_type_attribute_id INTEGER REFERENCES item_type_attributes(id) ON DELETE CASCADE,
            slug VARCHAR NOT NULL,
            display_name VARCHAR NOT NULL,
            price_modifier FLOAT NOT NULL DEFAULT 0.0,
            iced_price_modifier FLOAT NOT NULL DEFAULT 0.0,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            is_available BOOLEAN NOT NULL DEFAULT TRUE,
            display_order INTEGER NOT NULL DEFAULT 0
        )
    """))

    # Recreate attribute_option_ingredients table
    op.execute(text("""
        CREATE TABLE attribute_option_ingredients (
            id SERIAL PRIMARY KEY,
            attribute_option_id INTEGER NOT NULL REFERENCES attribute_options(id) ON DELETE CASCADE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
            quantity FLOAT NOT NULL DEFAULT 1.0,
            CONSTRAINT uix_attr_option_ingredient UNIQUE (attribute_option_id, ingredient_id)
        )
    """))

    # Create indexes
    op.execute(text("CREATE INDEX ix_attribute_options_item_type_attribute_id ON attribute_options(item_type_attribute_id)"))
    op.execute(text("CREATE INDEX ix_attribute_option_ingredients_attribute_option_id ON attribute_option_ingredients(attribute_option_id)"))
    op.execute(text("CREATE INDEX ix_attribute_option_ingredients_ingredient_id ON attribute_option_ingredients(ingredient_id)"))

    print("Note: Tables recreated but data is NOT restored.")
    print("The dropped data was redundant with global_attribute_options.")
