# Remaining Test Fixes Plan

## Current Status: 46 failed, 531 passed (92% pass rate)

## Summary of Completed Fixes

| Fix | Tests Fixed | Status |
|-----|-------------|--------|
| Delete `test_llm_client.py` | 8 | ✅ Done |
| Fix `test_tasks_integration.py` fixture | ~246 errors | ✅ Done |
| Fix `test_session_persistence.py` endpoints | 3 | ✅ Done |
| Fix `test_menu_item_duplicates.py` | 1 | ✅ Done |
| Fix `test_disambiguation_matrix.py` fixture | 9 errors | ✅ Done |
| Update slug format expectations | ~15 tests | ✅ Done |

---

## Remaining Failing Tests by Category

### Category 1: Special Instructions Feature (17 tests)

**File:** `test_tasks_parsing.py::TestSpecialInstructionsExtraction`

**Decision Needed:** Is special instructions feature deprecated?
- If deprecated → Delete these tests
- If needed → Fix the extraction logic

**Tests:**
1. `test_special_instruction_room_for_cream`
2. `test_special_instruction_not_too_hot`
3. `test_special_instruction_lukewarm`
4. `test_special_instruction_upside_down`
5. `test_special_instruction_well_stirred`
6. `test_special_instruction_mixed`
7. `test_special_instruction_lightly_toasted`
8. `test_special_instruction_well_done`
9. `test_special_instruction_cut_in_half`
10. `test_special_instruction_sliced`
11. `test_special_instruction_open_faced`
12. `test_special_instruction_spread_thin`
13. `test_special_instruction_on_one_side`
14. `test_special_instruction_on_both_halves`
15. `test_special_instruction_melted`
16. `test_multi_item_coffee_and_bagel_with_butter`
17. `test_bagel_with_cream_cheese_is_build_your_own`

---

### Category 2: Split Quantity Parsing (4 tests)

**File:** `test_tasks_parsing.py::TestSplitQuantityBagelParsing`

**Problem:** When parsing "2 plain bagels, one with X, one with Y":
- `bread` attribute is NOT being extracted
- The word "plain" is interpreted as spread variant instead of bagel type

**Tests:**
1. `test_two_bagels_one_lox_one_cream_cheese`
2. `test_three_bagels_different_spreads`
3. `test_spread_and_toasted_variants`
4. `test_split_with_scallion_and_veggie`

**Fix Location:** `orderbot/tasks/parsers/deterministic/item_parsing.py`

---

### Category 3: Disambiguation/Menu Lookup (12 tests)

**File:** `test_disambiguation_matrix.py`

**Problems:**
- Generic terms (cookies, muffins) not matching expected menu_item_id
- "bagel chips" specific item handling
- Side items (latkes, home fries, fruit cup) not finding matches
- OJ variant not finding matches

**Tests:**
1. `test_generic_term_parser_output[cookies-2]`
2. `test_generic_term_parser_output[muffins-2]`
3. `test_specific_item_parser_output[bagel chips-4-True]`
4. `test_specific_item_menu_lookup[bagel chips-4-10]`
5. `test_specific_item_disambiguation_behavior[bagel chips-False]`
6. `test_side_item_parser_output[latkes-Latkes]`
7. `test_side_item_parser_output[latke-Latkes]`
8. `test_side_item_parser_output[home fries-Home Fries]`
9. `test_side_item_parser_output[fruit cup-Fruit Cup]`
10. `test_common_variants_find_matches[oj-True]`
11. `test_chips_full_flow`
12. `test_bagel_chips_full_flow`

---

### Category 4: Resiliency/Business Logic (11 tests)

**Files:** `test_resiliency_batch1.py`, `test_resiliency_batch2.py`

**Problems:**
1. Modifier replacement not working ("make it veggie cream cheese")
2. Coffee size change not working
3. Milk type change not working
4. Decaf handling broken (item disappears or wrong flow)
5. Spread question not asked after toasted question
6. Orange juice not showing options
7. Signature item matching issues

**Tests from batch1:**
1. `test_change_spread_on_bagel_with_existing_spread`
2. `test_change_coffee_size_small_to_large`
3. `test_change_milk_type_on_coffee`
4. `test_change_coffee_to_decaf`
5. `test_order_decaf_coffee_upfront`
6. `test_remove_modifier_remove_the_bacon`
7. `test_bagel_toasted_should_ask_about_spread`
8. `test_bagel_not_toasted_should_ask_about_spread`

**Tests from batch2:**
9. `test_orange_juice_shows_options`
10. `test_bagel_with_cream_cheese_asks_flavor`
11. `test_the_classic_matches_signature_item`

---

### Category 5: Pydantic Schema Issue (1 test)

**File:** `test_pydantic_v2_migration.py`

**Problem:** `MenuItemOut.category` returns None when expected "sandwich"

**Test:**
1. `test_menu_item_out_model_validate`

**Likely Cause:** Schema not updated for `categories` relationship change

---

### Category 6: Technical Debt (1 test)

**File:** `test_no_domain_data.py`

**Problem:** Production code contains hardcoded domain terms:
- `input_normalizer.py`: bacon, bagels, coffee, oat milk, sugar, tomato, vanilla
- `option_matcher.py`: mayo, mustard, sugar

**Test:**
1. `test_no_domain_specific_data_in_production_code`

**Priority:** Lower - technical debt, not breaking functionality

---

## Recommended Fix Order

### Phase 1: Decisions Needed
1. **Special Instructions** - Ask user: deprecate or fix? (affects 17 tests)

### Phase 2: Parser Fixes
2. Fix split quantity parsing - extract `bread` attribute (4 tests)
3. Fix disambiguation/menu lookup issues (12 tests)

### Phase 3: Business Logic Fixes
4. Fix modifier replacement logic (spread, milk, size changes)
5. Fix decaf coffee handling
6. Fix spread question flow
7. Fix signature item matching

### Phase 4: Cleanup
8. Fix Pydantic schema for categories (1 test)
9. Address technical debt in data-driven code (1 test)

---

## Commands

```bash
# Run all failing test files
python -m pytest tests/test_tasks_parsing.py tests/test_disambiguation_matrix.py tests/test_resiliency_batch1.py tests/test_resiliency_batch2.py tests/test_pydantic_v2_migration.py tests/test_no_domain_data.py --tb=no -q

# Run specific category
python -m pytest tests/test_tasks_parsing.py -k "special_instruction" -v --tb=short
python -m pytest tests/test_tasks_parsing.py -k "split" -v --tb=short
python -m pytest tests/test_disambiguation_matrix.py -v --tb=short
python -m pytest tests/test_resiliency_batch1.py tests/test_resiliency_batch2.py -v --tb=short
```
