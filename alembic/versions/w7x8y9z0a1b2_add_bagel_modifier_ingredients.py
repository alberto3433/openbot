"""Add bagel modifier ingredients and aliases.

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2025-01-04 16:00:00.000000

This migration:
1. Adds missing sliced cheeses (American, Swiss, Cheddar, etc.) with category='cheese'
2. Adds missing proteins (Sausage) with category='protein'
3. Adds missing toppings (Spinach, Mushrooms, Peppers, etc.) with category='topping'
4. Adds aliases to existing ingredients for synonym matching

These ingredients are used by the bagel modifier parsing system to recognize
user input like "add swiss cheese" or "with lox" and match them to menu items.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "w7x8y9z0a1b2"
down_revision: Union[str, None] = "v6w7x8y9z0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New cheeses to add (actual sliced cheeses for sandwiches)
NEW_CHEESES = [
    # (name, aliases)
    ("American Cheese", "american, american cheese, cheese"),
    ("Swiss Cheese", "swiss, swiss cheese"),
    ("Cheddar Cheese", "cheddar, cheddar cheese"),
    ("Muenster Cheese", "muenster, muenster cheese"),
    ("Provolone Cheese", "provolone, provolone cheese"),
    ("Gouda Cheese", "gouda, gouda cheese"),
    ("Mozzarella Cheese", "mozzarella, mozzarella cheese, mozz"),
    ("Pepper Jack Cheese", "pepper jack, pepper jack cheese, pepperjack"),
]

# New proteins to add
NEW_PROTEINS = [
    ("Sausage", "sausage, breakfast sausage"),
]

# New toppings to add
NEW_TOPPINGS = [
    ("Spinach", "spinach"),
    ("Mushrooms", "mushroom, mushrooms"),
    ("Green Pepper", "green pepper, green peppers"),
    ("Red Pepper", "red pepper, red peppers"),
    ("Bell Pepper", "bell pepper, bell peppers"),
    ("Salt", "salt"),
    ("Black Pepper", "pepper, black pepper"),
    ("Ketchup", "ketchup, catsup"),
]

# Aliases to add to existing ingredients
# Format: (ingredient_name, new_aliases_to_append)
ALIAS_UPDATES = [
    # Proteins
    ("Nova Scotia Salmon", "nova, lox, nova scotia, nova salmon"),
    ("Egg", "eggs"),
    ("Egg White", "egg whites"),
    ("Scrambled Eggs", "scrambled egg"),
    ("Baked Salmon", "salmon"),
    # Toppings
    ("Tomato", "tomatoes"),
    ("Cucumber", "cucumbers"),
    ("Onion", "onions"),
    ("Red Onion", "red onions"),
    ("Pickles", "pickle"),
    # Sauces (also used as toppings)
    ("Mayo", "mayonnaise"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Add new cheeses
    for name, aliases in NEW_CHEESES:
        # Check if already exists
        result = conn.execute(
            sa.text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.scalar() is None:
            conn.execute(
                sa.text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, is_available, aliases)
                    VALUES (:name, 'cheese', 'slice', false, true, :aliases)
                """),
                {"name": name, "aliases": aliases}
            )

    # Add new proteins
    for name, aliases in NEW_PROTEINS:
        result = conn.execute(
            sa.text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.scalar() is None:
            conn.execute(
                sa.text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, is_available, aliases)
                    VALUES (:name, 'protein', 'piece', false, true, :aliases)
                """),
                {"name": name, "aliases": aliases}
            )

    # Add new toppings
    for name, aliases in NEW_TOPPINGS:
        result = conn.execute(
            sa.text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.scalar() is None:
            conn.execute(
                sa.text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, is_available, aliases)
                    VALUES (:name, 'topping', 'piece', false, true, :aliases)
                """),
                {"name": name, "aliases": aliases}
            )

    # Update aliases for existing ingredients
    for name, new_aliases in ALIAS_UPDATES:
        # Get current aliases
        result = conn.execute(
            sa.text("SELECT id, aliases FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        row = result.fetchone()
        if row:
            ing_id = row[0]
            current_aliases = row[1] or ""

            # Merge aliases (avoid duplicates)
            existing = set(a.strip().lower() for a in current_aliases.split(",") if a.strip())
            new = set(a.strip().lower() for a in new_aliases.split(",") if a.strip())
            merged = existing | new

            merged_str = ", ".join(sorted(merged))

            conn.execute(
                sa.text("UPDATE ingredients SET aliases = :aliases WHERE id = :id"),
                {"aliases": merged_str, "id": ing_id}
            )


def downgrade() -> None:
    conn = op.get_bind()

    # Remove new cheeses
    for name, _ in NEW_CHEESES:
        conn.execute(
            sa.text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )

    # Remove new proteins
    for name, _ in NEW_PROTEINS:
        conn.execute(
            sa.text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )

    # Remove new toppings
    for name, _ in NEW_TOPPINGS:
        conn.execute(
            sa.text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )

    # Note: We don't revert alias updates as it's complex to track
    # what was added vs what was original
