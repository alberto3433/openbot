"""Add bagel_package item type with package_variety and package_contents attributes

Creates a new item type for bagel packages with data-driven selection flow:
1. bagel_package item type linked to "breads" display group
2. package_variety attribute (assorted vs custom)
3. package_contents attribute (package_multi_select input type)
4. Skip rule: "assorted" triggers skip of package_contents
5. Updates package menu items to use new item type

Revision ID: bagel_package_01
Revises: weight_alias_01
Create Date: 2026-02-07
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "bagel_package_01"
down_revision = "weight_alias_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. Update check constraint on input_type to allow 'package_multi_select'
    op.execute("""
        ALTER TABLE global_attributes
        DROP CONSTRAINT IF EXISTS ck_global_attributes_input_type
    """)
    op.execute("""
        ALTER TABLE global_attributes
        ADD CONSTRAINT ck_global_attributes_input_type
        CHECK (input_type IN ('single_select', 'multi_select', 'boolean', 'quantity', 'package_multi_select'))
    """)

    # 1. Create bagel_package item type linked to breads display group
    op.execute("""
        INSERT INTO item_types (slug, display_name, display_name_plural, menu_display_group_id, has_side_choice)
        SELECT 'bagel_package', 'Bagel Package', 'Bagel Packages',
               (SELECT id FROM menu_display_groups WHERE slug = 'breads'),
               false
        WHERE NOT EXISTS (
            SELECT 1 FROM item_types WHERE slug = 'bagel_package'
        )
    """)

    # 2. Create package_variety global attribute
    op.execute("""
        INSERT INTO global_attributes (slug, display_name, input_type, question_text)
        SELECT 'package_variety', 'Package Variety', 'single_select',
               'Would you like an assorted mix, or would you prefer to choose your bagel types?'
        WHERE NOT EXISTS (
            SELECT 1 FROM global_attributes WHERE slug = 'package_variety'
        )
    """)

    # 3. Create options for package_variety
    # Option: assorted
    op.execute("""
        INSERT INTO global_attribute_options (global_attribute_id, slug, display_name, display_order, is_default, is_available, price_modifier)
        SELECT
            (SELECT id FROM global_attributes WHERE slug = 'package_variety'),
            'assorted', 'Assorted Mix', 1, false, true, 0.0
        WHERE NOT EXISTS (
            SELECT 1 FROM global_attribute_options
            WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
            AND slug = 'assorted'
        )
    """)

    # Option: custom
    op.execute("""
        INSERT INTO global_attribute_options (global_attribute_id, slug, display_name, display_order, is_default, is_available, price_modifier)
        SELECT
            (SELECT id FROM global_attributes WHERE slug = 'package_variety'),
            'custom', 'Choose Types', 2, false, true, 0.0
        WHERE NOT EXISTS (
            SELECT 1 FROM global_attribute_options
            WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
            AND slug = 'custom'
        )
    """)

    # Add aliases for assorted option (e.g., "mix it up", "you pick", "chef's choice")
    op.execute("""
        INSERT INTO global_attribute_option_aliases (global_attribute_option_id, alias)
        SELECT
            (SELECT id FROM global_attribute_options
             WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
             AND slug = 'assorted'),
            unnest(ARRAY['mix it up', 'you pick', 'dealers choice', 'mix', 'assorted', 'surprise me'])
        ON CONFLICT (alias) DO NOTHING
    """)

    # Add aliases for custom option (e.g., "I'll choose", "let me pick", "custom")
    op.execute("""
        INSERT INTO global_attribute_option_aliases (global_attribute_option_id, alias)
        SELECT
            (SELECT id FROM global_attribute_options
             WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
             AND slug = 'custom'),
            unnest(ARRAY['choose', 'pick', 'select', 'custom', 'let me pick', 'ill choose', 'i will choose', 'specific'])
        ON CONFLICT (alias) DO NOTHING
    """)

    # 4. Create package_contents global attribute with new input_type
    op.execute("""
        INSERT INTO global_attributes (slug, display_name, input_type, question_text)
        SELECT 'package_contents', 'Package Contents', 'package_multi_select',
               'What bagel types would you like? For example, ''3 plain and 3 everything'''
        WHERE NOT EXISTS (
            SELECT 1 FROM global_attributes WHERE slug = 'package_contents'
        )
    """)

    # 5. Link attributes to bagel_package item type
    # package_variety is first, required, ask in conversation
    op.execute("""
        INSERT INTO item_type_global_attributes (item_type_id, global_attribute_id, display_order, is_required, allow_none, ask_in_conversation, listen_only)
        SELECT
            (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            (SELECT id FROM global_attributes WHERE slug = 'package_variety'),
            1, true, false, true, false
        WHERE NOT EXISTS (
            SELECT 1 FROM item_type_global_attributes
            WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package')
            AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
        )
    """)

    # package_contents is second, NOT required by default (only if custom), ask in conversation
    op.execute("""
        INSERT INTO item_type_global_attributes (item_type_id, global_attribute_id, display_order, is_required, allow_none, ask_in_conversation, listen_only)
        SELECT
            (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            (SELECT id FROM global_attributes WHERE slug = 'package_contents'),
            2, false, false, true, false
        WHERE NOT EXISTS (
            SELECT 1 FROM item_type_global_attributes
            WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package')
            AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_contents')
        )
    """)

    # 6. Add skip rule: assorted -> skip package_contents
    op.execute("""
        INSERT INTO global_attribute_option_skips (triggering_option_id, skipped_attribute_id)
        SELECT
            (SELECT id FROM global_attribute_options
             WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
             AND slug = 'assorted'),
            (SELECT id FROM global_attributes WHERE slug = 'package_contents')
        WHERE NOT EXISTS (
            SELECT 1 FROM global_attribute_option_skips
            WHERE triggering_option_id = (
                SELECT id FROM global_attribute_options
                WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
                AND slug = 'assorted'
            )
            AND skipped_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_contents')
        )
    """)

    # 7. Update package menu items to use new item type and set quantity_per_unit
    op.execute("""
        UPDATE menu_items
        SET item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            quantity_per_unit = 3
        WHERE name = '3 Bagel Package'
    """)

    op.execute("""
        UPDATE menu_items
        SET item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            quantity_per_unit = 6
        WHERE name = '6 Bagel Package'
    """)

    op.execute("""
        UPDATE menu_items
        SET item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            quantity_per_unit = 13
        WHERE name = 'Baker''s Dozen'
    """)

    op.execute("""
        UPDATE menu_items
        SET item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            quantity_per_unit = 12
        WHERE name = 'Bagel Package - Dozen Bagels & 2 Cream Cheese'
    """)

    # 8. Add item type aliases for recognition
    op.execute("""
        INSERT INTO item_type_aliases (item_type_id, alias)
        SELECT
            (SELECT id FROM item_types WHERE slug = 'bagel_package'),
            unnest(ARRAY['bagel pack', 'pack of bagels', 'bagels package', 'dozen bagels', 'bakers dozen'])
        ON CONFLICT (alias) DO NOTHING
    """)


def downgrade() -> None:
    # Revert check constraint
    op.execute("""
        ALTER TABLE global_attributes
        DROP CONSTRAINT IF EXISTS ck_global_attributes_input_type
    """)
    op.execute("""
        ALTER TABLE global_attributes
        ADD CONSTRAINT ck_global_attributes_input_type
        CHECK (input_type IN ('single_select', 'multi_select', 'boolean', 'quantity'))
    """)

    # Revert menu items back to bagel item type
    op.execute("""
        UPDATE menu_items
        SET item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel'),
            quantity_per_unit = NULL
        WHERE name IN ('3 Bagel Package', '6 Bagel Package', 'Baker''s Dozen', 'Bagel Package - Dozen Bagels & 2 Cream Cheese')
    """)

    # Remove skip rules
    op.execute("""
        DELETE FROM global_attribute_option_skips
        WHERE triggering_option_id IN (
            SELECT id FROM global_attribute_options
            WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
        )
    """)

    # Remove item type global attribute links
    op.execute("""
        DELETE FROM item_type_global_attributes
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package')
    """)

    # Remove item type aliases
    op.execute("""
        DELETE FROM item_type_aliases
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel_package')
    """)

    # Remove option aliases for package_variety
    op.execute("""
        DELETE FROM global_attribute_option_aliases
        WHERE global_attribute_option_id IN (
            SELECT id FROM global_attribute_options
            WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
        )
    """)

    # Remove package_variety options
    op.execute("""
        DELETE FROM global_attribute_options
        WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'package_variety')
    """)

    # Remove global attributes
    op.execute("DELETE FROM global_attributes WHERE slug = 'package_contents'")
    op.execute("DELETE FROM global_attributes WHERE slug = 'package_variety'")

    # Remove item type
    op.execute("DELETE FROM item_types WHERE slug = 'bagel_package'")
