# Plan: Make item_converters.py More Generic and Data-Driven

## Analysis

### Current State

The `MenuItemConverter.from_dict()` method (lines 327-344) has **hardcoded field mappings**:

```python
menu_item = MenuItemTask(
    menu_item_name=item_dict.get("menu_item_name") or "Unknown",
    menu_item_id=item_dict.get("menu_item_id"),
    menu_item_type=menu_item_type,
    modifications=item_dict.get("modifications") or [],
    removed_ingredients=...,
    side_choice=item_dict.get("side_choice"),      # ← Hardcoded
    bagel_choice=item_dict.get("bagel_choice"),    # ← Hardcoded
    toasted=item_dict.get("toasted"),              # ← Hardcoded
    spread=item_dict.get("spread"),                # ← Hardcoded
    spread_price=spread_price,                     # ← Hardcoded
    requires_side_choice=item_dict.get("requires_side_choice", False),
    ...
)
```

Similarly, the `MenuItemTask` model (lines 216-222 of models.py) has **hardcoded fields**:

```python
side_choice: str | None = None
bagel_choice: str | None = None
bagel_choice_upcharge: float = 0.0
spread_price: float | None = None
requires_side_choice: bool = False
```

### Problem

This violates the data-driven architecture principle from CLAUDE.md:

> **No hardcoded attributes** - Item attributes come from `item_type_attributes` table

These field names (`side_choice`, `bagel_choice`, `toasted`, `spread`) are **domain-specific vocabulary** that shouldn't exist in the codebase. If we wanted to use this system for a sushi restaurant, these fields would be meaningless.

### Target State

All item configuration should flow through `attribute_values` dict, which is populated from:
1. Database-defined attributes (`get_item_type_attributes()`)
2. Incoming dict data (dynamically mapped)

The model should have **zero domain-specific field names** - only:
- Generic identity fields: `menu_item_name`, `menu_item_id`, `menu_item_type`
- Generic state fields: `status`, `quantity`, `unit_price`
- Generic container: `attribute_values: dict[str, Any]`

---

## Implementation Plan

### Phase 1: Audit Current Usage

Before removing hardcoded fields, identify all usages:

| Field | Usages | Migration Path |
|-------|--------|----------------|
| `side_choice` | ~15 files | Move to `attribute_values["side_choice"]` |
| `bagel_choice` | ~10 files | Move to `attribute_values["bagel_choice"]` or DB-defined `{side}_choice` |
| `toasted` | ~20 files | Already has property accessor → keep as-is |
| `spread` | ~15 files | Already has property accessor → keep as-is |
| `spread_price` | ~5 files | Store as `attribute_values["spread_price"]` |
| `requires_side_choice` | ~8 files | Derive from DB: `item_type_has_attribute(type, "side_choice")` |

### Phase 2: Create Generic Property Accessors

Instead of hardcoded fields, create a **dynamic property pattern**:

```python
class MenuItemTask(ItemTask):
    attribute_values: dict[str, Any] = Field(default_factory=dict)

    def get_attr(self, slug: str, default: Any = None) -> Any:
        """Get attribute value by slug."""
        return self.attribute_values.get(slug, default)

    def set_attr(self, slug: str, value: Any) -> None:
        """Set attribute value by slug."""
        if value is not None:
            self.attribute_values[slug] = value
        elif slug in self.attribute_values:
            del self.attribute_values[slug]
```

Keep backward-compatible property accessors for commonly-used fields during migration:

```python
@property
def side_choice(self) -> str | None:
    return self.get_attr("side_choice")

@side_choice.setter
def side_choice(self, value: str | None) -> None:
    self.set_attr("side_choice", value)
```

### Phase 3: Make from_dict() Data-Driven

Replace hardcoded field mapping with dynamic attribute restoration:

