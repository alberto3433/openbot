"""fish_sandwich_data_driven_and_salad_reclassification

Revision ID: p0q1r2s3t4u6
Revises: o9p0q1r2s3t5
Create Date: 2026-01-09 11:00:00.000000

This migration:
1. Removes 'fish' attribute from fish_sandwich (not needed - fish type comes from menu item name)
2. Removes 'extras' attribute from fish_sandwich (consolidated into toppings)
3. Removes Avocado Horseradish and Tobiko ingredients from fish_sandwich
4. Reclassifies salad sandwiches to appropriate item types
5. Fixes Nova Scotia Salmon on Bagel to be fish_sandwich
6. Deletes the salad_sandwich item type
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p0q1r2s3t4u6'
down_revision: Union[str, Sequence[str], None] = 'k6l7m8n9o0p1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Item type IDs
FISH_SANDWICH_ID = 7
SALAD_SANDWICH_ID = 14
EGG_SANDWICH_ID = 6
DELI_SANDWICH_ID = 17

# Attribute IDs to delete
FISH_ATTR_ID = 52
EXTRAS_ATTR_ID = 54

# Ingredient IDs to remove
AVOCADO_HORSERADISH_ID = 163
TOBIKO_ID = 164

# Menu item IDs for reclassification
BAKED_SALMON_SALAD_ID = 416
TUNA_SALAD_ID = 414
WHITEFISH_SALAD_ID = 415
EGG_SALAD_ID = 417
CHICKEN_SALAD_ID = 418
CRANBERRY_PECAN_CHICKEN_ID = 419
LEMON_CHICKEN_SALAD_ID = 420
NOVA_SCOTIA_ON_BAGEL_ID = 364


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Delete ingredient links for 'fish' attribute
    conn.execute(sa.text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :fish_type_id
        AND ingredient_group = 'fish'
    """), {'fish_type_id': FISH_SANDWICH_ID})

    # 2. Delete 'fish' attribute from fish_sandwich
    conn.execute(sa.text("""
        DELETE FROM item_type_attributes
        WHERE id = :attr_id
    """), {'attr_id': FISH_ATTR_ID})

    # 3. Delete ingredient links for 'extras' attribute
    conn.execute(sa.text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :fish_type_id
        AND ingredient_group = 'extras'
    """), {'fish_type_id': FISH_SANDWICH_ID})

    # 4. Delete 'extras' attribute from fish_sandwich
    conn.execute(sa.text("""
        DELETE FROM item_type_attributes
        WHERE id = :attr_id
    """), {'attr_id': EXTRAS_ATTR_ID})

    # 5. Remove Avocado Horseradish and Tobiko from fish_sandwich toppings
    conn.execute(sa.text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :fish_type_id
        AND ingredient_id IN (:ingr1, :ingr2)
    """), {
        'fish_type_id': FISH_SANDWICH_ID,
        'ingr1': AVOCADO_HORSERADISH_ID,
        'ingr2': TOBIKO_ID
    })

    # 6. Reclassify fish-based salad sandwiches to fish_sandwich
    conn.execute(sa.text("""
        UPDATE menu_items
        SET item_type_id = :fish_type_id,
            category = 'fish_sandwich'
        WHERE id IN (:id1, :id2, :id3)
    """), {
        'fish_type_id': FISH_SANDWICH_ID,
        'id1': BAKED_SALMON_SALAD_ID,
        'id2': TUNA_SALAD_ID,
        'id3': WHITEFISH_SALAD_ID
    })

    # 7. Reclassify Egg Salad Sandwich to egg_sandwich
    conn.execute(sa.text("""
        UPDATE menu_items
        SET item_type_id = :egg_type_id,
            category = 'egg_sandwich'
        WHERE id = :id
    """), {
        'egg_type_id': EGG_SANDWICH_ID,
        'id': EGG_SALAD_ID
    })

    # 8. Reclassify chicken salad sandwiches to deli_sandwich
    conn.execute(sa.text("""
        UPDATE menu_items
        SET item_type_id = :deli_type_id,
            category = 'deli_sandwich'
        WHERE id IN (:id1, :id2, :id3)
    """), {
        'deli_type_id': DELI_SANDWICH_ID,
        'id1': CHICKEN_SALAD_ID,
        'id2': CRANBERRY_PECAN_CHICKEN_ID,
        'id3': LEMON_CHICKEN_SALAD_ID
    })

    # 9. Fix Nova Scotia Salmon on Bagel to be fish_sandwich
    conn.execute(sa.text("""
        UPDATE menu_items
        SET item_type_id = :fish_type_id,
            category = 'fish_sandwich'
        WHERE id = :id
    """), {
        'fish_type_id': FISH_SANDWICH_ID,
        'id': NOVA_SCOTIA_ON_BAGEL_ID
    })

    # 10. Delete salad_sandwich item type attributes first (foreign key constraint)
    conn.execute(sa.text("""
        DELETE FROM item_type_attributes
        WHERE item_type_id = :salad_type_id
    """), {'salad_type_id': SALAD_SANDWICH_ID})

    # 11. Delete salad_sandwich ingredient links
    conn.execute(sa.text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :salad_type_id
    """), {'salad_type_id': SALAD_SANDWICH_ID})

    # 12. Delete salad_sandwich item type
    conn.execute(sa.text("""
        DELETE FROM item_types
        WHERE id = :salad_type_id
    """), {'salad_type_id': SALAD_SANDWICH_ID})


def downgrade() -> None:
    """
    Note: This downgrade is partial - it restores menu item classifications
    but does not fully recreate deleted attributes/ingredients.
    """
    conn = op.get_bind()

    # Recreate salad_sandwich item type
    conn.execute(sa.text("""
        INSERT INTO item_types (id, slug, display_name, skip_config)
        VALUES (:id, 'salad_sandwich', 'Salad Sandwich', FALSE)
    """), {'id': SALAD_SANDWICH_ID})

    # Restore menu item classifications
    conn.execute(sa.text("""
        UPDATE menu_items
        SET item_type_id = :salad_type_id,
            category = 'salad_sandwich'
        WHERE id IN (:id1, :id2, :id3, :id4, :id5, :id6, :id7)
    """), {
        'salad_type_id': SALAD_SANDWICH_ID,
        'id1': BAKED_SALMON_SALAD_ID,
        'id2': TUNA_SALAD_ID,
        'id3': WHITEFISH_SALAD_ID,
        'id4': EGG_SALAD_ID,
        'id5': CHICKEN_SALAD_ID,
        'id6': CRANBERRY_PECAN_CHICKEN_ID,
        'id7': LEMON_CHICKEN_SALAD_ID
    })

    # Restore Nova Scotia Salmon on Bagel to egg_sandwich
    conn.execute(sa.text("""
        UPDATE menu_items
        SET item_type_id = :egg_type_id,
            category = 'Egg Sandwich'
        WHERE id = :id
    """), {
        'egg_type_id': EGG_SANDWICH_ID,
        'id': NOVA_SCOTIA_ON_BAGEL_ID
    })
