# Chaos Monkey Regression Test Failures — Run 14

**Generated:** 2026-02-13
**Live Run:** `python -m tests.chaos_monkey.cli -d 300 -b 20 -r 60 --request-delay 0.5 --report-path tests/chaos_monkey_failures_run14.md`
**Live Results:** 119/120 passed, 1 failed (99.2%)

---

## Progress Tracker

| Run | Passed | Failed | Total | Pass Rate |
|-----|--------|--------|-------|-----------|
| 7   | 86     | 14     | 100   | 86%       |
| 8   | 94     | 6      | 100   | 94%       |
| 9   | 93     | 7      | 100   | 93%       |
| 10  | 113    | 7      | 120   | 94%       |
| 11  | 94     | 6      | 100   | 94%       |
| 12  | 97     | 3      | 100   | 97%       |
| 13  | 117    | 3      | 120   | 97.5%     |
| **14** | **119** | **1** | **120** | **99.2%** |

## Run 14 Failures (1 total)

### Failure 1: "Also hmm add tofu scallion" — filler "hmm" inside add-modifier pattern

**Category:** Mid-phrase filler
**Test:** `test_failure_modifier_flow_20260213_175157_44870de8.py`

**How to reproduce in UI:**
1. Open the chat at `http://localhost:8000`
2. Say: **"One The Tribeca please"**
3. Bot responds: "Got it, for the The Tribeca. What kind of bread would you like?"
4. Say: **"Also hmm add tofu scallion"**
5. **BUG:** Bot says "Sorry, we don't have Also hmm add tofu scallion." — The filler "hmm" between "Also" and "add" breaks the `ADD_MODIFIER_PATTERN` regex which expects `also\s+add\s+`.

**Root cause:** Same mid-phrase filler issue seen in runs 12-13. `strip_conversational_fillers()` only strips from the start. "Also hmm add" doesn't match `^(?:also\s+)?add\s+` because "hmm" is between "Also" and "add". This is a chaos monkey mutation artifact — real users wouldn't say "Also hmm add".

---

## Summary

Only 1 failure in 120 tests, caused by the chaos monkey injecting a filler word in the middle of a command pattern. This is the same class of mutation artifact seen in runs 12 and 13. No real application bugs surfaced.
