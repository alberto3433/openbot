"""Populate aliases for speed menu items.

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2025-01-04 15:00:00.000000

This migration populates the aliases column for signature/speed menu items
so that users can order them using various common phrases like "bec",
"bacon egg and cheese", "the classic", etc.

The aliases are used by the menu data cache to build a mapping from
user input variations to the actual menu item names in the database.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "s3t4u5v6w7x8"
down_revision = "r2s3t4u5v6w7"
branch_labels = None
depends_on = None


# Mapping of menu item names to their aliases (comma-separated)
# These aliases allow users to order using common variations
SPEED_MENU_ALIASES = {
    # The Classic BEC - most popular breakfast sandwich
    # Note: "the classic" and "classic" also point here (no standalone "The Classic" item)
    "The Classic BEC": (
        "the classic bec, classic bec, bec, b.e.c., b.e.c, "
        "bacon egg and cheese, bacon egg cheese, bacon and egg and cheese, "
        "bacon eggs and cheese, bacon eggs cheese, egg bacon and cheese, "
        "egg and bacon and cheese, egg bacon cheese, bacon n egg n cheese, "
        "bacon n egg and cheese, the classic, classic"
    ),

    # SEC - Sausage Egg and Cheese
    "SEC": (
        "sec, s.e.c., s.e.c, sausage egg and cheese bagel, "
        "sausage egg and cheese, sausage egg cheese, sausage eggs and cheese, "
        "sausage eggs cheese, sausage and egg and cheese, egg sausage and cheese, "
        "egg and sausage and cheese, egg sausage cheese"
    ),

    # HEC - Ham Egg and Cheese
    "HEC": (
        "hec, h.e.c., h.e.c, ham egg and cheese bagel, "
        "ham egg and cheese, ham egg cheese, ham eggs and cheese, "
        "ham eggs cheese, ham and egg and cheese, egg ham and cheese, "
        "egg and ham and cheese, egg ham cheese"
    ),

    # The Zucker's Traditional - nova, cream cheese, capers, onion
    "The Zucker's Traditional": (
        "the traditional, traditional, the zucker's traditional, "
        "zucker's traditional, zuckers traditional, the zuckers traditional"
    ),

    # The Leo - nova, cream cheese, tomato, onion, capers, scrambled eggs
    "The Leo": "the leo, leo",

    # The Max Zucker - eggs, pastrami, swiss, mustard
    "The Max Zucker": "the max zucker, max zucker",

    # The Avocado Toast
    "The Avocado Toast": "the avocado toast, avocado toast",

    # The Chelsea Club
    "The Chelsea Club": "the chelsea club, chelsea club",

    # The Flatiron - sturgeon version (was "The Flatiron Traditional")
    "The Flatiron": "the flatiron, flatiron, the flatiron traditional, flatiron traditional",

    # The Lexington - egg whites, swiss, spinach
    "The Lexington": "the lexington, lexington",

    # The Latke BEC
    "The Latke BEC": "latke bec, the latke bec",

    # The Truffled Egg (was "Truffled Egg Sandwich")
    "The Truffled Egg": "the truffled egg, truffled egg, truffled egg sandwich",

    # Additional signature items that could benefit from aliases
    "The Delancey": "the delancey, delancey",
    "The Health Nut": "the health nut, health nut",
    "The Reuben": "the reuben, reuben",
    "The BLT": "the blt, blt, b.l.t., b.l.t",
    "The Natural": "the natural, natural",
    "Hot Pastrami Sandwich": "hot pastrami sandwich, hot pastrami, pastrami sandwich",
    "Turkey Club": "turkey club, the turkey club",
    "Nova Scotia Salmon on Bagel": "nova scotia salmon, nova salmon, nova on bagel, lox on bagel",

    # Egg sandwiches
    "The Chelsea": "the chelsea, chelsea",
    "The Columbus": "the columbus, columbus",
    "The Hudson": "the hudson, hudson",
    "The Midtown": "the midtown, midtown",
    "The Wall Street": "the wall street, wall street",
    "The Grand Central": "the grand central, grand central",
    "The Tribeca": "the tribeca, tribeca",
    "Scrambled Eggs on Bagel": "scrambled eggs on bagel, scrambled egg bagel, scrambled eggs bagel",
    "Two Scrambled Eggs on Bagel": "two scrambled eggs on bagel, 2 scrambled eggs on bagel",
    "The Health Nut Egg Sandwich": "the health nut egg sandwich, health nut egg sandwich, health nut egg",

    # Fish sandwiches
    "The Alton Brown": "the alton brown, alton brown",

    # Omelettes - add common aliases
    "The Mulberry Omelette": "the mulberry omelette, mulberry omelette, the mulberry, mulberry",
    "The Truffled Egg Omelette": "the truffled egg omelette, truffled egg omelette",
    "The Lexington Omelette": "the lexington omelette, lexington omelette",
    "The Columbus Omelette": "the columbus omelette, columbus omelette",
    "The Health Nut Omelette": "the health nut omelette, health nut omelette",
    "The Nova Omelette": "the nova omelette, nova omelette",
    "The Delancey Omelette": "the delancey omelette, delancey omelette",
    "The Chipotle Egg Omelette": "the chipotle egg omelette, chipotle egg omelette, chipotle omelette",
}


def upgrade() -> None:
    """Populate aliases for speed menu items."""
    connection = op.get_bind()

    for item_name, aliases in SPEED_MENU_ALIASES.items():
        # Update the aliases column for each item
        # Use COALESCE to append to existing aliases if any
        connection.execute(
            sa.text("""
                UPDATE menu_items
                SET aliases = CASE
                    WHEN aliases IS NULL OR aliases = '' THEN :aliases
                    ELSE aliases || ', ' || :aliases
                END
                WHERE name = :name
            """),
            {"name": item_name, "aliases": aliases}
        )

    # Log how many items were updated
    result = connection.execute(
        sa.text("SELECT COUNT(*) FROM menu_items WHERE aliases IS NOT NULL AND aliases != ''")
    )
    count = result.scalar()
    print(f"Updated aliases for menu items. Total items with aliases: {count}")


def downgrade() -> None:
    """Remove speed menu aliases (set to NULL for items we updated)."""
    connection = op.get_bind()

    item_names = list(SPEED_MENU_ALIASES.keys())

    # Clear aliases for items we updated
    # Note: This is a simplified downgrade - if aliases were appended to existing ones,
    # this will clear all aliases, not just the ones we added
    for item_name in item_names:
        connection.execute(
            sa.text("UPDATE menu_items SET aliases = NULL WHERE name = :name"),
            {"name": item_name}
        )
