# Menu Rationalization TODOs

This document tracks all discrepancies between the Zucker's website menu and the Neon database.

**Created**: 2026-01-06
**Status**: ✅ COMPLETE

---

## 1. Database Cleanup - Duplicate/Orphaned Items

### TODO 1.1: Clean up duplicate "Chips" items
- **Status**: [x] COMPLETED (2026-01-06)
- **Issue**: 199 duplicate "Chips" entries at $1.29 each with "unknown" item type
- **Action**:
  - Deleted 199 orphaned "Chips" entries
  - Deleted "Kettle Chips" ($2.75) and "Potato Chips" ($2.50)
  - Added 4 specific Kettle Cooked varieties at $2.50 each under Snack type:
    - Kettle Cooked Sea Salt
    - Kettle Cooked Sea Salt & Vinegar
    - Kettle Cooked Jalapeno
    - Kettle Cooked Smokehouse BBQ

### TODO 1.2: Clean up duplicate "Custom Sandwich" items
- **Status**: [x] COMPLETED (2026-01-06)
- **Issue**: 199 duplicate "Custom Sandwich" entries at $5.99 each with "unknown" item type
- **Action**: Deleted all 199 orphaned entries

### TODO 1.3: Clean up duplicate "Italian Stallion" items
- **Status**: [x] COMPLETED (2026-01-06)
- **Issue**: 199 duplicate "Italian Stallion" entries at $9.49 each, marked as signature but "unknown" item type
- **Action**: Deleted all 199 orphaned entries (item not on current website menu)

---

## 2. Signature Item Composition Discrepancies

### TODO 2.1: The Alton Brown - Ingredient mismatch
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Description**: "Smoked Trout with Plain Cream Cheese, Avocado Horseradish, and Tobiko"
- **Website Description**: "Smoked Trout, Plain Cream Cheese, Avocado, Horseradish and Onion Pepper & Caper Relish"
- **Discrepancy**: DB says "Tobiko", Website says "Onion Pepper & Caper Relish"
- **Action**: Updated DB description to match website

### TODO 2.2: The Chipotle Egg - Ingredient mismatch
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Description**: "Three Eggs with Pepper Jack Cheese, Jalapenos, and Chipotle Cream Cheese"
- **Website Description**: "Two eggs, pepper jack, chipotle cream cheese, avocado and pico de gallo"
- **Discrepancy**: DB says 3 eggs, Website says 2 eggs; DB missing avocado & pico de gallo
- **Action**: Updated DB description to match website

### TODO 2.3: The Delancey Omelette - Description mismatch
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Description**: "Three Eggs with Corned Beef or Pastrami, Onions, and Swiss Cheese"
- **Website Description**: "Two eggs, corned beef or pastrami, breakfast potato latke, sauteed onions and Swiss cheese"
- **Discrepancy**: DB says 3 eggs and missing latke; Website says 2 eggs with latke
- **Action**: Updated DB description to match website

### TODO 2.4: Minor wording differences (Romaine vs Lettuce)
- **Status**: [x] COMPLETED (2026-01-06)
- **Items affected**: The Grand Central, The Tribeca
- **Discrepancy**: DB says "Romaine", Website says "lettuce"
- **Action**: Updated both items to use "lettuce" per website

---

## 3. Signature Items in DB But NOT on Website

### TODO 3.1: Review "The Natural" (Deli Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $15.95
- **DB Description**: "Smoked Turkey, Brie, Beefsteak Tomatoes, Lettuce, and Dijon Dill Sauce"
- **Question**: Discontinued or missing from website?
- **Action**: Deleted - not on website

### TODO 3.2: Review "The Hudson" (Egg Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $11.95
- **DB Description**: (none)
- **Question**: Discontinued or missing from website?
- **Action**: Deleted - not on website

### TODO 3.3: Review "The Midtown" (Egg Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $10.50
- **DB Description**: (none)
- **Question**: Discontinued or missing from website?
- **Action**: Deleted - not on website

