# V1-060 speed test

Made-up history (rows): units 300, customers 3,000, leases 3,000, invoices 33,000, invoice_lines 33,000, payments 32,880, payment_allocations 32,880, receipts 32,880, utility_readings 72,600, audit_events 98,645

Limits: middle time at most 0.5 s, slowest at most 1.0 s, over 10 calls after one warm-up call. Home page: 1.5 s and 2.0 s. Rent nonpayment alerts: 1.0 s and 1.5 s. Reports and registers with no dates (the whole history): 3.0 s and 4.0 s.

| Read | HTTP | Middle (s) | Slowest (s) | Answer size (bytes) | Result |
|---|---|---|---|---|---|
| Units list | 200 | 0.046 | 0.065 | 24,058 | pass |
| Customers list | 200 | 0.061 | 0.072 | 7,867 | pass |
| Leases list | 200 | 0.058 | 0.067 | 44,190 | pass |
| Invoices list | 200 | 0.241 | 0.308 | 84,983 | pass |
| Payments list | 200 | 0.097 | 0.116 | 67,311 | pass |
| Refunds list | 200 | 0.060 | 0.076 | 164 | pass |
| Reservations list | 200 | 0.056 | 0.123 | 119 | pass |
| Rent nonpayment alerts | 200 | 0.515 | 0.644 | 36,892 | pass |
| Initial Rent unpaid alerts | 200 | 0.061 | 0.073 | 255 | pass |
| Unbilled Utility periods | 200 | 0.049 | 0.057 | 138 | pass |
| Waiting for approval | 200 | 0.041 | 0.050 | 164 | pass |
| Customer ledger list | 200 | 0.047 | 0.056 | 4,337 | pass |
| Financial workspaces | 200 | 0.047 | 0.056 | 719 | pass |
| Customer page | 200 | 0.059 | 0.070 | 16,312 | pass |
| Customer account ledger | 200 | 0.278 | 0.311 | 34,476 | pass |
| Customer money summary | 200 | 0.066 | 0.075 | 630 | pass |
| Lease page | 200 | 0.059 | 0.065 | 1,410 | pass |
| Lease timeline | 200 | 0.074 | 0.082 | 111 | pass |
| Unit page | 200 | 0.041 | 0.054 | 563 | pass |
| Unit timeline | 200 | 0.057 | 0.076 | 101 | pass |
| Unit meters | 200 | 0.056 | 0.059 | 1,639 | pass |
| Meter readings | 200 | 0.063 | 0.071 | 18,521 | pass |
| Invoice page | 200 | 0.061 | 0.070 | 1,766 | pass |
| Payment page | 200 | 0.082 | 0.090 | 1,463 | pass |
| Payment receipt | 200 | 0.085 | 0.105 | 1,291 | pass |
| Home page | 200 | 1.298 | 1.469 | 1,075 | pass |
| Payments page (this month) | 200 | 0.197 | 0.280 | 111,319 | pass |
| Receive payment list | 200 | 0.060 | 0.069 | 660 | pass |
| Waiting for approval page | 200 | 0.051 | 0.054 | 203 | pass |
| Move-out list | 200 | 0.045 | 0.055 | 125 | pass |
| Services settings | 200 | 0.046 | 0.058 | 144 | pass |
| Unit inventory | 200 | 0.045 | 0.052 | 270 | pass |
| Total income report | 200 | 0.834 | 1.045 | 7,528 | pass |
| Total payment report | 200 | 0.908 | 1.159 | 8,849 | pass |
| Total electricity report | 200 | 0.071 | 0.077 | 373 | pass |
| Invoice register | 200 | 1.130 | 1.431 | 118,488 | pass |
| Payments register | 200 | 1.761 | 1.878 | 149,628 | pass |
| Credit ledger | 200 | 0.069 | 0.078 | 673 | pass |
| Deposits register | 200 | 0.067 | 0.077 | 655 | pass |
| Unit occupancy | 200 | 0.066 | 0.075 | 71,622 | pass |
| Lease dates | 200 | 0.089 | 0.211 | 80,845 | pass |

Next month's scheduled Rent run (limit 120 s): 4.1 s, status SUCCEEDED, 300 new Rent Invoices: pass.
