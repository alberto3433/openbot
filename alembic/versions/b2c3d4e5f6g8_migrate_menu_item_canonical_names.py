"""Migrate MENU_ITEM_CANONICAL_NAMES as aliases to menu_items.

Revision ID: b2c3d4e5f6g8
Revises: a1b2c3d4e5f7
Create Date: 2025-01-04 23:00:00.000000

This migration adds short forms from MENU_ITEM_CANONICAL_NAMES as aliases to their
corresponding menu items. This enables eliminating the hardcoded KNOWN_MENU_ITEMS
constant in favor of database lookups.

The aliases are merged with any existing aliases (avoiding duplicates).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g8"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mappings from MENU_ITEM_CANONICAL_NAMES that need to be added as aliases
# Format: {canonical_name: [list of aliases to add]}
# These are grouped by canonical name to enable efficient merging
ALIAS_ADDITIONS = {
    # Spread sandwiches
    "Plain Cream Cheese Sandwich": ["plain cream cheese"],
    "Scallion Cream Cheese Sandwich": ["scallion cream cheese"],
    "Vegetable Cream Cheese Sandwich": ["veggie cream cheese", "vegetable cream cheese"],
    "Sun-Dried Tomato Cream Cheese Sandwich": ["sun dried tomato cream cheese"],
    "Strawberry Cream Cheese Sandwich": ["strawberry cream cheese"],
    "Blueberry Cream Cheese Sandwich": ["blueberry cream cheese"],
    "Kalamata Olive Cream Cheese Sandwich": ["olive cream cheese"],
    "Maple Raisin Walnut Cream Cheese Sandwich": ["maple raisin walnut", "maple walnut cream cheese"],
    "Jalapeno Cream Cheese Sandwich": ["jalapeno cream cheese", "jalapeño cream cheese"],
    "Nova Scotia Cream Cheese Sandwich": ["nova cream cheese", "lox spread sandwich"],
    "Truffle Cream Cheese Sandwich": ["truffle cream cheese"],
    "Butter Sandwich": ["bagel with butter"],
    "Peanut Butter Sandwich": ["peanut butter bagel"],
    "Nutella Sandwich": ["nutella bagel"],
    "Hummus Sandwich": ["hummus bagel"],
    "Avocado Spread Sandwich": ["avocado spread"],
    "Tofu Plain Sandwich": ["tofu plain", "plain tofu"],
    "Tofu Scallion Sandwich": ["tofu scallion", "scallion tofu"],
    "Tofu Vegetable Sandwich": ["tofu veggie", "tofu vegetable", "veggie tofu"],
    "Tofu Nova Sandwich": ["tofu nova", "nova tofu"],
    # Smoked fish sandwiches
    "Belly Lox Sandwich": ["belly lox", "belly lox sandwich", "belly lox on bagel", "lox"],
    "Gravlax Sandwich": ["gravlax", "gravlax sandwich", "gravlax on bagel"],
    "Nova Scotia Salmon Sandwich": ["nova sandwich", "nova on bagel", "nova lox", "nova lox sandwich", "lox sandwich"],
    # Salad sandwiches
    "Tuna Salad Sandwich": ["tuna salad", "tuna sandwich"],
    "Whitefish Salad Sandwich": ["whitefish salad", "whitefish sandwich"],
    "Baked Salmon Salad Sandwich": ["baked salmon salad", "salmon salad sandwich"],
    "Egg Salad Sandwich": ["egg salad"],
    "Chicken Salad Sandwich": ["chicken salad"],
    "Cranberry Pecan Chicken Salad Sandwich": ["cranberry pecan chicken salad", "cranberry chicken salad"],
    "Lemon Chicken Salad Sandwich": ["lemon chicken salad"],
    # Signature sandwiches
    "The BLT": ["blt", "the blt"],
    "The Chelsea Club": ["chelsea club", "the chelsea club"],
    "The Natural": ["natural", "the natural"],
    # Tropicana
    "Tropicana Orange Juice 46 oz": ["tropicana orange juice 46 oz", "tropicana 46 oz"],
    "Tropicana Orange Juice No Pulp": ["tropicana no pulp", "tropicana"],
    "Fresh Squeezed Orange Juice": ["fresh squeezed orange juice"],
    # Coca Cola products
    "Coca-Cola": ["coke", "coca cola", "coca-cola"],
    "Diet Coke": ["diet coke", "diet coca cola"],
    "Coke Zero": ["coke zero", "coca cola zero"],
    # Dr. Brown's
    "Dr. Brown's Cream Soda": ["dr brown's cream soda", "dr browns cream soda", "dr brown's", "dr browns", "dr. brown's", "dr. browns"],
    "Dr. Brown's Black Cherry": ["dr brown's black cherry", "dr browns black cherry"],
    "Dr. Brown's Cel-Ray": ["dr brown's cel-ray", "dr browns cel-ray", "cel-ray"],
    # Milk
    "Chocolate Milk": ["chocolate milk", "chocolate milks"],
    # Omelettes
    "Spinach & Feta Omelette": ["spinach and feta omelette", "spinach feta omelette", "spinach and feta omelet", "spinach feta omelet", "spinach & feta omelet"],
    "The Mulberry Omelette": ["mulberry", "the mulberry", "mulberry omelette", "the mulberry omelette"],
    "The Nova Omelette": ["nova omelette", "the nova omelette"],
    "Bacon and Cheddar Omelette": ["bacon and cheddar omelette", "bacon cheddar omelette"],
    # Grilled
    "Grilled Cheese": ["grilled cheese", "grilled cheese sandwich"],
    # Sides
    "Bacon": ["side of bacon", "bacon"],
    "Side of Sausage": ["side of sausage", "sausage"],
    "Turkey Bacon": ["turkey bacon", "side of turkey bacon"],
    "Latkes": ["latkes", "potato latkes"],
    "Bagel Chips": ["bagel chips"],
    "Fruit Cup": ["fruit cup"],
    "Fruit Salad": ["fruit salad"],
    "Cole Slaw": ["cole slaw", "coleslaw"],
    "Potato Salad": ["potato salad"],
    "Macaroni Salad": ["macaroni salad"],
    # Breakfast
    "Oatmeal": ["oatmeal"],
    "Organic Steel-Cut Oatmeal": ["steel cut oatmeal", "organic steel-cut oatmeal"],
    "Yogurt Parfait": ["yogurt parfait", "yogurt"],
    "Low Fat Yogurt Granola Parfait": ["low fat yogurt granola parfait"],
}


def upgrade() -> None:
    """Add aliases from MENU_ITEM_CANONICAL_NAMES to menu items."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        for canonical_name, new_aliases in ALIAS_ADDITIONS.items():
            # Get current item and its aliases
            result = session.execute(
                sa.text("SELECT id, aliases FROM menu_items WHERE LOWER(name) = LOWER(:name)"),
                {"name": canonical_name}
            )
            row = result.fetchone()

            if not row:
                print(f"  WARNING: Menu item not found: {canonical_name}")
                continue

            item_id, existing_aliases = row

            # Parse existing aliases into a set (for deduplication)
            existing_set = set()
            if existing_aliases:
                existing_set = {a.strip().lower() for a in existing_aliases.split(",")}

            # Add new aliases (avoiding duplicates)
            new_aliases_lower = {a.lower() for a in new_aliases}
            combined_aliases = existing_set | new_aliases_lower

            # Sort and join
            combined_csv = ", ".join(sorted(combined_aliases))

            # Update if changed
            if combined_csv != existing_aliases:
                session.execute(
                    sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
                    {"aliases": combined_csv, "id": item_id}
                )
                added = new_aliases_lower - existing_set
                if added:
                    print(f"  {canonical_name}: added {added}")

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """This migration cannot be easily reversed as it merges aliases."""
    pass
