# Menu Classification Hierarchy - Options Analysis

## Current System

Menu items flow through a strict chain: **MenuItem → ItemType → MenuDisplayGroup** (each step is many-to-one). Display groups are flat — no hierarchy. Each item type belongs to exactly ONE display group. Aliases on display groups allow recognition ("pastries" → "desserts_pastries"), but they're just synonyms pointing to the same flat group.

**The problem**: If we create a "Candy Bars" display group and move candy items there, they disappear from "Snacks" queries. The system can't express "all candy bars are snacks, but not all snacks are candy bars."

---

## Option 1: Parent-Child Hierarchy (Tree)

**Add `parent_id` to `menu_display_groups` table.**

```
Snacks (parent=null)
├── Candy Bars (parent=Snacks)
├── Chips (parent=Snacks)
└── Cookies (parent=Snacks)

Drinks (parent=null)
├── Hot Drinks (parent=Drinks)
└── Cold Drinks (parent=Drinks)
```

- Item types belong to the **most specific** (leaf) group
- Query "snacks" → collects items from Snacks + all descendants
- Query "candy bars" → collects items from Candy Bars only
- Aliases still work: "candy" alias on the "Candy Bars" group

**Schema change**: One column addition (`parent_id` FK to self).

**Cache change**: When resolving a display group query, recursively collect all descendant group slugs, then gather item types from all of them.

### Pros
- **Minimal schema change** — single nullable FK column
- **Automatic inheritance** — adding a candy bar to "Candy Bars" automatically makes it appear in "Snacks" queries with zero extra work
- **Intuitive admin UX** — just pick a parent group from a dropdown
- **Maintenance is simple** — hierarchy is defined once at the group level, not per-item
- **Works well for the "menu categories" mental model** — menus are naturally tree-shaped (Drinks → Hot Drinks → Coffee, Tea)
- **Cache is straightforward** — build adjacency list at startup, traverse on query

### Cons
- **Single hierarchy only** — an item type can only live in one leaf group. "Chocolate Pretzels" can't be under both "Candy" and "Pretzels" without picking one
- **Depth management** — need to decide max depth (2-3 levels is practical; deeper gets confusing)
- **"What do you have?" at root level** — needs to decide whether to show top-level groups only or flatten everything. Current behavior (show top-level) works naturally
- **Cross-cutting categories don't fit** — "Gluten-free" or "Seasonal" don't belong in a product tree

---

## Option 2: Multi-Group Membership (Many-to-Many)

**New junction table `item_type_display_groups` allowing item types to belong to multiple display groups.**

```
item_type_display_groups
├── item_type_id (FK → item_types)
├── display_group_id (FK → menu_display_groups)
└── is_primary (boolean, for "main" classification)
```

- Keep existing `menu_display_group_id` on item_types as the primary group
- Add secondary memberships via junction table
- "Candy Bar" item type → primary: "Candy Bars", secondary: "Snacks"
- Query "snacks" → find all item types with "Snacks" as primary OR secondary membership
- Query "candy bars" → find all item types with "Candy Bars" membership

### Pros
- **Maximum flexibility** — an item type can appear in any number of groups
- **Cross-cutting categories work** — "Gluten-free", "Seasonal", "New Items" can be groups alongside "Snacks" and "Candy"
- **No depth limits** — flat model, no tree traversal needed
- **No structural constraints** — any grouping you want, you can express

### Cons
- **Manual maintenance per item type** — every candy bar item type needs BOTH "Candy Bars" and "Snacks" manually added. If you add a new candy bar and forget to also add it to "Snacks", it won't appear in snack queries. **This is the single biggest drawback** — it defeats the "all candies are snacks" invariant
- **Consistency burden** — no enforcement of hierarchical rules. Admin has to "just know" that all candy items should also be tagged as snacks
- **Proliferation risk** — with no structure, groups tend to multiply and overlap in messy ways
- **"What do you have?" complexity** — need to decide which groups to show (primary only? all?) and avoid duplicates
- **Larger schema change** — new junction table + migration of existing relationships

