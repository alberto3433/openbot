"""populate_dietary_attributes

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-01-02

Populates dietary and allergen attribute values for existing ingredients
based on their ingredient types and names.

Dietary logic:
- is_vegan/is_vegetarian: True if ingredient is plant-based
- is_gluten_free: False for wheat-based items (bagels, bread)
- is_dairy_free: False for cream cheese, butter, etc.
- is_kosher: True by default for a kosher establishment

Allergen logic:
- contains_eggs: True for eggs, mayo, egg-based items
- contains_fish: True for salmon, lox, whitefish, tuna
- contains_sesame: True for sesame bagels, hummus, everything seeds
- contains_nuts: True for walnut cream cheeses, peanut butter, nutella
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'l6m7n8o9p0q1'
down_revision: Union[str, Sequence[str], None] = 'k5l6m7n8o9p0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Define dietary attributes for ingredients by pattern matching
# Format: (name_pattern, attributes_dict) - patterns are case-insensitive

# Default: All items start with these values
DEFAULT_ATTRS = {
    'is_vegan': False,
    'is_vegetarian': False,
    'is_gluten_free': True,  # Most items are GF except bread/bagels
    'is_dairy_free': True,
    'is_kosher': True,  # Zucker's is kosher
    'contains_eggs': False,
    'contains_fish': False,
    'contains_sesame': False,
    'contains_nuts': False,
}

# Items that are vegan (all plant-based)
VEGAN_ITEMS = [
    # Vegetables/Toppings
    'tomato', 'onion', 'red onion', 'capers', 'lettuce', 'cucumber',
    'pickles', 'sauerkraut', 'sprouts', 'avocado', 'avocado spread',
    # Condiments
    'mustard', 'hot sauce', 'olive oil',
    # Spreads
    'hummus', 'peanut butter',
    # Tofu-based (except nova)
    'tofu cream cheese', 'tofu scallion cream cheese', 'tofu vegetable cream cheese',
]

# Items that are vegetarian but not vegan
VEGETARIAN_ONLY_ITEMS = [
    # Dairy products
    'plain cream cheese', 'scallion cream cheese', 'vegetable cream cheese',
    'sun-dried tomato cream cheese', 'strawberry cream cheese', 'blueberry cream cheese',
    'kalamata olive cream cheese', 'maple raisin walnut cream cheese',
    'jalapeño cream cheese', 'truffle cream cheese', 'honey walnut cream cheese',
    'butter',
    # Eggs
    'egg', 'egg white', 'scrambled eggs', 'egg salad',
    # Contains eggs
    'mayo', 'russian dressing',
    # Contains dairy
    'nutella',
]

# Meat items (not vegetarian, not vegan)
MEAT_ITEMS = [
    'bacon', 'turkey', 'pastrami', 'corned beef', 'ham',
]

# Fish items (not vegetarian, not vegan)
FISH_ITEMS = [
    'nova scotia salmon', 'baked salmon', 'whitefish salad', 'tuna salad',
    'nova scotia cream cheese', 'lox spread', 'tofu nova cream cheese',
]

# Items containing gluten (wheat-based)
GLUTEN_ITEMS = [
    'plain bagel', 'everything bagel', 'sesame bagel', 'poppy bagel',
    'onion bagel', 'pumpernickel bagel', 'salt bagel', 'cinnamon raisin bagel',
    'garlic bagel', 'whole wheat bagel', 'everything wheat bagel', 'bialy',
    'wheat flatz', 'wheat everything flatz',
]

# Items that are gluten-free (explicit)
GLUTEN_FREE_ITEMS = [
    'gluten free bagel', 'gluten free everything bagel',
]

# Items containing dairy (use exact match for 'butter' to avoid matching 'peanut butter')
DAIRY_ITEMS = [
    'plain cream cheese', 'scallion cream cheese', 'vegetable cream cheese',
    'sun-dried tomato cream cheese', 'strawberry cream cheese', 'blueberry cream cheese',
    'kalamata olive cream cheese', 'maple raisin walnut cream cheese',
    'jalapeño cream cheese', 'nova scotia cream cheese', 'truffle cream cheese',
    'lox spread', 'honey walnut cream cheese', 'nutella',
]

# Dairy items that require exact match (to avoid false positives like "peanut butter")
DAIRY_EXACT_MATCH = ['butter']

# Items containing eggs
EGG_ITEMS = [
    'egg', 'egg white', 'scrambled eggs', 'egg salad', 'mayo', 'russian dressing',
    'tuna salad',  # Typically made with mayo
]

# Items containing fish
FISH_CONTAINING_ITEMS = [
    'nova scotia salmon', 'baked salmon', 'whitefish salad', 'tuna salad',
    'nova scotia cream cheese', 'lox spread', 'tofu nova cream cheese',
]

# Items containing sesame
SESAME_ITEMS = [
    'sesame bagel', 'everything bagel', 'everything wheat bagel',
    'wheat everything flatz', 'everything seeds', 'hummus',
    'gluten free everything bagel',  # Everything bagels have sesame
]

# Items containing nuts
NUT_ITEMS = [
    'maple raisin walnut cream cheese', 'honey walnut cream cheese',
    'peanut butter', 'nutella',
]


def get_attributes_for_ingredient(name: str) -> dict:
    """Determine dietary attributes for an ingredient based on its name."""
    name_lower = name.lower()

    # Start with defaults
    attrs = DEFAULT_ATTRS.copy()

    # Check vegan items (also vegetarian)
    for pattern in VEGAN_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_vegan'] = True
            attrs['is_vegetarian'] = True
            break

    # Check vegetarian-only items
    for pattern in VEGETARIAN_ONLY_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_vegetarian'] = True
            break

    # Check meat items (not vegetarian)
    for pattern in MEAT_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_vegetarian'] = False
            attrs['is_vegan'] = False
            break

    # Check fish items (not vegetarian for pescatarian distinction)
    for pattern in FISH_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_vegetarian'] = False
            attrs['is_vegan'] = False
            attrs['contains_fish'] = True
            break

    # Check gluten items
    for pattern in GLUTEN_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_gluten_free'] = False
            # Standard bagels are vegan and vegetarian (flour, water, yeast, salt)
            attrs['is_vegan'] = True
            attrs['is_vegetarian'] = True
            attrs['is_dairy_free'] = True
            break

    # Check explicit gluten-free items
    for pattern in GLUTEN_FREE_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_gluten_free'] = True
            attrs['is_vegan'] = True
            attrs['is_vegetarian'] = True
            attrs['is_dairy_free'] = True
            break

    # Check dairy items
    for pattern in DAIRY_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['is_dairy_free'] = False
            break

    # Check dairy items that require exact match
    for pattern in DAIRY_EXACT_MATCH:
        if name_lower == pattern:
            attrs['is_dairy_free'] = False
            break

    # Check egg items
    for pattern in EGG_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['contains_eggs'] = True
            break

    # Check fish-containing items
    for pattern in FISH_CONTAINING_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['contains_fish'] = True
            break

    # Check sesame items
    for pattern in SESAME_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['contains_sesame'] = True
            break

    # Check nut items
    for pattern in NUT_ITEMS:
        if pattern in name_lower or name_lower == pattern:
            attrs['contains_nuts'] = True
            break

    return attrs


def upgrade() -> None:
    """Populate dietary attributes for all ingredients."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get all ingredients
    result = session.execute(sa.text("SELECT id, name FROM ingredients"))
    ingredients = result.fetchall()

    update_count = 0
    for ingredient_id, name in ingredients:
        attrs = get_attributes_for_ingredient(name)

        # Update the ingredient
        session.execute(
            sa.text("""
                UPDATE ingredients SET
                    is_vegan = :is_vegan,
                    is_vegetarian = :is_vegetarian,
                    is_gluten_free = :is_gluten_free,
                    is_dairy_free = :is_dairy_free,
                    is_kosher = :is_kosher,
                    contains_eggs = :contains_eggs,
                    contains_fish = :contains_fish,
                    contains_sesame = :contains_sesame,
                    contains_nuts = :contains_nuts
                WHERE id = :id
            """),
            {
                'id': ingredient_id,
                **attrs
            }
        )
        update_count += 1

    session.commit()
    print(f"Updated dietary attributes for {update_count} ingredients")


def downgrade() -> None:
    """Reset all dietary attributes to defaults."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Reset all to False (the default)
    session.execute(
        sa.text("""
            UPDATE ingredients SET
                is_vegan = false,
                is_vegetarian = false,
                is_gluten_free = false,
                is_dairy_free = false,
                is_kosher = false,
                contains_eggs = false,
                contains_fish = false,
                contains_sesame = false,
                contains_nuts = false
        """)
    )

    session.commit()
