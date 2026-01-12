# Parallel Work TODOs

Work items that can be done independently of the data-driven order flow refactoring.

## Database

- [ ] Run database integrity migration (`alembic upgrade head`)
  - Adds FK constraints for store_id columns
  - Adds ondelete cascades
  - Adds check constraints for enum columns
  - Adds non-negative constraints for prices/quantities

## FAQ/Question Handling

### Dietary/Allergen Questions
- [ ] "Is this gluten-free?"
- [ ] "Do you have vegan options?"
- [ ] "Does the everything bagel have sesame?" (allergy concern)
- [ ] "What's dairy-free?"
- [ ] "Does this contain nuts?"

### Delivery Info
- [ ] "What's the delivery fee?"
- [ ] "What's the minimum order for delivery?"
- [ ] "How long will delivery take?"

### Payment Questions
- [ ] "Do you take cash?"
- [ ] "Do you accept Apple Pay?"

### Bulk/Catering
- [ ] "Can I order a dozen bagels?"
- [ ] "Do you do catering?"
- [ ] "What's the discount for large orders?"

### Customization
- [ ] "Can I get extra lox?" (upcharge items)
- [ ] "Can I get that without onions?"

### Comparison/Clarification
- [ ] "What's the difference between nova and lox?"
- [ ] "What sizes do you have for coffee?"

### Order Timing
- [ ] "How long will my order take?"
- [ ] "Can I schedule an order for later?"

## Admin Panel Improvements

- [ ] Review admin UX for gaps
- [ ] Add bulk operations (e.g., bulk price updates)
- [ ] Add search/filter to menu management
- [ ] Improve mobile responsiveness

## Analytics Enhancements

- [ ] Order patterns reporting (popular items, time of day)
- [ ] Session abandonment analysis
- [ ] Conversion funnel metrics
- [ ] Revenue reports by store/day/item

## Test Coverage

- [ ] Admin API endpoint tests
- [ ] Edge case tests for order flows
- [ ] Load/performance tests

## Documentation

- [ ] API documentation (OpenAPI/Swagger)
- [ ] User-facing help text improvements
- [ ] Deployment guide

## Performance/Infrastructure

- [ ] Cache loading optimization (currently ~1 minute)
- [ ] Query optimization audit
- [ ] Monitoring/alerting setup
- [ ] CI/CD pipeline improvements