### TODO 3.4: Review "The Wall Street" (Egg Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $10.95
- **DB Description**: (none)
- **Question**: Discontinued or missing from website?
- **Action**: Deleted - not on website

### TODO 3.5: Review "The Zucker's Traditional" (Fish Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $18.95
- **DB Description**: "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers"
- **Note**: Website has "The Traditional" at $17.25 - same item with different name
- **Action**: Renamed to "The Traditional" (price update deferred to TODO 6.1)

### TODO 3.6: Review "The Nova Omelette"
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $14.95
- **DB Description**: (none)
- **Question**: Discontinued or missing from website?
- **Action**: Deleted - not on website

### TODO 3.7: Review "HEC" (Egg Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $9.95
- **DB Description**: (none)
- **Note**: Likely "Ham Egg Cheese" - may be sold but not on web menu
- **Action**: Deleted - not on website

### TODO 3.8: Review "SEC" (Egg Sandwich)
- **Status**: [x] COMPLETED (2026-01-06)
- **DB Price**: $9.95
- **DB Description**: (none)
- **Note**: Likely "Sausage Egg Cheese" - may be sold but not on web menu
- **Action**: Deleted - not on website

### TODO 3.9: Review duplicate "Turkey Club" entries
- **Status**: [x] COMPLETED (2026-01-06)
- **Issue**: 208 duplicate entries in DB, all at $15.95
- **Action**: Deleted all 208 entries - item not on website

### TODO 3.10: Review "The Chelsea" vs "The Chelsea Club"
- **Status**: [x] COMPLETED (2026-01-06)
- **DB has both**: The Chelsea (Egg Sandwich, $10.95) and The Chelsea Club (Deli Sandwich, $15.95)
- **Website has**: The Chelsea Club at $13.50
- **Question**: Are these different items or duplicates?
- **Action**: Deleted "The Chelsea" (not on website); kept "The Chelsea Club" (price update deferred to TODO 6.1)

---

## 4. Items on Website But NOT in Database (Key Items)

### TODO 4.1: Add Bagel Packages
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - 3 Bagel Package ($13.00)
  - 6 Bagel Package ($21.00)
  - Bakers Dozen ($25.80)
  - Bagel Package - Dozen Bagels & 2 Cream Cheese ($38.00)
- **Action**: Added all 4 items

### TODO 4.2: Add Sourdough Bagels
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Plain Sourdough Bagel ($2.00)
  - Sesame Sourdough Bagel ($2.00)
  - Everything Sourdough Bagel ($2.00)
- **Action**: Added all 3 items

### TODO 4.3: Add New Signature Sandwiches
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - The Cheesesteak ($11.75)
  - The RB Prime ($13.95) - "Fresh Carved Roast Beef, Cheddar, Romaine, Beefsteak Tomatoes"
  - The Pizza BEC ($9.85) - "Tomato Sauce, Mozzarella, Choice of Pepperoni, Bacon, Or Sausage Topped with 2 Fried Eggs"
  - The Mulberry ($10.95) - "Two eggs, esposito's sausage, green and red peppers and sauteed onions"
  - The Tuna Melt ($11.75) - "tuna, melted swiss"
  - The Old School Tuna Sandwich ($11.95) - "Our fresh tuna salad, Romaine and tomatoes"
  - Sweet & Spicy Traditional ($17.50) - "Nova Scotia salmon, Jalapeno-Honey, beefsteak tomatoes, red onions, and capers"
  - The Flatiron Traditional ($17.50) - "Everything seeded salmon, scallion, cream cheese and fresh avocado"
  - Open Face Traditional ($17.50)
- **Action**: Added all 9 items as signature items

### TODO 4.4: Add Cheese Sandwiches (plain cheese on bagel)
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - American Cheese Sandwich ($6.25)
  - Cheddar Cheese Sandwich ($6.25)
  - Swiss Cheese Sandwich ($6.25)
  - Pepper Jack Cheese Sandwich ($6.25)
  - Mozzarella Sandwich ($6.95)
  - Havarti Cheese Sandwich ($6.95)
  - Provolone Cheese Sandwich ($6.25)
  - Muenster Cheese Sandwich ($6.25)
