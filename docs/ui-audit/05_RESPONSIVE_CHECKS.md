# 05 — Responsive checks (UI v81 round 3)

Owner request 07/11/2026 17:30 (round 3): responsive card grids, one filled button per area, Home Tasks as four cards, list pages where only the table scrolls, and a full check of every screen at five sizes with the result written down per screen. This file is that check. The design v81 mock-up (https://claude.ai/artifact/CLyBzHBQEb9HQrPQMpLDqv, v7) was changed first, then the app on branch `ui-v81` (PR #14).

## 1. How the check was done

- **Sizes:** 390 × 844 (phone), 768 × 1024 (tablet), 1366 × 768, 1440 × 900 and 1920 × 1080 (desktops).
- **Design:** the v81 HTML file opened as a file in Chromium (Playwright), UTF-8, every menu item and every tab: 61 screens × 5 sizes = 305 screenshots. The 390 and 768 screenshots were taken again this way; the garbled characters of round 2 came from the screenshot tool, not from the file.
- **App:** the `ui-v81` build served over HTTPS in the cloud review environment, signed in as the Owner, every menu item and its tabs: 49 screens × 5 sizes = 245 screenshots. Sample data: 15 Units, 14 Customers, 12 signed Leases with their first Invoice and Payment (made through the API, no shortcuts in the database), no utilities, no short stays, no problem reports and no Ledger entries beyond those payments.
- **What a script measured on every screen and size**, from inside the page, after it settled:
  1. Page scrolls sideways (page width above the screen width).
  2. Text cut off: a label, value, note, button, heading, tab, column heading or chip whose text is clipped or ends in "…".
  3. Text on more than 2 lines (notes on a phone may take 3; a page's sentence under its title may wrap).
  4. Card grids: cards per row, the last row, cards of one row with different heights.
  5. Filled (green) buttons on the screen and whether an area has two.
  6. The main table: rows it has, rows fully on screen, whether its area scrolls, whether page and table both scroll ("double scrollbar"), and whether the column headings stick.
  7. Empty room under the page when the page does not scroll.
- **Then the screenshots were looked at**, screen by screen, side by side with the design (`/mnt/project-files/ui-audit/round3/` holds the comparison sheets; a small set is in `screenshots/round3/`).
- **Result per screen and size:** OK (nothing found), Kept (something found that stays on purpose, with the reason), Fix (still to change). The tables in sections 5 and 6 list every screen.

## 2. What changed in round 3

### Card grids (owner point 1)

- Design and app: one rule set for every number-card grid. Phone (under 640 px): Owner money cards 1 per row, other cards 2 per row; a last odd card takes the full width. Tablet (640–1023 px): Owner money 2 per row, other cards 3 per row; a last row of 1 or 2 cards spreads out. Desktop (1024 px and up): as before (4 per row, 3 + 2 and 4 + 3 + 3 balancing).
- Cards in one row share the same height (`align-items: stretch`); a label is clamped at 2 lines, a note at 3 (4 on a phone); a value never wraps.
- On a phone the card icon is hidden, the label is a little smaller and the value scales with the screen width, so nothing is cut off at 390 px.
- Reports cards (`.rp-cards`) follow the same rules.
- Tasks cards: 4 in a row on desktops and tablets, 2 × 2 on a phone.

### Buttons (owner point 2)

- Design and app: a plain button is an outline button (Paper, a dark edge, bold dark words); only the one main action of an area is a filled green button. "Enter meter readings" and "Open the daily sheet" are plain buttons. The chosen part of a switch and a selected pill use the selected-card look (a tint with a green underline), not a green fill, so an area never shows two filled buttons.
- This replaces the light-green button fill of DL-107 part (2) (V1-060 B6). The DL-107 rule "a button never looks like a text box" still holds: a text box has a light grey edge and normal words; a button has a dark edge and bold centred words. The decision log entry goes through another thread (this branch does not edit `docs/`).

### Home: Tasks as cards (owner point 3)

- Four cards in one row: Overdue · Today · This week · Later. Each shows the count and one short line ("Oldest: 34 days late", "Do them today", "Next: in 2 days", "Nothing here"). The Overdue count is red above 0.
- Tapping a card opens that card's list under the cards; only one list is open; the selected card is highlighted like a selected number card on Invoices; tapping it again closes the list.
- When Home opens with overdue items, the Overdue list is open; otherwise no list is open.
- The selected card is in the URL (`#/home?tasks=overdue|today|week|later`), so Back returns to it.

### List pages: the table scrolls, the top stays (owner point 4)

- Desktop and tablet (screen at least 1024 px wide and 700 px tall): the page fits the screen; title, tabs, filters and number cards stay in place; the main table scrolls inside its own area that fills the rest of the screen; its column headings stick at the top of that area; pagination or "Load more" stays at the bottom of the area.
- Short desktop screens (under 1000 px tall, for example 1366 × 768) use a tighter look so the table keeps room: one-line number cards without the icon and note, smaller title, tighter rows and filter boxes.
- Round 12 (12/11/2026): in the tighter look a button, a switch and a number card keep 44 px in height (the owner's 44 px rule; they were 38, 36 and 42 px). A list loses about 20 px of its height on such a screen. The row counts of section 4 were measured before this change.
- Round 13 (13/11/2026): the screen check covers the Invoices list, one Invoice and New Quotation at the five sizes; all pass. The amount-owed box of the Customer card moved to the warm warning ground for 4.5:1 contrast.
- Round 14 (13/11/2026): the screen check covers the Utilities readings list, the Meters tab and one meter at the five sizes; all pass. The reading-day pictures were taken with the browser clock set to 24/11/2026.
- Phones, tablets under 1024 px wide and short screens: the page scrolls normally and only the column headings stick under the top bar. When the table is wider than the screen it scrolls sideways in its box; then the headings scroll with it (a browser limit: a box that scrolls sideways cannot pin its headings to the window).
- When tall blocks above the list leave no room for a table area (less than 240 px), the page scrolls normally and the headings stick under the top bar.
- Back returns to the same scroll position inside the table (kept per page while the app is open).
- Applied to every list page the shell renders: the script picks the visible table with the most rows on the page (never on a record page or in a dialog).

### Other

- A tab strip that scrolls sideways no longer widens the page on a phone (Settings, Short stays).
- Design: the "Messages to send manually" box on Viewing requests folds to one line with its count; the Customers table heading reads "Legal name (last, middle, first)"; the card label "Staff reimbursements due" is "Owed to staff" (design and app) so it fits a phone card in 2 lines.

## 3. Kept differences (on purpose, with the reason)

| What | Where | Why it stays |
|---|---|---|
| Fewer than 8 rows at 1366 × 768 | List pages whose rows have 2 or 3 lines (Viewing requests, Guests, Problem reports, Products, Stock movements, Expenses, Meter readings, Employees, Payroll, Linked tenants, FAQ, Budget) | A 768 px tall screen holds the top bar, tabs, title, number cards and filters; what is left fits 4–7 rows of 2–3 lines. Open question 12 proposes one-line rows with the details on the record page. |
| The page scrolls normally | Grouped pages: Chart of accounts, Journal entries (by day), Financial statements, Month-end close, Storage locations, Settings General | They are several tables or forms on one page, not one list. |
| Tasks: 4 cards in one row on a tablet | Home at 768 px | The owner set 2 × 2 for phones and 4 in a row for desktops; a tablet is wide enough for 4. |
| Notes on 3 lines (4 on a phone) | Number cards with a long note | The owner's wording of the note is kept; the label stays within 2 lines. |
| A page's sentence under its title wraps | Phones | It is a sentence, not a label. |
| Column headings do not stick on a phone when the table scrolls sideways | Wide tables at 390 px | Browser limit (see point 4). On tables that fit the screen they stick. |
| Empty room under a short table | Pages with few rows in the sample data | The table shows all its rows; nothing more to show. |
| Plain buttons look like the design's outline buttons, not DL-107's light green | Everywhere | Owner round 3: outline buttons as in the design. |

## 4. Rows visible on the desktop sizes (the main list pages)

The counts below are rows fully on screen when the page opens, measured on the review build. "Of" is the rows the page has.

| Page | 1366 × 768 design | 1366 × 768 app | 1440 × 900 design | 1440 × 900 app | 1920 × 1080 design | 1920 × 1080 app |
|---|---|---|---|---|---|---|
| Invoices | 8 of 166 | 4 of 12 | 11 of 166 | 6 of 12 | 8 of 166 | 10 of 12 |
| Payments | 3 of 3 | 3 of 12 | 3 of 3 | 6 of 12 | 3 of 3 | 9 of 12 |
| Leases | 9 of 29 | 5 of 12 | 12 of 29 | 8 of 12 | 10 of 29 | 11 of 12 |
| Customers | — | 6 of 14 | — | 9 of 14 | — | 14 of 14 |
| Units | 13 of 28 | 8 of 15 | 9 of 28 | 11 of 15 | 8 of 28 | 10 of 15 |
| Audit log | 4 of 4 | 7 of 50 | 4 of 4 | 9 of 50 | 4 of 4 | 9 of 50 |
| Problem reports | 1 of 15 | — | 3 of 15 | — | 4 of 15 | — |
| Viewing requests | 6 of 8 | — | 6 of 8 | — | 6 of 8 | — |
| Expenses | 4 of 46 | — | 6 of 46 | — | 10 of 46 | — |
| Employees | 2 of 8 | — | 3 of 8 | — | 4 of 8 | — |

"—": the page has no table rows in the sample data (the app) or no main table (grouped pages). The app rows are 2 lines tall on these pages (number and customer, name and phone), so 1366 × 768 shows 4 to 7 of them: open question 12 (one-line rows) is the way to 8 or more on every list page at that size.

## 5. Design v81 (v7): every screen at five sizes

| Size | OK | Kept difference | To fix |
|---|---|---|---|
| 390×844 | 61 | 0 | 0 |
| 768×1024 | 61 | 0 | 0 |
| 1366×768 | 43 | 18 | 0 |
| 1440×900 | 48 | 13 | 0 |
| 1920×1080 | 50 | 11 | 0 |

| Screen | Size | Page scrolls sideways | Text cut off | Text on 3+ lines | Card grids | Filled buttons | Table rows shown | Page and table both scroll | Empty space under the page | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| home | 390×844 | no | none | none | 5 cards, 1/row, 12 cards, 2/row, 4 cards, 2/row | 1 | — | no | 0 | OK |
| home | 768×1024 | no | none | none | 5 cards, 2/row, 12 cards, 3/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| home | 1366×768 | no | none | none | 5 cards, 3/row, 12 cards, 4/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| home | 1440×900 | no | none | none | 5 cards, 3/row, 12 cards, 4/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| home | 1920×1080 | no | none | none | 5 cards, 3/row, 12 cards, 4/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| payments | 390×844 | no | none | none | 8 cards, 2/row | 1 | 0 of 3 on the first screen | no | 0 | OK |
| payments | 768×1024 | no | none | none | 8 cards, 3/row | 1 | 0 of 3 on the first screen | no | 0 | OK |
| payments | 1366×768 | no | none | none | 8 cards, 4/row | 1 | 3 of 3 | no | 180px (nothing more to show) | OK |
| payments | 1440×900 | no | none | none | 8 cards, 4/row | 1 | 3 of 3 | no | 354px (nothing more to show) | OK |
| payments | 1920×1080 | no | none | none | 8 cards, 4/row | 1 | 3 of 3 | no | 186px (nothing more to show) | OK |
| invoices:Invoices | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 166 on the first screen | no | 0 | OK |
| invoices:Invoices | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 2 of 166 on the first screen | no | 0 | OK |
| invoices:Invoices | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 8 of 166 | no | 8px | OK |
| invoices:Invoices | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 11 of 166 | no | 8px | OK |
| invoices:Invoices | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 8 of 166 | no | 16px | OK |
| invoices:Quotations | 390×844 | no | none | none | 3 cards, 1/row | 1 | 0 of 5 on the first screen | no | 0 | OK |
| invoices:Quotations | 768×1024 | no | none | none | 3 cards, 1/row | 1 | 1 of 5 on the first screen | no | 0 | OK |
| invoices:Quotations | 1366×768 | no | none | none | 3 cards, 3/row | 1 | 5 of 5 | no | 157px (nothing more to show) | OK |
| invoices:Quotations | 1440×900 | no | none | none | 3 cards, 3/row | 1 | 5 of 5 | no | 315px (nothing more to show) | OK |
| invoices:Quotations | 1920×1080 | no | none | none | 3 cards, 3/row | 1 | 5 of 5 | no | 306px (nothing more to show) | OK |
| readings:Meter readings | 390×844 | no | none | none | — | 0 | 0 of 23 on the first screen | no | 0 | OK |
| readings:Meter readings | 768×1024 | no | none | none | — | 0 | 4 of 23 on the first screen | no | 0 | OK |
| readings:Meter readings | 1366×768 | no | none | none | — | 0 | 6 of 23 | no | 8px | Kept: Two-line rows (meter and last reading): 6 rows fit at 1366 × 768. One-line rows are open question 12. |
| readings:Meter readings | 1440×900 | no | none | none | — | 0 | 9 of 23 | no | 8px | OK |
| readings:Meter readings | 1920×1080 | no | none | none | — | 0 | 10 of 23 | no | 16px | OK |
| readings:Meters | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 47 on the first screen | no | 0 | OK |
| readings:Meters | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 2 of 47 on the first screen | no | 0 | OK |
| readings:Meters | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 8 of 47 | no | 8px | OK |
| readings:Meters | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 11 of 47 | no | 8px | OK |
| readings:Meters | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 9 of 47 | no | 16px | OK |
| approvals:Financial approvals | 390×844 | no | none | none | 4 cards, 2/row | 0 | 0 of 1 on the first screen | no | 0 | OK |
| approvals:Financial approvals | 768×1024 | no | none | none | 4 cards, 2/row | 0 | 1 of 1 on the first screen | no | 0 | OK |
| approvals:Financial approvals | 1366×768 | no | none | none | 4 cards, 4/row | 0 | 1 of 1 | no | 254px (nothing more to show) | OK |
| approvals:Financial approvals | 1440×900 | no | none | none | 4 cards, 4/row | 0 | 1 of 1 | no | 386px (nothing more to show) | OK |
| approvals:Financial approvals | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | 1 of 1 | no | 394px (nothing more to show) | OK |
| approvals:Field reports | 390×844 | no | none | none | 4 cards, 2/row | 0 | 0 of 1 on the first screen | no | 0 | OK |
| approvals:Field reports | 768×1024 | no | none | none | 4 cards, 2/row | 0 | 1 of 1 on the first screen | no | 0 | OK |
| approvals:Field reports | 1366×768 | no | none | none | 4 cards, 4/row | 0 | 1 of 1 | no | 290px (nothing more to show) | OK |
| approvals:Field reports | 1440×900 | no | none | none | 4 cards, 4/row | 0 | 1 of 1 | no | 422px (nothing more to show) | OK |
| approvals:Field reports | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | 1 of 1 | no | 431px (nothing more to show) | OK |
| approvals:Short-stay approvals | 390×844 | no | none | none | — | 0 | 0 of 1 on the first screen | no | 0 | OK |
| approvals:Short-stay approvals | 768×1024 | no | none | none | — | 0 | 1 of 1 on the first screen | no | 0 | OK |
| approvals:Short-stay approvals | 1366×768 | no | none | none | — | 0 | 1 of 1 | no | 0 | OK |
| approvals:Short-stay approvals | 1440×900 | no | none | none | — | 0 | 1 of 1 | no | 70px (nothing more to show) | OK |
| approvals:Short-stay approvals | 1920×1080 | no | none | none | — | 0 | 1 of 1 | no | 237px (nothing more to show) | OK |
| reservations:Viewing requests | 390×844 | no | none | none | 4 cards, 2/row | 0 | 0 of 8 on the first screen | no | 0 | OK |
| reservations:Viewing requests | 768×1024 | no | none | none | 4 cards, 2/row | 0 | 2 of 8 on the first screen | no | 0 | OK |
| reservations:Viewing requests | 1366×768 | no | none | none | 4 cards, 4/row | 0 | 6 of 8 | no | 0 | Kept: Three-line rows (request, customer, visit) and a block under the list: 6 rows fit. One-line rows are open question 12. |
| reservations:Viewing requests | 1440×900 | no | none | none | 4 cards, 4/row | 0 | 6 of 8 | no | 9px | Kept: Three-line rows (request, customer, visit) and a block under the list: 6 rows fit. One-line rows are open question 12. |
| reservations:Viewing requests | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | 6 of 8 | no | 16px | Kept: Three-line rows (request, customer, visit) and a block under the list: 6 rows fit. One-line rows are open question 12. |
| reservations:Viewing dashboard | 390×844 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| reservations:Viewing dashboard | 768×1024 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| reservations:Viewing dashboard | 1366×768 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| reservations:Viewing dashboard | 1440×900 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| reservations:Viewing dashboard | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| reservations:Reservations | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 5 on the first screen | no | 0 | OK |
| reservations:Reservations | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 2 of 5 on the first screen | no | 0 | OK |
| reservations:Reservations | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 5 of 5 | no | 114px (nothing more to show) | OK |
| reservations:Reservations | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 5 of 5 | no | 246px (nothing more to show) | OK |
| reservations:Reservations | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 5 of 5 | no | 238px (nothing more to show) | OK |
| stays:Calendar | 390×844 | no | none | none | — | 1 | — | no | 0 | OK |
| stays:Calendar | 768×1024 | no | none | none | — | 1 | — | no | 0 | OK |
| stays:Calendar | 1366×768 | no | none | none | — | 1 | — | no | 0 | OK |
| stays:Calendar | 1440×900 | no | none | none | — | 1 | — | no | 0 | OK |
| stays:Calendar | 1920×1080 | no | none | none | — | 1 | — | no | 0 | OK |
| stays:Bookings | 390×844 | no | none | none | — | 1 | 0 of 5 on the first screen | no | 0 | OK |
| stays:Bookings | 768×1024 | no | none | none | — | 1 | 1 of 5 on the first screen | no | 0 | OK |
| stays:Bookings | 1366×768 | no | none | none | — | 1 | 5 of 5 | no | 49px (nothing more to show) | OK |
| stays:Bookings | 1440×900 | no | none | none | — | 1 | 5 of 5 | no | 181px (nothing more to show) | OK |
| stays:Bookings | 1920×1080 | no | none | none | — | 1 | 5 of 5 | no | 367px (nothing more to show) | OK |
| stays:Quotes | 390×844 | no | none | none | — | 0 | 1 of 1 on the first screen | no | 0 | OK |
| stays:Quotes | 768×1024 | no | none | none | — | 0 | 1 of 1 on the first screen | no | 0 | OK |
| stays:Quotes | 1366×768 | no | none | none | — | 0 | 1 of 1 | no | 286px (nothing more to show) | OK |
| stays:Quotes | 1440×900 | no | none | none | — | 0 | 1 of 1 | no | 418px (nothing more to show) | OK |
| stays:Quotes | 1920×1080 | no | none | none | — | 0 | 1 of 1 | no | 556px (nothing more to show) | OK |
| stays:Guests | 390×844 | no | none | none | — | 0 | 0 of 14 on the first screen | no | 0 | OK |
| stays:Guests | 768×1024 | no | none | none | — | 0 | 1 of 14 on the first screen | no | 0 | OK |
| stays:Guests | 1366×768 | no | none | none | — | 0 | 4 of 14 | no | 45px | Kept: Two-line rows (guest and phone) and a notice above the list. One-line rows are open question 12. |
| stays:Guests | 1440×900 | no | none | none | — | 0 | 6 of 14 | no | 45px | Kept: Two-line rows (guest and phone) and a notice above the list. One-line rows are open question 12. |
| stays:Guests | 1920×1080 | no | none | none | — | 0 | 7 of 14 | no | 16px | Kept: Two-line rows (guest and phone) and a notice above the list. One-line rows are open question 12. |
| stays:Housekeeping | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| stays:Housekeeping | 768×1024 | no | none | none | — | 0 | — | no | 0 | OK |
| stays:Housekeeping | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| stays:Housekeeping | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| stays:Housekeeping | 1920×1080 | no | none | none | — | 0 | — | no | 0 | OK |
| stays:Weekly report | 390×844 | no | none | none | — | 0 | 0 of 6 on the first screen | no | 0 | OK |
| stays:Weekly report | 768×1024 | no | none | none | — | 0 | 0 of 6 on the first screen | no | 0 | OK |
| stays:Weekly report | 1366×768 | no | none | none | — | 0 | 6 of 6 | no | 0 | OK |
| stays:Weekly report | 1440×900 | no | none | none | — | 0 | 6 of 6 | no | 0 | OK |
| stays:Weekly report | 1920×1080 | no | none | none | — | 0 | 6 of 6 | no | 0 | OK |
| stays:Booking sites | 390×844 | no | none | none | — | 1 | 0 of 6 on the first screen | no | 0 | OK |
| stays:Booking sites | 768×1024 | no | none | none | — | 1 | 1 of 6 on the first screen | no | 0 | OK |
| stays:Booking sites | 1366×768 | no | none | none | — | 1 | 2 of 6 | no | 45px | OK |
| stays:Booking sites | 1440×900 | no | none | none | — | 1 | 3 of 6 | no | 45px | OK |
| stays:Booking sites | 1920×1080 | no | none | none | — | 1 | 5 of 6 | no | 16px | OK |
| leases:Leases | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 29 on the first screen | no | 0 | OK |
| leases:Leases | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 5 of 29 on the first screen | no | 0 | OK |
| leases:Leases | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 9 of 29 | no | 8px | OK |
| leases:Leases | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 12 of 29 | no | 8px | OK |
| leases:Leases | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 10 of 29 | no | 16px | OK |
| leases:Notices | 390×844 | no | none | none | 4 cards, 2/row | 0 | 0 of 2 on the first screen | no | 0 | OK |
| leases:Notices | 768×1024 | no | none | none | 4 cards, 2/row | 0 | 1 of 2 on the first screen | no | 0 | OK |
| leases:Notices | 1366×768 | no | none | none | 4 cards, 4/row | 0 | 2 of 2 | no | 0 | OK |
| leases:Notices | 1440×900 | no | none | none | 4 cards, 4/row | 0 | 2 of 2 | no | 22px (nothing more to show) | OK |
| leases:Notices | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | 2 of 2 | no | 95px (nothing more to show) | OK |
| leases:Move-outs | 390×844 | no | none | none | 4 cards, 2/row | 0 | 0 of 6 on the first screen | no | 0 | OK |
| leases:Move-outs | 768×1024 | no | none | none | 4 cards, 2/row | 0 | 3 of 6 on the first screen | no | 0 | OK |
| leases:Move-outs | 1366×768 | no | none | none | 4 cards, 4/row | 0 | 6 of 6 | no | 23px (nothing more to show) | OK |
| leases:Move-outs | 1440×900 | no | none | none | 4 cards, 4/row | 0 | 6 of 6 | no | 155px (nothing more to show) | OK |
| leases:Move-outs | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | 6 of 6 | no | 158px (nothing more to show) | OK |
| customers:Customers | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 35 on the first screen | no | 0 | OK |
| customers:Customers | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 2 of 35 on the first screen | no | 0 | OK |
| customers:Customers | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 10 of 35 | no | 9px | OK |
| customers:Customers | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 14 of 35 | no | 9px | OK |
| customers:Customers | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 12 of 35 | no | 16px | OK |
| customers:Birthdays | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| customers:Birthdays | 768×1024 | no | none | none | — | 0 | — | no | 0 | OK |
| customers:Birthdays | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| customers:Birthdays | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| customers:Birthdays | 1920×1080 | no | none | none | — | 0 | — | no | 0 | OK |
| units | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 28 on the first screen | no | 0 | OK |
| units | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 4 of 28 on the first screen | no | 0 | OK |
| units | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 13 of 28 | no | 0 | OK |
| units | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 9 of 28 | no | 8px | OK |
| units | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 8 of 28 | no | 16px | OK |
| inspections:Inspections | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 6 on the first screen | no | 0 | OK |
| inspections:Inspections | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 2 of 6 on the first screen | no | 0 | OK |
| inspections:Inspections | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 2 of 6 | no | 0 | OK |
| inspections:Inspections | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 6 of 6 | no | 0 | OK |
| inspections:Inspections | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 6 of 6 | no | 0 | OK |
| treqs:Reports | 390×844 | no | none | none | — | 1 | 0 of 15 on the first screen | no | 0 | OK |
| treqs:Reports | 768×1024 | no | none | none | — | 1 | 0 of 15 on the first screen | no | 0 | OK |
| treqs:Reports | 1366×768 | no | none | none | — | 1 | 1 of 15 | no | 0 | Kept: Two notices, four filters and the state pills sit above the list; the rows have two lines. One-line rows are open question 12. |
| treqs:Reports | 1440×900 | no | none | none | — | 1 | 3 of 15 | no | 0 | Kept: Two notices, four filters and the state pills sit above the list; the rows have two lines. One-line rows are open question 12. |
| treqs:Reports | 1920×1080 | no | none | none | — | 1 | 4 of 15 | no | 16px | Kept: Two notices, four filters and the state pills sit above the list; the rows have two lines. One-line rows are open question 12. |
| treqs:Monthly report | 390×844 | no | none | none | — | 0 | 0 of 7 on the first screen | no | 0 | OK |
| treqs:Monthly report | 768×1024 | no | none | none | — | 0 | 0 of 7 on the first screen | no | 0 | OK |
| treqs:Monthly report | 1366×768 | no | none | none | — | 0 | 0 of 7 | no | 0 | OK |
| treqs:Monthly report | 1440×900 | no | none | none | — | 0 | 0 of 7 | no | 0 | OK |
| treqs:Monthly report | 1920×1080 | no | none | none | — | 0 | 0 of 7 | no | 0 | OK |
| products:Products | 390×844 | no | none | none | 3 cards, 1/row | 1 | 0 of 18 on the first screen | no | 0 | OK |
| products:Products | 768×1024 | no | none | none | 3 cards, 1/row | 1 | 0 of 18 on the first screen | no | 0 | OK |
| products:Products | 1366×768 | no | none | none | 3 cards, 3/row | 1 | 5 of 18 | no | 8px | Kept: Two-line rows (product and code). One-line rows are open question 12. |
| products:Products | 1440×900 | no | none | none | 3 cards, 3/row | 1 | 9 of 18 | no | 8px | OK |
| products:Products | 1920×1080 | no | none | none | 3 cards, 3/row | 1 | 7 of 18 | no | 16px | Kept: Two-line rows (product and code). One-line rows are open question 12. |
| products:Stock movements | 390×844 | no | none | none | — | 1 | 2 of 60 on the first screen | no | 0 | OK |
| products:Stock movements | 768×1024 | no | none | none | — | 1 | 5 of 60 on the first screen | no | 0 | OK |
| products:Stock movements | 1366×768 | no | none | none | — | 1 | 3 of 60 | no | 8px | Kept: Two-line rows and a filter row. One-line rows are open question 12. |
| products:Stock movements | 1440×900 | no | none | none | — | 1 | 6 of 60 | no | 8px | Kept: Two-line rows and a filter row. One-line rows are open question 12. |
| products:Stock movements | 1920×1080 | no | none | none | — | 1 | 12 of 60 | no | 16px | OK |
| products:Storage locations | 390×844 | no | none | none | — | 0 | 0 of 38 on the first screen | no | 0 | OK |
| products:Storage locations | 768×1024 | no | none | none | — | 0 | 0 of 38 on the first screen | no | 0 | OK |
| products:Storage locations | 1366×768 | no | none | none | — | 0 | 0 of 38 | no | 0 | Kept: A grouped page (one table per place): the page scrolls normally. |
| products:Storage locations | 1440×900 | no | none | none | — | 0 | 4 of 38 | no | 0 | Kept: A grouped page (one table per place): the page scrolls normally. |
| products:Storage locations | 1920×1080 | no | none | none | — | 0 | 6 of 38 | no | 16px | Kept: A grouped page (one table per place): the page scrolls normally. |
| ledger:Expense requests | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 6 on the first screen | no | 0 | OK |
| ledger:Expense requests | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 0 of 6 on the first screen | no | 0 | OK |
| ledger:Expense requests | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 0 of 6 | no | 0 | OK |
| ledger:Expense requests | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 3 of 6 | no | 0 | OK |
| ledger:Expense requests | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 3 of 6 | no | 0 | OK |
| ledger:Expenses | 390×844 | no | none | none | — | 1 | 1 of 46 on the first screen | no | 0 | OK |
| ledger:Expenses | 768×1024 | no | none | none | — | 1 | 3 of 46 on the first screen | no | 0 | OK |
| ledger:Expenses | 1366×768 | no | none | none | — | 1 | 4 of 46 | no | 8px | Kept: Two-line rows (expense and supplier). One-line rows are open question 12. |
| ledger:Expenses | 1440×900 | no | none | none | — | 1 | 6 of 46 | no | 45px | Kept: Two-line rows (expense and supplier). One-line rows are open question 12. |
| ledger:Expenses | 1920×1080 | no | none | none | — | 1 | 10 of 46 | no | 16px | OK |
| ledger:Supplier bills | 390×844 | no | none | none | 3 cards, 2/row | 1 | 0 of 3 on the first screen | no | 0 | OK |
| ledger:Supplier bills | 768×1024 | no | none | none | 3 cards, 3/row | 1 | 2 of 3 on the first screen | no | 0 | OK |
| ledger:Supplier bills | 1366×768 | no | none | none | 3 cards, 3/row | 1 | 2 of 3 | no | 8px | OK |
| ledger:Supplier bills | 1440×900 | no | none | none | 3 cards, 3/row | 1 | 3 of 3 | no | 188px (nothing more to show) | OK |
| ledger:Supplier bills | 1920×1080 | no | none | none | 3 cards, 3/row | 1 | 3 of 3 | no | 202px (nothing more to show) | OK |
| ledger:Journal entries | 390×844 | no | none | none | — | 1 | 0 of 80 on the first screen | no | 0 | OK |
| ledger:Journal entries | 768×1024 | no | none | none | — | 1 | 0 of 80 on the first screen | no | 0 | OK |
| ledger:Journal entries | 1366×768 | no | none | none | — | 1 | 0 of 80 | no | 0 | Kept: Grouped by day with a total under each day: the page scrolls normally. |
| ledger:Journal entries | 1440×900 | no | none | none | — | 1 | 0 of 80 | no | 0 | Kept: Grouped by day with a total under each day: the page scrolls normally. |
| ledger:Journal entries | 1920×1080 | no | none | none | — | 1 | 3 of 80 | no | 0 | Kept: Grouped by day with a total under each day: the page scrolls normally. |
| ledger:Needs check · 4 | 390×844 | no | none | none | — | 0 | 0 of 4 on the first screen | no | 0 | OK |
| ledger:Needs check · 4 | 768×1024 | no | none | none | — | 0 | 0 of 4 on the first screen | no | 0 | OK |
| ledger:Needs check · 4 | 1366×768 | no | none | none | — | 0 | 0 of 4 | no | 0 | OK |
| ledger:Needs check · 4 | 1440×900 | no | none | none | — | 0 | 0 of 4 | no | 0 | OK |
| ledger:Needs check · 4 | 1920×1080 | no | none | none | — | 0 | 1 of 4 | no | 0 | OK |
| ledger:Chart of accounts | 390×844 | no | none | none | — | 0 | 0 of 19 on the first screen | no | 0 | OK |
| ledger:Chart of accounts | 768×1024 | no | none | none | — | 0 | 0 of 19 on the first screen | no | 0 | OK |
| ledger:Chart of accounts | 1366×768 | no | none | none | — | 0 | 0 of 19 | no | 0 | Kept: Grouped by account type, one table per group: the page scrolls normally. |
| ledger:Chart of accounts | 1440×900 | no | none | none | — | 0 | 0 of 19 | no | 0 | Kept: Grouped by account type, one table per group: the page scrolls normally. |
| ledger:Chart of accounts | 1920×1080 | no | none | none | — | 0 | 0 of 19 | no | 0 | Kept: Grouped by account type, one table per group: the page scrolls normally. |
| ledger:Financial statements | 390×844 | no | none | none | — | 0 | 0 of 30 on the first screen | no | 0 | OK |
| ledger:Financial statements | 768×1024 | no | none | none | — | 0 | 2 of 30 on the first screen | no | 0 | OK |
| ledger:Financial statements | 1366×768 | no | none | none | — | 0 | 3 of 30 | no | 0 | Kept: Several statements on one page: the page scrolls normally. |
| ledger:Financial statements | 1440×900 | no | none | none | — | 0 | 9 of 30 | no | 0 | OK |
| ledger:Financial statements | 1920×1080 | no | none | none | — | 0 | 10 of 30 | no | 16px | OK |
| ledger:Budget | 390×844 | no | none | none | — | 0 | 1 of 19 on the first screen | no | 0 | OK |
| ledger:Budget | 768×1024 | no | none | none | — | 0 | 6 of 19 on the first screen | no | 0 | OK |
| ledger:Budget | 1366×768 | no | none | none | — | 0 | 6 of 19 | no | 0 | Kept: A budget line per account with two-line rows: 6 rows fit at 1366 × 768. |
| ledger:Budget | 1440×900 | no | none | none | — | 0 | 8 of 19 | no | 73px | OK |
| ledger:Budget | 1920×1080 | no | none | none | — | 0 | 10 of 19 | no | 16px | OK |
| ledger:Fixed assets | 390×844 | no | none | none | — | 1 | 1 of 4 on the first screen | no | 0 | OK |
| ledger:Fixed assets | 768×1024 | no | none | none | — | 1 | 3 of 4 on the first screen | no | 0 | OK |
| ledger:Fixed assets | 1366×768 | no | none | none | — | 1 | 3 of 4 | no | 8px | OK |
| ledger:Fixed assets | 1440×900 | no | none | none | — | 1 | 4 of 4 | no | 168px (nothing more to show) | OK |
| ledger:Fixed assets | 1920×1080 | no | none | none | — | 1 | 4 of 4 | no | 307px (nothing more to show) | OK |
| ledger:Bank and cash | 390×844 | no | none | none | — | 1 | 0 of 4 on the first screen | no | 0 | OK |
| ledger:Bank and cash | 768×1024 | no | none | none | — | 1 | 0 of 4 on the first screen | no | 0 | OK |
| ledger:Bank and cash | 1366×768 | no | none | none | — | 1 | 0 of 4 | no | 0 | OK |
| ledger:Bank and cash | 1440×900 | no | none | none | — | 1 | 0 of 4 | no | 0 | OK |
| ledger:Bank and cash | 1920×1080 | no | none | none | — | 1 | 0 of 4 | no | 0 | OK |
| ledger:Month-end close | 390×844 | no | none | none | — | 0 | 0 of 14 on the first screen | no | 0 | OK |
| ledger:Month-end close | 768×1024 | no | none | none | — | 0 | 0 of 14 on the first screen | no | 0 | OK |
| ledger:Month-end close | 1366×768 | no | none | none | — | 0 | 0 of 14 | no | 0 | Kept: A checklist above the table: the page scrolls normally. |
| ledger:Month-end close | 1440×900 | no | none | none | — | 0 | 0 of 14 | no | 0 | Kept: A checklist above the table: the page scrolls normally. |
| ledger:Month-end close | 1920×1080 | no | none | none | — | 0 | 0 of 14 | no | 0 | Kept: A checklist above the table: the page scrolls normally. |
| reports | 390×844 | no | none | none | 4 cards, 2/row, 9 cards, 2/row | 0 | — | no | 0 | OK |
| reports | 768×1024 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| reports | 1366×768 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| reports | 1440×900 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| reports | 1920×1080 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| history | 390×844 | no | none | none | — | 1 | 0 of 64 on the first screen | no | 0 | OK |
| history | 768×1024 | no | none | none | — | 1 | 6 of 64 on the first screen | no | 0 | OK |
| history | 1366×768 | no | none | none | — | 1 | 8 of 64 | no | 8px | OK |
| history | 1440×900 | no | none | none | — | 1 | 12 of 64 | no | 8px | OK |
| history | 1920×1080 | no | none | none | — | 1 | 13 of 64 | no | 16px | OK |
| staff:Employees | 390×844 | no | none | none | — | 1 | 0 of 8 on the first screen | no | 0 | OK |
| staff:Employees | 768×1024 | no | none | none | — | 1 | 1 of 8 on the first screen | no | 0 | OK |
| staff:Employees | 1366×768 | no | none | none | — | 1 | 2 of 8 | no | 0 | Kept: The 'New staff from Telegram' box (people to link) sits above the list, and rows have two lines. |
| staff:Employees | 1440×900 | no | none | none | — | 1 | 3 of 8 | no | 8px | Kept: The 'New staff from Telegram' box (people to link) sits above the list, and rows have two lines. |
| staff:Employees | 1920×1080 | no | none | none | — | 1 | 4 of 8 | no | 16px | Kept: The 'New staff from Telegram' box (people to link) sits above the list, and rows have two lines. |
| staff:Salary loans | 390×844 | no | none | none | — | 1 | 0 of 3 on the first screen | no | 0 | OK |
| staff:Salary loans | 768×1024 | no | none | none | — | 1 | 2 of 3 on the first screen | no | 0 | OK |
| staff:Salary loans | 1366×768 | no | none | none | — | 1 | 3 of 3 | no | 151px (nothing more to show) | OK |
| staff:Salary loans | 1440×900 | no | none | none | — | 1 | 3 of 3 | no | 283px (nothing more to show) | OK |
| staff:Salary loans | 1920×1080 | no | none | none | — | 1 | 3 of 3 | no | 462px (nothing more to show) | OK |
| staff:Payroll | 390×844 | no | none | none | — | 1 | 0 of 8 on the first screen | no | 0 | OK |
| staff:Payroll | 768×1024 | no | none | none | — | 1 | 0 of 8 on the first screen | no | 0 | OK |
| staff:Payroll | 1366×768 | no | none | none | — | 1 | 4 of 8 | no | 0 | Kept: The pay period, the four step cards and two-line rows sit above and in the list. |
| staff:Payroll | 1440×900 | no | none | none | — | 1 | 4 of 8 | no | 8px | Kept: The pay period, the four step cards and two-line rows sit above and in the list. |
| staff:Payroll | 1920×1080 | no | none | none | — | 1 | 6 of 8 | no | 16px | Kept: The pay period, the four step cards and two-line rows sit above and in the list. |
| staff:Attendance | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| staff:Attendance | 768×1024 | no | none | none | — | 0 | — | no | 0 | OK |
| staff:Attendance | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| staff:Attendance | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| staff:Attendance | 1920×1080 | no | none | none | — | 0 | — | no | 0 | OK |
| telegram:Linked tenants | 390×844 | no | none | none | — | 0 | 0 of 8 on the first screen | no | 0 | OK |
| telegram:Linked tenants | 768×1024 | no | none | none | — | 0 | 1 of 8 on the first screen | no | 0 | OK |
| telegram:Linked tenants | 1366×768 | no | none | none | — | 0 | 5 of 8 | no | 0 | Kept: A notice above the list and three-line rows (account, customer, next step). |
| telegram:Linked tenants | 1440×900 | no | none | none | — | 0 | 7 of 8 | no | 0 | Kept: A notice above the list and three-line rows (account, customer, next step). |
| telegram:Linked tenants | 1920×1080 | no | none | none | — | 0 | 8 of 8 | no | 0 | OK |
| telegram:Contact office | 390×844 | no | none | none | — | 0 | 0 of 2 on the first screen | no | 0 | OK |
| telegram:Contact office | 768×1024 | no | none | none | — | 0 | 2 of 2 on the first screen | no | 0 | OK |
| telegram:Contact office | 1366×768 | no | none | none | — | 0 | 2 of 2 | no | 207px (nothing more to show) | OK |
| telegram:Contact office | 1440×900 | no | none | none | — | 0 | 2 of 2 | no | 339px (nothing more to show) | OK |
| telegram:Contact office | 1920×1080 | no | none | none | — | 0 | 2 of 2 | no | 488px (nothing more to show) | OK |
| telegram:FAQ | 390×844 | no | none | none | — | 1 | 0 of 8 on the first screen | no | 0 | OK |
| telegram:FAQ | 768×1024 | no | none | none | — | 1 | 2 of 8 on the first screen | no | 0 | OK |
| telegram:FAQ | 1366×768 | no | none | none | — | 1 | 7 of 8 | no | 8px | Kept: Two-line rows (question and answer): 7 rows fit at 1366 × 768. |
| telegram:FAQ | 1440×900 | no | none | none | — | 1 | 8 of 8 | no | 158px (nothing more to show) | OK |
| telegram:FAQ | 1920×1080 | no | none | none | — | 1 | 8 of 8 | no | 210px (nothing more to show) | OK |
| telegram:Telegram health | 390×844 | no | none | none | — | 0 | 0 of 6 on the first screen | no | 0 | OK |
| telegram:Telegram health | 768×1024 | no | none | none | — | 0 | 0 of 6 on the first screen | no | 0 | OK |
| telegram:Telegram health | 1366×768 | no | none | none | — | 0 | 0 of 6 | no | 0 | OK |
| telegram:Telegram health | 1440×900 | no | none | none | — | 0 | 0 of 6 | no | 0 | OK |
| telegram:Telegram health | 1920×1080 | no | none | none | — | 0 | 0 of 6 | no | 0 | OK |
| access:Users | 390×844 | no | none | none | — | 1 | 0 of 5 on the first screen | no | 0 | OK |
| access:Users | 768×1024 | no | none | none | — | 1 | 2 of 5 on the first screen | no | 0 | OK |
| access:Users | 1366×768 | no | none | none | — | 1 | 5 of 5 | no | 159px (nothing more to show) | OK |
| access:Users | 1440×900 | no | none | none | — | 1 | 5 of 5 | no | 291px (nothing more to show) | OK |
| access:Users | 1920×1080 | no | none | none | — | 1 | 5 of 5 | no | 370px (nothing more to show) | OK |
| access:Roles | 390×844 | no | none | none | — | 0 | 1 of 4 on the first screen | no | 0 | OK |
| access:Roles | 768×1024 | no | none | none | — | 0 | 4 of 4 on the first screen | no | 0 | OK |
| access:Roles | 1366×768 | no | none | none | — | 0 | 4 of 4 | no | 161px (nothing more to show) | OK |
| access:Roles | 1440×900 | no | none | none | — | 0 | 4 of 4 | no | 293px (nothing more to show) | OK |
| access:Roles | 1920×1080 | no | none | none | — | 0 | 4 of 4 | no | 380px (nothing more to show) | OK |
| access:Sign-in and security | 390×844 | no | none | none | — | 0 | 0 of 5 on the first screen | no | 0 | OK |
| access:Sign-in and security | 768×1024 | no | none | none | — | 0 | 0 of 5 on the first screen | no | 0 | OK |
| access:Sign-in and security | 1366×768 | no | none | none | — | 0 | 1 of 5 | no | 0 | OK |
| access:Sign-in and security | 1440×900 | no | none | none | — | 0 | 4 of 5 | no | 0 | OK |
| access:Sign-in and security | 1920×1080 | no | none | none | — | 0 | 5 of 5 | no | 103px (nothing more to show) | OK |
| access:History | 390×844 | no | none | none | — | 0 | 2 of 4 on the first screen | no | 0 | OK |
| access:History | 768×1024 | no | none | none | — | 0 | 4 of 4 on the first screen | no | 0 | OK |
| access:History | 1366×768 | no | none | none | — | 0 | 4 of 4 | no | 246px (nothing more to show) | OK |
| access:History | 1440×900 | no | none | none | — | 0 | 4 of 4 | no | 473px (nothing more to show) | OK |
| access:History | 1920×1080 | no | none | none | — | 0 | 4 of 4 | no | 554px (nothing more to show) | OK |
| settings:General | 390×844 | no | none | none | — | 1 | 0 of 34 on the first screen | no | 0 | OK |
| settings:General | 768×1024 | no | none | none | — | 1 | 0 of 34 on the first screen | no | 0 | OK |
| settings:General | 1366×768 | no | none | none | — | 1 | 0 of 34 | no | 0 | Kept: A settings page with forms and a table: the page scrolls normally. |
| settings:General | 1440×900 | no | none | none | — | 1 | 0 of 34 | no | 0 | Kept: A settings page with forms and a table: the page scrolls normally. |
| settings:General | 1920×1080 | no | none | none | — | 1 | 0 of 34 | no | 0 | Kept: A settings page with forms and a table: the page scrolls normally. |
| settings:Utility rates | 390×844 | no | none | none | — | 1 | 1 of 4 on the first screen | no | 0 | OK |
| settings:Utility rates | 768×1024 | no | none | none | — | 1 | 4 of 4 on the first screen | no | 0 | OK |
| settings:Utility rates | 1366×768 | no | none | none | — | 1 | 4 of 4 | no | 0 | OK |
| settings:Utility rates | 1440×900 | no | none | none | — | 1 | 4 of 4 | no | 0 | OK |
| settings:Utility rates | 1920×1080 | no | none | none | — | 1 | 4 of 4 | no | 0 | OK |
| settings:Monthly services | 390×844 | no | none | none | — | 1 | 0 of 1 on the first screen | no | 0 | OK |
| settings:Monthly services | 768×1024 | no | none | none | — | 1 | 1 of 1 on the first screen | no | 0 | OK |
| settings:Monthly services | 1366×768 | no | none | none | — | 1 | 1 of 1 | no | 0 | OK |
| settings:Monthly services | 1440×900 | no | none | none | — | 1 | 1 of 1 | no | 0 | OK |
| settings:Monthly services | 1920×1080 | no | none | none | — | 1 | 1 of 1 | no | 0 | OK |
| settings:Unit setup | 390×844 | no | none | none | — | 1 | — | no | 0 | OK |
| settings:Unit setup | 768×1024 | no | none | none | — | 1 | — | no | 0 | OK |
| settings:Unit setup | 1366×768 | no | none | none | — | 1 | — | no | 0 | OK |
| settings:Unit setup | 1440×900 | no | none | none | — | 1 | — | no | 0 | OK |
| settings:Unit setup | 1920×1080 | no | none | none | — | 1 | — | no | 0 | OK |
| settings:System health | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 768×1024 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 1920×1080 | no | none | none | — | 0 | — | no | 0 | OK |

## 6. App (branch ui-v81): every screen at five sizes

| Size | OK | Kept difference | To fix |
|---|---|---|---|
| 390×844 | 48 | 1 | 0 |
| 768×1024 | 48 | 1 | 0 |
| 1366×768 | 42 | 7 | 0 |
| 1440×900 | 45 | 4 | 0 |
| 1920×1080 | 48 | 1 | 0 |

| Screen | Size | Page scrolls sideways | Text cut off | Text on 3+ lines | Card grids | Filled buttons | Table rows shown | Page and table both scroll | Empty space under the page | Result |
|---|---|---|---|---|---|---|---|---|---|---|
| home | 390×844 | no | none | none | 5 cards, 1/row, 10 cards, 2/row, 4 cards, 2/row | 1 | — | no | 0 | OK |
| home | 768×1024 | no | none | none | 5 cards, 2/row, 10 cards, 3/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| home | 1366×768 | no | none | none | 5 cards, 3/row, 10 cards, 4/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| home | 1440×900 | no | none | none | 5 cards, 3/row, 10 cards, 4/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| home | 1920×1080 | no | none | none | 5 cards, 3/row, 10 cards, 4/row, 4 cards, 4/row | 1 | — | no | 0 | OK |
| payments | 390×844 | no | none | Cleaning, damage and other one-time charges 0 payments (4 lines) | 8 cards, 2/row | 1 | 0 of 12 on the first screen | no | 0 | Kept: The notes on the payment-kind cards keep the owner's wording (for example "Cleaning, damage and other one-time charges") and take 3 short lines on a phone; the labels stay within 2 lines. |
| payments | 768×1024 | no | none | Trash Collection and other Services 0 payments (3 lines); Added by the app after the Due Date 0 payments (3 lines) | 8 cards, 3/row | 1 | 0 of 12 on the first screen | no | 0 | Kept: The notes on the payment-kind cards take 3 lines at 3 cards per row; the labels stay within 2 lines. |
| payments | 1366×768 | no | none | none | 8 cards, 4/row | 1 | 3 of 12 | no | 10px | Kept: Two-line rows (payment and customer) under two rows of cards. One-line rows are open question 12. |
| payments | 1440×900 | no | none | none | 8 cards, 4/row | 1 | 6 of 12 | no | 10px | Kept: Two-line rows (payment and customer) under two rows of cards. One-line rows are open question 12. |
| payments | 1920×1080 | no | none | none | 8 cards, 4/row | 1 | 9 of 12 | no | 11px | OK |
| invoices:Invoices | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 12 on the first screen | no | 0 | OK |
| invoices:Invoices | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 4 of 12 on the first screen | no | 0 | OK |
| invoices:Invoices | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 4 of 12 | no | 10px | Kept: Two-line rows (invoice and customer). One-line rows are open question 12. |
| invoices:Invoices | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 6 of 12 | no | 10px | Kept: Two-line rows (invoice and customer). One-line rows are open question 12. |
| invoices:Invoices | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 10 of 12 | no | 11px | OK |
| invoices:Quotations | 390×844 | no | none | none | 4 cards, 2/row | 1 | — | no | 104px (nothing more to show) | OK |
| invoices:Quotations | 768×1024 | no | none | none | 4 cards, 2/row | 1 | — | no | 361px (nothing more to show) | OK |
| invoices:Quotations | 1366×768 | no | none | none | 4 cards, 4/row | 1 | — | no | 302px (nothing more to show) | OK |
| invoices:Quotations | 1440×900 | no | none | none | 4 cards, 4/row | 1 | — | no | 434px (nothing more to show) | OK |
| invoices:Quotations | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | — | no | 614px (nothing more to show) | OK |
| utilities:Meter readings | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| utilities:Meter readings | 768×1024 | no | none | none | — | 0 | — | no | 314px (nothing more to show) | OK |
| utilities:Meter readings | 1366×768 | no | none | none | — | 0 | — | no | 134px (nothing more to show) | OK |
| utilities:Meter readings | 1440×900 | no | none | none | — | 0 | — | no | 266px (nothing more to show) | OK |
| utilities:Meter readings | 1920×1080 | no | none | none | — | 0 | — | no | 446px (nothing more to show) | OK |
| utilities:Meters | 390×844 | no | none | none | 3 cards, 2/row | 1 | — | no | 0 | OK |
| utilities:Meters | 768×1024 | no | none | none | 3 cards, 3/row | 1 | — | no | 164px (nothing more to show) | OK |
| utilities:Meters | 1366×768 | no | none | none | 3 cards, 3/row | 1 | — | no | 0 | OK |
| utilities:Meters | 1440×900 | no | none | none | 3 cards, 3/row | 1 | — | no | 83px (nothing more to show) | OK |
| utilities:Meters | 1920×1080 | no | none | none | 3 cards, 3/row | 1 | — | no | 263px (nothing more to show) | OK |
| approvals | 390×844 | no | none | none | 4 cards, 2/row | 1 | — | no | 0 | OK |
| approvals | 768×1024 | no | none | none | 4 cards, 2/row | 1 | — | no | 205px (nothing more to show) | OK |
| approvals | 1366×768 | no | none | none | 4 cards, 4/row | 1 | — | no | 99px (nothing more to show) | OK |
| approvals | 1440×900 | no | none | none | 4 cards, 4/row | 1 | — | no | 248px (nothing more to show) | OK |
| approvals | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | — | no | 428px (nothing more to show) | OK |
| visitreqs:Viewing requests | 390×844 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| visitreqs:Viewing requests | 768×1024 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| visitreqs:Viewing requests | 1366×768 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| visitreqs:Viewing requests | 1440×900 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| visitreqs:Viewing requests | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| visitreqs:Reservations | 390×844 | no | none | none | 4 cards, 2/row | 1 | — | no | 110px (nothing more to show) | OK |
| visitreqs:Reservations | 768×1024 | no | none | none | 4 cards, 2/row | 1 | — | no | 361px (nothing more to show) | OK |
| visitreqs:Reservations | 1366×768 | no | none | none | 4 cards, 4/row | 1 | — | no | 302px (nothing more to show) | OK |
| visitreqs:Reservations | 1440×900 | no | none | none | 4 cards, 4/row | 1 | — | no | 434px (nothing more to show) | OK |
| visitreqs:Reservations | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | — | no | 614px (nothing more to show) | OK |
| shortstays | 390×844 | no | none | none | — | 1 | 6 of 15 on the first screen | no | 0 | OK |
| shortstays | 768×1024 | no | none | none | — | 1 | 10 of 15 on the first screen | no | 0 | OK |
| shortstays | 1366×768 | no | none | none | — | 1 | 8 of 15 | no | 10px | OK |
| shortstays | 1440×900 | no | none | none | — | 1 | 10 of 15 | no | 10px | OK |
| shortstays | 1920×1080 | no | none | none | — | 1 | 13 of 15 | no | 16px | OK |
| leases:Leases | 390×844 | no | none | none | 4 cards, 2/row | 1 | 2 of 12 on the first screen | no | 0 | OK |
| leases:Leases | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 6 of 12 on the first screen | no | 0 | OK |
| leases:Leases | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 5 of 12 | no | 10px | Kept: Two-line rows (lease and customer). One-line rows are open question 12. |
| leases:Leases | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 8 of 12 | no | 11px | OK |
| leases:Leases | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 11 of 12 | no | 11px | OK |
| leases:Notices:Rent arrears notices | 390×844 | no | none | none | 3 cards, 2/row | 0 | — | no | 0 | OK |
| leases:Notices:Rent arrears notices | 768×1024 | no | none | none | 3 cards, 3/row | 0 | — | no | 78px (nothing more to show) | OK |
| leases:Notices:Rent arrears notices | 1366×768 | no | none | none | 3 cards, 3/row | 0 | — | no | 0 | OK |
| leases:Notices:Rent arrears notices | 1440×900 | no | none | none | 3 cards, 3/row | 0 | — | no | 0 | OK |
| leases:Notices:Rent arrears notices | 1920×1080 | no | none | none | 3 cards, 3/row | 0 | — | no | 229px (nothing more to show) | OK |
| leases:Notices:Lease breach notices | 390×844 | no | none | none | — | 1 | — | no | 0 | OK |
| leases:Notices:Lease breach notices | 768×1024 | no | none | none | — | 1 | — | no | 282px (nothing more to show) | OK |
| leases:Notices:Lease breach notices | 1366×768 | no | none | none | — | 1 | — | no | 0 | OK |
| leases:Notices:Lease breach notices | 1440×900 | no | none | none | — | 1 | — | no | 210px (nothing more to show) | OK |
| leases:Notices:Lease breach notices | 1920×1080 | no | none | none | — | 1 | — | no | 390px (nothing more to show) | OK |
| leases:Move-outs | 390×844 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| leases:Move-outs | 768×1024 | no | none | none | 4 cards, 2/row | 0 | — | no | 276px (nothing more to show) | OK |
| leases:Move-outs | 1366×768 | no | none | none | 4 cards, 4/row | 0 | — | no | 161px (nothing more to show) | OK |
| leases:Move-outs | 1440×900 | no | none | none | 4 cards, 4/row | 0 | — | no | 293px (nothing more to show) | OK |
| leases:Move-outs | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | — | no | 494px (nothing more to show) | OK |
| customers | 390×844 | no | none | none | 4 cards, 2/row | 1 | 1 of 14 on the first screen | no | 0 | OK |
| customers | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 8 of 14 on the first screen | no | 0 | OK |
| customers | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 6 of 14 | no | 11px | Kept: Two-line rows (name and phone). One-line rows are open question 12. |
| customers | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 9 of 14 | no | 11px | OK |
| customers | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 14 of 14 | no | 25px (nothing more to show) | OK |
| units | 390×844 | no | none | none | 4 cards, 2/row | 1 | 0 of 15 on the first screen | no | 0 | OK |
| units | 768×1024 | no | none | none | 4 cards, 2/row | 1 | 7 of 15 on the first screen | no | 0 | OK |
| units | 1366×768 | no | none | none | 4 cards, 4/row | 1 | 8 of 15 | no | 10px | OK |
| units | 1440×900 | no | none | none | 4 cards, 4/row | 1 | 11 of 15 | no | 10px | OK |
| units | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | 10 of 15 | no | 16px | OK |
| inspections | 390×844 | no | none | none | — | 0 | — | no | 137px (nothing more to show) | OK |
| inspections | 768×1024 | no | none | none | — | 0 | — | no | 573px (nothing more to show) | OK |
| inspections | 1366×768 | no | none | none | — | 0 | — | no | 357px (nothing more to show) | OK |
| inspections | 1440×900 | no | none | none | — | 0 | — | no | 489px (nothing more to show) | OK |
| inspections | 1920×1080 | no | none | none | — | 0 | — | no | 669px (nothing more to show) | OK |
| problems:Reports | 390×844 | no | none | none | — | 1 | — | no | 227px (nothing more to show) | OK |
| problems:Reports | 768×1024 | no | none | none | — | 1 | — | no | 573px (nothing more to show) | OK |
| problems:Reports | 1366×768 | no | none | none | — | 1 | — | no | 373px (nothing more to show) | OK |
| problems:Reports | 1440×900 | no | none | none | — | 1 | — | no | 505px (nothing more to show) | OK |
| problems:Reports | 1920×1080 | no | none | none | — | 1 | — | no | 685px (nothing more to show) | OK |
| problems:Monthly report | 390×844 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| problems:Monthly report | 768×1024 | no | none | none | 4 cards, 2/row | 0 | — | no | 0 | OK |
| problems:Monthly report | 1366×768 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| problems:Monthly report | 1440×900 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| problems:Monthly report | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | — | no | 0 | OK |
| products:Products | 390×844 | no | none | none | — | 1 | — | no | 185px (nothing more to show) | OK |
| products:Products | 768×1024 | no | none | none | — | 1 | — | no | 529px (nothing more to show) | OK |
| products:Products | 1366×768 | no | none | none | — | 1 | — | no | 320px (nothing more to show) | OK |
| products:Products | 1440×900 | no | none | none | — | 1 | — | no | 452px (nothing more to show) | OK |
| products:Products | 1920×1080 | no | none | none | — | 1 | — | no | 654px (nothing more to show) | OK |
| products:Stock movements | 390×844 | no | none | none | — | 1 | — | no | 213px (nothing more to show) | OK |
| products:Stock movements | 768×1024 | no | none | none | — | 1 | — | no | 626px (nothing more to show) | OK |
| products:Stock movements | 1366×768 | no | none | none | — | 1 | — | no | 370px (nothing more to show) | OK |
| products:Stock movements | 1440×900 | no | none | none | — | 1 | — | no | 524px (nothing more to show) | OK |
| products:Stock movements | 1920×1080 | no | none | none | — | 1 | — | no | 704px (nothing more to show) | OK |
| products:Storage locations | 390×844 | no | none | none | — | 0 | — | no | 305px (nothing more to show) | OK |
| products:Storage locations | 768×1024 | no | none | none | — | 0 | — | no | 656px (nothing more to show) | OK |
| products:Storage locations | 1366×768 | no | none | none | — | 0 | — | no | 400px (nothing more to show) | OK |
| products:Storage locations | 1440×900 | no | none | none | — | 0 | — | no | 532px (nothing more to show) | OK |
| products:Storage locations | 1920×1080 | no | none | none | — | 0 | — | no | 737px (nothing more to show) | OK |
| exreqs:Expense requests | 390×844 | no | none | none | 4 cards, 2/row | 1 | — | no | 0 | OK |
| exreqs:Expense requests | 768×1024 | no | none | none | 4 cards, 2/row | 1 | — | no | 0 | OK |
| exreqs:Expense requests | 1366×768 | no | none | none | 4 cards, 4/row | 1 | — | no | 0 | OK |
| exreqs:Expense requests | 1440×900 | no | none | none | 4 cards, 4/row | 1 | — | no | 0 | OK |
| exreqs:Expense requests | 1920×1080 | no | none | none | 4 cards, 4/row | 1 | — | no | 214px (nothing more to show) | OK |
| exreqs:Expenses | 390×844 | no | none | none | — | 1 | — | no | 0 | OK |
| exreqs:Expenses | 768×1024 | no | none | none | — | 1 | — | no | 432px (nothing more to show) | OK |
| exreqs:Expenses | 1366×768 | no | none | none | — | 1 | — | no | 276px (nothing more to show) | OK |
| exreqs:Expenses | 1440×900 | no | none | none | — | 1 | — | no | 408px (nothing more to show) | OK |
| exreqs:Expenses | 1920×1080 | no | none | none | — | 1 | — | no | 588px (nothing more to show) | OK |
| exreqs:Supplier bills | 390×844 | no | none | none | 3 cards, 2/row | 1 | — | no | 0 | OK |
| exreqs:Supplier bills | 768×1024 | no | none | none | 3 cards, 3/row | 1 | — | no | 206px (nothing more to show) | OK |
| exreqs:Supplier bills | 1366×768 | no | none | none | 3 cards, 3/row | 1 | — | no | 0 | OK |
| exreqs:Supplier bills | 1440×900 | no | none | none | 3 cards, 3/row | 1 | — | no | 187px (nothing more to show) | OK |
| exreqs:Supplier bills | 1920×1080 | no | none | none | 3 cards, 3/row | 1 | — | no | 392px (nothing more to show) | OK |
| exreqs:Journal entries | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Journal entries | 768×1024 | no | none | none | — | 0 | — | no | 458px (nothing more to show) | OK |
| exreqs:Journal entries | 1366×768 | no | none | none | — | 0 | — | no | 251px (nothing more to show) | OK |
| exreqs:Journal entries | 1440×900 | no | none | none | — | 0 | — | no | 383px (nothing more to show) | OK |
| exreqs:Journal entries | 1920×1080 | no | none | none | — | 0 | — | no | 589px (nothing more to show) | OK |
| exreqs:Needs check | 390×844 | no | none | none | — | 0 | 0 of 2 on the first screen | no | 0 | OK |
| exreqs:Needs check | 768×1024 | no | none | none | — | 0 | 2 of 2 on the first screen | no | 0 | OK |
| exreqs:Needs check | 1366×768 | no | none | none | — | 0 | 1 of 2 | no | 0 | OK |
| exreqs:Needs check | 1440×900 | no | none | none | — | 0 | 2 of 2 | no | 0 | OK |
| exreqs:Needs check | 1920×1080 | no | none | none | — | 0 | 2 of 2 | no | 0 | OK |
| exreqs:Chart of accounts | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Chart of accounts | 768×1024 | no | none | none | — | 0 | — | no | 381px (nothing more to show) | OK |
| exreqs:Chart of accounts | 1366×768 | no | none | none | — | 0 | — | no | 280px (nothing more to show) | OK |
| exreqs:Chart of accounts | 1440×900 | no | none | none | — | 0 | — | no | 412px (nothing more to show) | OK |
| exreqs:Chart of accounts | 1920×1080 | no | none | none | — | 0 | — | no | 592px (nothing more to show) | OK |
| exreqs:Financial statements | 390×844 | no | none | none | — | 0 | 0 of 12 on the first screen | no | 0 | OK |
| exreqs:Financial statements | 768×1024 | no | none | none | — | 0 | 2 of 12 on the first screen | no | 0 | OK |
| exreqs:Financial statements | 1366×768 | no | none | none | — | 0 | 0 of 12 | no | 0 | Kept: Several statements on one page: the page scrolls normally. |
| exreqs:Financial statements | 1440×900 | no | none | none | — | 0 | 4 of 12 | no | 0 | Kept: Several statements on one page: the page scrolls normally. |
| exreqs:Financial statements | 1920×1080 | no | none | none | — | 0 | 9 of 12 | no | 10px | OK |
| exreqs:Budget | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Budget | 768×1024 | no | none | none | — | 0 | — | no | 438px (nothing more to show) | OK |
| exreqs:Budget | 1366×768 | no | none | none | — | 0 | — | no | 256px (nothing more to show) | OK |
| exreqs:Budget | 1440×900 | no | none | none | — | 0 | — | no | 388px (nothing more to show) | OK |
| exreqs:Budget | 1920×1080 | no | none | none | — | 0 | — | no | 568px (nothing more to show) | OK |
| exreqs:Fixed assets | 390×844 | no | none | none | — | 1 | — | no | 0 | OK |
| exreqs:Fixed assets | 768×1024 | no | none | none | — | 1 | — | no | 164px (nothing more to show) | OK |
| exreqs:Fixed assets | 1366×768 | no | none | none | — | 1 | — | no | 0 | OK |
| exreqs:Fixed assets | 1440×900 | no | none | none | — | 1 | — | no | 140px (nothing more to show) | OK |
| exreqs:Fixed assets | 1920×1080 | no | none | none | — | 1 | — | no | 376px (nothing more to show) | OK |
| exreqs:Bank and cash | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Bank and cash | 768×1024 | no | none | none | — | 0 | — | no | 270px (nothing more to show) | OK |
| exreqs:Bank and cash | 1366×768 | no | none | none | — | 0 | — | no | 88px (nothing more to show) | OK |
| exreqs:Bank and cash | 1440×900 | no | none | none | — | 0 | — | no | 220px (nothing more to show) | OK |
| exreqs:Bank and cash | 1920×1080 | no | none | none | — | 0 | — | no | 456px (nothing more to show) | OK |
| exreqs:Month-end close | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Month-end close | 768×1024 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Month-end close | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Month-end close | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| exreqs:Month-end close | 1920×1080 | no | none | none | — | 0 | — | no | 131px (nothing more to show) | OK |
| reports | 390×844 | no | none | none | 4 cards, 2/row, 9 cards, 2/row | 0 | — | no | 0 | OK |
| reports | 768×1024 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| reports | 1366×768 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| reports | 1440×900 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 0 | OK |
| reports | 1920×1080 | no | none | none | 4 cards, 2/row, 9 cards, 3/row | 0 | — | no | 66px (nothing more to show) | OK |
| history | 390×844 | no | none | none | — | 1 | 3 of 50 on the first screen | no | 0 | OK |
| history | 768×1024 | no | none | none | — | 1 | 8 of 50 on the first screen | no | 0 | OK |
| history | 1366×768 | no | none | none | — | 1 | 7 of 50 | no | 10px | Kept: Two-line rows (event and who): 7 rows fit at 1366 × 768. One-line rows are open question 12. |
| history | 1440×900 | no | none | none | — | 1 | 9 of 50 | no | 10px | OK |
| history | 1920×1080 | no | none | none | — | 1 | 9 of 50 | no | 16px | OK |
| employees:Employees | 390×844 | no | none | none | — | 1 | — | no | 68px (nothing more to show) | OK |
| employees:Employees | 768×1024 | no | none | none | — | 1 | — | no | 442px (nothing more to show) | OK |
| employees:Employees | 1366×768 | no | none | none | — | 1 | — | no | 186px (nothing more to show) | OK |
| employees:Employees | 1440×900 | no | none | none | — | 1 | — | no | 318px (nothing more to show) | OK |
| employees:Employees | 1920×1080 | no | none | none | — | 1 | — | no | 498px (nothing more to show) | OK |
| employees:Salary loans | 390×844 | no | none | none | — | 1 | — | no | 114px (nothing more to show) | OK |
| employees:Salary loans | 768×1024 | no | none | none | — | 1 | — | no | 487px (nothing more to show) | OK |
| employees:Salary loans | 1366×768 | no | none | none | — | 1 | — | no | 231px (nothing more to show) | OK |
| employees:Salary loans | 1440×900 | no | none | none | — | 1 | — | no | 363px (nothing more to show) | OK |
| employees:Salary loans | 1920×1080 | no | none | none | — | 1 | — | no | 566px (nothing more to show) | OK |
| employees:Payroll | 390×844 | no | none | none | — | 1 | — | no | 0 | OK |
| employees:Payroll | 768×1024 | no | none | none | — | 1 | — | no | 348px (nothing more to show) | OK |
| employees:Payroll | 1366×768 | no | none | none | — | 1 | — | no | 170px (nothing more to show) | OK |
| employees:Payroll | 1440×900 | no | none | none | — | 1 | — | no | 302px (nothing more to show) | OK |
| employees:Payroll | 1920×1080 | no | none | none | — | 1 | — | no | 504px (nothing more to show) | OK |
| employees:Attendance | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| employees:Attendance | 768×1024 | no | none | none | — | 0 | — | no | 257px (nothing more to show) | OK |
| employees:Attendance | 1366×768 | no | none | none | — | 0 | — | no | 65px (nothing more to show) | OK |
| employees:Attendance | 1440×900 | no | none | none | — | 0 | — | no | 197px (nothing more to show) | OK |
| employees:Attendance | 1920×1080 | no | none | none | — | 0 | — | no | 431px (nothing more to show) | OK |
| tglinks:Linked tenants | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| tglinks:Linked tenants | 768×1024 | no | none | none | — | 0 | — | no | 142px (nothing more to show) | OK |
| tglinks:Linked tenants | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| tglinks:Linked tenants | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| tglinks:Linked tenants | 1920×1080 | no | none | none | — | 0 | — | no | 242px (nothing more to show) | OK |
| tglinks:Contact office | 390×844 | no | none | none | — | 0 | — | no | 225px (nothing more to show) | OK |
| tglinks:Contact office | 768×1024 | no | none | none | — | 0 | — | no | 565px (nothing more to show) | OK |
| tglinks:Contact office | 1366×768 | no | none | none | — | 0 | — | no | 309px (nothing more to show) | OK |
| tglinks:Contact office | 1440×900 | no | none | none | — | 0 | — | no | 441px (nothing more to show) | OK |
| tglinks:Contact office | 1920×1080 | no | none | none | — | 0 | — | no | 621px (nothing more to show) | OK |
| tglinks:FAQ | 390×844 | no | none | none | — | 1 | — | no | 62px (nothing more to show) | OK |
| tglinks:FAQ | 768×1024 | no | none | none | — | 1 | — | no | 491px (nothing more to show) | OK |
| tglinks:FAQ | 1366×768 | no | none | none | — | 1 | — | no | 260px (nothing more to show) | OK |
| tglinks:FAQ | 1440×900 | no | none | none | — | 1 | — | no | 392px (nothing more to show) | OK |
| tglinks:FAQ | 1920×1080 | no | none | none | — | 1 | — | no | 572px (nothing more to show) | OK |
| tglinks:Telegram health | 390×844 | no | none | none | 4 cards, 2/row | 0 | 0 of 3 on the first screen | no | 0 | OK |
| tglinks:Telegram health | 768×1024 | no | none | none | 4 cards, 2/row | 0 | 3 of 3 on the first screen | no | 0 | OK |
| tglinks:Telegram health | 1366×768 | no | none | none | 4 cards, 4/row | 0 | 3 of 3 | no | 0 | OK |
| tglinks:Telegram health | 1440×900 | no | none | none | 4 cards, 4/row | 0 | 3 of 3 | no | 0 | OK |
| tglinks:Telegram health | 1920×1080 | no | none | none | 4 cards, 4/row | 0 | 3 of 3 | no | 0 | OK |
| access | 390×844 | no | none | none | — | 2 | 1 of 1 on the first screen | no | 0 | OK |
| access | 768×1024 | no | none | none | — | 2 | 1 of 1 on the first screen | no | 299px (nothing more to show) | OK |
| access | 1366×768 | no | none | none | — | 2 | 1 of 1 | no | 166px (nothing more to show) | OK |
| access | 1440×900 | no | none | none | — | 2 | 1 of 1 | no | 298px (nothing more to show) | OK |
| access | 1920×1080 | no | none | none | — | 2 | 1 of 1 | no | 409px (nothing more to show) | OK |
| settings:General | 390×844 | no | none | none | — | 0 | 0 of 30 on the first screen | no | 0 | OK |
| settings:General | 768×1024 | no | none | none | — | 0 | 0 of 30 on the first screen | no | 0 | OK |
| settings:General | 1366×768 | no | none | none | — | 0 | 0 of 30 | no | 0 | Kept: A settings page with forms and rules tables: the page scrolls normally. |
| settings:General | 1440×900 | no | none | none | — | 0 | 0 of 30 | no | 0 | Kept: A settings page with forms and rules tables: the page scrolls normally. |
| settings:General | 1920×1080 | no | none | none | — | 0 | 0 of 30 | no | 0 | Kept: A settings page with forms and rules tables: the page scrolls normally. |
| settings:Utility rates | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:Utility rates | 768×1024 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:Utility rates | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:Utility rates | 1440×900 | no | none | none | — | 0 | — | no | 64px (nothing more to show) | OK |
| settings:Utility rates | 1920×1080 | no | none | none | — | 0 | — | no | 244px (nothing more to show) | OK |
| settings:Monthly services | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:Monthly services | 768×1024 | no | none | none | — | 0 | — | no | 158px (nothing more to show) | OK |
| settings:Monthly services | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:Monthly services | 1440×900 | no | none | none | — | 0 | — | no | 160px (nothing more to show) | OK |
| settings:Monthly services | 1920×1080 | no | none | none | — | 0 | — | no | 384px (nothing more to show) | OK |
| settings:Unit setup | 390×844 | no | none | none | — | 0 | — | no | 56px (nothing more to show) | OK |
| settings:Unit setup | 768×1024 | no | none | none | — | 0 | — | no | 366px (nothing more to show) | OK |
| settings:Unit setup | 1366×768 | no | none | none | — | 0 | — | no | 210px (nothing more to show) | OK |
| settings:Unit setup | 1440×900 | no | none | none | — | 0 | — | no | 342px (nothing more to show) | OK |
| settings:Unit setup | 1920×1080 | no | none | none | — | 0 | — | no | 522px (nothing more to show) | OK |
| settings:System health | 390×844 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 768×1024 | no | none | none | — | 0 | — | no | 65px (nothing more to show) | OK |
| settings:System health | 1366×768 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 1440×900 | no | none | none | — | 0 | — | no | 0 | OK |
| settings:System health | 1920×1080 | no | none | none | — | 0 | — | no | 225px (nothing more to show) | OK |

## 7. Screenshots

- Comparison sheets (design beside app, every screen, every size): `/mnt/project-files/ui-audit/round3/` (`<screen>-<size>.jpg`, design on the left, app on the right).
- In the repository: `docs/ui-audit/screenshots/round3/` holds Home at the five sizes (design and app) and the main list pages at 1366 × 768 and 1440 × 900, with a README.

## 7. Automatic check from round 5 (08/11/2026)

The measurements of section 1 are now a Playwright test, `frontend/e2e/screens.spec.ts` (TEST-FE-1922), run by `npm run screens` and by the CI job `screens`. It opens every screen listed in `frontend/e2e/screens.ts` at the five sizes against the built app with replayed server answers and fails on horizontal overflow, a target under 44 × 44 px, contrast under 4.5:1, cut-off text, a role badge inside a button, a lone card in a desktop grid row and two stacked tables. Screens join the list as they move onto the shared layouts; the pilot (Lease details, New Lease) is in, Home (plain and with a Tasks card open) joined in round 6, and the side menu (open, collapsed, groups folded; the drawer on a phone or tablet) in round 6b. Since round 6b the check also reads the side menu with the page, fails on any visible internal ID or placeholder text (a UUID, "LEASE-" + hex, "Primary Lease Customer"...), and replays the recorded sign-in with its expiry moved to the present. The result per screen is in `02_DESIGN_V81_CHANGES.md`, rounds 5 to 6b.
