-- Create table
CREATE TABLE IF NOT EXISTS menu_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL, -- "sandwich", "side", "drink"
    is_signature INTEGER NOT NULL DEFAULT 0,
    base_price REAL NOT NULL,
    available_qty INTEGER NOT NULL DEFAULT 10,
    metadata TEXT
);

-- Signature Sandwiches (10 items)
INSERT INTO menu_items (name, category, is_signature, base_price, available_qty, metadata) VALUES
('Italian Classic', 'sandwich', 1, 8.50, 10, '{"size":"6 or 12","defaults":{"bread":"white","protein":"salami","cheese":"provolone","toppings":["lettuce","tomato","onion"],"sauces":["Italian vinaigrette"],"toasted":true}}'),
('Turkey Club', 'sandwich', 1, 8.00, 10, '{"defaults":{"bread":"wheat","protein":"turkey","cheese":"cheddar","toppings":["lettuce","tomato"],"sauces":["mayo"],"toasted":false}}'),
('Veggie Delight', 'sandwich', 1, 7.50, 10, '{"defaults":{"bread":"multigrain","protein":"no meat","cheese":"Swiss","toppings":["lettuce","tomato","cucumber","olives"],"sauces":["ranch"],"toasted":false}}'),
('Chicken Pesto', 'sandwich', 1, 9.00, 10, '{"defaults":{"bread":"ciabatta","protein":"chicken","cheese":"provolone","toppings":["tomato"],"sauces":["pesto"],"toasted":true}}'),
('Roast Beef Supreme', 'sandwich', 1, 9.50, 10, '{"defaults":{"bread":"white","protein":"roast beef","cheese":"Swiss","toppings":["onion"],"sauces":["mayo"],"toasted":true}}'),
('Ham & Swiss', 'sandwich', 1, 7.75, 10, '{"defaults":{"bread":"white","protein":"ham","cheese":"Swiss","toppings":["lettuce"],"sauces":["mustard"],"toasted":false}}'),
('Buffalo Chicken', 'sandwich', 1, 8.75, 10, '{"defaults":{"bread":"wheat","protein":"chicken","cheese":"pepper jack","toppings":["lettuce"],"sauces":["ranch","buffalo"],"toasted":true}}'),
('Tuna Salad', 'sandwich', 1, 7.50, 10, '{"defaults":{"bread":"white","protein":"no meat","cheese":"no cheese","toppings":["lettuce","pickles"],"sauces":["mayo"],"toasted":false}}'),
('Meatball Marinara', 'sandwich', 1, 8.25, 10, '{"defaults":{"bread":"white","protein":"meatball","cheese":"provolone","toppings":[],"sauces":["marinara"],"toasted":true}}'),
('Caprese', 'sandwich', 1, 7.75, 10, '{"defaults":{"bread":"ciabatta","protein":"no meat","cheese":"provolone","toppings":["tomato"],"sauces":["balsamic glaze"],"toasted":false}}');

-- Build-Your-Own Entries
INSERT INTO menu_items (name, category, is_signature, base_price, available_qty, metadata) VALUES
('BYO Sandwich 6', 'sandwich', 0, 7.00, 10, '{"size":"6"}'),
('BYO Sandwich 12', 'sandwich', 0, 11.00, 10, '{"size":"12"}');

-- Sides
INSERT INTO menu_items (name, category, is_signature, base_price, available_qty, metadata) VALUES
('chips', 'side', 0, 2.00, 10, NULL),
('cookie', 'side', 0, 2.50, 10, NULL);

-- Drinks
INSERT INTO menu_items (name, category, is_signature, base_price, available_qty, metadata) VALUES
('soda', 'drink', 0, 2.50, 10, NULL),
('bottled water', 'drink', 0, 2.00, 10, NULL),
('iced tea', 'drink', 0, 2.75, 10, NULL);
