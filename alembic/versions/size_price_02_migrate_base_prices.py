"""Migrate base_price to size_prices

Revision ID: size_price_02
Revises: size_price_01
Create Date: 2026-01-14

This migration converts existing menu item base_prices to the new
size-based pricing system. Each menu item gets a size_price entry
using the "each" size from the "quantity" category.

This ensures all existing items continue to work with the new pricing
system while maintaining backward compatibility.

After this migration:
- All menu items will have at least one size_price entry
- Items with single "each" size won't need disambiguation
- The pricing engine will use size_prices instead of base_price
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'size_price_02'
down_revision = 'size_price_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Get the company_id
    result = conn.execute(text("SELECT id FROM company LIMIT 1"))
    row = result.fetchone()
    if not row:
        print("No company found, skipping data migration")
        return
    company_id = row[0]

    # Get the "quantity" category and "each" size
    result = conn.execute(text("""
        SELECT c.id, s.id
        FROM menu_item_size_categories c
        JOIN menu_item_sizes s ON s.category_id = c.id
        WHERE c.slug = 'quantity' AND c.company_id = :company_id AND s.name = 'each'
    """), {'company_id': company_id})
    row = result.fetchone()

    if not row:
        print("No 'quantity' category or 'each' size found, skipping data migration")
        return

    quantity_category_id = row[0]
    each_size_id = row[1]

    # Get all menu items that don't already have size_prices
    result = conn.execute(text("""
        SELECT mi.id, mi.base_price
        FROM menu_items mi
        LEFT JOIN menu_item_size_prices sp ON sp.menu_item_id = mi.id
        WHERE mi.base_price IS NOT NULL
          AND mi.base_price > 0
          AND sp.id IS NULL
    """))

    items_to_migrate = result.fetchall()

    if not items_to_migrate:
        print("No menu items to migrate")
        return

    print(f"Migrating {len(items_to_migrate)} menu items to size-based pricing")

    # Insert size_price entries for each menu item
    for item_id, base_price in items_to_migrate:
        conn.execute(text("""
            INSERT INTO menu_item_size_prices (menu_item_id, size_id, price)
            VALUES (:menu_item_id, :size_id, :price)
        """), {
            'menu_item_id': item_id,
            'size_id': each_size_id,
            'price': base_price
        })

    # Update menu items to set size_category_id to "quantity"
    conn.execute(text("""
        UPDATE menu_items
        SET size_category_id = :category_id
        WHERE id IN (
            SELECT menu_item_id FROM menu_item_size_prices
        )
        AND size_category_id IS NULL
    """), {'category_id': quantity_category_id})

    print(f"Successfully migrated {len(items_to_migrate)} menu items")


def downgrade() -> None:
    conn = op.get_bind()

    # Get the "each" size ID
    result = conn.execute(text("""
        SELECT s.id
        FROM menu_item_sizes s
        JOIN menu_item_size_categories c ON s.category_id = c.id
        WHERE c.slug = 'quantity' AND s.name = 'each'
    """))
    row = result.fetchone()

    if row:
        each_size_id = row[0]
        # Delete all size_prices that use the "each" size
        # (these were created by this migration)
        conn.execute(text("""
            DELETE FROM menu_item_size_prices
            WHERE size_id = :size_id
        """), {'size_id': each_size_id})

    # Clear size_category_id on all menu items
    conn.execute(text("""
        UPDATE menu_items
        SET size_category_id = NULL
    """))
