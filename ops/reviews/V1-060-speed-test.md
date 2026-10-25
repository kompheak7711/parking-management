# V1-060 speed test

Made-up history (rows): units 300, customers 3,000, leases 3,000, invoices 33,000, invoice_lines 33,000, payments 32,880, payment_allocations 32,880, receipts 32,880, utility_readings 72,600, audit_events 98,640

Limits: middle time at most 0.5 s, slowest at most 1.0 s, over 10 calls after one warm-up call.

| Read | HTTP | Middle (s) | Slowest (s) | Answer size (bytes) | Result |
|---|---|---|---|---|---|
| Units list | 200 | 0.039 | 0.044 | 16,158 | pass |
| Customers list | 200 | 0.055 | 0.065 | 6,861 | pass |
| Leases list | 200 | 0.050 | 0.054 | 44,189 | pass |
| Invoices list | 200 | 0.223 | 0.253 | 84,982 | pass |
| Payments list | 200 | 0.098 | 0.104 | 67,311 | pass |
| Refunds list | 200 | 0.058 | 0.065 | 164 | pass |
| Reservations list | 200 | 0.052 | 0.058 | 119 | pass |
| Rent nonpayment alerts | 200 | 0.441 | 0.482 | 36,904 | pass |
| Initial Rent unpaid alerts | 200 | 0.062 | 0.079 | 255 | pass |
| Unbilled Utility periods | 200 | 0.045 | 0.047 | 138 | pass |
| Waiting for approval | 200 | 0.042 | 0.057 | 164 | pass |
| Customer ledger list | 200 | 0.045 | 0.050 | 4,331 | pass |
| Financial workspaces | 200 | 0.040 | 0.050 | 719 | pass |
| Customer page | 200 | 0.055 | 0.058 | 19,728 | pass |
| Customer account ledger | 200 | 0.306 | 0.379 | 39,338 | pass |
| Customer money summary | 200 | 0.066 | 0.072 | 630 | pass |
| Lease page | 200 | 0.050 | 0.062 | 1,411 | pass |
| Lease timeline | 200 | 0.066 | 0.095 | 111 | pass |
| Unit page | 200 | 0.040 | 0.059 | 407 | pass |
| Unit timeline | 200 | 0.053 | 0.063 | 101 | pass |
| Unit meters | 200 | 0.056 | 0.063 | 1,639 | pass |
| Meter readings | 200 | 0.058 | 0.067 | 18,521 | pass |
| Invoice page | 200 | 0.055 | 0.066 | 1,760 | pass |
| Payment page | 200 | 0.068 | 0.085 | 1,463 | pass |
| Payment receipt | 200 | 0.074 | 0.083 | 1,291 | pass |

Next month's scheduled Rent run (limit 120 s): 3.9 s, status SUCCEEDED, 300 new Rent Invoices: pass.
