# Testing Strategy

## Backend

- Unit tests for business rules
- Service tests
- API integration tests
- Database constraint tests
- Migration tests
- Authorization tests

## Frontend

- Component tests
- Form validation tests
- User workflow tests
- API error-state tests
- Accessibility checks

## Financial testing

Every financial workflow must test:

- Normal case
- Zero values
- Partial payment
- Overpayment
- Duplicate submission
- Invalid dates
- Rounding behavior
- Reversal or void behavior
- Concurrent requests where relevant
