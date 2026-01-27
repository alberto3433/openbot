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

## Database Test Data Cleanup

Tests that create database records (item types, menu items, orders, etc.) **MUST clean up after themselves**.

### Rules

1. **Use fixture cleanup** - Add cleanup logic to pytest fixtures using `try/finally`:
   ```python
   @pytest.fixture
   def db_session():
       session = SessionLocal()
       try:
           yield session
       finally:
           _cleanup_test_data(session)
           session.close()
   ```

2. **Delete in correct order** - Respect foreign key constraints:
   - Delete child records first (e.g., `MenuItemSizePrice` before `MenuItem`)
   - Delete junction table records before parent tables
   - Use `.delete()` for bulk deletes, `.delete(obj)` for individual records

3. **Use unique test identifiers** - Name test data distinctively so cleanup can find it:
   - `"Test Sandwich Pydantic"` instead of `"Sandwich"`
   - `"test_each"` instead of `"each"`
   - `"Test Customer"` instead of `"John"`

4. **Handle cleanup failures gracefully** - Wrap cleanup in try/except to avoid masking test failures:
   ```python
   def _cleanup_test_data(session):
       try:
           # cleanup logic
           session.commit()
       except Exception as e:
           session.rollback()
           print(f"Warning: Failed to clean up test data: {e}")
   ```

5. **Never leave test data in production DB** - The same database is used for development, so leftover test data pollutes the menu.