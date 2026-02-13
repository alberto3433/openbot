"""Link remaining physical-ingredient attribute options to ingredients table.

Revision ID: link_options_001
Revises: toast_01
Create Date: 2026-02-13

Sets ingredient_id on GlobalAttributeOption rows that represent physical
ingredients (toppings, spreads) but aren't yet linked. After linking,
slug/display_name are NULLed so the cache loader derives them from the
ingredient at runtime — ensuring a single source of truth for slugs.

Also adds a CHECK constraint enforcing that every option has a slug source:
either its own slug or a linked ingredient.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "link_options_001"
down_revision: Union[str, Sequence[str], None] = "toast_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Options to link to EXISTING ingredients (by ingredient slug).
# Format: (option_id, ingredient_slug)
LINK_TO_EXISTING = [
    (192, "onion"),          # toppings: Onions -> ingredient onion (id 39)
    (193, "red_onion"),      # toppings: Red Onions -> ingredient red_onion (id 40)
    (305, "pico_de_gallo"),  # toppings: Pico de Gallo -> ingredient pico_de_gallo (id 143)
    (306, "salsa"),          # toppings: Salsa -> ingredient salsa (id 144)
]

# Options that need NEW ingredients created first.
# Format: (option_id, ingredient_slug, ingredient_name, category)
CREATE_AND_LINK = [
    (190, "tomatoes", "Tomatoes", "topping"),
    (181, "scallion_tofu", "Scallion Tofu Spread", "spread"),
]

# Backup: original slug/display_name values for downgrade.
ORIGINAL_VALUES = {
    190: ("tomatoes", "Tomatoes"),
    192: ("onions", "Onions"),
    193: ("red_onions", "Red Onions"),
    305: ("pico_de_gallo", "Pico de Gallo"),
    306: ("salsa", "Salsa"),
    181: ("scallion_tofu", "Scallion Tofu Spread"),
}


def upgrade() -> None:
    conn = op.get_bind()

    # --- Part 1a: Link options to existing ingredients ---
    for option_id, ingredient_slug in LINK_TO_EXISTING:
        row = conn.execute(
            sa.text("SELECT id FROM ingredients WHERE slug = :slug"),
            {"slug": ingredient_slug},
        ).fetchone()
        if not row:
            raise RuntimeError(
                f"Expected ingredient '{ingredient_slug}' not found. "
                f"Cannot link option {option_id}."
            )
        ingredient_id = row[0]
        conn.execute(
            sa.text(
                "UPDATE global_attribute_options "
                "SET ingredient_id = :ing_id, slug = NULL, display_name = NULL "
                "WHERE id = :opt_id AND ingredient_id IS NULL"
            ),
            {"ing_id": ingredient_id, "opt_id": option_id},
        )

    # --- Part 1b: Create missing ingredients, then link ---
    for option_id, ing_slug, ing_name, ing_category in CREATE_AND_LINK:
        result = conn.execute(
            sa.text(
                "INSERT INTO ingredients (name, slug, category, track_inventory, unit_id) "
                "VALUES (:name, :slug, :category, true, 1) "
                "ON CONFLICT (slug) DO UPDATE SET name = :name "
                "RETURNING id"
            ),
            {"name": ing_name, "slug": ing_slug, "category": ing_category},
        )
        ingredient_id = result.fetchone()[0]
        conn.execute(
            sa.text(
                "UPDATE global_attribute_options "
                "SET ingredient_id = :ing_id, slug = NULL, display_name = NULL "
                "WHERE id = :opt_id AND ingredient_id IS NULL"
            ),
            {"ing_id": ingredient_id, "opt_id": option_id},
        )

    # --- Part 2: Add CHECK constraint ---
    conn.execute(
        sa.text(
            "ALTER TABLE global_attribute_options "
            "ADD CONSTRAINT chk_slug_source "
            "CHECK (ingredient_id IS NOT NULL OR slug IS NOT NULL)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove CHECK constraint
    conn.execute(
        sa.text(
            "ALTER TABLE global_attribute_options "
            "DROP CONSTRAINT IF EXISTS chk_slug_source"
        )
    )

    # Restore original slug/display_name and unlink
    for option_id, (orig_slug, orig_display) in ORIGINAL_VALUES.items():
        conn.execute(
            sa.text(
                "UPDATE global_attribute_options "
                "SET slug = :slug, display_name = :display, ingredient_id = NULL "
                "WHERE id = :opt_id"
            ),
            {"slug": orig_slug, "display": orig_display, "opt_id": option_id},
        )

    # Remove created ingredients (only if no other references)
    for _, ing_slug, _, _ in CREATE_AND_LINK:
        conn.execute(
            sa.text(
                "DELETE FROM ingredients WHERE slug = :slug "
                "AND id NOT IN ("
                "  SELECT DISTINCT ingredient_id FROM global_attribute_options "
                "  WHERE ingredient_id IS NOT NULL"
                ") AND id NOT IN ("
                "  SELECT DISTINCT ingredient_id FROM menu_item_ingredients "
                "  WHERE ingredient_id IS NOT NULL"
                ")"
            ),
            {"slug": ing_slug},
        )
