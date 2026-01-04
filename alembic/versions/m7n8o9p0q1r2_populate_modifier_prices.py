"""populate_modifier_prices

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-01-03

This migration populates all modifier prices from the hardcoded constants in
pricing.py into the database (AttributeOption.price_modifier).

This allows prices to be managed via the admin UI instead of requiring code changes.

Data migrated:
- Bagel modifiers: proteins, cheeses, spreads, toppings/extras, bagel types (gluten free)
- Coffee modifiers: milk alternatives, flavor syrups
- Iced upcharges were already handled in migration 2b9737e29757
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'm7n8o9p0q1r2'
down_revision: Union[str, Sequence[str], None] = 'l6m7n8o9p0q1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ============================================================================
# Data from pricing.py to migrate
# ============================================================================

# Proteins with their upcharges
PROTEINS = [
    {"slug": "ham", "display_name": "Ham", "price_modifier": 2.00},
    {"slug": "bacon", "display_name": "Bacon", "price_modifier": 2.00},
    {"slug": "egg", "display_name": "Egg", "price_modifier": 1.50},
    {"slug": "nova_scotia_salmon", "display_name": "Nova Scotia Salmon", "price_modifier": 6.00},
    {"slug": "turkey", "display_name": "Turkey", "price_modifier": 2.50},
    {"slug": "pastrami", "display_name": "Pastrami", "price_modifier": 3.00},
    {"slug": "sausage", "display_name": "Sausage", "price_modifier": 2.00},
]

# Cheeses with their upcharges
CHEESES = [
    {"slug": "american", "display_name": "American", "price_modifier": 0.75},
    {"slug": "swiss", "display_name": "Swiss", "price_modifier": 0.75},
    {"slug": "cheddar", "display_name": "Cheddar", "price_modifier": 0.75},
    {"slug": "muenster", "display_name": "Muenster", "price_modifier": 0.75},
    {"slug": "provolone", "display_name": "Provolone", "price_modifier": 0.75},
]

# Spreads with their upcharges (for bagels)
SPREADS = [
    {"slug": "cream_cheese", "display_name": "Cream Cheese", "price_modifier": 1.50},
    {"slug": "butter", "display_name": "Butter", "price_modifier": 0.50},
    {"slug": "scallion_cream_cheese", "display_name": "Scallion Cream Cheese", "price_modifier": 1.75},
    {"slug": "vegetable_cream_cheese", "display_name": "Vegetable Cream Cheese", "price_modifier": 1.75},
]

# Toppings/extras with their upcharges
TOPPINGS = [
    {"slug": "avocado", "display_name": "Avocado", "price_modifier": 2.00},
    {"slug": "tomato", "display_name": "Tomato", "price_modifier": 0.50},
    {"slug": "onion", "display_name": "Onion", "price_modifier": 0.50},
    {"slug": "capers", "display_name": "Capers", "price_modifier": 0.75},
]

# Bagel types with upcharges (gluten free is the main specialty type)
BAGEL_TYPES = [
    {"slug": "plain", "display_name": "Plain", "price_modifier": 0.00, "is_default": True},
    {"slug": "everything", "display_name": "Everything", "price_modifier": 0.00},
    {"slug": "sesame", "display_name": "Sesame", "price_modifier": 0.00},
    {"slug": "poppy", "display_name": "Poppy", "price_modifier": 0.00},
    {"slug": "onion", "display_name": "Onion", "price_modifier": 0.00},
    {"slug": "salt", "display_name": "Salt", "price_modifier": 0.00},
    {"slug": "pumpernickel", "display_name": "Pumpernickel", "price_modifier": 0.00},
    {"slug": "whole_wheat", "display_name": "Whole Wheat", "price_modifier": 0.00},
    {"slug": "cinnamon_raisin", "display_name": "Cinnamon Raisin", "price_modifier": 0.00},
    {"slug": "egg", "display_name": "Egg", "price_modifier": 0.00},
    {"slug": "gluten_free", "display_name": "Gluten Free", "price_modifier": 0.80},
]

# Milk alternatives for coffee
MILKS = [
    {"slug": "whole", "display_name": "Whole Milk", "price_modifier": 0.00, "is_default": True},
    {"slug": "skim", "display_name": "Skim Milk", "price_modifier": 0.00},
    {"slug": "oat", "display_name": "Oat Milk", "price_modifier": 0.50},
    {"slug": "almond", "display_name": "Almond Milk", "price_modifier": 0.50},
    {"slug": "soy", "display_name": "Soy Milk", "price_modifier": 0.50},
]

# Flavor syrups for coffee
SYRUPS = [
    {"slug": "vanilla", "display_name": "Vanilla", "price_modifier": 0.65},
    {"slug": "hazelnut", "display_name": "Hazelnut", "price_modifier": 0.65},
    {"slug": "caramel", "display_name": "Caramel", "price_modifier": 0.65},
    {"slug": "peppermint", "display_name": "Peppermint", "price_modifier": 1.00},
]


def get_or_create_item_type(session, slug: str, display_name: str, is_configurable: bool = True) -> int:
    """Get or create an item type and return its ID."""
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = :slug"),
        {"slug": slug}
    ).fetchone()

    if result:
        return result[0]

    session.execute(
        sa.text("""
            INSERT INTO item_types (slug, display_name, is_configurable, skip_config)
            VALUES (:slug, :display_name, :is_configurable, FALSE)
        """),
        {"slug": slug, "display_name": display_name, "is_configurable": is_configurable}
    )

    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = :slug"),
        {"slug": slug}
    ).fetchone()

    return result[0]


def get_or_create_attribute_definition(
    session,
    item_type_id: int,
    slug: str,
    display_name: str,
    input_type: str = "single_select",
    is_required: bool = False,
    allow_none: bool = True,
    display_order: int = 10,
) -> int:
    """Get or create an attribute definition and return its ID."""
    result = session.execute(
        sa.text("""
            SELECT id FROM attribute_definitions
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": slug}
    ).fetchone()

    if result:
        return result[0]

    session.execute(
        sa.text("""
            INSERT INTO attribute_definitions
            (item_type_id, slug, display_name, input_type, is_required, allow_none, display_order)
            VALUES (:item_type_id, :slug, :display_name, :input_type, :is_required, :allow_none, :display_order)
        """),
        {
            "item_type_id": item_type_id,
            "slug": slug,
            "display_name": display_name,
            "input_type": input_type,
            "is_required": is_required,
            "allow_none": allow_none,
            "display_order": display_order,
        }
    )

    result = session.execute(
        sa.text("""
            SELECT id FROM attribute_definitions
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": slug}
    ).fetchone()

    return result[0]


def create_or_update_option(
    session,
    attr_def_id: int,
    slug: str,
    display_name: str,
    price_modifier: float,
    is_default: bool = False,
    display_order: int = 0,
) -> None:
    """Create or update an attribute option."""
    existing = session.execute(
        sa.text("""
            SELECT id FROM attribute_options
            WHERE attribute_definition_id = :attr_def_id AND slug = :slug
        """),
        {"attr_def_id": attr_def_id, "slug": slug}
    ).fetchone()

    if existing:
        # Update existing option
        session.execute(
            sa.text("""
                UPDATE attribute_options
                SET price_modifier = :price_modifier,
                    display_name = :display_name,
                    is_default = :is_default,
                    display_order = :display_order
                WHERE id = :id
            """),
            {
                "id": existing[0],
                "price_modifier": price_modifier,
                "display_name": display_name,
                "is_default": is_default,
                "display_order": display_order,
            }
        )
    else:
        # Insert new option (use explicit TRUE/FALSE for PostgreSQL compatibility)
        session.execute(
            sa.text("""
                INSERT INTO attribute_options
                (attribute_definition_id, slug, display_name, price_modifier, iced_price_modifier, is_default, display_order, is_available)
                VALUES (:attr_def_id, :slug, :display_name, :price_modifier, 0.0, :is_default, :display_order, TRUE)
            """),
            {
                "attr_def_id": attr_def_id,
                "slug": slug,
                "display_name": display_name,
                "price_modifier": price_modifier,
                "is_default": is_default,
                "display_order": display_order,
            }
        )


def upgrade() -> None:
    """Populate modifier prices from hardcoded constants."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # ========================================================================
    # 1. Create bagel item type and its attributes
    # ========================================================================
    bagel_type_id = get_or_create_item_type(session, "bagel", "Bagel", is_configurable=True)

    # Bagel type attribute (plain, everything, gluten free, etc.)
    bagel_type_attr_id = get_or_create_attribute_definition(
        session, bagel_type_id, "bagel_type", "Bagel Type",
        input_type="single_select", is_required=True, allow_none=False, display_order=1
    )
    for i, opt in enumerate(BAGEL_TYPES):
        create_or_update_option(
            session, bagel_type_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Spread attribute
    spread_attr_id = get_or_create_attribute_definition(
        session, bagel_type_id, "spread", "Spread",
        input_type="single_select", is_required=False, allow_none=True, display_order=2
    )
    for i, opt in enumerate(SPREADS):
        create_or_update_option(
            session, spread_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Protein attribute
    protein_attr_id = get_or_create_attribute_definition(
        session, bagel_type_id, "protein", "Protein",
        input_type="multi_select", is_required=False, allow_none=True, display_order=3
    )
    for i, opt in enumerate(PROTEINS):
        create_or_update_option(
            session, protein_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Cheese attribute
    cheese_attr_id = get_or_create_attribute_definition(
        session, bagel_type_id, "cheese", "Cheese",
        input_type="multi_select", is_required=False, allow_none=True, display_order=4
    )
    for i, opt in enumerate(CHEESES):
        create_or_update_option(
            session, cheese_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Topping/extras attribute
    topping_attr_id = get_or_create_attribute_definition(
        session, bagel_type_id, "topping", "Topping",
        input_type="multi_select", is_required=False, allow_none=True, display_order=5
    )
    for i, opt in enumerate(TOPPINGS):
        create_or_update_option(
            session, topping_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # ========================================================================
    # 2. Add milk and syrup attributes to sized_beverage
    # ========================================================================
    sized_bev_type_id = get_or_create_item_type(session, "sized_beverage", "Sized Beverage", is_configurable=True)

    # Milk attribute
    milk_attr_id = get_or_create_attribute_definition(
        session, sized_bev_type_id, "milk", "Milk",
        input_type="single_select", is_required=False, allow_none=True, display_order=2
    )
    for i, opt in enumerate(MILKS):
        create_or_update_option(
            session, milk_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Syrup attribute
    syrup_attr_id = get_or_create_attribute_definition(
        session, sized_bev_type_id, "syrup", "Flavor Syrup",
        input_type="multi_select", is_required=False, allow_none=True, display_order=3
    )
    for i, opt in enumerate(SYRUPS):
        create_or_update_option(
            session, syrup_attr_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # ========================================================================
    # 3. Also add these modifiers to sandwich item type (if it exists)
    #    so they can be shared across sandwich and bagel items
    # ========================================================================
    sandwich_type_id = get_or_create_item_type(session, "sandwich", "Sandwich", is_configurable=True)

    # Protein for sandwiches
    sandwich_protein_id = get_or_create_attribute_definition(
        session, sandwich_type_id, "protein", "Protein",
        input_type="multi_select", is_required=False, allow_none=True, display_order=1
    )
    for i, opt in enumerate(PROTEINS):
        create_or_update_option(
            session, sandwich_protein_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Cheese for sandwiches
    sandwich_cheese_id = get_or_create_attribute_definition(
        session, sandwich_type_id, "cheese", "Cheese",
        input_type="multi_select", is_required=False, allow_none=True, display_order=2
    )
    for i, opt in enumerate(CHEESES):
        create_or_update_option(
            session, sandwich_cheese_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    # Topping for sandwiches
    sandwich_topping_id = get_or_create_attribute_definition(
        session, sandwich_type_id, "topping", "Topping",
        input_type="multi_select", is_required=False, allow_none=True, display_order=3
    )
    for i, opt in enumerate(TOPPINGS):
        create_or_update_option(
            session, sandwich_topping_id, opt["slug"], opt["display_name"],
            opt["price_modifier"], opt.get("is_default", False), display_order=i + 1
        )

    session.commit()


def downgrade() -> None:
    """Remove the populated modifier options.

    Note: This only removes options created by this migration.
    It does not remove the item types or attribute definitions
    as they may be used by other data.
    """
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get bagel item type
    bagel_result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()

    if bagel_result:
        bagel_type_id = bagel_result[0]

        # Get attribute definitions for bagel
        for attr_slug in ["bagel_type", "spread", "protein", "cheese", "topping"]:
            attr_result = session.execute(
                sa.text("""
                    SELECT id FROM attribute_definitions
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": bagel_type_id, "slug": attr_slug}
            ).fetchone()

            if attr_result:
                # Delete all options for this attribute
                session.execute(
                    sa.text("DELETE FROM attribute_options WHERE attribute_definition_id = :attr_def_id"),
                    {"attr_def_id": attr_result[0]}
                )

    # Get sized_beverage item type
    bev_result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
    ).fetchone()

    if bev_result:
        bev_type_id = bev_result[0]

        # Get milk and syrup attribute definitions
        for attr_slug in ["milk", "syrup"]:
            attr_result = session.execute(
                sa.text("""
                    SELECT id FROM attribute_definitions
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": bev_type_id, "slug": attr_slug}
            ).fetchone()

            if attr_result:
                session.execute(
                    sa.text("DELETE FROM attribute_options WHERE attribute_definition_id = :attr_def_id"),
                    {"attr_def_id": attr_result[0]}
                )

    # Get sandwich item type
    sandwich_result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'sandwich'")
    ).fetchone()

    if sandwich_result:
        sandwich_type_id = sandwich_result[0]

        for attr_slug in ["protein", "cheese", "topping"]:
            attr_result = session.execute(
                sa.text("""
                    SELECT id FROM attribute_definitions
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": sandwich_type_id, "slug": attr_slug}
            ).fetchone()

            if attr_result:
                session.execute(
                    sa.text("DELETE FROM attribute_options WHERE attribute_definition_id = :attr_def_id"),
                    {"attr_def_id": attr_result[0]}
                )

    session.commit()