- **Action**: Added all 8 items

### TODO 4.5: Add New Cream Cheese Sandwiches
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Chipotle Cream Cheese Sandwich ($6.25)
  - Jalapeño Honey Cream Cheese Sandwich ($6.25)
  - Lemon Blueberry Cream Cheese Sandwich ($6.25)
  - B&W Truffle Cream Cheese Sandwich ($6.00)
  - Roasted Scallion Shallot Caper & Garlic Cream Cheese Sandwich ($6.00)
  - Kalamata Olive Feta Cream Cheese Sandwich ($6.25)
  - Nova Cream Cheese Sandwich ($7.25)
- **Action**: Added all 7 items

### TODO 4.6: Add New Omelettes
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - The Classic Omelette ($8.25) - "Create your own Omelette"
  - The Classic BEC Omelette ($11.50)
  - The Columbus BEC Omelette ($13.50)
  - The Leo Omelette ($13.85)
- **Action**: Added all 4 items

### TODO 4.7: Add Pizza Bagels
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Pepperoni Pizza Bagel ($4.95)
  - The Margherita Pizza Bagel ($3.95)
- **Action**: Added all 2 items

### TODO 4.8: Add Croissants
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Croissant ($3.85)
  - Chocolate Croissant ($3.85)
- **Action**: Added all 2 items

### TODO 4.9: Add Babka Slices
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Apple Cinnamon Babka ($14.95)
  - Apple Cinnamon Babka Slice ($3.50)
  - Chocolate Babka Slice ($3.50)
  - Cinnamon Babka Slice ($3.50)
- **Action**: Added all 4 items

### TODO 4.10: Add Hamantaschen
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Apricot Hamantaschen ($1.25)
  - Poppy Hamantaschen ($1.25)
  - Raspberry Hamantaschen ($1.25)
- **Action**: Added all 3 items

### TODO 4.11: Add New Beverages
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Boxed Coffee Large ($70.00)
  - Boxed Coffee Small ($35.00)
  - Olipop sodas (4 varieties, $3.25 each)
  - Health-ade Kombucha (2 varieties, $4.50 each)
  - Vitamin Water (4 varieties, $3.75 each)
  - Gatorade (3 varieties, $3.75 each)
  - Joe's teas/lemonade (4 varieties, $3.25 each)
  - Naked juices (4 varieties, $5.75 each)
  - Red Bull ($4.75)
  - Essentia Water (3 sizes)
  - Irving Farm Cold Brew ($4.99)
- **Action**: Added all 28 beverage items

### TODO 4.12: Add Joyva Candies
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Joyva Halva Chocolate ($2.35)
  - Joyva Halva Original ($2.35)
  - Joyva Marble Halva ($2.35)
  - Joyva Jelly Bar ($2.35)
  - Joyva Jelly Rings ($2.35)
  - Joyva Marshmallow ($2.35)
  - Joyva Single Jelly Ring ($0.75)
- **Action**: Added all 7 items

### TODO 4.13: Add Chip Varieties
- **Status**: [x] COMPLETED (2026-01-06) - Previously completed in TODO 1.1
- **Items to add**:
  - Kettle Cooked Sea Salt ($2.50)
  - Kettle Cooked Sea Salt & Vinegar ($2.50)
  - Kettle Cooked Jalapeno ($2.50)
  - Kettle Cooked Smokehouse BBQ ($2.50)
- **Action**: Already added in TODO 1.1

### TODO 4.14: Add Other Snacks
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Bjorn Qorn Popcorn ($2.95)
  - Pop Daddy Pretzels - Dill Pickle ($3.65)
  - Pop Daddy Pretzels - Yellow Mustard ($3.65)
- **Action**: Added all 3 items

### TODO 4.15: Add Missing Sides
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Side of Avocado ($3.50)
  - Side of Pickles ($1.50)
  - Side of Cucumbers ($0.75)
  - Side of Lettuce ($0.75)
  - Side of Tomato ($1.10)
  - Side of Onion ($0.60)
  - Side of Capers ($0.75)
