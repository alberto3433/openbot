# Analysis: Where Signature Sandwich Ingredients Come From

## Overview

This document analyzes how ingredients for signature sandwiches like "The Lexington" are stored, retrieved, and (not) used throughout the order flow.

---

## 1. Database Storage (Two Locations)

**The Lexington (menu_items table, id=386):**

| Column | Value |
|--------|-------|
| `description` | `"Egg Whites, Swiss, and Spinach"` |
| `default_config` | `{"bread": "Bagel", "protein": "Egg White", "cheese": "Swiss", "toppings": ["Spinach"]}` |
| `recipe_id` | `None` (no Recipe relationship) |

---

## 2. How Ingredients Are Used (Or Not Used)

### A. Answering "What's in The Lexington?"

**Flow:**
1. `menu_index_builder._build_item_descriptions()` (line 694-716) creates mapping:
   ```python
   {"the lexington": "Egg Whites, Swiss, and Spinach"}
   ```
2. Stored in `menu_index["item_descriptions"]`
3. User asks -> `menu_inquiry_handler.handle_item_description_inquiry()` (line 675-743)
4. Looks up `item_descriptions.get("the lexington")` -> returns description
5. **Response:** "The Lexington has Egg Whites, Swiss, and Spinach. Would you like to order one?"

**Status: WORKS - Uses `description` column**

---

### B. LLM Describing Ingredients

**Flow:**
1. `menu_index_builder.py` (line 155) includes:
   ```python
   "default_config": {"bread": "Bagel", "protein": "Egg White", ...}
   ```
2. `sammy/llm_client.py` (lines 92-100) instructs LLM:
   ```
   "Read its default_config to describe the ingredients"
   ```
3. LLM can say: "The Lexington comes on a bagel with egg whites, Swiss cheese, and spinach"

**Status: WORKS - Uses `default_config` column**

---

### C. ORDERING The Lexington (THE GAP)

**Flow:**
1. User: "I'll have The Lexington"
2. `item_adder_handler.add_menu_item()` (lines 106-365):
   ```python
   menu_item = self.menu_lookup.lookup_menu_item(item_name)
   # Returns full dict INCLUDING default_config

   canonical_name = menu_item.get("name")      # "The Lexington"
   price = menu_item.get("base_price")         # 9.25
   menu_item_id = menu_item.get("id")          # 386
   # default_config is IGNORED - never extracted!

   item = MenuItemTask(
       menu_item_name=canonical_name,
       menu_item_id=menu_item_id,
       unit_price=price,
       # NO ingredients field!
   )
   ```

**Status: GAP - `default_config` is available but NOT stored in `MenuItemTask`**

---

### D. Persisting Order to Database

**Flow:**
1. `order.py._add_order_items()` (lines 335-381):
   ```python
   item_config = it.get("item_config") or {}
   # item_config only contains: menu_item_type, toasted, bagel_choice, etc.
   # NO ingredients from default_config!
   ```

**Status: GAP - Ingredients never make it to `order_items.item_config`**

---

### E. Converting MenuItemTask to Dict (for UI/persistence)

**Flow:**
1. `item_converters.py` `MenuItemConverter.to_dict()` (lines 131-211):
   ```python
   "item_config": {
       "menu_item_type": menu_item_type,
       "side_choice": side_choice,
       "bagel_choice": bagel_choice,
       "toasted": toasted,
       "spread": spread,
       "modifications": getattr(item, 'modifications', []),
       "modifiers": modifiers,
   }
   ```

**Status: GAP - Only captures user configuration choices, NOT the original ingredients**

---

## 3. Data Flow Diagram

```
DATABASE                          IN-MEMORY                      PERSISTED/UI
----------------------------------------------------------------------------------
menu_items.description ---------> item_descriptions -----> Answer "what's on?"
    "Egg Whites, Swiss..."

menu_items.default_config ------> menu_index JSON -------> LLM prompts only
    {bread, protein, cheese...}

menu_items.name ----------------> MenuItemTask ----------> OrderItem
menu_items.base_price             (only name, price,       (only name, price,
menu_items.id                      id, modifications)       item_config with
                                                           toasted/bagel_choice)

                                   DEFAULT_CONFIG
                                   NEVER TRANSFERRED!
```

---

## 4. Key Files Involved

| File | Role |
|------|------|
| `sandwich_bot/models.py` (line 265) | `MenuItem.default_config` column definition |
| `sandwich_bot/menu_index_builder.py` (line 155) | Includes `default_config` in menu JSON |
| `sandwich_bot/tasks/item_adder_handler.py` (lines 293-296) | Only extracts name, price, id - ignores default_config |
| `sandwich_bot/tasks/models.py` (lines 559-619) | `MenuItemTask` has no field for ingredients |
| `sandwich_bot/tasks/item_converters.py` (lines 201-210) | `item_config` output only has user choices |
| `sandwich_bot/services/order.py` (lines 366-378) | Persists `item_config` to `OrderItem` |

---

## 5. Why This Matters

When an order for "The Lexington" is placed:
- The kitchen ticket shows: **"The Lexington"** (just the name)
- It does NOT show: "Egg White, Swiss, Spinach on a Bagel"

The system **relies on the kitchen knowing** what "The Lexington" means, rather than explicitly storing the ingredients in the order.

This is a **design choice**, not a bug - signature items are referenced by name, and the recipe is implicit. But it means `default_config` is only used for **informational purposes** (describing items), not for **order capture**.

---

## 6. Open Questions

1. Should the UI display the original `default_config` from the menu item?
2. Should `default_config` be merged into `item_config` when ordering signature items?
3. Is the current behavior (name-only reference) intentional for kitchen workflows?
