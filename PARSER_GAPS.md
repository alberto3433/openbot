# Parser Gaps - TODO Tracker

Identified gaps in the deterministic parser based on resiliency testing (batches 9-18).
These phrases currently fall through to LLM fallback and should have deterministic handlers.

## High Priority

### Gratitude & Social Responses
- [x] "thank you" - should acknowledge and continue/complete order
- [x] "thanks" - should acknowledge and continue/complete order
- [x] "sorry" - treated as filler word, parses what follows (e.g., "sorry, I meant X")

### Help & Confusion
- [x] "help" - should provide helpful guidance about ordering
- [x] "I'm confused" - should offer assistance
- [x] "what can you do?" - should explain capabilities

### Abbreviations & Shorthand
- [x] "OJ" - maps to Tropicana Orange Juice
- [x] "SEC" - maps to The Classic BEC (sausage egg and cheese)

## Medium Priority

### Pronoun/Context References
- [ ] "same thing" - should duplicate last item
- [ ] "another one of those" - should add another of last item
- [ ] "make that iced" - should modify last coffee to iced

### Corrections After Misunderstanding
- [ ] "no, I said [X]" - should correct item to X
- [ ] "I meant the [size] one" - should change size
- [ ] "that's not what I ordered" - should ask for clarification

### Affirmative/Negative in Context
- [ ] "yes" / "yeah sure" - should confirm pending question (toasting, etc.)
- [ ] "no" / "nope" - should decline pending option

## Lower Priority

### Dietary & Allergy Questions
- [ ] "is [item] gluten-free?" - should provide dietary info
- [ ] "do you have vegan options?" - should list vegan items
- [ ] "is there dairy in [item]?" - should provide allergen info

### Availability Questions
- [ ] "is the [item] available?" - should check/confirm availability
- [ ] "are you out of [item]?" - should respond about stock
- [ ] "do you have any specials today?" - should list specials or explain

### Partial/Incomplete Orders
- [ ] "I want a" (incomplete) - should prompt for what they want
- [ ] Multi-turn: "coffee" then "large" - should apply size to pending coffee

---

## Test Coverage

| Batch | Category | Tests | Passed | Failed |
|-------|----------|-------|--------|--------|
| 9 | Affirmative/Negative | 3 | 1 | 2 |
| 10 | Gratitude & Social | 3 | 3 | 0 |
| 11 | Dietary & Allergy | 3 | 0 | 3 |
| 12 | Abbreviations | 3 | 3 | 0 |
| 13 | Preparation Preferences | 3 | 3 | 0 |
| 14 | Pronoun/Context | 3 | 0 | 3 |
| 15 | Corrections | 3 | 0 | 3 |
| 16 | Partial/Incomplete | 3 | 1 | 2 |
| 17 | Availability | 3 | 1 | 2 |
| 18 | Help & Confusion | 3 | 3 | 0 |
| **Total** | | **30** | **16** | **14** |

## Notes

- Tests that pass are handled by LLM fallback (works but not deterministic)
- Failures indicate the response doesn't meet expected criteria
- Priority based on frequency of customer usage patterns
- Some items may need menu database updates (dietary info, specials)
