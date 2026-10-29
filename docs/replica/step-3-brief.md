# Step 3 brief (owner, 2026-10-29, as recorded in the session)

Step 3: Parking Type and default price.

- Parking Type: the editable Unit Types list in Settings (migration 227) becomes the Parking Types
  list. The owner's Parking Types: Covered $45, Uncovered $35, Motorbike $15, Tuk-Tuk/Food Cart $25.
- Default monthly price per Parking (not per type). It fills the Lease price when staff make a
  Lease for that Parking; staff can change the Lease price. Invoices use the Lease price.
  Changing a Parking's default price never changes existing Leases or Invoices.
- Only users allowed to change rates may change a default price.
- Money is whole USD cents (integer), never floating point.
- Tests first (test-driven-development). Run all tests on this Mac. Report, then stop.

Standing rules: change only the words staff see; keep hidden code names; never delete data;
never touch Property Rental; do not add features that were not asked for; ask one question at a
time with options and a recommendation.
