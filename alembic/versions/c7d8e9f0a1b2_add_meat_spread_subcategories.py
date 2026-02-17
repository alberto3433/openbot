"""Add meat and spread subcategories

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'b6c7d8e9f0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Meat subcategory groupings ---

FISH_SLUGS = [
    'nova_scotia_salmon', 'belly_lox', 'kippered_salmon', 'scottish_salmon',
    'wild_coho_salmon', 'wild_pacific_salmon', 'baked_salmon', 'pastrami_salmon',
    'everything_seeded_salmon', 'gravlax', 'sable', 'lake_sturgeon',
    'smoked_trout', 'herring', 'whitefish_salad', 'baked_salmon_salad',
    'tuna_salad',
]

POULTRY_SLUGS = [
    'turkey', 'smoked_turkey', 'turkey_bacon', 'chicken_salad',
    'grilled_chicken', 'lemon_chicken_salad', 'cranberry_pecan_chicken_salad',
    'chicken_sausage',
]

PORK_SLUGS = [
    'bacon', 'applewood_smoked_bacon', 'ham', 'black_forest_ham',
    'pepperoni', 'sausage', 'sausage_patty', 'espositos_sausage',
]

BEEF_SLUGS = [
    'pastrami', 'corned_beef', 'roast_beef', 'sliced_steak',
]


# --- Spread subcategory groupings ---

CREAM_CHEESE_SLUGS = [
    'plain_cream_cheese', 'scallion_cream_cheese', 'vegetable_cream_cheese',
    'lox_cream_cheese', 'nova_cream_cheese', 'nova_scotia_cream_cheese',
    'olive_cream_cheese', 'olive_pimento_cream_cheese', 'blueberry_cream_cheese',
    'strawberry_cream_cheese', 'honey_walnut_cream_cheese', 'walnut_raisin_cc',
    'jalapeno_cc', 'jalapeno_honey_cream_cheese', 'chipotle_cream_cheese',
    'sun_dried_tomato_cream_cheese', 'truffle_cream_cheese',
    'b&w_truffle_cream_cheese', 'kalamata_olive_cream_cheese',
    'lemon_blueberry_cream_cheese', 'maple_raisin_walnut_cream_cheese',
    'roasted_scallion_shallot_caper_&_garlic_cream_cheese',
    'tofu_cream_cheese', 'tofu_nova_cream_cheese',
    'tofu_scallion_cream_cheese', 'tofu_vegetable_cream_cheese',
]

BUTTER_SLUGS = [
    'butter', 'cinnamon_sugar_butter',
]

NUT_SPREAD_SLUGS = [
    'peanut_butter', 'nutella',
]

JELLY_SLUGS = [
    'grape_jelly', 'strawberry_jelly',
]

OTHER_SPREAD_SLUGS = [
    'hummus', 'avocado_spread', 'scallion_tofu',
]


def _update_subcategory(conn: sa.engine.Connection, slugs: list[str], subcategory: str) -> None:
    """Set subcategory for a list of ingredient slugs."""
    if not slugs:
        return
    placeholders = ', '.join(f':s{i}' for i in range(len(slugs)))
    params = {f's{i}': slug for i, slug in enumerate(slugs)}
    params['subcategory'] = subcategory
    conn.execute(
        sa.text(
            f"UPDATE ingredients SET subcategory = :subcategory "
            f"WHERE slug IN ({placeholders})"
        ),
        params,
    )


def upgrade() -> None:
    conn = op.get_bind()

    # Meat subcategories
    _update_subcategory(conn, FISH_SLUGS, 'fish')
    _update_subcategory(conn, POULTRY_SLUGS, 'poultry')
    _update_subcategory(conn, PORK_SLUGS, 'pork')
    _update_subcategory(conn, BEEF_SLUGS, 'beef')

    # Spread subcategories
    _update_subcategory(conn, CREAM_CHEESE_SLUGS, 'cream_cheese')
    _update_subcategory(conn, BUTTER_SLUGS, 'butter')
    _update_subcategory(conn, NUT_SPREAD_SLUGS, 'nut_spread')
    _update_subcategory(conn, JELLY_SLUGS, 'jelly')
    _update_subcategory(conn, OTHER_SPREAD_SLUGS, 'other')


def downgrade() -> None:
    conn = op.get_bind()
    # Clear meat subcategories
    conn.execute(sa.text(
        "UPDATE ingredients SET subcategory = NULL WHERE category = 'meat'"
    ))
    # Clear spread subcategories
    conn.execute(sa.text(
        "UPDATE ingredients SET subcategory = NULL WHERE category = 'spread'"
    ))
