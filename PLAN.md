# Plan: Update Shot Question Phrasing

## Goal
Make the shot questions more natural sounding:
- Espresso drinks (latte, cappuccino, etc.): "Any extra shots?"
- Non-espresso drinks (coffee, cold brew): "Would you like an espresso shot?"

## Changes

### 1. Update `espresso` item type - `espresso_shots` attribute

```sql
UPDATE item_type_global_attributes ita
SET ask_in_conversation = true,
    question_text = 'Any extra shots?'
FROM item_types it, global_attributes ga
WHERE ita.item_type_id = it.id
  AND ita.global_attribute_id = ga.id
  AND it.slug = 'espresso'
  AND ga.slug = 'espresso_shots';
```

### 2. Update `sized_beverage` item type - `shots` attribute

```sql
UPDATE item_type_global_attributes ita
SET question_text = 'Would you like an espresso shot?'
FROM item_types it, global_attributes ga
WHERE ita.item_type_id = it.id
  AND ita.global_attribute_id = ga.id
  AND it.slug = 'sized_beverage'
  AND ga.slug = 'shots';
```

## Verification

After running the updates, verify with:

```sql
SELECT it.slug as item_type, ga.slug as attr, ita.question_text, ita.ask_in_conversation
FROM item_type_global_attributes ita
JOIN item_types it ON ita.item_type_id = it.id
JOIN global_attributes ga ON ita.global_attribute_id = ga.id
WHERE ga.slug IN ('espresso_shots', 'shots')
ORDER BY it.slug;
```

Expected output:
| item_type | attr | question_text | ask_in_conversation |
|-----------|------|---------------|---------------------|
| espresso | espresso_shots | Any extra shots? | true |
| sized_beverage | shots | Would you like an espresso shot? | true |

## Testing

Test in chatbot UI:
1. Order a latte → should ask "Any extra shots?"
2. Order a hot coffee → should ask "Would you like an espresso shot?"
3. Respond with "two" or "double" → should apply quantity correctly

## Notes
- No code changes required - database only
- Quantity parsing already handles: "two shots", "triple", "double", "yes, two please"
- All espresso-based drinks (latte, cappuccino, americano, macchiato) are already classified as `espresso` item type
