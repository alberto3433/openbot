# Source Code Rules

Source code in this directory CAN be domain-specific but it should never be used outside of this directory.

- You can hardcoded business terms (menu items, product names, categories)
- All source code in this directory is for testing purposes only.
- Any method or function that gets created under this directory should start with `test_` prefix.

## Test Failure Protocol: DB Sync

When tests fail due to unexpected bot responses (e.g., asking different questions than expected):

1. **Check DB definitions first** - The database is the source of truth for:
   - Attribute `ask_in_conversation` flags
   - Attribute `display_order` (determines question sequence)
   - Required vs optional attributes
   - Question text

2. **Update tests to match DB behavior** when:
   - DB definition changed intentionally (e.g., adding `scooped` attribute before `spread`)
   - Test expectations were based on old DB state
   - Business requirements evolved

3. **Query the DB to understand current state**:
   ```sql
   SELECT slug, display_order, ask_in_conversation, question_text
   FROM item_type_attributes
   WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel')
   ORDER BY display_order;
   ```

4. **DO NOT hardcode expected questions** - If a test expects "Would you like cream cheese?" but DB says to ask about scooping first, update the test to expect the scooped question.