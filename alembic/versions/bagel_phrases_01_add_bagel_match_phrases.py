"""Add bagel equivalents to required_match_phrases

For items that have '<something> sandwich' entries but no corresponding
'<something> bagel' entries, this migration adds the bagel versions.

Revision ID: bagel_phrases_01
Revises: plain_cc_01
Create Date: 2025-02-04

"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'bagel_phrases_01'
down_revision = 'plain_cc_01'
branch_labels = None
depends_on = None


def upgrade():
    # Updates: append bagel phrases to existing required_match_phrases
    updates = [
        (395, 'scallion cream cheese sandwich, scallion cream cheese bagel'),
        (396, 'vegetable cream cheese sandwich, vegetable cream cheese bagel'),
        (397, 'tomato cream cheese sandwich, tomato cream cheese bagel'),
        (398, 'strawberry cream cheese sandwich, strawberry cream cheese bagel'),
        (399, 'blueberry cream cheese sandwich,blue berry cream cheese sandwich, blueberry cream cheese bagel, blue berry cream cheese bagel'),
        (401, 'walnut cream cheese sandwich, walnut cream cheese bagel'),
        (402, 'jalapeno cream cheese sandwich, jalapeno cream cheese bagel'),
        (403, 'nova scotia cream cheese sandwich,lox cream cheese sandwich, nova scotia cream cheese bagel, lox cream cheese bagel'),
        (404, 'truffle cream cheese sandwich, truffle cream cheese bagel'),
        (405, 'butter sandwich, butter bagel'),
        (406, 'peanut butter sandwich, peanut butter bagel'),
        (407, 'nutella sandwich, nutella bagel'),
        (408, 'hummus sandwich, hummus bagel'),
        (409, 'avocado sandwich,avocado spread sandwich, avocado bagel, avocado spread bagel'),
        (410, 'tofu sandwich,tofu plain sandwich, tofu bagel, tofu plain bagel'),
        (411, 'tofu scallion sandwich, tofu scallion bagel'),
        (412, 'tofu vegetable sandwich,tofu veggie sandwich,vegetable tofu sandwich,veggie tofu sandwich, tofu vegetable bagel, tofu veggie bagel, vegetable tofu bagel, veggie tofu bagel'),
        (413, 'tofu nova sandwich,nova tofu sandwich, tofu nova bagel, nova tofu bagel'),
        (414, 'tuna salad sandwich,tuna sandwich, tuna salad bagel, tuna bagel'),
        (415, 'whitefish salad sandwich,whitefish sandwich, whitefish salad bagel, whitefish bagel'),
        (416, 'salmon sandwich,salmon salad sandwich, salmon bagel, salmon salad bagel'),
        (417, 'egg salad sandwich, egg salad bagel'),
        (418, 'chicken salad sandwich, chicken salad bagel'),
        (420, 'lemon chicken salad sandwich,lemon chicken sandwich, lemon chicken salad bagel, lemon chicken bagel'),
        (461, 'cured salmon sandwich,gravlax sandwich, cured salmon bagel, gravlax bagel'),
        (462, 'sable sandwich,sable fish sandwich, sable bagel, sable fish bagel'),
        (532, 'corned beef sandwich, corned beef bagel'),
        (536, 'smoked turkey sandwich, smoked turkey bagel'),
        (537, 'ham sandwich, ham bagel'),
        (540, 'belly lox sandwich, belly lox bagel'),
        (542, 'pastrami salmon sandwich, pastrami salmon bagel'),
        (543, 'scottish salmon sandwich, scottish salmon bagel'),
        (547, 'trout sandwich, trout bagel'),
        (9846, 'american cheese sandwich, american cheese bagel'),
        (9847, 'Cheddar Sandwich,Cheddar Cheese Sandwich, cheddar bagel, cheddar cheese bagel'),
        (9848, 'Swiss Cheese Sandwich,Swiss Sandwich, swiss cheese bagel, swiss bagel'),
        (9849, 'Pepper Jack Sandwich,Pepper Jack Cheese Sandwich, pepper jack bagel, pepper jack cheese bagel'),
        (9850, 'Mozzarella Sandwich,Mozzarella Cheese Sandwich, mozzarella bagel, mozzarella cheese bagel'),
        (9851, 'havarti sandwich,havarti cheese sandwich, havarti bagel, havarti cheese bagel'),
        (9852, 'Provolone Sandwich,Provolone Cheese Sandwich, provolone bagel, provolone cheese bagel'),
        (9853, 'Muenster Sandwich,Muenster Cheese Sandwich, muenster bagel, muenster cheese bagel'),
        (9854, 'chipotle cream cheese sandwich, chipotle cream cheese bagel'),
        (9855, 'Jalapeno Honey Cream Cheese Sandwich,jalapeño Honey Cream Cheese Sandwich, jalapeno honey cream cheese bagel, jalapeño honey cream cheese bagel'),
        (9856, 'lemon blueberry cream cheese sandwich, lemon blueberry cream cheese bagel'),
        (9857, 'Truffle Cream Cheese Sandwich, truffle cream cheese bagel'),
        (9859, 'Feta Cream Cheese Sandwich, feta cream cheese bagel'),
        (9860, 'Nova cream cheese sandwich, nova cream cheese bagel'),
        (9932, 'grape jelly sandwich, grape jelly bagel'),
        (9933, 'strawberry jelly sandwich, strawberry jelly bagel'),
        (9934, 'PBJ sandwich,pb&j sandwich,pb and j sandwich,peanut butter & jelly sandwich,peanut butter and jelly sandwich, pbj bagel, pb&j bagel, pb and j bagel, peanut butter & jelly bagel, peanut butter and jelly bagel'),
        (9936, 'tofu spread sandwich,tofu sandwich, tofu spread bagel, tofu bagel'),
        (9937, 'nova tofu spread sandwich,nova tofu sandwich, nova tofu spread bagel, nova tofu bagel'),
        (9938, 'scallion tofu spread sandwich,scallion tofu sandwich, scallion tofu spread bagel, scallion tofu bagel'),
        (9939, 'vegetable tofu spread sandwich,vegetable tofu sandwich,veggie tofu spread sandwich,veggie tofu sandwich, vegetable tofu spread bagel, vegetable tofu bagel, veggie tofu spread bagel, veggie tofu bagel'),
    ]

    conn = op.get_bind()
    for item_id, new_phrases in updates:
        conn.execute(
            text("UPDATE menu_items SET required_match_phrases = :phrases WHERE id = :id"),
            {"phrases": new_phrases, "id": item_id}
        )


def downgrade():
    # Restore original values (sandwich phrases only, no bagel)
    original = [
        (395, 'scallion cream cheese sandwich'),
        (396, 'vegetable cream cheese sandwich'),
        (397, 'tomato cream cheese sandwich'),
        (398, 'strawberry cream cheese sandwich'),
        (399, 'blueberry cream cheese sandwich,blue berry cream cheese sandwich'),
        (401, 'walnut cream cheese sandwich'),
        (402, 'jalapeno cream cheese sandwich'),
        (403, 'nova scotia cream cheese sandwich,lox cream cheese sandwich'),
        (404, 'truffle cream cheese sandwich'),
        (405, 'butter sandwich'),
        (406, 'peanut butter sandwich'),
        (407, 'nutella sandwich'),
        (408, 'hummus sandwich'),
        (409, 'avocado sandwich,avocado spread sandwich'),
        (410, 'tofu sandwich,tofu plain sandwich'),
        (411, 'tofu scallion sandwich'),
        (412, 'tofu vegetable sandwich,tofu veggie sandwich,vegetable tofu sandwich,veggie tofu sandwich'),
        (413, 'tofu nova sandwich,nova tofu sandwich'),
        (414, 'tuna salad sandwich,tuna sandwich'),
        (415, 'whitefish salad sandwich,whitefish sandwich'),
        (416, 'salmon sandwich,salmon salad sandwich'),
        (417, 'egg salad sandwich'),
        (418, 'chicken salad sandwich'),
        (420, 'lemon chicken salad sandwich,lemon chicken sandwich'),
        (461, 'cured salmon sandwich,gravlax sandwich'),
        (462, 'sable sandwich,sable fish sandwich'),
        (532, 'corned beef sandwich'),
        (536, 'smoked turkey sandwich'),
        (537, 'ham sandwich'),
        (540, 'belly lox sandwich'),
        (542, 'pastrami salmon sandwich'),
        (543, 'scottish salmon sandwich'),
        (547, 'trout sandwich'),
        (9846, 'american cheese sandwich'),
        (9847, 'Cheddar Sandwich,Cheddar Cheese Sandwich'),
        (9848, 'Swiss Cheese Sandwich,Swiss Sandwich'),
        (9849, 'Pepper Jack Sandwich,Pepper Jack Cheese Sandwich'),
        (9850, 'Mozzarella Sandwich,Mozzarella Cheese Sandwich'),
        (9851, 'havarti sandwich,havarti cheese sandwich'),
        (9852, 'Provolone Sandwich,Provolone Cheese Sandwich'),
        (9853, 'Muenster Sandwich,Muenster Cheese Sandwich'),
        (9854, 'chipotle cream cheese sandwich'),
        (9855, 'Jalapeno Honey Cream Cheese Sandwich,jalapeño Honey Cream Cheese Sandwich'),
        (9856, 'lemon blueberry cream cheese sandwich'),
        (9857, 'Truffle Cream Cheese Sandwich'),
        (9859, 'Feta Cream Cheese Sandwich'),
        (9860, 'Nova cream cheese sandwich'),
        (9932, 'grape jelly sandwich'),
        (9933, 'strawberry jelly sandwich'),
        (9934, 'PBJ sandwich,pb&j sandwich,pb and j sandwich,peanut butter & jelly sandwich,peanut butter and jelly sandwich'),
        (9936, 'tofu spread sandwich,tofu sandwich'),
        (9937, 'nova tofu spread sandwich,nova tofu sandwich'),
        (9938, 'scallion tofu spread sandwich,scallion tofu sandwich'),
        (9939, 'vegetable tofu spread sandwich,vegetable tofu sandwich,veggie tofu spread sandwich,veggie tofu sandwich'),
    ]

    conn = op.get_bind()
    for item_id, orig_phrases in original:
        conn.execute(
            text("UPDATE menu_items SET required_match_phrases = :phrases WHERE id = :id"),
            {"phrases": orig_phrases, "id": item_id}
        )