- **Action**: Added all 7 items

### TODO 4.16: Add Soup Sizes
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Chicken Noodle Large ($7.95)
  - Chicken Noodle Small ($6.95)
  - Lentil Large ($7.25)
  - Lentil Small ($6.25)
- **Action**: Added all 4 items

### TODO 4.17: Add Yogurt Parfaits
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Strawberry Yogurt Parfait ($4.75)
  - Vanilla Yogurt Parfait ($4.75)
- **Action**: Added all 2 items

### TODO 4.18: Add Fruit Items
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Small Fruit Salad ($2.95)
  - Large Fruit Salad ($4.95)
  - Mixed Berry Cup ($5.99)
  - Granola Small ($2.95)
  - Granola Large ($6.75)
- **Action**: Added all 5 items

### TODO 4.19: Add Jelly/PB Sandwiches
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Grape Jelly Sandwich ($3.75)
  - Strawberry Jelly Sandwich ($3.75)
  - Peanut Butter & Jelly Sandwich ($5.95)
  - Cinnamon Sugar Butter Sandwich ($4.85)
- **Action**: Added all 4 items

### TODO 4.20: Add Tofu Spread Variants
- **Status**: [x] COMPLETED (2026-01-06)
- **Items to add**:
  - Tofu Spread Sandwich ($5.35)
  - Nova Tofu Spread Sandwich ($6.95)
  - Scallion Tofu Spread Sandwich ($6.25)
  - Vegetable Tofu Spread Sandwich ($6.25)
- **Action**: Added all 4 items

---

## 5. Items in DB But NOT on Website (Review for Removal/Retention)

### TODO 5.1: Review By-the-Pound items
- **Status**: [x] COMPLETED (2026-01-06)
- **Count**: 55 items
- **Question**: Keep in DB for in-store sales even if not on web menu?
- **Action**: KEPT - website has "lb" items for catering; these are valid menu items

### TODO 5.2: Review Specialty Bagels not on website
- **Status**: [x] COMPLETED (2026-01-06)
- **Items**: Asiago, Marble Rye, Bialy, Egg Bagel, Salt Bagel, Wheat varieties (7+)
- **Question**: Discontinued or just not on web menu?
- **Action**: Deleted 12 specialty bagels not on website

### TODO 5.3: Review Omelettes not on website
- **Status**: [x] COMPLETED (2026-01-06)
- **Items**: Cheese Omelette, Corned Beef Omelette, Egg White Avocado Omelette, Pastrami Omelette, Salami Omelette, Sausage Omelette, Southwest Omelette, Spinach & Feta Omelette, Truffle Omelette, Turkey Omelette, Veggie Omelette, Western Omelette, The Columbus Omelette
- **Question**: Discontinued or just not on web menu?
- **Action**: Deleted 13 omelettes not on website; kept 11 that ARE on website

### TODO 5.4: Review Salads not on website
- **Status**: [x] COMPLETED (2026-01-06)
- **Items**: The Caesar, The Garden
- **Question**: Discontinued or just not on web menu?
- **Action**: Deleted both - not on website

---

## 6. Price Discrepancies (For Later)

### TODO 6.1: Update prices to match website
- **Status**: [x] COMPLETED (2026-01-06)
- **Count**: 61 items with price differences
- **Action**: Updated 60 items to match website prices
- **Exception**: "The Truffled Egg" kept at $21.95 (website shows $11.25 - possible error)

---

## Progress Tracking

| Section | Total TODOs | Completed | Remaining |
|---------|-------------|-----------|-----------|
| 1. Cleanup Duplicates | 3 | 3 | 0 |
| 2. Composition Discrepancies | 4 | 4 | 0 |
| 3. DB Items Not on Website | 10 | 10 | 0 |
| 4. Website Items Not in DB | 20 | 20 | 0 |
| 5. Review for Removal | 4 | 4 | 0 |
| 6. Price Updates | 1 | 1 | 0 |
| **TOTAL** | **42** | **42** | **0** |
