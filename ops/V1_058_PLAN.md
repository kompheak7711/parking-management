# V1-058 plan: the screen rebuild to the owner's design

Started 2026-10-24 (owner: "can you start v1-058 now?"). Source of truth for looks: the owner's mock-up (v43) and DESIGN.md 0.29 (/mnt/project-files/ui-design/). The business rules and docs/006 decide what a screen does. Menu: the order the owner approved on 2026-10-24 (UX Design thread): Home; Daily work (Payments, Invoices, Utilities, Waiting for approval); Tenants (Bookings, Leases with tabs Leases, Letters, Move-out, Customers); Building (Units); Office (Reports, History, Settings). V1.1 items (Visit requests, Birthdays, Unit care) come after V1.

Work branch: claude/project-thread-08txpf. implementation/foundation only with the owner's yes. The login thread (L8) merges first; this branch then takes implementation/foundation in and fixes any App.tsx conflict.

Steps (the owner checks each area from screenshots, then on the Mac):

1. R1 app shell: green menu, top bar (Phnom Penh time, ខ្មែរ / EN), brand colours and fonts as role tokens (light and dark), one page per menu item with its own address; the existing screens move into their pages unchanged. No money logic changes.
2. R1b: the menu shows only the items a user may use (UI-008); needs a small read of the signed-in user's capabilities and Property.
3. R2 Units and Customers. 4. R3 Bookings, Leases, Letters, Move-out. 5. R4 Utilities. 6. R5 Invoices and Payments. 7. R6 Home (eight cards, To-do list). 8. R7 Waiting for approval, Settings (tabs), Users, System health, History. Reports come with V1-057.

Run rules: frontend-only steps run the frontend gates (format, typecheck, lint, all frontend tests, build) and no PostgreSQL run; a step that changes the server or the database runs the affected PostgreSQL tests. One review round per step (three for sign-in or session code). Non-money design points are decided by Claude under the owner's 2026-10-23 22:30 rule and listed in the report; money rules and who-may-do-what over money go to the owner.

## Step log

- R1 (2026-10-24): shell, tokens, pages and tabs built. Old screen tests open their page through the address (openPage); TEST-FE-801 to 809 added. Frontend 1,649 passed. Decided by Claude under the owner's 2026-10-23 22:30 rule: all screens stay mounted and the closed pages are hidden, so a half-typed form survives a page change; Home is a start page until R6; Waiting for approval and History say they come in R7, Reports in V1-057; Khmer names for Tenants, Building and Bookings are new and need the native check.
