"""Drop legacy and unused tables and columns, normalize string references to FKs.

This migration performs comprehensive schema cleanup:

1. Drop empty legacy attribute tables (replaced by global_attributes system)
2. Drop empty recipe tables (never implemented)
3. Convert string slug references to proper FK relationships
4. Remove unused columns from item_type_global_attributes
5. Remove dietary flag columns from menu_items (will be computed from ingredients)

Revision ID: schema_cleanup_01
Revises: a4ee64f77a8d
Create Date: 2025-02-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'schema_cleanup_01'
down_revision = 'a4ee64f77a8d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =========================================================================
    # 1. Drop empty legacy attribute tables (order matters for FK constraints)
    # =========================================================================

    # First drop tables that reference others
    op.drop_table('attribute_option_ingredients')
    op.drop_table('menu_item_attribute_selections')
    op.drop_table('menu_item_attribute_values')
    op.drop_table('attribute_options')

    # Then drop parent tables
    op.drop_table('attribute_definitions')
    op.drop_table('item_type_attributes')

    # =========================================================================
    # 2. Drop empty recipe tables
    # =========================================================================

    op.drop_table('recipe_choice_items')
    op.drop_table('recipe_choice_groups')
    op.drop_table('recipe_ingredients')
    op.drop_table('recipes')

    # =========================================================================
    # 3. Convert global_attributes.modifies_ingredient_slug to FK
    # =========================================================================

    # Add new FK column
    op.add_column(
        'global_attributes',
        sa.Column('modifies_ingredient_id', sa.Integer(), nullable=True)
    )

    # Migrate data: convert slug to id
    op.execute("""
        UPDATE global_attributes ga
        SET modifies_ingredient_id = i.id
        FROM ingredients i
        WHERE ga.modifies_ingredient_slug = i.slug
    """)

    # Drop old slug column
    op.drop_column('global_attributes', 'modifies_ingredient_slug')

    # Add FK constraint
    op.create_foreign_key(
        'fk_global_attributes_modifies_ingredient',
        'global_attributes',
        'ingredients',
        ['modifies_ingredient_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # =========================================================================
    # 4. Convert item_types.variant_pricing_attribute to FK
    # =========================================================================

    # Add new FK column
    op.add_column(
        'item_types',
        sa.Column('variant_pricing_attribute_id', sa.Integer(), nullable=True)
    )

    # Migrate data: convert slug to id
    op.execute("""
        UPDATE item_types it
        SET variant_pricing_attribute_id = ga.id
        FROM global_attributes ga
        WHERE it.variant_pricing_attribute = ga.slug
    """)

    # Drop old slug column
    op.drop_column('item_types', 'variant_pricing_attribute')

    # Add FK constraint
    op.create_foreign_key(
        'fk_item_types_variant_pricing_attribute',
        'item_types',
        'global_attributes',
        ['variant_pricing_attribute_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # =========================================================================
    # 5. Convert attribute_inquiry_keywords to use FKs
    # =========================================================================

    # Add new FK columns
    op.add_column(
        'attribute_inquiry_keywords',
        sa.Column('item_type_id', sa.Integer(), nullable=True)
    )
    op.add_column(
        'attribute_inquiry_keywords',
        sa.Column('global_attribute_id', sa.Integer(), nullable=False, server_default='0')
    )

    # Migrate data
    op.execute("""
        UPDATE attribute_inquiry_keywords aik
        SET item_type_id = it.id
        FROM item_types it
        WHERE aik.item_type_slug = it.slug
    """)

    op.execute("""
        UPDATE attribute_inquiry_keywords aik
        SET global_attribute_id = ga.id
        FROM global_attributes ga
        WHERE aik.attribute_slug = ga.slug
    """)

    # Delete rows that couldn't be migrated (attribute_slug doesn't exist in global_attributes)
    op.execute("""
        DELETE FROM attribute_inquiry_keywords
        WHERE global_attribute_id = 0
    """)

    # Remove server default
    op.alter_column('attribute_inquiry_keywords', 'global_attribute_id', server_default=None)

    # Drop old slug columns
    op.drop_constraint('uq_attr_inquiry_keyword_item_type', 'attribute_inquiry_keywords', type_='unique')
    op.drop_index('idx_attr_inquiry_keyword_lookup', table_name='attribute_inquiry_keywords')
    op.drop_column('attribute_inquiry_keywords', 'item_type_slug')
    op.drop_column('attribute_inquiry_keywords', 'attribute_slug')

    # Add FK constraints
    op.create_foreign_key(
        'fk_attr_inquiry_keywords_item_type',
        'attribute_inquiry_keywords',
        'item_types',
        ['item_type_id'],
        ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'fk_attr_inquiry_keywords_global_attribute',
        'attribute_inquiry_keywords',
        'global_attributes',
        ['global_attribute_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # Recreate unique constraint and index with new columns
    op.create_unique_constraint(
        'uq_attr_inquiry_keyword_item_type',
        'attribute_inquiry_keywords',
        ['keyword', 'item_type_id']
    )
    op.create_index(
        'idx_attr_inquiry_keyword_lookup',
        'attribute_inquiry_keywords',
        ['keyword', 'item_type_id']
    )

    # =========================================================================
    # 6. Remove unused columns from item_type_global_attributes
    # =========================================================================

    op.drop_column('item_type_global_attributes', 'question_text_followup')
    op.drop_column('item_type_global_attributes', 'show_options_in_question')

    # =========================================================================
    # 7. Remove dietary flag columns from menu_items
    # =========================================================================

    op.drop_column('menu_items', 'is_vegan')
    op.drop_column('menu_items', 'is_vegetarian')
    op.drop_column('menu_items', 'is_gluten_free')
    op.drop_column('menu_items', 'is_dairy_free')
    op.drop_column('menu_items', 'is_kosher')
    op.drop_column('menu_items', 'contains_eggs')
    op.drop_column('menu_items', 'contains_fish')
    op.drop_column('menu_items', 'contains_sesame')
    op.drop_column('menu_items', 'contains_nuts')


def downgrade() -> None:
    # =========================================================================
    # 7. Restore dietary flag columns to menu_items
    # =========================================================================

    op.add_column('menu_items', sa.Column('contains_nuts', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('contains_sesame', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('contains_fish', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('contains_eggs', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_kosher', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_dairy_free', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_gluten_free', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_vegetarian', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_vegan', sa.Boolean(), nullable=True))

    # =========================================================================
    # 6. Restore unused columns to item_type_global_attributes
    # =========================================================================

    op.add_column('item_type_global_attributes', sa.Column('show_options_in_question', sa.Boolean(), nullable=True))
    op.add_column('item_type_global_attributes', sa.Column('question_text_followup', sa.Text(), nullable=True))

    # =========================================================================
    # 5. Restore attribute_inquiry_keywords slug columns
    # =========================================================================

    op.drop_constraint('fk_attr_inquiry_keywords_global_attribute', 'attribute_inquiry_keywords', type_='foreignkey')
    op.drop_constraint('fk_attr_inquiry_keywords_item_type', 'attribute_inquiry_keywords', type_='foreignkey')
    op.drop_constraint('uq_attr_inquiry_keyword_item_type', 'attribute_inquiry_keywords', type_='unique')
    op.drop_index('idx_attr_inquiry_keyword_lookup', table_name='attribute_inquiry_keywords')

    op.add_column('attribute_inquiry_keywords', sa.Column('attribute_slug', sa.String(50), nullable=False, server_default=''))
    op.add_column('attribute_inquiry_keywords', sa.Column('item_type_slug', sa.String(50), nullable=True))

    # Migrate data back
    op.execute("""
        UPDATE attribute_inquiry_keywords aik
        SET item_type_slug = it.slug
        FROM item_types it
        WHERE aik.item_type_id = it.id
    """)

    op.execute("""
        UPDATE attribute_inquiry_keywords aik
        SET attribute_slug = ga.slug
        FROM global_attributes ga
        WHERE aik.global_attribute_id = ga.id
    """)

    op.alter_column('attribute_inquiry_keywords', 'attribute_slug', server_default=None)

    op.drop_column('attribute_inquiry_keywords', 'global_attribute_id')
    op.drop_column('attribute_inquiry_keywords', 'item_type_id')

    op.create_unique_constraint('uq_attr_inquiry_keyword_item_type', 'attribute_inquiry_keywords', ['keyword', 'item_type_slug'])
    op.create_index('idx_attr_inquiry_keyword_lookup', 'attribute_inquiry_keywords', ['keyword', 'item_type_slug'])

    # =========================================================================
    # 4. Restore item_types.variant_pricing_attribute
    # =========================================================================

    op.drop_constraint('fk_item_types_variant_pricing_attribute', 'item_types', type_='foreignkey')
    op.add_column('item_types', sa.Column('variant_pricing_attribute', sa.String(), nullable=True))

    op.execute("""
        UPDATE item_types it
        SET variant_pricing_attribute = ga.slug
        FROM global_attributes ga
        WHERE it.variant_pricing_attribute_id = ga.id
    """)

    op.drop_column('item_types', 'variant_pricing_attribute_id')

    # =========================================================================
    # 3. Restore global_attributes.modifies_ingredient_slug
    # =========================================================================

    op.drop_constraint('fk_global_attributes_modifies_ingredient', 'global_attributes', type_='foreignkey')
    op.add_column('global_attributes', sa.Column('modifies_ingredient_slug', sa.String(100), nullable=True))

    op.execute("""
        UPDATE global_attributes ga
        SET modifies_ingredient_slug = i.slug
        FROM ingredients i
        WHERE ga.modifies_ingredient_id = i.id
    """)

    op.drop_column('global_attributes', 'modifies_ingredient_id')

    # =========================================================================
    # 2. Recreate recipe tables
    # =========================================================================

    op.create_table(
        'recipes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True)
    )

    op.create_table(
        'recipe_ingredients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('recipe_id', sa.Integer(), sa.ForeignKey('recipes.id'), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), sa.ForeignKey('ingredients.id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit_override', sa.String(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=True)
    )

    op.create_table(
        'recipe_choice_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('recipe_id', sa.Integer(), sa.ForeignKey('recipes.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('min_choices', sa.Integer(), nullable=True),
        sa.Column('max_choices', sa.Integer(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=True)
    )

    op.create_table(
        'recipe_choice_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('choice_group_id', sa.Integer(), sa.ForeignKey('recipe_choice_groups.id'), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), sa.ForeignKey('ingredients.id'), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=True),
        sa.Column('extra_price', sa.Float(), nullable=True)
    )

    # =========================================================================
    # 1. Recreate legacy attribute tables
    # =========================================================================

    op.create_table(
        'attribute_definitions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id'), nullable=True),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('input_type', sa.String(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=True),
        sa.Column('allow_none', sa.Boolean(), nullable=True),
        sa.Column('min_selections', sa.Integer(), nullable=True),
        sa.Column('max_selections', sa.Integer(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True)
    )

    op.create_table(
        'item_type_attributes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id'), nullable=True),
        sa.Column('slug', sa.String(), nullable=True),
        sa.Column('display_name', sa.String(), nullable=True),
        sa.Column('input_type', sa.String(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=True),
        sa.Column('allow_none', sa.Boolean(), nullable=True),
        sa.Column('min_selections', sa.Integer(), nullable=True),
        sa.Column('max_selections', sa.Integer(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True),
        sa.Column('ask_in_conversation', sa.Boolean(), nullable=True),
        sa.Column('question_text', sa.Text(), nullable=True),
        sa.Column('loads_from_ingredients', sa.Boolean(), nullable=True),
        sa.Column('ingredient_group', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True)
    )

    op.create_table(
        'attribute_options',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('attribute_definition_id', sa.Integer(), sa.ForeignKey('attribute_definitions.id'), nullable=True),
        sa.Column('item_type_attribute_id', sa.Integer(), sa.ForeignKey('item_type_attributes.id'), nullable=True),
        sa.Column('slug', sa.String(), nullable=True),
        sa.Column('display_name', sa.String(), nullable=True),
        sa.Column('price_modifier', sa.Float(), nullable=True),
        sa.Column('iced_price_modifier', sa.Float(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=True),
        sa.Column('is_available', sa.Boolean(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True)
    )

    op.create_table(
        'attribute_option_ingredients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('attribute_option_id', sa.Integer(), sa.ForeignKey('attribute_options.id'), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), sa.ForeignKey('ingredients.id'), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True)
    )

    op.create_table(
        'menu_item_attribute_values',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('menu_item_id', sa.Integer(), sa.ForeignKey('menu_items.id'), nullable=False),
        sa.Column('attribute_id', sa.Integer(), sa.ForeignKey('item_type_attributes.id'), nullable=False),
        sa.Column('option_id', sa.Integer(), sa.ForeignKey('attribute_options.id'), nullable=True),
        sa.Column('value_boolean', sa.Boolean(), nullable=True),
        sa.Column('value_text', sa.String(), nullable=True),
        sa.Column('still_ask', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True)
    )

    op.create_table(
        'menu_item_attribute_selections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('menu_item_id', sa.Integer(), sa.ForeignKey('menu_items.id'), nullable=False),
        sa.Column('attribute_id', sa.Integer(), sa.ForeignKey('item_type_attributes.id'), nullable=False),
        sa.Column('option_id', sa.Integer(), sa.ForeignKey('attribute_options.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True)
    )
