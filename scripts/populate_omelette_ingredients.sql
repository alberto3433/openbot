-- Populate missing default ingredients for omelettes
-- Run with: psql $DATABASE_URL -f scripts/populate_omelette_ingredients.sql

BEGIN;

-- The Classic BEC Omelette (id=9862)
-- Ingredients: 2 eggs, bacon, cheddar cheese
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(9862, 34, 2),   -- Egg (qty 2)
(9862, 29, 1),   -- Bacon
(9862, 81, 1);   -- Cheddar Cheese

-- The Classic Omelette (id=9861)
-- "Create your own" - just eggs as base
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(9861, 34, 2);   -- Egg (qty 2)

-- The Columbus BEC Omelette (id=9863)
-- Ingredients: 3 egg whites, turkey bacon, avocado, swiss cheese
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(9863, 35, 3),   -- Egg White (qty 3)
(9863, 112, 1),  -- Turkey Bacon
(9863, 37, 1),   -- Avocado
(9863, 80, 1);   -- Swiss Cheese

-- The Delancey Omelette with Pastrami (id=9983)
-- Ingredients: 2 eggs, pastrami, breakfast potato latke, sauteed onions, swiss cheese
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(9983, 34, 2),   -- Egg (qty 2)
(9983, 31, 1),   -- Pastrami
(9983, 127, 1),  -- Breakfast Potato Latke
(9983, 125, 1),  -- Sauteed Onions
(9983, 80, 1);   -- Swiss Cheese

-- The Leo Omelette (id=9864)
-- Ingredients: 3 eggs, nova scotia salmon, sauteed onions
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(9864, 34, 3),   -- Egg (qty 3)
(9864, 24, 1),   -- Nova Scotia Salmon
(9864, 125, 1);  -- Sauteed Onions

-- The Lexington Omelette (id=520)
-- Ingredients: 3 egg whites, swiss cheese, spinach
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(520, 35, 3),    -- Egg White (qty 3)
(520, 80, 1),    -- Swiss Cheese
(520, 88, 1);    -- Spinach

-- The Truffled Egg Omelette (id=519)
-- Ingredients: 2 eggs, swiss cheese, truffle cream cheese, sauteed mushrooms
INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity) VALUES
(519, 34, 2),    -- Egg (qty 2)
(519, 80, 1),    -- Swiss Cheese
(519, 62, 1),    -- Truffle Cream Cheese
(519, 124, 1);   -- Sauteed Mushrooms

COMMIT;

-- Verify the inserts
SELECT mi.name, COUNT(mii.ingredient_id) as num_ingredients
FROM menu_items mi
JOIN item_types it ON mi.item_type_id = it.id
LEFT JOIN menu_item_ingredients mii ON mi.id = mii.menu_item_id
WHERE it.slug = 'omelette'
GROUP BY mi.id, mi.name
ORDER BY mi.name;
