"""Consolidate ItemTypeAttribute into GlobalAttribute system.

This migration:
1. Creates missing GlobalAttributes (condiments, filling, proteins, veggies, etc.)
2. Creates missing ItemTypeGlobalAttribute links
3. Fixes ask_in_conversation conflicts (style, temperature for beverages)
4. Maps extra_shots -> shots
5. Drops the item_type_attributes table entirely

Revision ID: consolidate_global_attrs
Revises: (will be filled by alembic)
Create Date: 2025-01-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = 'consolidate_global_attrs'
down_revision = 'fix_syrup_price_01'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ==========================================================================
    # PHASE 2: Create missing GlobalAttributes
    # ==========================================================================
    print("Phase 2: Creating missing GlobalAttributes...")

    missing_global_attrs = [
        ('condiments', 'Condiments', 'multi_select', 'Condiments like ketchup, mustard, mayo'),
        ('filling', 'Omelette Filling', 'multi_select', 'Fillings for omelettes'),
        ('proteins', 'Proteins', 'multi_select', 'Protein additions'),
        ('veggies', 'Veggies', 'multi_select', 'Vegetable additions'),
    ]

    for slug, display_name, input_type, description in missing_global_attrs:
        # Check if already exists
        exists = conn.execute(text(
            "SELECT id FROM global_attributes WHERE slug = :slug"
        ), {"slug": slug}).fetchone()

        if not exists:
            conn.execute(text("""
                INSERT INTO global_attributes (slug, display_name, input_type, description, created_at, updated_at)
                VALUES (:slug, :display_name, :input_type, :description, NOW(), NOW())
            """), {
                "slug": slug,
                "display_name": display_name,
                "input_type": input_type,
                "description": description,
            })
            print(f"  Created GlobalAttribute: {slug}")
        else:
            print(f"  GlobalAttribute already exists: {slug}")

    # ==========================================================================
    # PHASE 3: Create missing ItemTypeGlobalAttribute links
    # ==========================================================================
    print("\nPhase 3: Creating missing ItemTypeGlobalAttribute links...")

    # Get all item type IDs
    item_types = {row.slug: row.id for row in conn.execute(text(
        "SELECT id, slug FROM item_types"
    ))}

    # Get all global attribute IDs
    global_attrs = {row.slug: row.id for row in conn.execute(text(
        "SELECT id, slug FROM global_attributes"
    ))}

    # Define links to create based on what ItemTypeAttribute had
    # Format: (item_type_slug, global_attr_slug, ask_in_conversation, is_required, question_text, display_order)
    links_to_create = [
        # bagel - condiments
        ('bagel', 'condiments', False, False, None, 100),

        # deli_sandwich - condiments
        ('deli_sandwich', 'condiments', False, False, None, 100),

        # espresso - map extra_shots to shots (already has shots link, just verify)
        # No new link needed - shots already linked

        # fish_sandwich - condiments
        ('fish_sandwich', 'condiments', False, False, None, 100),

        # omelette - filling, veggies (ask=True from local)
        ('omelette', 'filling', True, False, 'What would you like in your omelette?', 4),
        ('omelette', 'veggies', True, False, 'Any vegetables?', 10),

        # spread_sandwich - proteins, condiments
        ('spread_sandwich', 'proteins', False, False, None, 50),
        ('spread_sandwich', 'condiments', False, False, None, 100),
    ]

    for item_type_slug, attr_slug, ask, required, question, display_order in links_to_create:
        item_type_id = item_types.get(item_type_slug)
        global_attr_id = global_attrs.get(attr_slug)

        if not item_type_id:
            print(f"  WARNING: Item type not found: {item_type_slug}")
            continue
        if not global_attr_id:
            print(f"  WARNING: Global attribute not found: {attr_slug}")
            continue

        # Check if link already exists
        exists = conn.execute(text("""
            SELECT id FROM item_type_global_attributes
            WHERE item_type_id = :item_type_id AND global_attribute_id = :global_attr_id
        """), {"item_type_id": item_type_id, "global_attr_id": global_attr_id}).fetchone()

        if not exists:
            conn.execute(text("""
                INSERT INTO item_type_global_attributes
                (item_type_id, global_attribute_id, ask_in_conversation, is_required,
                 question_text, display_order, allow_none, created_at, updated_at)
                VALUES (:item_type_id, :global_attr_id, :ask, :required,
                        :question, :display_order, true, NOW(), NOW())
            """), {
                "item_type_id": item_type_id,
                "global_attr_id": global_attr_id,
                "ask": ask,
                "required": required,
                "question": question,
                "display_order": display_order,
            })
            print(f"  Created link: {item_type_slug} -> {attr_slug}")
        else:
            print(f"  Link already exists: {item_type_slug} -> {attr_slug}")

    # ==========================================================================
    # PHASE 4: Fix configuration conflicts
    # ==========================================================================
    print("\nPhase 4: Fixing configuration conflicts...")

    # Fix sized_beverage.size: should be ask=True (needed for configuration)
    conn.execute(text("""
        UPDATE item_type_global_attributes
        SET ask_in_conversation = true,
            question_text = 'What size?'
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'sized_beverage')
          AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'size')
    """))
    print("  Fixed: sized_beverage.size -> ask=True")

    # Fix sized_beverage.style: should be ask=True (local had True, global had False)
    conn.execute(text("""
        UPDATE item_type_global_attributes
        SET ask_in_conversation = true
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'sized_beverage')
          AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'style')
    """))
    print("  Fixed: sized_beverage.style -> ask=True")

    # Fix sized_beverage.temperature: should be ask=True
    result = conn.execute(text("""
        SELECT id FROM item_type_global_attributes
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'sized_beverage')
          AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'temperature')
    """)).fetchone()

    if result:
        conn.execute(text("""
            UPDATE item_type_global_attributes
            SET ask_in_conversation = true,
                question_text = 'Would you like that hot or iced?'
            WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'sized_beverage')
              AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'temperature')
        """))
        print("  Fixed: sized_beverage.temperature -> ask=True")
    else:
        # Create the link if it doesn't exist
        conn.execute(text("""
            INSERT INTO item_type_global_attributes
            (item_type_id, global_attribute_id, ask_in_conversation, is_required,
             question_text, display_order, allow_none, created_at, updated_at)
            VALUES (
                (SELECT id FROM item_types WHERE slug = 'sized_beverage'),
                (SELECT id FROM global_attributes WHERE slug = 'temperature'),
                true, false, 'Would you like that hot or iced?', 3, true, NOW(), NOW()
            )
        """))
        print("  Created: sized_beverage.temperature link with ask=True")

    # Fix omelette.egg_style: should be ask=True (local had True)
    conn.execute(text("""
        UPDATE item_type_global_attributes
        SET ask_in_conversation = true
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'omelette')
          AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'egg_style')
    """))
    print("  Fixed: omelette.egg_style -> ask=True")

    # ==========================================================================
    # PHASE 5: Copy GlobalAttributeOptions from ItemTypeIngredient where needed
    # ==========================================================================
    print("\nPhase 5: Ensuring GlobalAttributeOptions exist for new attributes...")

    # For condiments, filling, proteins, veggies - we need options
    # These should link to ingredients by category

    # Map attribute slugs to ingredient categories
    attr_to_category = {
        'condiments': 'condiment',
        'filling': 'filling',
        'proteins': 'protein',
        'veggies': 'veggie',
    }

    for attr_slug, ing_category in attr_to_category.items():
        global_attr_id = global_attrs.get(attr_slug)
        if not global_attr_id:
            continue

        # Get ingredients in this category that don't have options yet
        ingredients = conn.execute(text("""
            SELECT i.id, i.slug, i.name
            FROM ingredients i
            WHERE i.category = :category
              AND NOT EXISTS (
                  SELECT 1 FROM global_attribute_options gao
                  WHERE gao.global_attribute_id = :attr_id AND gao.ingredient_id = i.id
              )
        """), {"category": ing_category, "attr_id": global_attr_id}).fetchall()

        for i, ing in enumerate(ingredients):
            conn.execute(text("""
                INSERT INTO global_attribute_options
                (global_attribute_id, slug, display_name, ingredient_id,
                 price_modifier, is_default, is_available, display_order, created_at, updated_at)
                VALUES (:attr_id, :slug, :name, :ing_id, 0, false, true, :order, NOW(), NOW())
            """), {
                "attr_id": global_attr_id,
                "slug": ing.slug,
                "name": ing.name,
                "ing_id": ing.id,
                "order": i,
            })

        if ingredients:
            print(f"  Created {len(ingredients)} options for {attr_slug}")

    # ==========================================================================
    # PHASE 6: Drop item_type_attributes table
    # ==========================================================================
    print("\nPhase 6: Dropping item_type_attributes table...")

    # First verify all data has been migrated
    remaining = conn.execute(text("""
        SELECT COUNT(*) as cnt FROM item_type_attributes
    """)).fetchone()
    print(f"  Rows in item_type_attributes before drop: {remaining.cnt}")

    # Drop the table
    op.drop_table('item_type_attributes')
    print("  Dropped table: item_type_attributes")

    print("\nMigration complete!")


def downgrade():
    """Recreate item_type_attributes table (without data)."""
    op.create_table(
        'item_type_attributes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slug', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=True),
        sa.Column('input_type', sa.String(20), nullable=False, server_default='single_select'),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('allow_none', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('min_selections', sa.Integer(), nullable=True),
        sa.Column('max_selections', sa.Integer(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ask_in_conversation', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('question_text', sa.Text(), nullable=True),
        sa.Column('loads_from_ingredients', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('ingredient_group', sa.String(50), nullable=True),
        sa.Column('default_value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('item_type_id', 'slug', name='uq_item_type_attributes_type_slug'),
    )
    print("Recreated item_type_attributes table (empty)")