---

## Option 3: Group Inclusion (DAG — Directed Acyclic Graph)

**New junction table `display_group_includes` where groups can reference other groups.**

```
display_group_includes
├── parent_group_id (FK → menu_display_groups)
└── child_group_id (FK → menu_display_groups)
```

Example:
```
"Snacks" includes → ["Candy Bars", "Chips", "Cookies"]
"Sweets" includes → ["Candy Bars", "Desserts"]
```

- Item types still belong to exactly ONE display group (the most specific)
- "Candy Bars" items are in the "Candy Bars" group
- "Snacks" is configured to include "Candy Bars", "Chips", etc.
- Query "snacks" → resolve "Snacks" → find included groups → collect all items
- Query "candy bars" → resolve "Candy Bars" → just its items
- A child group can be included by **multiple** parent groups (DAG, not tree)

### Pros
- **Multiple parents** — "Candy Bars" can be under both "Snacks" AND "Sweets" simultaneously (unlike Option 1's single-parent tree)
- **Automatic inheritance** — like Option 1, adding an item to "Candy Bars" automatically makes it appear in all parent groups
- **Item types stay simple** — each belongs to one group (no junction table per item)
- **Hierarchy defined at group level** — maintenance is low-frequency (set up group relationships once, rarely change)
- **Flexible enough for cross-cutting** — "Seasonal" can include "Pumpkin Spice Latte" group and "Fall Pastries" group

### Cons
- **Cycle detection required** — need to prevent A includes B includes A (DAG validation)
- **More complex cache** — need to build and traverse inclusion graph at startup
- **Admin UX is harder to visualize** — a DAG is less intuitive than a tree. "Which groups include this group?" is harder to reason about than "what's the parent?"
- **Two new concepts** — junction table + DAG traversal, vs Option 1's simple parent_id
- **Overkill?** — for a bagel shop menu, multi-parent is rarely needed. A tree (Option 1) handles 95% of real cases

---

## Comparison Matrix

| Criteria                        | Option 1 (Tree)  | Option 2 (Multi-Group) | Option 3 (DAG)     |
|---------------------------------|------------------|------------------------|---------------------|
| Schema complexity               | Minimal (1 col)  | Medium (junction tbl)  | Medium (junction tbl)|
| Automatic inheritance           | Yes              | **No** (manual)        | Yes                 |
| Multiple parents                | No               | N/A (flat)             | Yes                 |
| Cross-cutting categories        | No               | Yes                    | Yes                 |
| Admin maintenance burden        | Low              | **High** (per-item)    | Low                 |
| Cache complexity                | Low              | Low                    | Medium              |
| Intuitive mental model          | High (tree)      | Medium (tags)          | Low (graph)         |
| Risk of inconsistency           | Low              | **High**               | Low                 |
| Handles 95% of real cases       | Yes              | Yes                    | Yes                 |
| Handles edge cases (multi-path) | No               | Yes                    | Yes                 |

---

## Recommendation

**Option 1 (Parent-Child Tree)** is the best fit for this project:

1. **Simplest change** — one nullable column, no new tables
2. **Automatic inheritance** — the key invariant ("all candy bars are snacks") is enforced by structure, not human memory
3. **Low maintenance** — set up the tree once, then just add items to leaf groups
4. **Natural mental model** — menus are inherently tree-shaped
5. **The 5% edge case** (item needs to be in two sibling groups) can be handled by aliases or by restructuring the tree slightly

The only scenario where Option 1 falls short is true cross-cutting categories ("Gluten-free items" across Food and Drinks). But those are better served by a separate tagging/filtering system if ever needed, rather than complicating the core menu hierarchy.

Option 3 (DAG) is the upgrade path if multi-parent becomes genuinely necessary later — the migration from tree to DAG is straightforward (replace `parent_id` column with junction table).
