"""
Migrate default_config JSON to relational menu_item_attribute_values tables.

This script:
1. Adds missing item_type_attributes for item types that have default_config data
2. Creates attribute_options for values found in default_config
3. Migrates default_config JSON values to menu_item_attribute_values and menu_item_attribute_selections

Run with: python scripts/migrate_default_config_to_relational.py
"""

import os
import json
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


# =============================================================================
# Configuration: Define attributes needed for each item type
# =============================================================================

# Attributes that should be added for each item type
# Format: {item_type_slug: [{slug, display_name, input_type, is_required, still_ask_default}, ...]}
ITEM_TYPE_ATTRIBUTE_DEFINITIONS = {
    'egg_sandwich': [
        {'slug': 'bread', 'display_name': 'Bread Choice', 'input_type': 'single_select', 'is_required': True, 'still_ask_default': True},
        {'slug': 'toasted', 'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': False, 'still_ask_default': True},
        {'slug': 'scooped', 'display_name': 'Scooped Out', 'input_type': 'boolean', 'is_required': False, 'still_ask_default': False},
        {'slug': 'egg_style', 'display_name': 'Egg Preparation', 'input_type': 'single_select', 'is_required': False, 'still_ask_default': True},
        {'slug': 'protein', 'display_name': 'Breakfast Protein', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'cheese', 'display_name': 'Cheese', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'spread', 'display_name': 'Cream Cheese / Tofu', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'toppings', 'display_name': 'Breakfast Toppings', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
    ],
    'signature_sandwich': [
        {'slug': 'bread', 'display_name': 'Bread', 'input_type': 'single_select', 'is_required': True, 'still_ask_default': True},
        {'slug': 'protein', 'display_name': 'Protein', 'input_type': 'single_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'cheese', 'display_name': 'Cheese', 'input_type': 'single_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'extras', 'display_name': 'Extras', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'toasted', 'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': True, 'still_ask_default': True},
    ],
    'fish_sandwich': [
        {'slug': 'fish', 'display_name': 'Fish', 'input_type': 'single_select', 'is_required': True, 'still_ask_default': False},
        {'slug': 'spread', 'display_name': 'Spread', 'input_type': 'single_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'extras', 'display_name': 'Extras', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'toasted', 'display_name': 'Toasted', 'input_type': 'boolean', 'is_required': True, 'still_ask_default': True},
    ],
    'salad_sandwich': [
        {'slug': 'salad', 'display_name': 'Salad Type', 'input_type': 'single_select', 'is_required': True, 'still_ask_default': False},
        # Note: bread and toasted already exist from attribute_definitions migration
    ],
    'spread_sandwich': [
        {'slug': 'spread', 'display_name': 'Spread', 'input_type': 'single_select', 'is_required': True, 'still_ask_default': False},
        # Note: bread and toasted already exist from attribute_definitions migration
    ],
    'omelette': [
        {'slug': 'eggs', 'display_name': 'Eggs', 'input_type': 'single_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'protein', 'display_name': 'Protein', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'cheese', 'display_name': 'Cheese', 'input_type': 'multi_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'spread', 'display_name': 'Spread', 'input_type': 'single_select', 'is_required': False, 'still_ask_default': False},
        {'slug': 'includes_side_choice', 'display_name': 'Includes Side', 'input_type': 'boolean', 'is_required': False, 'still_ask_default': False},
        {'slug': 'side_options', 'display_name': 'Side Options', 'input_type': 'text', 'is_required': False, 'still_ask_default': False},
        # Note: side_choice, bagel_choice, egg_style, filling, extras already exist
    ],
}

# Map common value variations to canonical slugs for options
VALUE_NORMALIZATIONS = {
    # Breads
    'bagel': 'bagel',
    'plain bagel': 'plain_bagel',
    'everything bagel': 'everything_bagel',
    'whole wheat bagel': 'whole_wheat_bagel',
    'sesame bagel': 'sesame_bagel',
    'onion bagel': 'onion_bagel',
    'poppy bagel': 'poppy_bagel',
    'cinnamon raisin bagel': 'cinnamon_raisin_bagel',
    'pumpernickel bagel': 'pumpernickel_bagel',
    'bialy': 'bialy',
    'roll': 'roll',
    'bread': 'bread',

    # Proteins
    'egg white': 'egg_white',
    'egg whites': 'egg_white',
    'scrambled eggs': 'scrambled_eggs',
    'fried egg': 'fried_egg',
    'bacon': 'bacon',
    'turkey': 'turkey',
    'smoked turkey': 'smoked_turkey',
    'ham': 'ham',
    'sausage': 'sausage',
    'nova scotia salmon': 'nova_scotia_salmon',
    'whitefish salad': 'whitefish_salad',

    # Cheeses
    'swiss': 'swiss',
    'american': 'american',
    'cheddar': 'cheddar',
    'muenster': 'muenster',
    'havarti': 'havarti',
    'brie': 'brie',
    'provolone': 'provolone',

    # Spreads
    'plain cream cheese': 'plain_cream_cheese',
    'scallion cream cheese': 'scallion_cream_cheese',
    'vegetable cream cheese': 'vegetable_cream_cheese',
    'sun-dried tomato cream cheese': 'sun_dried_tomato_cream_cheese',
    'lox spread cream cheese': 'lox_spread_cream_cheese',
    'olive cream cheese': 'olive_cream_cheese',
    'walnut raisin cream cheese': 'walnut_raisin_cream_cheese',
    'honey walnut cream cheese': 'honey_walnut_cream_cheese',
    'strawberry cream cheese': 'strawberry_cream_cheese',
    'jalapeno cream cheese': 'jalapeno_cream_cheese',
    'butter': 'butter',

    # Fish
    'nova scotia salmon': 'nova_scotia_salmon',
    'kippered salmon': 'kippered_salmon',
    'sable': 'sable',
    'whitefish': 'whitefish',
    'baked salmon': 'baked_salmon',

    # Toppings/Extras
    'tomato': 'tomato',
    'lettuce': 'lettuce',
    'onion': 'onion',
    'red onion': 'red_onion',
    'capers': 'capers',
    'avocado': 'avocado',
    'spinach': 'spinach',
    'mayo': 'mayo',
    'basil mayo': 'basil_mayo',
    'dijon dill sauce': 'dijon_dill_sauce',
    'russian dressing': 'russian_dressing',
    'cole slaw': 'cole_slaw',

    # Salads
    'tuna salad': 'tuna_salad',
    'chicken salad': 'chicken_salad',
    'egg salad': 'egg_salad',
    'whitefish salad': 'whitefish_salad',
    'baked salmon salad': 'baked_salmon_salad',
}


def normalize_value(value: str) -> str:
    """Normalize a config value to a canonical slug."""
    lower = value.lower().strip()
    return VALUE_NORMALIZATIONS.get(lower, lower.replace(' ', '_').replace('-', '_'))


def get_or_create_attribute(db, item_type_id: int, attr_def: dict) -> int:
    """Get existing attribute or create new one. Returns attribute ID."""
    result = db.execute(text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :type_id AND slug = :slug
    """), {'type_id': item_type_id, 'slug': attr_def['slug']})
    row = result.fetchone()

    if row:
        return row[0]

    # Create new attribute
    result = db.execute(text("""
        INSERT INTO item_type_attributes
        (item_type_id, slug, display_name, input_type, is_required, allow_none, ask_in_conversation)
        VALUES (:type_id, :slug, :display_name, :input_type, :is_required, :allow_none, :ask)
        RETURNING id
    """), {
        'type_id': item_type_id,
        'slug': attr_def['slug'],
        'display_name': attr_def['display_name'],
        'input_type': attr_def['input_type'],
        'is_required': attr_def['is_required'],
        'allow_none': not attr_def['is_required'],
        'ask': True,
    })
    return result.fetchone()[0]


def get_or_create_option(db, attribute_id: int, value: str) -> int:
    """Get existing option or create new one. Returns option ID."""
    slug = normalize_value(value)
    display_name = value.title() if value == value.lower() else value

    # First check if option exists via item_type_attribute_id
    result = db.execute(text("""
        SELECT id FROM attribute_options
        WHERE item_type_attribute_id = :attr_id AND slug = :slug
    """), {'attr_id': attribute_id, 'slug': slug})
    row = result.fetchone()

    if row:
        return row[0]

    # Check if option exists anywhere with this slug (might need to update its item_type_attribute_id)
    # This handles options that already exist from the schema migration
    result = db.execute(text("""
        SELECT ao.id, ao.item_type_attribute_id
        FROM attribute_options ao
        WHERE ao.slug = :slug
        LIMIT 1
    """), {'slug': slug})
    row = result.fetchone()

    if row:
        option_id, existing_attr_id = row
        # If this option doesn't have an item_type_attribute_id yet, update it
        if existing_attr_id is None:
            db.execute(text("""
                UPDATE attribute_options
                SET item_type_attribute_id = :attr_id
                WHERE id = :opt_id
            """), {'attr_id': attribute_id, 'opt_id': option_id})
        return option_id

    # Need to find a valid attribute_definition_id for the FK constraint
    # Get the item_type_id from the attribute
    result = db.execute(text("""
        SELECT item_type_id FROM item_type_attributes WHERE id = :attr_id
    """), {'attr_id': attribute_id})
    item_type_id = result.fetchone()[0]

    # Try to find an existing attribute_definition for this item_type
    result = db.execute(text("""
        SELECT id FROM attribute_definitions
        WHERE item_type_id = :type_id
        LIMIT 1
    """), {'type_id': item_type_id})
    row = result.fetchone()

    if row:
        attr_def_id = row[0]
    else:
        # Create a placeholder attribute_definition for this item_type
        # Use a unique slug to avoid conflicts
        placeholder_slug = f'_placeholder_{item_type_id}'
        result = db.execute(text("""
            SELECT id FROM attribute_definitions
            WHERE item_type_id = :type_id AND slug = :slug
        """), {'type_id': item_type_id, 'slug': placeholder_slug})
        existing = result.fetchone()

        if existing:
            attr_def_id = existing[0]
        else:
            result = db.execute(text("""
                INSERT INTO attribute_definitions
                (item_type_id, slug, display_name, input_type, is_required, allow_none)
                VALUES (:type_id, :slug, :display_name, 'single_select', false, true)
                RETURNING id
            """), {
                'type_id': item_type_id,
                'slug': placeholder_slug,
                'display_name': 'Placeholder',
            })
            attr_def_id = result.fetchone()[0]

    # Check if option already exists for this attr_def_id (unique constraint)
    result = db.execute(text("""
        SELECT id FROM attribute_options
        WHERE attribute_definition_id = :attr_def_id AND slug = :slug
    """), {'attr_def_id': attr_def_id, 'slug': slug})
    existing = result.fetchone()

    if existing:
        # Update the existing option to also reference our new item_type_attribute
        db.execute(text("""
            UPDATE attribute_options
            SET item_type_attribute_id = :attr_id
            WHERE id = :opt_id AND item_type_attribute_id IS NULL
        """), {'attr_id': attribute_id, 'opt_id': existing[0]})
        return existing[0]

    # Create new option
    result = db.execute(text("""
        INSERT INTO attribute_options
        (attribute_definition_id, item_type_attribute_id, slug, display_name, price_modifier, is_available)
        VALUES (:attr_def_id, :attr_id, :slug, :display_name, 0, true)
        RETURNING id
    """), {
        'attr_def_id': attr_def_id,
        'attr_id': attribute_id,
        'slug': slug,
        'display_name': display_name,
    })
    return result.fetchone()[0]


def migrate_menu_item_config(
    db,
    menu_item_id: int,
    item_type_id: int,
    item_type_slug: str,
    config: Dict[str, Any],
    attr_definitions: Dict[str, dict]
) -> None:
    """Migrate a single menu item's default_config to relational tables."""

    for key, value in config.items():
        if value is None:
            continue

        # Get attribute definition
        attr_def = attr_definitions.get(key)
        if not attr_def:
            logger.warning(f"  Skipping unknown config key '{key}' for {item_type_slug}")
            continue

        # Get or create the attribute
        attr_id = get_or_create_attribute(db, item_type_id, attr_def)

        # Handle different value types
        if isinstance(value, list):
            # Multi-select: create entries in menu_item_attribute_selections
            for v in value:
                option_id = get_or_create_option(db, attr_id, str(v))
                # Check if selection already exists
                result = db.execute(text("""
                    SELECT id FROM menu_item_attribute_selections
                    WHERE menu_item_id = :mi_id AND attribute_id = :attr_id AND option_id = :opt_id
                """), {'mi_id': menu_item_id, 'attr_id': attr_id, 'opt_id': option_id})
                if not result.fetchone():
                    db.execute(text("""
                        INSERT INTO menu_item_attribute_selections
                        (menu_item_id, attribute_id, option_id)
                        VALUES (:mi_id, :attr_id, :opt_id)
                    """), {'mi_id': menu_item_id, 'attr_id': attr_id, 'opt_id': option_id})

            # Also create a menu_item_attribute_values entry for still_ask
            result = db.execute(text("""
                SELECT id FROM menu_item_attribute_values
                WHERE menu_item_id = :mi_id AND attribute_id = :attr_id
            """), {'mi_id': menu_item_id, 'attr_id': attr_id})
            if not result.fetchone():
                db.execute(text("""
                    INSERT INTO menu_item_attribute_values
                    (menu_item_id, attribute_id, still_ask)
                    VALUES (:mi_id, :attr_id, :still_ask)
                """), {
                    'mi_id': menu_item_id,
                    'attr_id': attr_id,
                    'still_ask': attr_def.get('still_ask_default', False)
                })

        elif isinstance(value, bool):
            # Boolean value
            result = db.execute(text("""
                SELECT id FROM menu_item_attribute_values
                WHERE menu_item_id = :mi_id AND attribute_id = :attr_id
            """), {'mi_id': menu_item_id, 'attr_id': attr_id})
            if not result.fetchone():
                db.execute(text("""
                    INSERT INTO menu_item_attribute_values
                    (menu_item_id, attribute_id, value_boolean, still_ask)
                    VALUES (:mi_id, :attr_id, :value, :still_ask)
                """), {
                    'mi_id': menu_item_id,
                    'attr_id': attr_id,
                    'value': value,
                    'still_ask': attr_def.get('still_ask_default', False)
                })
        else:
            # Single select: create option and reference it
            option_id = get_or_create_option(db, attr_id, str(value))
            result = db.execute(text("""
                SELECT id FROM menu_item_attribute_values
                WHERE menu_item_id = :mi_id AND attribute_id = :attr_id
            """), {'mi_id': menu_item_id, 'attr_id': attr_id})
            if not result.fetchone():
                db.execute(text("""
                    INSERT INTO menu_item_attribute_values
                    (menu_item_id, attribute_id, option_id, still_ask)
                    VALUES (:mi_id, :attr_id, :opt_id, :still_ask)
                """), {
                    'mi_id': menu_item_id,
                    'attr_id': attr_id,
                    'opt_id': option_id,
                    'still_ask': attr_def.get('still_ask_default', False)
                })


def fix_multi_select_single_values(db):
    """
    Fix menu items where multi_select attributes were stored as single values
    in menu_item_attribute_values instead of menu_item_attribute_selections.

    This happens when the default_config has a single string value for a field
    that is actually a multi_select (e.g., "protein": "Egg White" instead of
    "protein": ["Egg White"]).
    """
    logger.info("Fixing multi_select fields with single values...")

    # Find multi_select attributes that have option_id set in menu_item_attribute_values
    result = db.execute(text("""
        SELECT mav.menu_item_id, mav.attribute_id, mav.option_id, ita.slug, mi.name
        FROM menu_item_attribute_values mav
        JOIN item_type_attributes ita ON mav.attribute_id = ita.id
        JOIN menu_items mi ON mav.menu_item_id = mi.id
        WHERE ita.input_type = 'multi_select' AND mav.option_id IS NOT NULL
    """))

    rows = list(result)
    logger.info(f"Found {len(rows)} multi_select values to fix")

    for mi_id, attr_id, option_id, attr_slug, mi_name in rows:
        # Check if selection already exists
        exists = db.execute(text("""
            SELECT id FROM menu_item_attribute_selections
            WHERE menu_item_id = :mi_id AND attribute_id = :attr_id AND option_id = :opt_id
        """), {'mi_id': mi_id, 'attr_id': attr_id, 'opt_id': option_id}).fetchone()

        if not exists:
            # Add the selection
            db.execute(text("""
                INSERT INTO menu_item_attribute_selections
                (menu_item_id, attribute_id, option_id)
                VALUES (:mi_id, :attr_id, :opt_id)
            """), {'mi_id': mi_id, 'attr_id': attr_id, 'opt_id': option_id})
            logger.info(f"  Added {attr_slug} selection for {mi_name}")

        # Clear the option_id from menu_item_attribute_values (keep for still_ask)
        db.execute(text("""
            UPDATE menu_item_attribute_values
            SET option_id = NULL
            WHERE menu_item_id = :mi_id AND attribute_id = :attr_id
        """), {'mi_id': mi_id, 'attr_id': attr_id})


def fix_mismatched_attribute_selections(db):
    """
    Fix selections where the option's item_type_attribute_id doesn't match the selection's attribute_id.

    This happens when:
    1. An option was originally created for one attribute (e.g., attribute 16)
    2. A selection was created pointing to that option
    3. But the selection references a different attribute (e.g., attribute 45)
    4. The API filters options by item_type_attribute_id, so the option doesn't show in the UI

    Fix: For each mismatched selection, find or create an option with the correct
    item_type_attribute_id and update the selection to use it.
    """
    logger.info("Fixing mismatched attribute selections...")

    # Find all selections where option.item_type_attribute_id != selection.attribute_id
    result = db.execute(text("""
        SELECT
            mas.id as selection_id,
            mas.menu_item_id,
            mas.attribute_id,
            mas.option_id,
            ao.slug as option_slug,
            ao.display_name as option_display_name,
            ao.item_type_attribute_id as option_attr_id,
            mi.name as menu_item_name,
            ita.slug as attr_slug
        FROM menu_item_attribute_selections mas
        JOIN attribute_options ao ON mas.option_id = ao.id
        JOIN menu_items mi ON mas.menu_item_id = mi.id
        JOIN item_type_attributes ita ON mas.attribute_id = ita.id
        WHERE ao.item_type_attribute_id IS NULL
           OR ao.item_type_attribute_id != mas.attribute_id
        ORDER BY mi.name, ita.slug
    """))

    rows = list(result)
    logger.info(f"Found {len(rows)} mismatched selections to fix")

    fixed_count = 0
    skipped_count = 0
    created_options = 0

    for row in rows:
        selection_id = row[0]
        menu_item_id = row[1]
        attribute_id = row[2]
        old_option_id = row[3]
        option_slug = row[4]
        option_display_name = row[5]
        old_option_attr_id = row[6]
        menu_item_name = row[7]
        attr_slug = row[8]

        # Find an option with the same slug but correct item_type_attribute_id
        correct_option = db.execute(text("""
            SELECT id FROM attribute_options
            WHERE slug = :slug AND item_type_attribute_id = :attr_id
        """), {'slug': option_slug, 'attr_id': attribute_id}).fetchone()

        if correct_option:
            correct_option_id = correct_option[0]
        else:
            # Need to find or create an option with the correct item_type_attribute_id
            # First get the attribute_definition_id from the existing option
            old_opt_info = db.execute(text("""
                SELECT attribute_definition_id, price_modifier, is_available
                FROM attribute_options WHERE id = :opt_id
            """), {'opt_id': old_option_id}).fetchone()

            attr_def_id = old_opt_info[0] if old_opt_info else None
            price_mod = old_opt_info[1] if old_opt_info else 0
            is_avail = old_opt_info[2] if old_opt_info else True

            # Check if there's an existing option with same (attr_def_id, slug) that we can update
            existing_by_def = db.execute(text("""
                SELECT id, item_type_attribute_id FROM attribute_options
                WHERE attribute_definition_id = :attr_def_id AND slug = :slug
            """), {'attr_def_id': attr_def_id, 'slug': option_slug}).fetchone()

            if existing_by_def:
                # Update this option's item_type_attribute_id
                opt_id = existing_by_def[0]
                current_ita_id = existing_by_def[1]
                if current_ita_id != attribute_id:
                    db.execute(text("""
                        UPDATE attribute_options
                        SET item_type_attribute_id = :attr_id
                        WHERE id = :opt_id
                    """), {'attr_id': attribute_id, 'opt_id': opt_id})
                    logger.info(f"  Updated option {option_slug} (id={opt_id}) item_type_attribute_id -> {attribute_id}")
                correct_option_id = opt_id
            else:
                # Create the new option
                new_opt = db.execute(text("""
                    INSERT INTO attribute_options
                    (attribute_definition_id, item_type_attribute_id, slug, display_name, price_modifier, is_available)
                    VALUES (:attr_def_id, :attr_id, :slug, :display_name, :price_mod, :is_avail)
                    RETURNING id
                """), {
                    'attr_def_id': attr_def_id,
                    'attr_id': attribute_id,
                    'slug': option_slug,
                    'display_name': option_display_name,
                    'price_mod': price_mod,
                    'is_avail': is_avail
                }).fetchone()
                correct_option_id = new_opt[0]
                created_options += 1
                logger.info(f"  Created new option {option_slug} (id={correct_option_id}) for attribute {attr_slug}")

        # Check if a selection with the correct option already exists
        existing = db.execute(text("""
            SELECT id FROM menu_item_attribute_selections
            WHERE menu_item_id = :mi_id AND attribute_id = :attr_id AND option_id = :opt_id
        """), {'mi_id': menu_item_id, 'attr_id': attribute_id, 'opt_id': correct_option_id}).fetchone()

        if existing:
            # Correct selection already exists, just delete the mismatched one
            db.execute(text("""
                DELETE FROM menu_item_attribute_selections WHERE id = :sel_id
            """), {'sel_id': selection_id})
            logger.info(f"  {menu_item_name}: Deleted duplicate {attr_slug} selection (correct already exists)")
            skipped_count += 1
        else:
            # Update the selection to use the correct option
            db.execute(text("""
                UPDATE menu_item_attribute_selections
                SET option_id = :new_opt_id
                WHERE id = :sel_id
            """), {'new_opt_id': correct_option_id, 'sel_id': selection_id})
            logger.info(f"  {menu_item_name}: Fixed {attr_slug} selection -> option {correct_option_id}")
            fixed_count += 1

    logger.info(f"Completed: {fixed_count} fixed, {skipped_count} deleted (duplicates), {created_options} new options created")


def run_migration():
    """Run the full migration."""
    db = SessionLocal()

    try:
        # Get all item types
        result = db.execute(text("SELECT id, slug FROM item_types"))
        item_types = {row[1]: row[0] for row in result}

        # Build attribute definitions lookup
        # Combine predefined definitions with existing ones from DB
        all_attr_defs = {}
        for type_slug, attrs in ITEM_TYPE_ATTRIBUTE_DEFINITIONS.items():
            all_attr_defs[type_slug] = {a['slug']: a for a in attrs}

        # Add attributes that already exist in DB
        result = db.execute(text("""
            SELECT it.slug, ita.slug, ita.display_name, ita.input_type, ita.is_required
            FROM item_type_attributes ita
            JOIN item_types it ON ita.item_type_id = it.id
        """))
        for row in result:
            type_slug, attr_slug, display_name, input_type, is_required = row
            if type_slug not in all_attr_defs:
                all_attr_defs[type_slug] = {}
            if attr_slug not in all_attr_defs[type_slug]:
                all_attr_defs[type_slug][attr_slug] = {
                    'slug': attr_slug,
                    'display_name': display_name,
                    'input_type': input_type,
                    'is_required': is_required,
                    'still_ask_default': True,
                }

        # Get all menu items with default_config
        result = db.execute(text("""
            SELECT mi.id, mi.name, mi.item_type_id, it.slug as item_type_slug, mi.default_config
            FROM menu_items mi
            JOIN item_types it ON mi.item_type_id = it.id
            WHERE mi.default_config IS NOT NULL
        """))

        menu_items = list(result)
        logger.info(f"Found {len(menu_items)} menu items with default_config")

        for mi_id, mi_name, item_type_id, item_type_slug, config in menu_items:
            if not config:
                continue

            logger.info(f"Migrating: {mi_name} ({item_type_slug})")

            attr_defs = all_attr_defs.get(item_type_slug, {})
            if not attr_defs:
                logger.warning(f"  No attribute definitions for {item_type_slug}, skipping")
                continue

            migrate_menu_item_config(
                db, mi_id, item_type_id, item_type_slug, config, attr_defs
            )

        # Fix multi_select fields that were stored as single values
        fix_multi_select_single_values(db)

        db.commit()
        logger.info("Migration completed successfully!")

        # Print summary
        result = db.execute(text("SELECT COUNT(*) FROM menu_item_attribute_values"))
        values_count = result.fetchone()[0]
        result = db.execute(text("SELECT COUNT(*) FROM menu_item_attribute_selections"))
        selections_count = result.fetchone()[0]

        logger.info(f"Created {values_count} attribute values and {selections_count} multi-select selections")

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db.close()


def run_fix_mismatched_selections():
    """Run just the mismatched selections fix."""
    db = SessionLocal()
    try:
        fix_mismatched_attribute_selections(db)
        db.commit()
        logger.info("Fix completed successfully!")
    except Exception as e:
        db.rollback()
        logger.error(f"Fix failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--fix-selections":
        run_fix_mismatched_selections()
    else:
        run_migration()
