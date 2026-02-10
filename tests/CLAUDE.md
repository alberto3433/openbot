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

## Full Test Suite Report Format

When asked to run the full test suite, generate a report in this format:

### 1. Run Command
```bash
python -m pytest --tb=short -q 2>&1
```

### 2. Report Structure

```
# Test Suite Report

## Summary
- **Total**: X tests
- **Passed**: X
- **Failed**: X
- **Skipped**: X
- **XFailed**: X (expected failures)

## Failed Tests by Root Cause

### Category 1: [Root Cause Description]
**Affected tests**: X

| Test | Input | Expected | Actual |
|------|-------|----------|--------|
| test_name | "user input" | expected behavior | actual behavior |

### Category 2: [Root Cause Description]
...

## Totals by Category
| Root Cause | Count |
|------------|-------|
| Category 1 | X |
| Category 2 | X |
| **Total Failed** | **X** |
```

### 3. Root Cause Categories to Use

Categorize failures into these common root causes:

1. **Item Type Detection** - Wrong item type detected (e.g., espresso vs coffee_based_beverage)
2. **Pricing Errors** - Missing prices, wrong calculations
3. **Modifier Handling** - Add/remove modifier failures
4. **Question Ordering** - Wrong attribute question asked
5. **Cancellation/Removal** - Cancel commands not working
6. **Menu Query** - Menu inquiry responses incorrect
7. **Parsing Issues** - Input not parsed correctly
8. **Side Item Handling** - Side items not recognized
9. **Multi-item Parsing** - Multiple items in one input fail
10. **Spread/Attribute Handling** - Attribute value issues
11. **Domain Data Leakage** - Hardcoded domain data in production code
12. **Other** - Miscellaneous failures

### 4. Extracting Input/Expected/Actual

From the pytest assertion output, extract:
- **Input**: The user input string being tested (from test setup or assertion message)
- **Expected**: What the assertion expected (left side of `==`, or described in assertion message)
- **Actual**: What the code produced (right side of `==`, or the actual value shown)

Example assertion output:
```
E   AssertionError: Expected milk/sweetener/syrup question, got: Got it, for the Espresso. What size?
```
→ Input: "espresso" | Expected: milk/sweetener/syrup question | Actual: "What size?"

Example assertion output:
```
E   assert 'true' is True
```
→ Input: "make it a decaf" | Expected: decaf=True (bool) | Actual: decaf='true' (string)

### 5. Example Report Entry

```markdown
### Item Type Detection Issues
**Affected tests**: 5

| Test | Input | Expected | Actual |
|------|-------|----------|--------|
| test_another_espresso_creates_menu_item_task | "another espresso" | item_type='espresso' | item_type='coffee_based_beverage' |
| test_parse_open_input_detects_another_espresso | "another espresso" | item_type='espresso' | item_type='coffee_based_beverage' |
```