```python
def from_dict(self, item_dict: Dict[str, Any]) -> MenuItemTask:
    menu_item_type = item_dict.get("menu_item_type") or item_dict.get("item_type")

    # Start with explicit attribute_values from dict
    attribute_values = item_dict.get("attribute_values") or {}

    # Data-driven: get expected attributes from DB
    if menu_item_type:
        item_attrs = menu_cache.get_item_type_attributes(menu_item_type)

        # Restore any top-level fields that match DB-defined attributes
        for attr_slug in item_attrs.keys():
            if attr_slug not in attribute_values and attr_slug in item_dict:
                attribute_values[attr_slug] = item_dict[attr_slug]
            # Also check for {attr_slug}_price companion fields
            price_key = f"{attr_slug}_price"
            if price_key in item_dict:
                attribute_values[price_key] = item_dict[price_key]

    # Also restore common legacy fields that may not be in item_attrs
    # (for backward compatibility during migration)
    for legacy_field in ["side_choice", "bagel_choice", "spread_price"]:
        if legacy_field not in attribute_values and legacy_field in item_dict:
            attribute_values[legacy_field] = item_dict[legacy_field]

    menu_item = MenuItemTask(
        menu_item_name=item_dict.get("menu_item_name") or "Unknown",
        menu_item_id=item_dict.get("menu_item_id"),
        menu_item_type=menu_item_type,
        modifications=item_dict.get("modifications") or [],
        quantity=item_dict.get("quantity", 1),
        attribute_values=attribute_values,
    )
    self._restore_common_fields(menu_item, item_dict)
    return menu_item
```

### Phase 4: Make to_dict() Data-Driven

Replace hardcoded field output with dynamic attribute serialization:

```python
def to_dict(self, item: ItemTask, pricing: "PricingEngine | None" = None) -> Dict[str, Any]:
    attribute_values = getattr(item, 'attribute_values', {}) or {}
    menu_item_type = getattr(item, 'menu_item_type', None)

    result = self._build_common_dict_fields(item)
    result.update({
        "menu_item_name": item.menu_item_name,
        "menu_item_id": getattr(item, 'menu_item_id', None),
        "menu_item_type": menu_item_type,
        "attribute_values": attribute_values,
        # ... modifiers, display_name, etc.
    })

    # Data-driven: output DB-defined attributes at top level for backward compatibility
    if menu_item_type:
        item_attrs = menu_cache.get_item_type_attributes(menu_item_type)
        for attr_slug in item_attrs.keys():
            if attr_slug in attribute_values:
                result[attr_slug] = attribute_values[attr_slug]

    # Also output legacy fields for backward compatibility
    for legacy_field in ["side_choice", "bagel_choice", "spread_price", "requires_side_choice"]:
        if legacy_field in attribute_values:
            result[legacy_field] = attribute_values[legacy_field]

    return result
```

### Phase 5: Remove Hardcoded Fields from Model

After all usages migrate to property accessors:

```python
class MenuItemTask(ItemTask):
    item_type: Literal["menu_item"] = "menu_item"

    # Core identity (keep these)
    menu_item_name: str
    menu_item_id: int | None = None
    menu_item_type: str | None = None

    # Lists (keep these - not attribute-like)
    modifications: list[str] = Field(default_factory=list)
    removed_ingredients: list[str] = Field(default_factory=list)

    # Dynamic attributes (replaces all hardcoded fields)
    attribute_values: dict[str, Any] = Field(default_factory=dict)

    # REMOVED:
    # - side_choice (now in attribute_values)
    # - bagel_choice (now in attribute_values)
    # - bagel_choice_upcharge (now in attribute_values)
    # - spread_price (now in attribute_values)
    # - requires_side_choice (derived from DB)
```

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing serialized orders | Keep backward-compat properties during migration |
| Test failures | Update tests incrementally, run regression suite |
| Performance (extra DB lookups) | Already cached in `menu_cache._item_type_attributes` |
| Frontend expects specific fields | Keep top-level output for backward compatibility |

---

## Recommended Approach

**Incremental migration** over 3-4 PRs:

1. **PR 1**: Add `get_attr()`/`set_attr()` helpers + property accessors for `side_choice`, `bagel_choice`, etc.
2. **PR 2**: Update `from_dict()` to be data-driven (restore to attribute_values)
3. **PR 3**: Update `to_dict()` to be data-driven (serialize from attribute_values)
4. **PR 4**: Remove hardcoded fields from model, keep only property accessors

This approach ensures backward compatibility at each step and allows testing incrementally.

---

## Questions for Clarification

1. Should we keep `requires_side_choice` as a derived property (from DB) or store it in `attribute_values`?
2. Are there any external systems (APIs, webhooks) that depend on the exact output format?
3. What's the priority: full data-driven purity vs. shipping features?
