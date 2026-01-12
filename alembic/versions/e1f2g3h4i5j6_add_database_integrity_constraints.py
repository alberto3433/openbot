"""Add database integrity constraints

This migration adds comprehensive data integrity constraints:
1. Foreign keys for store_id columns (5 tables)
2. ondelete cascades for existing FKs (8 tables)
3. Check constraints for enum-like columns (9 columns)
4. Non-negative constraints for prices/quantities

Revision ID: e1f2g3h4i5j6
Revises: d6e7f8g9h0i1
Create Date: 2025-01-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2g3h4i5j6'
down_revision: Union[str, None] = 'd6e7f8g9h0i1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. STORE_ID FOREIGN KEYS
    # =========================================================================
    # These tables reference store_id but lack FK constraints to stores table

    # Orders.store_id -> stores.store_id (SET NULL on delete)
    op.create_foreign_key(
        'fk_orders_store_id',
        'orders', 'stores',
        ['store_id'], ['store_id'],
        ondelete='SET NULL'
    )

    # chat_sessions.store_id -> stores.store_id (SET NULL on delete)
    op.create_foreign_key(
        'fk_chat_sessions_store_id',
        'chat_sessions', 'stores',
        ['store_id'], ['store_id'],
        ondelete='SET NULL'
    )

    # session_analytics.store_id -> stores.store_id (SET NULL on delete)
    op.create_foreign_key(
        'fk_session_analytics_store_id',
        'session_analytics', 'stores',
        ['store_id'], ['store_id'],
        ondelete='SET NULL'
    )

    # menu_item_store_availability.store_id -> stores.store_id (CASCADE on delete)
    op.create_foreign_key(
        'fk_menu_item_store_availability_store_id',
        'menu_item_store_availability', 'stores',
        ['store_id'], ['store_id'],
        ondelete='CASCADE'
    )

    # ingredient_store_availability.store_id -> stores.store_id (CASCADE on delete)
    op.create_foreign_key(
        'fk_ingredient_store_availability_store_id',
        'ingredient_store_availability', 'stores',
        ['store_id'], ['store_id'],
        ondelete='CASCADE'
    )

    # =========================================================================
    # 2. ONDELETE CASCADES FOR EXISTING FKs
    # =========================================================================
    # Need to drop and recreate FKs to add ondelete behavior

    # --- OrderItem.order_id -> CASCADE ---
    op.drop_constraint('order_items_order_id_fkey', 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'order_items_order_id_fkey',
        'order_items', 'orders',
        ['order_id'], ['id'],
        ondelete='CASCADE'
    )

    # --- OrderItem.menu_item_id -> SET NULL ---
    op.drop_constraint('order_items_menu_item_id_fkey', 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'order_items_menu_item_id_fkey',
        'order_items', 'menu_items',
        ['menu_item_id'], ['id'],
        ondelete='SET NULL'
    )

    # --- OrderItem.item_type_id -> SET NULL ---
    op.drop_constraint('fk_order_items_item_type', 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'fk_order_items_item_type',
        'order_items', 'item_types',
        ['item_type_id'], ['id'],
        ondelete='SET NULL'
    )

    # --- MenuItem.item_type_id -> SET NULL ---
    op.drop_constraint('fk_menu_items_item_type', 'menu_items', type_='foreignkey')
    op.create_foreign_key(
        'fk_menu_items_item_type',
        'menu_items', 'item_types',
        ['item_type_id'], ['id'],
        ondelete='SET NULL'
    )

    # --- MenuItem.recipe_id -> SET NULL ---
    op.drop_constraint('menu_items_recipe_id_fkey', 'menu_items', type_='foreignkey')
    op.create_foreign_key(
        'menu_items_recipe_id_fkey',
        'menu_items', 'recipes',
        ['recipe_id'], ['id'],
        ondelete='SET NULL'
    )

    # --- RecipeIngredient.recipe_id -> CASCADE ---
    op.drop_constraint('recipe_ingredients_recipe_id_fkey', 'recipe_ingredients', type_='foreignkey')
    op.create_foreign_key(
        'recipe_ingredients_recipe_id_fkey',
        'recipe_ingredients', 'recipes',
        ['recipe_id'], ['id'],
        ondelete='CASCADE'
    )

    # --- RecipeIngredient.ingredient_id -> CASCADE ---
    op.drop_constraint('recipe_ingredients_ingredient_id_fkey', 'recipe_ingredients', type_='foreignkey')
    op.create_foreign_key(
        'recipe_ingredients_ingredient_id_fkey',
        'recipe_ingredients', 'ingredients',
        ['ingredient_id'], ['id'],
        ondelete='CASCADE'
    )

    # --- RecipeChoiceGroup.recipe_id -> CASCADE ---
    op.drop_constraint('recipe_choice_groups_recipe_id_fkey', 'recipe_choice_groups', type_='foreignkey')
    op.create_foreign_key(
        'recipe_choice_groups_recipe_id_fkey',
        'recipe_choice_groups', 'recipes',
        ['recipe_id'], ['id'],
        ondelete='CASCADE'
    )

    # --- RecipeChoiceItem.choice_group_id -> CASCADE ---
    op.drop_constraint('recipe_choice_items_choice_group_id_fkey', 'recipe_choice_items', type_='foreignkey')
    op.create_foreign_key(
        'recipe_choice_items_choice_group_id_fkey',
        'recipe_choice_items', 'recipe_choice_groups',
        ['choice_group_id'], ['id'],
        ondelete='CASCADE'
    )

    # --- RecipeChoiceItem.ingredient_id -> CASCADE ---
    op.drop_constraint('recipe_choice_items_ingredient_id_fkey', 'recipe_choice_items', type_='foreignkey')
    op.create_foreign_key(
        'recipe_choice_items_ingredient_id_fkey',
        'recipe_choice_items', 'ingredients',
        ['ingredient_id'], ['id'],
        ondelete='CASCADE'
    )

    # =========================================================================
    # 3. CHECK CONSTRAINTS FOR ENUM-LIKE COLUMNS
    # =========================================================================

    # Order.status
    op.create_check_constraint(
        'ck_orders_status',
        'orders',
        "status IN ('pending', 'pending_payment', 'confirmed', 'preparing', 'ready', 'completed', 'cancelled')"
    )

    # Order.order_type
    op.create_check_constraint(
        'ck_orders_order_type',
        'orders',
        "order_type IN ('pickup', 'delivery')"
    )

    # Order.payment_status
    op.create_check_constraint(
        'ck_orders_payment_status',
        'orders',
        "payment_status IN ('unpaid', 'pending_payment', 'paid')"
    )

    # Order.payment_method (nullable, so allow NULL)
    op.create_check_constraint(
        'ck_orders_payment_method',
        'orders',
        "payment_method IS NULL OR payment_method IN ('cash', 'card_in_store', 'card_phone', 'card_link')"
    )

    # Store.status
    op.create_check_constraint(
        'ck_stores_status',
        'stores',
        "status IN ('open', 'closed')"
    )

    # GlobalAttribute.input_type
    op.create_check_constraint(
        'ck_global_attributes_input_type',
        'global_attributes',
        "input_type IN ('single_select', 'multi_select', 'boolean')"
    )

    # ItemTypeAttribute.input_type
    op.create_check_constraint(
        'ck_item_type_attributes_input_type',
        'item_type_attributes',
        "input_type IN ('single_select', 'multi_select', 'boolean', 'text')"
    )

    # SessionAnalytics.status
    op.create_check_constraint(
        'ck_session_analytics_status',
        'session_analytics',
        "status IN ('abandoned', 'completed')"
    )

    # ResponsePattern.pattern_type
    op.create_check_constraint(
        'ck_response_pattern_pattern_type',
        'response_pattern',
        "pattern_type IN ('affirmative', 'negative', 'cancel', 'done')"
    )

    # =========================================================================
    # 4. NON-NEGATIVE CONSTRAINTS
    # =========================================================================

    # Order price fields
    op.create_check_constraint(
        'ck_orders_subtotal_non_negative',
        'orders',
        'subtotal IS NULL OR subtotal >= 0'
    )
    op.create_check_constraint(
        'ck_orders_city_tax_non_negative',
        'orders',
        'city_tax IS NULL OR city_tax >= 0'
    )
    op.create_check_constraint(
        'ck_orders_state_tax_non_negative',
        'orders',
        'state_tax IS NULL OR state_tax >= 0'
    )
    op.create_check_constraint(
        'ck_orders_delivery_fee_non_negative',
        'orders',
        'delivery_fee IS NULL OR delivery_fee >= 0'
    )
    op.create_check_constraint(
        'ck_orders_total_price_non_negative',
        'orders',
        'total_price >= 0'
    )

    # Store tax/fee fields
    op.create_check_constraint(
        'ck_stores_city_tax_rate_non_negative',
        'stores',
        'city_tax_rate >= 0'
    )
    op.create_check_constraint(
        'ck_stores_state_tax_rate_non_negative',
        'stores',
        'state_tax_rate >= 0'
    )
    op.create_check_constraint(
        'ck_stores_delivery_fee_non_negative',
        'stores',
        'delivery_fee >= 0'
    )

    # MenuItem.base_price
    op.create_check_constraint(
        'ck_menu_items_base_price_non_negative',
        'menu_items',
        'base_price >= 0'
    )

    # Ingredient.base_price
    op.create_check_constraint(
        'ck_ingredients_base_price_non_negative',
        'ingredients',
        'base_price >= 0'
    )

    # OrderItem fields
    op.create_check_constraint(
        'ck_order_items_quantity_positive',
        'order_items',
        'quantity > 0'
    )
    op.create_check_constraint(
        'ck_order_items_unit_price_non_negative',
        'order_items',
        'unit_price >= 0'
    )
    op.create_check_constraint(
        'ck_order_items_line_total_non_negative',
        'order_items',
        'line_total >= 0'
    )


def downgrade() -> None:
    # =========================================================================
    # 4. DROP NON-NEGATIVE CONSTRAINTS
    # =========================================================================
    op.drop_constraint('ck_order_items_line_total_non_negative', 'order_items', type_='check')
    op.drop_constraint('ck_order_items_unit_price_non_negative', 'order_items', type_='check')
    op.drop_constraint('ck_order_items_quantity_positive', 'order_items', type_='check')
    op.drop_constraint('ck_ingredients_base_price_non_negative', 'ingredients', type_='check')
    op.drop_constraint('ck_menu_items_base_price_non_negative', 'menu_items', type_='check')
    op.drop_constraint('ck_stores_delivery_fee_non_negative', 'stores', type_='check')
    op.drop_constraint('ck_stores_state_tax_rate_non_negative', 'stores', type_='check')
    op.drop_constraint('ck_stores_city_tax_rate_non_negative', 'stores', type_='check')
    op.drop_constraint('ck_orders_total_price_non_negative', 'orders', type_='check')
    op.drop_constraint('ck_orders_delivery_fee_non_negative', 'orders', type_='check')
    op.drop_constraint('ck_orders_state_tax_non_negative', 'orders', type_='check')
    op.drop_constraint('ck_orders_city_tax_non_negative', 'orders', type_='check')
    op.drop_constraint('ck_orders_subtotal_non_negative', 'orders', type_='check')

    # =========================================================================
    # 3. DROP CHECK CONSTRAINTS FOR ENUM-LIKE COLUMNS
    # =========================================================================
    op.drop_constraint('ck_response_pattern_pattern_type', 'response_pattern', type_='check')
    op.drop_constraint('ck_session_analytics_status', 'session_analytics', type_='check')
    op.drop_constraint('ck_item_type_attributes_input_type', 'item_type_attributes', type_='check')
    op.drop_constraint('ck_global_attributes_input_type', 'global_attributes', type_='check')
    op.drop_constraint('ck_stores_status', 'stores', type_='check')
    op.drop_constraint('ck_orders_payment_method', 'orders', type_='check')
    op.drop_constraint('ck_orders_payment_status', 'orders', type_='check')
    op.drop_constraint('ck_orders_order_type', 'orders', type_='check')
    op.drop_constraint('ck_orders_status', 'orders', type_='check')

    # =========================================================================
    # 2. RESTORE ORIGINAL FKs (without ondelete)
    # =========================================================================

    # --- RecipeChoiceItem.ingredient_id ---
    op.drop_constraint('recipe_choice_items_ingredient_id_fkey', 'recipe_choice_items', type_='foreignkey')
    op.create_foreign_key(
        'recipe_choice_items_ingredient_id_fkey',
        'recipe_choice_items', 'ingredients',
        ['ingredient_id'], ['id']
    )

    # --- RecipeChoiceItem.choice_group_id ---
    op.drop_constraint('recipe_choice_items_choice_group_id_fkey', 'recipe_choice_items', type_='foreignkey')
    op.create_foreign_key(
        'recipe_choice_items_choice_group_id_fkey',
        'recipe_choice_items', 'recipe_choice_groups',
        ['choice_group_id'], ['id']
    )

    # --- RecipeChoiceGroup.recipe_id ---
    op.drop_constraint('recipe_choice_groups_recipe_id_fkey', 'recipe_choice_groups', type_='foreignkey')
    op.create_foreign_key(
        'recipe_choice_groups_recipe_id_fkey',
        'recipe_choice_groups', 'recipes',
        ['recipe_id'], ['id']
    )

    # --- RecipeIngredient.ingredient_id ---
    op.drop_constraint('recipe_ingredients_ingredient_id_fkey', 'recipe_ingredients', type_='foreignkey')
    op.create_foreign_key(
        'recipe_ingredients_ingredient_id_fkey',
        'recipe_ingredients', 'ingredients',
        ['ingredient_id'], ['id']
    )

    # --- RecipeIngredient.recipe_id ---
    op.drop_constraint('recipe_ingredients_recipe_id_fkey', 'recipe_ingredients', type_='foreignkey')
    op.create_foreign_key(
        'recipe_ingredients_recipe_id_fkey',
        'recipe_ingredients', 'recipes',
        ['recipe_id'], ['id']
    )

    # --- MenuItem.recipe_id ---
    op.drop_constraint('menu_items_recipe_id_fkey', 'menu_items', type_='foreignkey')
    op.create_foreign_key(
        'menu_items_recipe_id_fkey',
        'menu_items', 'recipes',
        ['recipe_id'], ['id']
    )

    # --- MenuItem.item_type_id ---
    op.drop_constraint('fk_menu_items_item_type', 'menu_items', type_='foreignkey')
    op.create_foreign_key(
        'fk_menu_items_item_type',
        'menu_items', 'item_types',
        ['item_type_id'], ['id']
    )

    # --- OrderItem.item_type_id ---
    op.drop_constraint('fk_order_items_item_type', 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'fk_order_items_item_type',
        'order_items', 'item_types',
        ['item_type_id'], ['id']
    )

    # --- OrderItem.menu_item_id ---
    op.drop_constraint('order_items_menu_item_id_fkey', 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'order_items_menu_item_id_fkey',
        'order_items', 'menu_items',
        ['menu_item_id'], ['id']
    )

    # --- OrderItem.order_id ---
    op.drop_constraint('order_items_order_id_fkey', 'order_items', type_='foreignkey')
    op.create_foreign_key(
        'order_items_order_id_fkey',
        'order_items', 'orders',
        ['order_id'], ['id']
    )

    # =========================================================================
    # 1. DROP STORE_ID FOREIGN KEYS
    # =========================================================================
    op.drop_constraint('fk_ingredient_store_availability_store_id', 'ingredient_store_availability', type_='foreignkey')
    op.drop_constraint('fk_menu_item_store_availability_store_id', 'menu_item_store_availability', type_='foreignkey')
    op.drop_constraint('fk_session_analytics_store_id', 'session_analytics', type_='foreignkey')
    op.drop_constraint('fk_chat_sessions_store_id', 'chat_sessions', type_='foreignkey')
    op.drop_constraint('fk_orders_store_id', 'orders', type_='foreignkey')
