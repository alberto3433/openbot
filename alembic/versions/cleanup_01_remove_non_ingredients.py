"""Remove non-ingredient records from ingredients table

Revision ID: cleanup_01
Revises: size_price_02
Create Date: 2026-01-15

This migration removes records from the ingredients table that are not
actual food ingredients. These records were incorrectly stored as
ingredients but should be managed via the attribute_options table instead:

DELETED CATEGORIES (33 records, 7 aliases):
- size (3): Small, Medium, Large -> managed by attribute_options.size
- espresso_shots (4): Single/Double/Triple/Quad Shot -> managed by attribute_options.extra_shots
- style (3): Black, Dark, Light -> managed by attribute_options.style
- temperature (2): Hot, Iced -> managed by attribute_options.temperature
- egg_style (5): Fried, Scrambled, Over Easy, etc. -> managed by attribute_options.egg_style
- egg_quantity (5): 2-6 Eggs -> managed by attribute_options.egg_quantity
- beverage (9): Americano, Latte, Coffee, etc. -> these are menu_items, not ingredients
- side (2): Fruit Salad -> these are menu_items, not ingredients

RECATEGORIZED:
- condiment (4 items) -> sauce: Avocado Horseradish, Pico de Gallo, Salsa, Sour Cream
- vegetable (1 item) -> topping: Broccoli

CURRENT STATE AFTER CLEANUP:
- ingredient_categories: protein, topping, sauce, cheese, spread, milk, sweetener, syrup, bread
- ingredients: 181 records across 9 categories (all valid food ingredients)
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'cleanup_01'
down_revision = 'size_price_02'
branch_labels = None
depends_on = None

# Categories that should NOT be in the ingredients table
NON_INGREDIENT_CATEGORIES = [
    'size',
    'espresso_shots',
    'style',
    'temperature',
    'egg_style',
    'egg_quantity',
    'beverage',
    'side',
]


def upgrade() -> None:
    conn = op.get_bind()

    # Delete ingredient_aliases first (FK constraint)
    result = conn.execute(text("""
        DELETE FROM ingredient_aliases
        WHERE ingredient_id IN (
            SELECT id FROM ingredients WHERE category = ANY(:cats)
        )
    """), {'cats': NON_INGREDIENT_CATEGORIES})
    print(f"Deleted {result.rowcount} ingredient_aliases for non-ingredient categories")

    # Delete non-ingredient records
    result = conn.execute(text("""
        DELETE FROM ingredients WHERE category = ANY(:cats)
    """), {'cats': NON_INGREDIENT_CATEGORIES})
    print(f"Deleted {result.rowcount} non-ingredient records")

    # Recategorize orphaned categories
    # condiment -> sauce
    result = conn.execute(text("""
        UPDATE ingredients SET category = 'sauce' WHERE category = 'condiment'
    """))
    if result.rowcount > 0:
        print(f"Recategorized {result.rowcount} items from condiment to sauce")

    # vegetable -> topping
    result = conn.execute(text("""
        UPDATE ingredients SET category = 'topping' WHERE category = 'vegetable'
    """))
    if result.rowcount > 0:
        print(f"Recategorized {result.rowcount} items from vegetable to topping")

    # Verify no orphaned categories remain
    result = conn.execute(text("""
        SELECT DISTINCT i.category
        FROM ingredients i
        LEFT JOIN ingredient_categories ic ON i.category = ic.slug
        WHERE ic.id IS NULL
    """))
    orphans = [row[0] for row in result.fetchall()]
    if orphans:
        print(f"WARNING: Orphaned categories still exist: {orphans}")
    else:
        print("All ingredients now have valid categories")


def downgrade() -> None:
    """
    Downgrade is intentionally minimal.

    The deleted records were incorrectly stored data that should not exist.
    Re-creating them would reintroduce the data model inconsistency.

    If you need to restore these records, manually insert them or restore
    from a database backup.
    """
    print("Note: Non-ingredient records are not restored on downgrade.")
    print("These records were incorrectly stored and should not exist.")
    print("Size, shots, style, temperature options are managed via attribute_options table.")
