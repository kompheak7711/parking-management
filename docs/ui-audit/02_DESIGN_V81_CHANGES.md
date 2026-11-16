# 02 Design v81 changes

Date 07/11/2026. Branch `ui-v81`.

## Where the design is

- Design v81 (clickable): https://claude.ai/artifact/CLyBzHBQEb9HQrPQMpLDqv (new link, so the v80 link stays as it was).
- File: `/mnt/project-files/ui-design/chetana-app-v81.html`. Mock-up v80 is unchanged at `/mnt/project-files/ui-design/chetana-app.html` and https://claude.ai/artifact/88HdZkSvKAKHmzPEDpUW71.
- Source: `/mnt/project-files/ui-design/round4-source/app42.js` and `i18n42.js` (build.py loads them after round 36). v81 was found in the same place as v80, so nothing was saved under `docs/ui-audit/design/`.
- Check run on v81: every menu screen, tab, 66 record pages and 146 buttons and dialogs, in English and Khmer, at 1180 and 390 wide. No script errors and no missing words.

## What changed

1. **Wording.** The A1 review (03_WORDING_REVIEW.md) applied to the design: 148 design texts changed (list below). Ledger names 1100/1110 Accounts receivable, 2210 Unapplied payments, 3900 Retained earnings. Khmer is not changed except the new words, which are marked `// new` in the source.
2. **Sub-tab rule (B2).** Settings (and any list page with more than one table) shows a sub-tab row. Record pages (Lease, Customer, Unit, Employee, Reservation) stay on one page, as the owner asked on 07/11 07:55 (see 8). Settings sub-tabs: "Details" (records) or "General" (Settings) first, holding the cards, then one sub-tab per table with a count badge. Number cards stay above. A page with one table and no cards has no sub-tab row. Pills on desktop, one scrolling row on a phone. The chosen sub-tab is kept in the address (`#unit?tab=t1`) and does not add a Back step. Keyboard: arrow keys, Home and End.
3. **Back rule (B3).** The Back link reads "Back to X" (the page you came from). It returns to that page with its tab, filters and scroll place. Opened directly, it goes to the parent list. The browser Back button does the same, and closes an open drawer first. Changing a section tab or sub-tab adds no history step.
4. **Drawer forms (B2).** Add and Edit forms open as a right drawer (full-screen sheet at 640 px or less), with the Save row fixed at the bottom. Closing with changes asks first. Confirm dialogs without fields stay in the middle.
5. **Audit log Export.** One "Export" button; the dialog asks Excel (.xlsx) or PDF.
6. **Items the app already has**, now in the design: riel bank 1021 (Bank and cash sub-tab with "Riel in the bank" and the ABA riel statement match), the riel account per Payment Method, the riel amount for a Refund paid from 1021 in Needs check, and the Short stays Quotes tab.
7. Footer and banner say "Design v81".
8. **Owner changes after Part A (07/11 07:55).**
   - Record pages stay on one page, no sub-tabs. The History card shows the latest 5 with a "History" button to a full History page. Customer: Latest Receipts shows 5 with "All Receipts"; Customer statement shows only the balance due with "Full statement". Unit and Lease work the same way.
   - Buttons stay short: a role badge never sits inside a button. "Reduce or waive MANAGER" is now "Adjust charge" with "Manager only" beside it. This applies to every button with a role badge.
   - Short stays: pressing Check out before the booked check-out day shows "Not the check-out date" with "Keep the stay" or "Check out early".

## Not changed in v81 (on purpose)

- Viewing dashboard, Field reports, Birthdays, Guests and the collapsible menu stay in the design but are not built (owner: do not build them now). The app will not show them.
- Dates stay dd/mm/yyyy (see Open question 1 in 03).
- Export buttons cannot save a file inside the artifact viewer. This is a mock-up limit only.

## Before and after

### 1. Home

Banner now says design v81; menu, cards and to-do list keep the 02/11 words.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![01-home before 1280](screenshots/design-v81/01-home-before-1280.png) | ![01-home after 1280](screenshots/design-v81/01-home-after-1280.png) |

Phone (v81, 375): ![01-home after 375](screenshots/design-v81/01-home-after-375.png)

### 2. Unit record (U101)

"Back to Units" instead of "Back". The record stays on one page; the History card shows the latest 5 with a History button (owner 07/11 07:55).

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![02-unit-record before 1280](screenshots/design-v81/02-unit-record-before-1280.png) | ![02-unit-record after 1280](screenshots/design-v81/02-unit-record-after-1280.png) |

Phone (v81, 375): ![02-unit-record after 375](screenshots/design-v81/02-unit-record-after-375.png)

### 3. Settings

First tab renamed General (sub-tab rule); General holds the settings cards, each table (Business rules, Problem types, Payment Methods, Document numbering) gets its own sub-tab.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![03-settings before 1280](screenshots/design-v81/03-settings-before-1280.png) | ![03-settings after 1280](screenshots/design-v81/03-settings-after-1280.png) |

Phone (v81, 375): ![03-settings after 375](screenshots/design-v81/03-settings-after-375.png)

### 4. Ledger, Bank and cash

Pills become sub-tabs: ABA USD account (1020), ABA KHR account (1021), Cash count. New 1021 sub-tab: Riel in the bank, month-end rate, value in dollars, exchange gain or loss (4100), and the ABA riel statement match.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![04-bank-and-cash before 1280](screenshots/design-v81/04-bank-and-cash-before-1280.png) | ![04-bank-and-cash after 1280](screenshots/design-v81/04-bank-and-cash-after-1280.png) |

Phone (v81, 375): ![04-bank-and-cash after 375](screenshots/design-v81/04-bank-and-cash-after-375.png)

### 5. Ledger, Needs check

New "Refunds paid from the riel account" list: "Enter the riel paid for this Refund". Payment Method accounts table gets a "Riel account" column (ABA PAY and KHQR use 1021).

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![05-needs-check before 1280](screenshots/design-v81/05-needs-check-before-1280.png) | ![05-needs-check after 1280](screenshots/design-v81/05-needs-check-after-1280.png) |

Phone (v81, 375): ![05-needs-check after 375](screenshots/design-v81/05-needs-check-after-375.png)

### 6. Short stays, Quotes

Before: the short-stay quotes list sat under Invoices › Quotations. After: its own Quotes tab in Short stays, as in the app.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![06-short-stay-quotes before 1280](screenshots/design-v81/06-short-stay-quotes-before-1280.png) | ![06-short-stay-quotes after 1280](screenshots/design-v81/06-short-stay-quotes-after-1280.png) |

Phone (v81, 375): ![06-short-stay-quotes after 375](screenshots/design-v81/06-short-stay-quotes-after-375.png)

### 7. Audit log, Export

One "Export" button (was "Export audit" with an ALL CAPS badge). The dialog asks Excel (.xlsx) or PDF.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![07-audit-log-export before 1280](screenshots/design-v81/07-audit-log-export-before-1280.png) | ![07-audit-log-export after 1280](screenshots/design-v81/07-audit-log-export-after-1280.png) |

Phone (v81, 375): ![07-audit-log-export after 375](screenshots/design-v81/07-audit-log-export-after-375.png)

### 8. Employees and payroll, Attendance

Staff use Clock-in and Clock-out (owner decision 4); guests keep Check-in and Check-out.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![08-attendance before 1280](screenshots/design-v81/08-attendance-before-1280.png) | ![08-attendance after 1280](screenshots/design-v81/08-attendance-after-1280.png) |

Phone (v81, 375): ![08-attendance after 375](screenshots/design-v81/08-attendance-after-375.png)

### 9. Add and Edit form

Forms open as a right drawer (full-screen sheet on a phone). Closing with changes asks "Discard your changes?" with Keep editing or Discard.

| Before (v80, 1280) | After (v81, 1280) |
|---|---|
| ![09-edit-form before 1280](screenshots/design-v81/09-edit-form-before-1280.png) | ![09-edit-form after 1280](screenshots/design-v81/09-edit-form-after-1280.png) |

Phone (v81, 375): ![09-edit-form after 375](screenshots/design-v81/09-edit-form-after-375.png)

### Customer record

One page. Statement shows the balance due and "Full statement"; Latest Receipts shows 5 and "All Receipts"; History shows 5 and "History".

| v81, 1280 | v81, 375 |
|---|---|
| ![10-customer-record 1280](screenshots/design-v81/10-customer-record-after-1280.png) | ![10-customer-record 375](screenshots/design-v81/10-customer-record-after-375.png) |

### Lease record

Signers, Occupants and History together on one page; History shows the latest 5 and a History button.

| v81, 1280 | v81, 375 |
|---|---|
| ![11-lease-record 1280](screenshots/design-v81/11-lease-record-after-1280.png) | ![11-lease-record 375](screenshots/design-v81/11-lease-record-after-375.png) |

### Late-payment charge button

"Adjust charge" with "Manager only" beside the button.

| v81, 1280 | v81, 375 |
|---|---|
| ![12-late-charge-button 1280](screenshots/design-v81/12-late-charge-button-after-1280.png) | ![12-late-charge-button 375](screenshots/design-v81/12-late-charge-button-after-375.png) |

### Short stay early check-out

Warning before checking out a paid stay before its check-out day.

| v81, 1280 | v81, 375 |
|---|---|
| ![13-early-checkout-warning 1280](screenshots/design-v81/13-early-checkout-warning-after-1280.png) | ![13-early-checkout-warning 375](screenshots/design-v81/13-early-checkout-warning-after-375.png) |

## Wording changed in the design (v80 → v81)

| Key | v80 | v81 |
|---|---|---|
| `mgr_badge` | MANAGER | Manager |
| `cu_former` | Former tenant | Past tenant |
| `rv_5` | Utilities, Meter readings. Type a number lower than the last reading, then a very high one. Type 302 in the Unit box. Try 6 months, then Import and Use the sample file. | Utilities, Meter readings. Enter a number lower than the last reading, then a very high one. Enter 302 in the Unit box. Try 6 months, then Import and Use the sample file. |
| `rv_9` | Payments. Check the eight cards at the top. Tap a card to show only those payments. Try All, This month, Last month and Pick dates. | Payments. Check the eight cards at the top. Tap a card to show only those payments. Try All, This month, Last month and Choose dates. |
| `ni_w4` | Everything is saved in History. | Everything is saved in the audit log. |
| `ni_dlg_c` | The Customer does not owe it until a Manager issues it. This is saved in History. | The Customer does not owe it until a Manager issues it. This is saved in the audit log. |
| `ut_unit_bad` | No Unit "{0}". Type U101 to U406, or clear the box to see all Units. | No Unit "{0}". Enter U101 to U406, or clear the box to see all Units. |
| `im_mock` | Mock-up: the check uses sample rows, not the file you pick. | Mock-up: the check uses sample rows, not the file you choose. |
| `im_note` | Each reading is checked again when it is saved, the same as typing it in. This is saved in History. | Each reading is checked again when it is saved, the same as entering it in. This is saved in the audit log. |
| `mt_report_c` | Its readings stop being used. Use from the day after the last good reading ({0}) will be estimated once a new meter is in. Replace it before reading day {1}. This is saved in History. | Its readings stop being used. Use from the day after the last good reading ({0}) will be estimated once a new meter is in. Replace it before reading day {1}. This is saved in the audit log. |
| `mt_replace_c` | {0} stops on the day before. It stays in the history. The new meter is used from the day it is put in. A Manager approves the estimate before it is billed. This is saved in History. | {0} stops on the day before. It stays in the history. The new meter is used from the day it is put in. A Manager approves the estimate before it is billed. This is saved in the audit log. |
| `es_lock` | The app works this out. Nobody can type an estimate. | The app works this out. Nobody can enter an estimate. |
| `u_edit_note` | Changes are dated and kept in History. The Unit number cannot change. | Changes are dated and kept in the audit log. The Unit number cannot change. |
| `u_inv_note` | Type the number of each item in the Unit. 0 removes it from the list. | Enter the number of each item in the Unit. 0 removes it from the list. |
| `rp_staff_note` | Staff see the operational reports only. Money totals, audit and exports are for the Owner and Managers (V1-057). | Staff see the operational reports only. Money totals, audit and exports are for the Owner and Managers. |
| `ex_logged` | Every export is written to History with who, when and which filters. Small files are not kept; big files are kept 24 hours. | Every export is written to the audit log with who, when and which filters. Small files are not kept; big files are kept 24 hours. |
| `ex_toast` | {0} exported as {1} and written to History. | {0} exported as {1} and written to the audit log. |
| `hi_export` | Export audit | Export |
| `hi_note` | Each search here is itself written to History (V1-057). Record pages show the same events for one record. | Each search here is itself written to the audit log. Record pages show the same events for one record. |
| `ev_signin_mfa` | Signed in with MFA code | Signed in with two-step sign-in |
| `se_sub` | Changed by the Owner, or by a user the Owner allows. Every change is dated and kept in History. | Changed by the Owner, or by a user the Owner allows. Every change is dated and kept in the audit log. |
| `se_signin_2` | Owner and Managers must use a second code (MFA app), with recovery codes kept safe. | Owner and Managers must use two-step sign-in, with recovery codes kept safe. |
| `se_user_note` | The new user sets a password at first sign-in. Owners and Managers must also set up the MFA app. | The new user sets a password at first sign-in. Owners and Managers must also set up two-step sign-in. |
| `rs_note` | This is the usual price. Staff may change the price on an Invoice. A new price here is used for new Invoices only; Invoices already made never change. Every change is kept in History. | This is the usual price. Staff may change the price on an Invoice. A new price here is used for new Invoices only; Invoices already made never change. Every change is kept in the audit log. |
| `no_prefix` | Letters | Prefix |
| `lt_waived_s` | No charge is owed. The reason is kept in History. | No charge is owed. The reason is kept in the audit log. |
| `au_fact2` | Owner and Managers also type a code from their phone. | Owner and Managers also enter a code from their phone. |
| `au_e_user` | Type your username. | Enter your username. |
| `au_e_pw` | Type your password. | Enter your password. |
| `au_code_s` | Open the authenticator app on your phone and type the 6-digit code for CHETANA. | Open the authenticator app on your phone and enter the 6-digit code for CHETANA. |
| `au_e_code` | Type the 6 digits from your phone. | Enter the 6 digits from your phone. |
| `au_e_code_bad` | That code is not right. Type the newest code from your phone. | That code is not right. Enter the newest code from your phone. |
| `au_e_rc` | Type a recovery code, like 7KQ4-M2XD. | Enter a recovery code, like 7KQ4-M2XD. |
| `au_fg_lost` | Lost both your phone and your recovery codes? Only the server emergency procedure can help. It is done on the office computer itself, by the person who set the app up. | Lost both your phone and your recovery codes? Only the emergency reset can help. It is done on the office computer itself, by the person who set the app up. |
| `au_np_change` | Type your current password, then your new one. | Enter your current password, then your new one. |
| `au_new2` | Type the new password again | Enter the new password again |
| `au_e_cur` | Type your current password. | Enter your current password. |
| `au_su_key` | Cannot scan? Type this key instead: | Cannot scan? Enter this key instead: |
| `au_su_3` | Type the 6-digit code the app shows. | Enter the 6-digit code the app shows. |
| `au_mock_h` | Any username from Settings, Users and any password work. Type “wrong” as the password to see the error. Codes: any 6 digits; 000000 is wrong. | Any username from Settings, Users and any password work. Enter “wrong” as the password to see the error. Codes: any 6 digits; 000000 is wrong. |
| `ur_conseq` | {0} is signed out everywhere at once. This is written to History. | {0} is signed out everywhere at once. This is written to the audit log. |
| `im_e_empty` | Empty. Type the reading. | Empty. Enter the reading. |
| `n_letters` | Letters due | Notices due |
| `tip_letter` | Open Letters | Open Notices |
| `ap_rule` | The person who prepared a draft may also confirm it only if they have approval rights. Both names are kept in History. | The person who prepared a draft may also confirm it only if they have approval rights. Both names are kept in the audit log. |
| `ltc_due` | Letters due | Notices due |
| `lt_d_no` | Letter number | Notice number |
| `pb_conf_b` | Chan Dara saved a change to {0} at {1}, while you were editing it. Your change was not saved. What you typed is kept below. | Chan Dara saved a change to {0} at {1}, while you were editing it. Your change was not saved. What you entered is kept below. |
| `pb_conf_yours` | You typed | You entered |
| `lt_due_t` | Letters not given yet | Notices not given yet |
| `mr_worker_h` | Type the name: staff or an outside repairer. | Enter the name: staff or an outside repairer. |
| `mg_e_worker` | Type who does the work. | Enter who does the work. |
| `vs_body` | The request is hidden from the open list but kept in History. | The request is hidden from the open list but kept in the audit log. |
| `l13_err_name` | Type a name. | Enter a name. |
| `l13_err_price` | Type a price above $0.00. | Enter a price above $0.00. |
| `ft_note` | Remove works only while no feature uses the type. Every change is kept in History. | Remove works only while no feature uses the type. Every change is kept in the audit log. |
| `uf_note` | Feature types come from the Feature types list. Remove works only while no Unit uses the feature. Every change is kept in History. | Feature types come from the Feature types list. Remove works only while no Unit uses the feature. Every change is kept in the audit log. |
| `iv13_note` | Where lists this Unit's own features. Each save is dated and kept in History. | Where lists this Unit's own features. Each save is dated and kept in the audit log. |
| `n13_pick` | Pick a Regular service… | Choose a Regular service… |
| `n13_svc_note` | The price comes from Settings › Regular services and cannot be typed here. A Manager changes a price only in Settings. | The price comes from Settings › Regular services and cannot be entered here. A Manager changes a price only in Settings. |
| `n13_dmg_intro` | A Damage charge always comes from a finding: pick one below. The finding is the proof. | A Damage charge always comes from a finding: choose one below. The finding is the proof. |
| `n13_e_find` | Pick the finding to bill. | Choose the finding to bill. |
| `day_unreal` | This is not a real day. Type it as dd/mm/yyyy, for example 28/02/2026. | This is not a real day. Enter it as dd/mm/yyyy, for example 28/02/2026. |
| `n18_svc_pick` | Pick a Regular service… | Choose a Regular service… |
| `r18_refused` | Refused: {0} | Rejected: {0} |
| `p19_sugg_from_typed` | typed by {0} | entered by {0} |
| `p19_cost_e` | Type a cost above $0.00. | Enter a cost above $0.00. |
| `p19_e_name` | Type the name in English. | Enter the name in English. |
| `p19_e_price` | Type a price above $0.00. | Enter a price above $0.00. |
| `sm_sale_note` | A Sale is never typed here. It is made by the app when the Customer signs a Quotation and the Invoice is issued. A voided Invoice puts the items back. | A Sale is never entered here. It is made by the app when the Customer signs a Quotation and the Invoice is issued. A voided Invoice puts the items back. |
| `sm_e_qty` | Type a whole number from 1 to 999. | Enter a whole number from 1 to 999. |
| `sm_e_cost` | Type the cost for one. | Enter the cost for one. |
| `sm_e_ref` | Type the receipt or shop. | Enter the receipt or shop. |
| `sm_e_reason` | Type the reason. | Enter the reason. |
| `lc_e` | Type a name. | Enter a name. |
| `lc_unit_note` | Locations are never typed. A Location is a Unit and one of its places, so the name and the Unit can never disagree. | Locations are never entered. A Location is a Unit and one of its places, so the name and the Unit can never disagree. |
| `q19_new_sub` | Pick products. Price comes from Products. The Customer signs the printed Quotation, then the Invoice is issued. | Choose products. Price comes from Products. The Customer signs the printed Quotation, then the Invoice is issued. |
| `se20_units_n` | Counted from the Units list each time. Never typed. | Counted from the Units list each time. Never entered. |
| `se20_e_name` | Type a name. | Enter a name. |
| `nr_letters` | Letters | Prefix |
| `pb21_e_name` | Type the product name. | Enter the product name. |
| `br_e_val` | Type a value that fits the unit. | Enter a value that fits the unit. |
| `br_e_date` | Type a real date, dd/mm/yyyy. | Enter a real date, dd/mm/yyyy. |
| `br_e_name` | Type the rule name. | Enter the rule name. |
| `ro_e_name` | Type the role name. | Enter the role name. |
| `pm_APPR_OPEN` | Open Waiting for approval | Open Approvals |
| `gl_newest` | Newest {0} entries. Pick a month to see all of it. | Newest {0} entries. Choose a month to see all of it. |
| `gl_x_e_sup` | Type the supplier. | Enter the supplier. |
| `gl_x_e_amt` | Type the amount. | Enter the amount. |
| `gl_bc_1` | Customer debt (1100) equals the unpaid Invoices | Accounts receivable (1100) equals the unpaid Invoices |
| `er_c_wait` | Waiting for approval | Pending approval |
| `er_e_amt` | Type the amount. | Enter the amount. |
| `er_e_date` | Type a date as dd/mm/yyyy, not after today. | Enter a date as dd/mm/yyyy, not after today. |
| `er_st_WAIT` | Waiting for approval | Pending approval |
| `gl_k_MOVE` | Money moved | Fund transfer |
| `gl26_e_date` | Type a date as dd/mm/yyyy, in an open month and not after today. | Enter a date as dd/mm/yyyy, in an open month and not after today. |
| `fa_e_name` | Type the item name. | Enter the item name. |
| `fa_e_life` | Type the number of years, 1 to 50. | Enter the number of years, 1 to 50. |
| `bu_edit_n` | Tap an account to type its amounts for each month. | Tap an account to enter its amounts for each month. |
| `bk_stmt_h` | Type the closing balance printed on the ABA statement. | Enter the closing balance printed on the ABA statement. |
| `cc_e_all` | Type what you counted in every box. | Enter what you counted in every box. |
| `aj_st_VOID` | Not approved | Rejected |
| `gl_r_sub` | Made from the journal entries. Pick a statement and a month. | Made from the journal entries. Choose a statement and a month. |
| `gl_r_ar` | Customer debt aging | Accounts receivable aging |
| `ag_ar_check` | Total equals Customer debt (1100 + 1110): {0}. | Total equals Accounts receivable (1100 + 1110): {0}. |
| `cl_books_d` | Every record has its entry, every entry is balanced, Customer debt equals the unpaid Invoices. | Every record has its entry, every entry is balanced, Accounts receivable equals the unpaid Invoices. |
| `ye_sub` | After December is closed, the Owner closes the year. The year's profit moves to 3900 Profit kept from past years. | After December is closed, the Owner closes the year. The year's profit moves to 3900 Retained earnings. |
| `emp_hist_n` | A change adds a new line with its start date and reason. Old lines are never typed over. | A change adds a new line with its start date and reason. Old lines are never entered over. |
| `tq_no` | Refuse | Reject |
| `tq_h_no` | Telegram request from {0} refused. | Telegram request from {0} rejected. |
| `sl_st_VOID` | Not approved | Rejected |
| `mm_n` | For riel, type the riel amount and the rate. The app works out the gain or loss. Petty cash moves only by Top up petty cash. | For riel, enter the riel amount and the rate. The app works out the gain or loss. Petty cash moves only by Top up petty cash. |
| `mm_done` | Money moved. Entry {0}. | Funds transferred. Entry {0}. |
| `mm_e_same` | Pick two different places. | Choose two different places. |
| `mm_e_riel` | Type the riel amount and the rate. | Enter the riel amount and the rate. |
| `at_in` | Check-in | Clock-in |
| `at_out` | Check-out | Clock-out |
| `at_st_noin` | No check-in | No clock-in |
| `at_f_W_h` | For Worked, the app shows Present or Late from the check-in time (late after {0} minutes). | For Worked, the app shows Present or Late from the clock-in time (late after {0} minutes). |
| `at_e_time` | Type the time like 07:05. | Enter the time like 07:05. |
| `at_day_n` | The night shift belongs to the day it starts. Late means the check-in is more than {0} minutes after the shift starts. | The night shift belongs to the day it starts. Late means the clock-in is more than {0} minutes after the shift starts. |
| `at_no` | Refuse | Reject |
| `at_no_t` | Refuse {0} | Reject {0} |
| `at_ot_NO` | Refused | Rejected |
| `at_e_before` | Overtime must be approved before the work. Pick today or a later day. | Overtime must be approved before the work. Choose today or a later day. |
| `at_h_no` | Overtime {0} refused for {1}: {2} | Overtime {0} rejected for {1}: {2} |
| `at_m_no` | Not approved | Rejected |
| `a31_h_acc` | Check-in of {0} on {1} accepted ({2}). | Clock-in of {0} on {1} accepted ({2}). |
| `f31_none` | Nothing needs attention. Every check-in is fine. | Nothing needs attention. Every clock-in is fine. |
| `p31_kind_in` | Check-in | Clock-in |
| `p31_kind_out` | Check-out | Clock-out |
| `q31_n` | Staff check in and out by scanning the QR at a place. The phone must be within {0} of the pin. Check-in opens {1} before the shift. | Staff clock in and out by scanning the QR at a place. The phone must be within {0} of the pin. Clock-in opens {1} before the shift. |
| `q31_area` | Check-in area | Clock-in area |
| `q31_pin_h` | Type the pin like 11.6045, 104.8902 (from Google Maps: press and hold the place). | Enter the pin like 11.6045, 104.8902 (from Google Maps: press and hold the place). |
| `q31_e_pin` | Type two numbers with a comma, like 11.6045, 104.8902. | Enter two numbers with a comma, like 11.6045, 104.8902. |
| `brn_ATT_QR_EARLY` | Earliest check-in | Earliest clock-in |
| `ss_dmg_nod` | Not approved by {0} | Rejected by {0} |
| `ss_e_lbusy` | This unit has a short-stay booking then. The booking stays: pick another unit or a later date. | This unit has a short-stay booking then. The booking stays: choose another unit or a later date. |
| `ss_nod` | Not approved | Rejected |
| `tr_e_time` | Pick a time later than now. | Choose a time later than now. |
| `tr_e_line` | Type one short line for the technician. | Enter one short line for the technician. |
| `tr_e_amt` | Type the amount. | Enter the amount. |
| `tg_c_name` | Name typed | Name entered |
| `tg_c_unit` | Unit typed | Unit entered |
| `tg_ph_try` | Try: {0} typed "{1}", Unit {2}. | Try: {0} entered "{1}", Unit {2}. |
| `tg_e_phone` | Type a phone number. | Enter a phone number. |
| `pr_join_s` | Pick the main report. Only open reports of the same kind are shown: the same Unit for a Unit Problem. | Choose the main report. Only open reports of the same kind are shown: the same Unit for a Unit Problem. |
| `pr_e_name` | Type the name. | Enter the name. |

## Round 2 (owner 07/11/2026 13:51): changed in the design

Source files `round4-source/i18n44.js` and `round4-source/app44.js`; the mock-up was rebuilt and republished at the same address.

| Key | Before | Round 2 | Why |
|---|---|---|---|
| `nav_staff` | Employees and payroll | Staff (Khmer បុគ្គលិក, native check needed) | Owner item 4. The page tabs stay Employees, Attendance, Loans and Payroll |
| `n_letters_s` | Day-20 and day-30 letters | Day-20 and day-30 notices | Owner item 2: "notices", not "letters" |
| `om_owe_s`, `om_over_s` | Opens Money customers owe | Opens Accounts receivable aging | Owner item 2: the report's approved name |
| `n_appr_s` | {0} to confirm · {1} money out | {0} to confirm · Refunds pending {1} | Owner item 2: the approved word for money out (04_GLOSSARY.md) |
| `vrc_booked` | Visits booked | Viewings booked | The app already carries the approved word (03) |
| `mk_confirm` | Waiting for a Manager | Pending Manager approval | Same |
| `er_c_adv` | Advances not cleared | Outstanding advances | Same |
| `er_c_owed`, `ag_owed_t` | Money owed to staff | Staff reimbursements due | Same |
| `gl_r_bc`, `cl_books` | Books check | Books reconciliation | Same |
| `gl_r_ap` | Supplier bill aging | Accounts payable aging | Same |
| `sb_c_late` | Late | Overdue | Same |
| `at_v_qr`, `q31_t` | QR places | QR locations | Same (03 `a_places`) |
| `emp_f_left` | Left | Past employees | Same (03 `e_left`) |
| `tg_pulls` | Last relay pulls | Recent message checks | Same (03 `pulls`) |
| `tg_tries_h`, `tg_tries_t` | Link tries that did not match | Failed link attempts | Same (03 `tries_h`) |
| `ow_t` | Owner money (Bank and cash button) | Owner's capital and drawings | Same (03 `ow_t`); the Home card stays "Owner money" |
| `mm_t` | Transfer funds (Bank and cash button) | Fund transfer | Same (03 `mm_t`) |

Layout in the design is unchanged: the app took the design's rules instead (full width, one head row, balanced card rows).

## Round 3 (owner 07/11/2026 17:30): changed in the design

Source files `round4-source/i18n45.js` and `round4-source/app45.js`; the mock-up was rebuilt and republished at the same address (v7).

| What | Round 3 | Why |
|---|---|---|
| Card grids | Phone: Owner money 1 per row, other cards 2 per row; tablet: 2 and 3 per row; desktop as before. Cards of one row share a height; labels clamp at 2 lines, notes at 3 (4 on a phone); the value never wraps; on a phone the icon is hidden and the value scales with the width. Reports cards and Tasks cards follow the same rules | Owner point 1 |
| Buttons | Row and list buttons are outline buttons; only the one main action of an area is filled. Selected pills and the chosen part of a switch use the selected-card look (tint with a green underline) | Owner point 2 |
| Home Tasks | Four cards (Overdue · Today · This week · Later) with the count and one line; the list opens under the cards, one at a time; the selected card is highlighted; Overdue opens by itself when it has items | Owner point 3 |
| List pages | On screens at least 1024 × 700 the page fits the screen and only the main table scrolls in its own area with sticky headings and the footer at its bottom; under 1000 px tall a tighter look (one-line cards without icon and note, smaller title, tighter rows); phones and short screens scroll normally with sticky headings; when tall blocks leave no room the page scrolls normally | Owner point 4 |
| `c_name_th` (new) | Customers table heading "Legal name (last, middle, first)" (Khmer ឈ្មោះតាមច្បាប់ (ត្រកូល កណ្តាល ខ្លួន), native check needed) | The column heading named the order of the name parts |
| `er_c_owed` | "Staff reimbursements due" → "Owed to staff" (Khmer unchanged) | The long word "reimbursements" needed 3 lines in a phone card |
| Viewing requests | The "Messages to send manually" box folds to one line with its count (open by a tap) | It took a third of a 768 px screen above the list |
| Tabs on phones | Table column headings stay on one line under 1024 px (the box scrolls sideways) | Headings wrapped to 3 lines at 390 px |

## Round 4 (owner 08/11/2026 05:43): changed in the design

Source files `round4-source/i18n46.js` and `round4-source/app46.js`; the mock-up was rebuilt and republished at the same address (v8).

| What | Round 4 | Why |
|---|---|---|
| `se_tab_biz` | General → Business (as in v80) | Owner A1: the first Settings tab no longer clashes with the sub-tab "General" |
| `se20_biz` | General → Business | Owner A1: the card with the business name |
| Settings › Business sub-tabs | General · Business rules · Problem types · Document numbering, set by name (no longer split by "is it a table"). Payment methods is back in General | Owner A1, A2 |
| Settings › General grid | Property, Business, Riel exchange rate, App preferences, Payment methods: 2 cards per row from 1024 px, 1 below; cards in a row share a height | Owner A2 |
| Settings table sub-tabs | A table sub-tab takes the full content width (no two-column split, no empty half). The list-page rule applies: the page fits the screen and the table scrolls in its own area; Business rules (one small table per area) scrolls as one panel | Owner A3 |
| Settings › Utility rates, Monthly services | One sub-tab per table (Utility Rates · Move-out cleaning rates; Monthly services · Monthly service types) | Owner A4: the same rule for every Settings tab with more than one table |
| Settings › System health | The one card takes the full width | No empty half (A3) |
| Hidden sub-tab panels | A hidden panel is really hidden (`[role=tabpanel][hidden]{display:none}`): the card's `display:grid` had overridden `hidden`, so every panel showed at once | Found while checking A3; this is why Document numbering sat alone on the right |
| Home | No line under the title ("CHETANA Residence · date · As of") and no line under "Tasks" | Owner B6, B7 |
| Menu tags | The "V1.1" tags go. "Later" marks a tab that is not built in the app yet: Viewing dashboard, Field reports, Guests (Short stays) | Owner D14 |
| Menu › Settings | Settings shows its tabs as sub-items (Business · Utility rates · Monthly services · Unit setup · System health) in the open menu and in the rail fly-out, with the current tab highlighted | Owner D14: every page with tabs shows them in the menu |
| Menu › Inspections | One tab is no tab: no "⌄" in the menu and no one-tab bar in the page | Owner D14: pages without tabs have no "⌄" |
| Version line | "Design v81 round 4 · 08/11/2026" | |

## Round 5 (owner 08/11/2026 06:55): shared layouts and the Lease pilot

No design change. The app got the shared layouts and the two pilot pages; everything else waits for the owner's approval of the pilot.

### Shared layouts (`frontend/src/shell/layouts.tsx`, styles at the end of `screens.css`)

| Layout | Rule |
|---|---|
| PageHeader | Back link on top; title (number font for a document number) + status badge + one-line summary on the left; the buttons on the right. "Manager only" is `RightNote` text beside a button, never inside it. While the page is on screen the shell draws no page title and no tab bar: the page's header is the head |
| DetailLayout | Two columns, 3fr / 2fr (about 60 / 40), one column under 1024 px |
| FormLayout | One form: the fields card on the left, the summary panel on the right, which stays in view while scrolling (sticky from 1024 px). `FieldGrid` puts two short fields per row on a desktop and one on a phone (under 640 px); `FullRow` takes the whole row |
| FactList | The record's facts in columns (design `.facts`): a small label over each value, a note under it, as many columns as fit (170 px each) |
| CardGrid, ListLayout | The round 3 rules (balanced card rows; the table scrolls, the top stays) |

### Pilot: Lease details and New Lease

Sheets (design left, app right) at 390, 768, 1366 × 768 and 1920 × 1080: `/mnt/project-files/ui-design/pilot-sheets/sheet-lease-<width>.png` and `sheet-newlease-<width>.png`.

Lease details, every difference from the design:

| Part | Design v81 | App | Fixed or why |
|---|---|---|---|
| Back link | "Back to Home" (the sample came from Home) | "Back to Leases" (names the page the person came from) | Same shared Back link |
| Title | "Lease · U101L0026" | "Lease · U206" | The app has no Lease number (the Lease read carries none). **Open question** |
| Buttons | Renew · Terminate Lease · Manager only · Print Lease | Renew · Terminate Lease · Manager only | "Print Lease" for a signed Lease does not exist in the app (only "Print draft" for a draft). **Open question**: which document prints for a signed Lease? |
| Tabs | None on the record page | None (the Leases / Notices / Move-outs tabs are gone from the record page) | Fixed |
| Lease card | Unit, Primary tenant, Start date, End date, Monthly rent, then Signed on, Renewal of | Same facts in the same order (`FactList`), Renewal of / Renewed by when the Lease has one | Fixed. The unit type and floor under Unit and the phone under Primary tenant are not in the Lease read; the phone is in the Customer card |
| Notes under the Lease card | One sentence | Same sentence; a signed Lease that is not moved in also keeps the app's next-step line under the header ("Signed, Unit is Occupied. Record the move-in…") | Kept: it says what to do next; the design sample is after move-in |
| Signers | Name + role on one line, "Signed <date>" under, chip "Signed" | Name, role under, chip "Signed <date>" | Kept: same facts, the date in the chip |
| Occupants | "Moved in <date>" | "Moves in with the Lease…" until the move-in is recorded | State of the sample Lease |
| Rent and services | Rows Initial Rent · Period · Due date · Then · Services | Same rows (Initial Rent with the pro-rata formula as its note; Period = Start Date to the end of the first billed month; Due date with the Start Date + 5 days note; Services with "Billed on the Rent Invoice each month.") | Fixed |
| Deposits | Required / Received / Balance due, "Received in full.", two plain notes | Same; "Outstanding" is now "Balance due"; the long note is plain text, no longer a blue box | Fixed |
| Customer card | Under Deposits: avatar, name, status chip, "Primary Tenant · Unit · type", Phone, Paid on time + note, Customer Credit, Unpaid Invoices (highlighted when owed), Open Customer | Same (new card; Paid on time from migration 20270711_362; Credit and Unpaid Invoices from the Customer's ledger position). The role line has no unit type (not in the Lease read) | Fixed |
| History | Events name the person ("Signed by Keo Vannak."), "History (4)" button | The app's event names ("Lease signed") with their note; the History button appears when there are more than five events | Kept: the timeline read has no actor name. **Open question** if the owner wants names |
| Layout at 390 and 768 | One column: Lease, Signers, Occupants, Rent and services, Deposits, Customer, History; buttons wrap under the title | Same order and wrapping | Fixed |
| Layout at 1366 and 1920 | Two columns about 60 / 40; five facts in a row at 1920 | Same | Fixed |

New Lease, every difference from the design:

| Part | Design v81 | App | Fixed or why |
|---|---|---|---|
| Header | Back link, "New Lease", one sentence | Same (the Back link names the page the person came from) | Fixed |
| Rows | Unit + Primary Tenant; Other Signers + Other occupants; Start Date + End Date; Monthly Rent + Security Deposit; pet tick; Services; Save as draft · Cancel | Same rows (`FieldGrid`), "Required" / "Optional" marks and the help texts as in the design | Fixed |
| Other Signers, Other occupants | Free text ("Names separated by commas") | Customer pickers ("Add a Customer…") | Kept: the app records Customers, not names (a Signer is a Customer) |
| Primary Tenant | A select | A select with a button to add a new Customer | Kept: an app function the design left out |
| Dates | Plain fields | Fields with a calendar button | Kept: the app's date field |
| End Date default | One year (02/11/2027 for 03/11/2026) | The app's existing rule (30/11/2027 for 08/11/2026) | Kept: not a layout matter; unchanged |
| Services | A radio list of the Property's Services | The same list when Services exist; "No Services are set up in Settings yet." and a "+ New Service" button when none | State of the review data |
| Right column | "What will be billed" + "Next step" (4 bullets), stays in view while scrolling | Same (`FormLayout` side panel) | Fixed |
| Layout at 390 and 768 | One column, one field per row, the side panels under the form | Same | Fixed |
| Layout at 1366 and 1920 | Two columns, two fields per row, no empty half page | Same | Fixed |

### Automatic checks (owner point 4)

`frontend/e2e/screens.spec.ts` (Playwright, `npm run screens`, CI job `screens`): every screen in `frontend/e2e/screens.ts` at 390 × 844, 768 × 1024, 1366 × 768, 1440 × 900 and 1920 × 1080 against the built app, with the server answers replayed from `frontend/e2e/fixtures/<name>.har.json` (recorded once with `node e2e/record.mjs`; no database and no API in CI). The check fails on horizontal page overflow, a button, link or tab under 44 × 44 px, colour contrast under 4.5:1 (axe-core), cut-off text or numbers, a role badge inside a button, a card alone in a grid row on a desktop, and two stacked tables. The screenshots of every screen and size go to `frontend/e2e/results/shots/`.

First run on the pilot: the Back link (38 px tall), the inline links (39 px) and "Open Customer" (32 px) failed the 44 px rule and were fixed in the shared styles (`.ui-crumb`, the inline-link rule, `.ui-btn.link`); everything else passed. Both pilot pages pass at all five sizes.

### Other changes in this round

- Lease page texts: "Outstanding" → "Balance due"; "Terminate" → "Terminate Lease"; "Save draft" → "Save as draft"; the New Lease help texts as in the design.
- The "Earlier forms" box under Leases is gone (the other pages keep theirs until their batch).
- New read `GET /api/v1/properties/{id}/customers/{id}/paid-on-time` (invoices.read; migration 20270711_362, function `app.customer_paid_on_time`): one Customer's Invoices of the last 12 months paid by their Due Date.
- Shared hit areas: the Back link, inline links and text buttons are 44 px tall to press without changing the lines around them.

### Open questions (for the owner)

1. Lease number: the design shows "Lease · U101L0026"; the app has no Lease number. Should Leases get a document number (prefix, numbering rule), or does the title stay "Lease · <Unit>"?
2. Print Lease for a signed Lease: which document should print (the signed agreement, the draft form, or nothing)?
3. History names: should the Lease timeline name the person who did each step ("Signed by Keo Vannak")? The timeline read has no actor name today.

## Round 5b (owner 08/11/2026 08:14): pilot approved, two fixes and three answers

The owner approved the pilot with two fixes and answered the three open questions. No design change.

### Fixes

| Fix | What changed | Where |
|---|---|---|
| History button | The "History (n)" button is always at the bottom of the History card, also with 5 steps or fewer; it opens the full History | Lease page (the other pages get it in their module batch) |
| Font weight | A `<b>` or `<strong>` inside a value took the browser's "bolder" (900 on a 600 value), so amounts, dates, the "Then…" text and "Received" were heavier than the design. One shared rule now keeps the value's weight (600, design `.kv2 dd`) on every page; the figures in a facts row are 600 as in design `.facts b`. Measured on the Lease page: Initial Rent, Due date, Then and Received are 600, the same as the design | `screens.css` (shared, every page) |

### Answers

| Question | Owner's answer | What was built |
|---|---|---|
| Lease number | Unit + "L" + 4-digit running number (U101L0026); existing Leases numbered by Start Date; shown in the title, on the Leases list, and on Notices and Invoices where a Lease is named; a new migration that only adds the number | **Migration 20270712_363** (see below). The Lease read has `lease_number`. Shown in the Lease title and its windows (Sign, Edit, Cancel, Move-in, Receive deposit, Terminate, Print draft), the Leases list (column "Lease"), Renewal of / Renewed by, the Notices pages, and the Invoice page's "Open Lease U101L0026" button. A Lease read without a number still names its Unit |
| Print Lease | It will print the signed agreement with the Lease's details; the agreement text is still with the lawyer, so do not build it now | Not built; the button stays out. **Open question: waiting for the final agreement text** |
| History names | Name the person for every step ("Draft made by Chan Sophea", "Signed by Keo Vannak"), from the name already stored with each step, on every page's History | Lease History done: each step reads "<step> by <name>"; a Signer's signature reads "Signed by <Signer>" with "Recorded by <name>" under it. The name is the user account's display name stored for the person who did the step; nothing is copied or changed. The other pages get the names in their module batch |

### Migration 20270712_363 (the only data change of this round)

- New table `app.lease_numbers` (Lease, Property, running number, Lease number, time given). Append-only: a change, a delete or a truncate is refused.
- New table `app.lease_number_counters`, one row per Property. It only moves up by one.
- An AFTER INSERT trigger on `app.leases` gives each new Lease the next number of its Property when it is drafted. Two drafts at the same time never share a number (the counter row is locked).
- The Leases already recorded were numbered once, per Property, in order of Start Date, then the day they were drafted. No existing row of any table is changed.
- The number is written once: a Unit renamed later keeps the old number on its earlier Leases. A cancelled draft keeps its number, so the numbers may have gaps.
- The app's own database role may read the numbers but not write them or read the counters. The migration cannot be rolled back (forward-only).
- Decision log: DL-220 (wording sent for a separate docs change).

### Sheets

The Lease sheets were made again at all five sizes (390, 768, 1366 × 768, 1440 × 900, 1920 × 1080): `/mnt/project-files/ui-design/pilot-sheets/sheet-lease-<width>.png` and `sheet-newlease-<width>.png`. Both pages pass the screen check at all five sizes.

Lease details, differences left after this round:

| Part | Design v81 | App | Why |
|---|---|---|---|
| Title | "Lease · U101L0026" | "Lease · U206L0022" (the sample Lease) | Same rule; different sample |
| Print Lease | A button | No button | Owner 08/11: waiting for the final agreement text |
| History lines | "Signed by Keo Vannak." with the time | "Signed by Keo Vannak", "Recorded by …" and the note under it, then the time | The note (reason) the person wrote is kept |

Tests: TEST-FE-1923 (Lease number in the title and list, History names, History button with two steps), TEST-FE-1924 (Invoice page Open Lease with the number); backend `test_lease_number_migration.py` (the next number and the names in the read; written once; the counter moves by one; the app role reads only).

## Round 6 (owner 08/11/2026 08:14): module batch 1, Home

The first module batch after the pilot, with the pilot's method: the shared layouts, a design-and-app sheet at all five sizes, the screen check passing, and every difference with its reason. No design change. The next module waits for the owner's approval of this one.

### What changed

| Part | Change | Where |
|---|---|---|
| Page head | Home is drawn with the shared `PageHeader`: the title "Home" on the left, Receive payment and Enter meter readings on the right (one title on the page) | `home/HomeScreen.tsx` |
| Card rows | The Home cards, the Owner money row and the Tasks cards use the shared `CardGrid` (the Tasks cards are one group named "Tasks") | `home/HomeScreen.tsx`, `home/OwnerMoney.tsx`, `shell/layouts.tsx` |
| Card titles | Every card title (h2) is 1.125rem, weight 600, as design v81 `h2` (it was 1.15rem bold). Small titles inside a card (h3) and the Tasks list title are 600 | Shared: every page |
| Card figures | A card that is a link shows its figure in the dark text colour, as design `.kpi .kv` (it showed the link green); red for a problem and grey for nothing stay. The Owner money figures are 1.6rem and stay on one line, as design `.om29 .kv` | Shared: every page with number cards |
| Grey text | The grey of "nothing here" figures is design v81's `--muted` (#6B6962, it was #79776F) | Shared: every page |
| Phone cards | Under 640 px a card has 12 px padding, as design `.kpi` on a phone (the rule was there but a later rule won over it) | Shared: every page with number cards |
| Cards without a bar | Owner money and Tasks cards have three rows (label, figure, note) like design `.kpi.nm`, so no empty row adds a gap at the bottom | `screens.css` |

Measured after the change at 1440 × 900 (design | app): page title 28 px / 600 | 28 px / 600; card titles 18 px / 600 | 18 px / 600; card labels 14 px / 600 | 14 px / 600; figures 28 px / 700 (Owner money 25.6 px / 700) | the same; notes 13 px / 400 | the same; task rows 16 px / 600 with the date 14 px / 600 | the same; figure colour #252A28 | #252A28.

### Sheets

`/mnt/project-files/ui-design/module-sheets/sheet-home-<width>.png` at 390, 768, 1366, 1440 and 1920 (design left, app right). The app side is Home with the Later Tasks card open (`#/home?tasks=later`), so the open list can be compared with the design's open Overdue list. The screen check opens Home both ways (`home`, `home-tasks`) at all five sizes and passes.

### Every difference left, with its reason

| Part | Design v81 | App | Why |
|---|---|---|---|
| Numbers in every card | Sample data | The review database's own numbers (mostly 0) | Not faked: the app shows what the database holds |
| Tasks list | Overdue open, 8 rows | Later open, 6 rows | No task is overdue in the review data; the app opens Overdue first when there is one (TEST-FE-929), as the design does |
| Task row names | Supplier bills, Invoices, letters | "Lease for LEASE-… ends" | The review database also holds the test Units, named LEASE-…; real Units read U101 and so on |
| Paid on time | 79% with a bar | "—" and "No Invoice was due in the last 12 months" | No Invoice was due in the review data, so there is no share to show |
| Attendance | 3 to check, warning icon | 0, tick icon | Review data |
| Line at the bottom | Green tick: the last billing run and rate update | Amber: no billing run has finished, no ABA rate loaded | Review data; the app says so instead of hiding it |
| Card heights in a row | Taller rows | Shorter rows | Cards in a row share the height of the longest note; the sample notes are longer |
| Menu | "Collapse menu" and a fold arrow per group | Fixed menu | Not built yet (open question 10) |
| Banner under the top bar | "Design v81, for owner approval…" | None | Design only |
| Page edge | Content starts 8 px further in | Same 16 px (phone) and 24 px (tablet) page margin | The design page has an extra 8 px body margin; the page margins are the same |

Tests: TEST-FE-1925 (Home on the shared PageHeader and CardGrid). The screen check (`frontend/e2e/screens.spec.ts`) now has `home` and `home-tasks` with the recorded answers in `frontend/e2e/fixtures/home.har.json`.

Shared changes reach the Lease pilot too: the Lease sheets were made again with the new card titles.

## Round 6b (owner 08/11/2026 09:57): Home fixes and the side menu

The owner answered the Home sheets with three points: the task texts showed internal codes, the side menu had to be built now (section D of 05:43), and "Paid on time" had to be checked. Home stays with the owner for approval; Payments has not started.

### 1. Task texts with internal codes ("Lease for LEASE-0a96849c55e3 ends · Primary Lease Customer")

**Root cause.** The screen never prints an ID: every Home task row is drawn from the Unit number and the Customer's legal name that the server sends (`home/HomeScreen.tsx` `rowOf`, `app.home_page` since migration 220). The review database held the backend test suite's rows, whose Units are literally named `LEASE-<hex>` and whose Customers are literally named "Primary Lease Customer", so the screen showed those names faithfully. Every task kind was checked in `app.home_page` (overdue first rent, Lease ending, Reservation ending, drafts waiting, deposit decisions, readings missing, day-20 and day-30 notices, settlements, refunds): each carries `unit_number` and `customer_name`, none carries a code the screen would show.

**Fix, as the owner asked.** "Comes from the test data" is no longer an answer: the review app now runs on the design's own sample data, loaded by a new script, `scripts/local/seed-design-data.py` (Mac launcher `scripts/local/seed-design-data.sh`). It loads, into an EMPTY test database only: the 23 Units U101 to U406 with their Unit Types and rents, the 30 people with their real names and phone numbers, one signed Lease per occupied Unit with the design's dates (so the Lease numbers run U101L0001 to U406L0023 by Start Date), this month's Rent Invoices with their payments (U203, U402 and U304 still unpaid), the U406 Reservation of Tep Sreymom with its Deposit and drafted Lease, the 46 meters with readings, and two birthdays in the coming week. Home then reads "Lease for U201 ends · Ouk Chanthy. Ask about renewing." and "Reservation for U406 ends · Tep Sreymom". The script refuses to run when the database already holds a Unit, and nothing is deleted or changed.

**What the sample data cannot do (database rule).** An Invoice and a payment allocation cannot be dated in the past: the database stamps the issue time and the allocation time with the real clock and refuses an issue time before the Invoice lines were written (`app.stamp_invoice_detail_change`, `app.validate_invoice_issuance_lines`, `app.validate_payment_allocation_source`). A recurring Rent Invoice may only be dated on its billing day and due on the 5th, and only for a month after the move-in month (`app.lease_is_billable_for_recurring_period`). So the Rent history of earlier months is not made up: the Invoices are this month's (dated 25/10, due 05/11, issued the moment the script runs), their payments are dated in the past week, and cards such as Overdue and Paid on time fill up as real months pass. This is the database protecting the financial record, as the repo rules ask, so the script works with it rather than around it.

**Playwright check.** `frontend/e2e/screens.spec.ts` step 7 reads every visible text of the page and the menu and FAILS on an internal ID or placeholder: a UUID, `LEASE-`/`INV-`/any capital prefix followed by hex, a long hex key, "Primary Lease Customer", "Primary Lease Tenant", "Lease Service", "Synthetic", "Lorem ipsum", "TODO", "undefined", "null", "NaN", "[object Object]", "Test Customer/Unit/Lease/Tenant/Property". Only the build id at the foot of the menu is left out. The Home fixture (`e2e/fixtures/home.har.json`) was re-recorded from the design data, so the check runs on the design's names.

### 2. Side menu (section D, points 12 to 17), built as the design app23.js

| Owner point | Built | Where |
|---|---|---|
| 12 "Collapse menu" | A button under the brand shrinks the menu to an 84 px rail of icons; the name and the sub-items show in a fly-out on hover or focus (Escape closes it and the focus returns to the icon); the button becomes "Expand menu" (Khmer បង្រួមម៉ឺនុយ / ពង្រីកម៉ឺនុយ); remembered on the device (`chetana-rail`); not shown under 1081 px | `shell/AppShell.tsx`, `shell/shell.css` |
| 13 Groups fold | Operations, Leasing, Property and Administration are buttons with `aria-expanded`; folded, a group shows its item count and "›" (for example "Property 4 ›"); the group of the open page is always open (it opens when the page is entered); remembered (`chetana-navgrp`); the folded group of the open page keeps a thin bar, as in the design | same |
| 14 Sub-items | An item with tabs (Invoices, Bookings, Leases, Products, Ledger, Staff, Telegram; Approvals, Users and access and Settings with their in-page tabs) gets a "⌄" whose sub-items link to the SAME addresses as the tabs (`#/letters`, `#/approvals?tab=shortstays`, `#/settings?tab=rates`...). No address changed. The open page's sub-items open by themselves, the current one is marked, and a sub-tab picked inside the page moves the mark (the tab bar now tells the address listeners). Items without tabs (Payments, Utilities, Short stays, Customers, Units, Inspections, Problem reports, Reports, Audit log) have no "⌄". Tabs not built yet are not in the menu; a person sees only the tabs they may open | `shell/navigation.ts` (`PAGE_SUB_TABS`, `subItemsOf`), `shell/AppShell.tsx`, `shell/ui.tsx` |
| 15 User card | Avatar, name and role ("Kompheak · Owner"; Khmer ម្ចាស់, អ្នកគ្រប់គ្រង, បុគ្គលិក) and Sign out. The role is the account class the server already keeps for each user (owner, manager, staff); the session answer now carries it as `account_class`, display only. "My account" shows while the role is unknown | `shell/AppShell.tsx`, `authClient.ts`, backend `auth_flow.py`, `auth_api.py` |
| 16 Phone | The same menu is the drawer behind ☰ (unchanged); Collapse menu and the fly-out do not exist there | `shell/shell.css` |
| 17 Keyboard | Group headers and "⌄" are real buttons (Enter and Space) with `aria-expanded` and `aria-controls`; the fly-out opens on focus and closes with Escape | `shell/AppShell.tsx` |

Measured at 1440 × 900 (design | app): menu width 252 | 252 px, rail 84 | 84 px; item rows 44 | 44 px; group header 36 | 44 px; sub-item rows 40 | 44 px (the 44 px touch rule of the owner's check, point 4, wins over the design's 36 and 40); fly-out 220 to 280 px wide, 44 px title row, both; icons 20 px, chevrons 16 px (18 px on the "⌄"), both.

### 3. "Paid on time" says "No Invoice was due in the last 12 months" while "Paid this month" shows money

**The card is right.** It counts an Invoice only once its Due Date has passed (`due_date < today`, migration 361), because an Invoice that is not yet due cannot be late. "Paid this month" counts the Invoices DUE in this month, paid or not. In the old review data every Invoice was due on 15/11, so on 08/11 "Paid this month" had Invoices to show and "Paid on time" had none yet. With the design data the Invoices are due 05/11: the card now counts them, "0% · 0 of 18 Invoices, last 12 months", because their payments were allocated the moment the script ran (08/11), three days after the Due Date (the database rule above). When the script runs on or before the 5th they count as paid on time. The design's 79 % needs twelve months of real Invoices and payments, which no script may invent.

### 4. Also found and fixed on the way

- The screen check's recorded sign-in ran out after 30 minutes (the recorded session's expiry times were in the past, so every screen showed "You were signed out"); the replay now moves them to the present (`e2e/replay.ts`).
- The drawer's close button shrank to 44 × 24 px when the menu was taller than the screen (a flex item with `min-height: auto`); every part of the menu is now `flex: none`.
- The tab bar's address update fired the new menu listener even when the page had no address (unit tests of the Settings tabs); it now fires only when the page is in the address.
- The menu's item markers clashed with the page markers of `App.tsx` (`data-page`), so the menu uses `data-menu-page`.

### Sheets

`/mnt/project-files/ui-design/module-sheets/`: `sheet-home-<w>.png` (Home with the design data, the Later Tasks card open), `sheet-menu-open-<w>.png`, `sheet-menu-collapsed-<w>.png`, `sheet-menu-folded-<w>.png` at 390, 768, 1366, 1440 and 1920 (design left, app right). On the phone and tablet sheets the menu is the open drawer; "Collapse menu" does not exist there, as the design.

### Every difference left, with its reason

| Part | Design v81 | App | Why |
|---|---|---|---|
| Owner money, Attendance, Approvals, Notices, Viewing requests, Problem reports, Cash and bank | Sample figures | $0.00 and 0 | The design data holds Units, people, Leases, this month's Rent Invoices and payments, the Reservation and the meters; it holds no ledger postings, supplier bills, expense reports, problem reports, viewing requests, attendance or notices (each needs its own module's rows; they come with that module's batch) |
| Paid this month | $3,716.20, 40 % of $9,222.25 | $5,560.00, 83 % of $6,690.00 | 15 of this month's 18 Rent Invoices are paid in the sample data (the design's figure includes Utilities and Products Invoices) |
| Paid on time | 79 %, 95 of 120 Invoices | 0 %, 0 of 18 Invoices | See point 3: counted, but allocated after the Due Date by the database rule |
| Overdue | $696.20, 4 Invoices | $1,130.00, 3 Invoices | The three unpaid Rent Invoices (U203, U402, U304); the design's fourth is a Utilities Invoice |
| Tasks | Overdue open, 8 rows (supplier bills, Invoices, a letter) | Later open, 4 Lease renewals; This week 1 (Reservation U406) | No supplier bill or expense report in the data; Rent Invoices unpaid since 05/11 become day-20 letters on 25/11 (BR-LETTER) and are not tasks before that |
| Meter readings missing | 15 | 46 | Every meter's November reading is missing in the sample data (reading day 24/11); the design counts 15 |
| Occupancy | 21 / 28 | 21 / 23 | The design has 28 Units in its text and 23 in its Units list; the script loads the 23 of the list |
| Menu brand line | "CHETANA Residence SAMPLE" on one line | "CHETANA Residence" wraps beside the DEVELOPMENT badge | The badge is the app's environment name; it is longer than the design's "SAMPLE" |
| Drawer (phone, tablet) | No close button; the first item has a focus ring | A × button at the top of the drawer | Kept from V1-058 (TEST-FE-807): a visible way to close without the scrim |
| Group header and sub-item height | 36 px and 40 px | 44 px | The owner's 44 px touch rule (06:55, point 4) |
| Avatar | "KP" | "K" | Initials come from the display name, which is one word ("Kompheak") |
| Build line | "Design v81 round 4 · 08/11/2026" | "Build development" | The app shows its build |

Tests: TEST-FE-1926 (Collapse menu), 1927 (groups), 1928 (sub-items and their addresses), 1929 (user card role), 1930 (fly-out); TEST-FE-809 updated (the sub-item Notices carries the current mark). Backend: the session answer's `account_class` (test_authentication_api). Screen check: 7 screens × 5 sizes pass, with the menu now inside the checks (targets, cut-off text, contrast, internal IDs).

### Open questions (for the owner)

- The design data: run it on the Mac test app only on an EMPTY test database (`sh scripts/local/seed-design-data.sh`); it refuses otherwise. A test database that already holds rows needs a fresh database first (database.sh).

## Round 7 (owner 12/11/2026 04:23): Home cards

The owner answered the Home sheets with a numbered picture and seven points. These are the owner's own choices, so where they differ from design v81 the owner's choice wins.

### What changed

| Owner point | Before | Now | Where |
|---|---|---|---|
| 1 | Box "Owner money" with the chip "Only the Owner sees this" | Box "Financial summary" (Khmer សង្ខេបហិរញ្ញវត្ថុ), no chip. Still shown only to a person with `ledger.owner_money` and `ledger.read` | `home/OwnerMoney.tsx`, `home/text.ts` |
| 2 | Each card: name, then the number on its own line, then the note | The number sits at the top right, beside the name; the note is under them. On Home this is every card: the Financial summary, the cards and the Tasks cards (class `ui-kpi-top`, head `ui-kpi-head`) | `home/HomeScreen.tsx`, `home/OwnerMoney.tsx`, `shell/screens.css` |
| 3 | No Short stays cards | "Short stay bookings": bookings with the status Booked (not checked in yet), note "1 arrives today". "Short stays checked in": guests staying now (status Checked in), note "1 checks out today". Both open Short stays; read with `short_stays.read` from the bookings list the Short stays page already reads | `home/HomeScreen.tsx` (`staysNowOf`) |
| 4 | "Occupancy 21 / 23 · 1 reserved · 1 vacant" | "Vacant Units 1 · 23 Units · 1 reserved" (only the vacant Units are counted; the same Home read) | `home/HomeScreen.tsx` |
| 5 | "Paid on time" card | "Low stock": products at or below their reorder level and still sold (the Products page's own `low_stock` mark); opens Products; read with `products.read` | `home/HomeScreen.tsx` (`lowStockOf`) |
| 6 | A wide "Attendance needs attention: n" row above the cards with the button "Open the daily sheet" | A card "Attendance" as the last card: the people to check today, note "Needs check 2 · No check-out 1" or "Nothing to check today"; opens the daily sheet | `home/HomeScreen.tsx`, `home/OwnerMoney.tsx` (`attendanceToCheck`) |
| 7 | Occupancy, Pending payment, Paid this month, Overdue, Leases ending soon, Approvals, Meter readings missing, Notices due, Viewing requests waiting, Problem reports, Birthdays, Paid on time | Vacant Units, Viewing requests waiting, Leases ending soon, Short stay bookings, Short stays checked in, Pending payment, Paid this month, Overdue, Approvals, Meter readings missing, Notices due, Problem reports, Birthdays, Low stock, Attendance | `home/HomeScreen.tsx` |

No database or server change: every number comes from a read the app already has, and each new card is read only by a person who holds its right; a read that fails leaves only its own card out.

### How the number fits (point 2)

- The name takes the room left of the number and may take three lines. The number is as tall as the icon circle, so it sits level with the first line of the name.
- When the name and the number do not fit side by side (a long amount in a narrow phone card), the number goes under the name, at the right. Nothing is cut.
- The card measures itself (a CSS container): a card narrower than 200 px inside drops the icon circle and draws the number a little smaller (1.05rem to 1.5rem with the card's width).
- A row of cards is only as tall as its own cards (it was as tall as the tallest card of the page).
- Fifteen cards are 4 + 4 + 4 + 3 on a desktop and fourteen are 4 + 4 + 3 + 3; a tablet keeps three per row and a phone two per row (round 3 rules).

### Review data

The review app's sample data got three sample products with a reorder level (and one without), three short-stay bookings in U305 (one checked in today, two booked) made through the app's own screens' server calls; Attendance has no rows yet, so its card reads "0 · Nothing to check today".

### Every difference from design v81 left, with its reason

| Part | Design v81 | App | Why |
|---|---|---|---|
| Box name | Owner money, "Only the Owner sees this" | Financial summary, no chip | Owner 12/11, point 1 |
| Card layout | Number on its own line under the name | Number at the top right | Owner 12/11, point 2 |
| Cards and order | 12 cards, Occupancy first, Paid on time last | 15 cards in the owner's order | Owner 12/11, points 3 to 7 |
| Paid on time | A Home card | Not on Home | Owner 12/11, point 5. The read stays: the Customer card on the Lease page still shows a Customer's "Paid on time" |

Tests: TEST-FE-928, 930, 931, 1294, 1912 and 1925 updated; TEST-FE-1907 (Financial summary) and 1908 (what Attendance counts) updated; new TEST-FE-1931 (the fifteen cards, their counts, rights and failures) and TEST-FE-1932 (the number beside the name on every Home card). Screen check: the Home answers were recorded again (now with the bookings, products and attendance reads); 7 screens × 5 sizes pass.

## Round 8 (owner 12/11/2026 04:34 and 04:36): Approvals and Settings in the real app

The owner tested the Mac test app and sent two lists. This round is the screen part of them for Approvals and Settings. The Payments and Receipt names ("Paid for") follow in their own round, because they need a small read-only database step. The Invoice types and the short-stay damage approval are rule changes: they went to the main chat and are not part of this branch's work.

### What changed

| Owner point | Before | Now | Where |
|---|---|---|---|
| Approvals: "Review tab corner round style" | The sub-tabs were round pills, the chosen one a filled green pill; a line ran under them | Sub-tabs are square and joined in one box with 8px corners, the chosen one tinted with a green underline: the same look as the filter row on Payments ("All / Today / This month"). The count beside a name is a plain number. On a phone the tabs are separate square buttons in one scrolling row. This is the shared sub-tab row, so Settings › Business, Utility rates, Monthly services and Users and access change the same way | `shell/screens.css` (`.ui-subtabs[role="tablist"]`) |
| Approvals › Financial: "check spacing of cards" | The number cards, the list, the note and "Processed today" touched each other (the tab's panel had no space rule) | A sub-tab's panel is a stack: its parts keep the normal space. On a page the panel uses the page's own space (22px), so Approvals looks the same with and without tabs; the tabs no longer add a second gap under themselves | `shell/ui.tsx` (`SubTabPanel`), `shell/screens.css` |
| Settings: cards and notes touching (seen while fixing the above) | System health's two cards and note, Unit setup's filter row and card, and the "earlier forms" note under every tab touched the part above | Settings keeps 16px between its cards, notes and filter rows | `settings/SettingsPage.tsx` (`ui-settings`, `ui-earlier`), `shell/screens.css` |
| Settings › General 1: rename "Riel exchange rate" to "Exchange"; show the rate with no riel payment yet | Card "Riel exchange rate" showed only the last rate used, or "No riel payment yet." | Card "Exchange" (Khmer អត្រាប្តូរប្រាក់) with two lines. "Rate now": the app's rate at this moment, from the read the Receive payment form already uses (a preview of one dollar; nothing is saved; needs `payments.record`). "Last rate used": the newest confirmed rate with its source and time, or "No riel payment yet." | `settings/BusinessTab.tsx`, `settings/text.ts`, `App.tsx` |
| Settings › Business rules 2: "Table columns are misaligned" | One table per group, each with its own column widths | Every group's table has the same widths (Rule 44%, Value 25%, Effective from 20%, Edit 11%) from 641px up; a long rule name or value wraps. On a phone each table keeps its own widths so it fits the screen | `settings/BusinessTab.tsx` (`ui-rules`), `shell/screens.css` |
| Settings › Monthly services 4: Rate history does not open; scrolling works only under the table | On a desktop the Services card was a fixed-height scrolling area (the round 3 "only the table scrolls" rule). "Rate history" sat at its bottom edge and opened out of sight, and the wheel scrolled the page only outside the card | A card that holds a history that folds open (`details.ui-hist`) is not fitted: that page scrolls as usual. Opened, the history scrolls into view under the top bar. A history still folded shut no longer counts as a second table | `shell/tableFit.ts`, `settings/RatesTab.tsx`, `shell/screens.css` |
| Settings › System health 5: "The health records are not set up on this computer yet. Needs attention." | Shown as a warning on every computer | On a test app (the screens' own label, the "DEVELOPMENT" mark in the menu) this note is normal: the chip says "Test computer" and a calm note says backups and health checks are set up by the real install. Any other note still says "Needs attention". On the real install nothing changes | `settings/SettingsPage.tsx`, `settings/text.ts`, `App.tsx` |

No database or server change in this round.

### The rate now: what the app can show today

The app has no link to ABA's published rate yet. The server's rate source is a placeholder that always answers "not available" (`UnavailableExchangeRateProvider`; nothing passes a real source to the app). So "Rate now" reads "Not available · The app cannot read the ABA rate now." on every computer until a source is connected, and the Receive payment form says "Today's riel rate is not available yet" for the same reason. The card shows the rate by itself as soon as the server has one. Connecting a source decides the rate used when riel is received, so it is the owner's decision and not a display change (open question 14 in 01).

### Review data

Six sample Monthly services with two later rate changes for four of them were added to the review app through the app's own server calls, so the Services table and its Rate history have rows.

### Every difference from design v81 left, with its reason

| Part | Design v81 | App | Why |
|---|---|---|---|
| Sub-tabs | Round pills | Square, joined | Owner 12/11: one tab look; the same as the Payments filter row |
| Riel card on General | "Riel exchange rate", last rate only | "Exchange", rate now and last rate used | Owner 12/11, Settings point 1 |
| Monthly services on a desktop | The table scrolls in its own area | The page scrolls | Owner 12/11, Settings point 4: the opened history needs room |
| System health on a test app | "Needs attention" | "Test computer" with a calm note | Owner 12/11, Settings point 5 |

Tests: TEST-FE-950 updated (the card's name and lines) and TEST-FE-955 extended (the history folds and comes into view); new TEST-FE-1933 (square tabs, the panel is a stack), 1934 (System health on a test app, Settings spacing), 1935 (Exchange card, Business rules column widths) and 1936 (a card with a history is not fitted).

## Round 9 (owner 12/11/2026 04:34): the Payments list and the Receipt page say the same "Paid for"

The owner's two Payments points from the real app:

1. "Receipt table / RCP260020 is paid for Move-out charges. Yet, in Receipt Detail, it is paid for a short stay."
2. "Receipt table / RCP260018 is paid for Rent Services Deposit. Yet, in Receipt Detail, is paid for Rent."

### Why the two screens differed

The list divided each payment by the category of the Invoice **line** it paid (Rent, Utilities, Services, and one kind for every one-time charge line, named "Move-out charges"). The Receipt page named the **type of the Invoice** (DL-221: Rent, Utilities, Short stay, Products, Damage, Other charges). A short stay's Invoice has one-time charge lines, so the list said "Move-out charges" and the page said "Short stay". A Rent Invoice may hold Services lines, so the list said "Rent, Services" and the page said "Rent".

### What changed

| Part | Before | Now | Where |
|---|---|---|---|
| Payments cards and the "Paid for" column | Rent, Utilities, Services, Late-payment charges, Deposits, **Move-out charges**, Customer Credit | Rent, Utilities, Services, Late-payment charges, Deposits, **Short stay, Products, Damage, Other charges**, Customer Credit. Money paid to a one-time charge counts under the type of its Invoice. The four new kinds add up to what "Move-out charges" was, so the cards still add up to the money received | `payments/PaymentsList.tsx`, `payments/text.ts`, migration 20270713_364 (`app.payments_period_summary`) |
| Card rows | 8 cards (4 + 4) | 11 cards: Total received, the ten kinds; 4 + 4 + 3 on a desktop by the shared card rule (no card alone) | shared `.ui-kpis` rule, unchanged |
| Receipt page, card "Paid for" | One line for each Invoice with its type | The same line, and under it the parts of that Invoice when they say more than its own name: "Rent $316.67 / Services $19.00" under a Rent Invoice. A short-stay Invoice shows no parts (its one part is the Invoice itself) | `payments/ReceiptPage.tsx`, `payments/paymentsClient.ts`, `shell/screens.css` (`.ui-app-parts`), migration 20270713_364 (`app.payment_receipt_lines` gives `parts`) |
| Printed Receipt | – | Not changed: it prints the Invoice lines as before | – |

Names of the new cards: Short stay ("Daily and weekly guests"), Products ("Sold with a Quotation"), Damage ("Move-out and short-stay damage"), Other charges ("Cleaning and other one-time charges"). The Khmer of the four notes is new and needs the native check.

### The database step (migration 20270713_364)

Read only. It changes the text of two read functions and nothing else: no table, row, amount, document, number or ledger entry. Each function is changed from the text the database holds (each old text must be there exactly once, or the migration stops), so a change made by another migration stays. Forward-only. It follows 20270712_363 and is the head of this branch. The Database thread checked it on a copy that followed the owner's Mac path before it was pushed.

An app from before this step that reads a database after it (or the other way round) shows "invalid response" on Payments instead of a wrong name: the screens refuse the old kind `MOVEOUT`.

### Review data

A Lease with two Monthly services (U406L0024) was drafted from a Booking and signed with cash through the app's own screens, so one real Receipt (RCP260018) pays Rent, Services and a Security Deposit.

### Every difference from design v81 left, with its reason

| Part | Design v81 | App | Why |
|---|---|---|---|
| Payments cards | Seven kinds with "Move-out charges" | Ten kinds by Invoice type | Owner 12/11, Payments points 1 and 2; DL-221 names |
| Receipt page "Paid for" | Invoice lines only | Parts under a Rent Invoice | Owner 12/11, Payments point 2 |
| Reports › Payments register | "Move-out charges" | "Move-out charges" (not changed yet) | Its own report read; Reports batch (01, open question 15) |

Tests: TEST-FE-914 updated (the category cards); new TEST-FE-1937 (cards, names, Paid for cells, card filter), 1938 (parts on the Receipt page; printed Receipt unchanged) and 1939 (the client reads the new kinds and parts and refuses the old kind); database tests `test_payments_paid_for_migration.py` (three) and `test_payments_summary_migration.py` (kinds and parts).

## Fixes after the first full check on GitHub (12/11/2026)

No screen design changes. The full check on GitHub ran on this branch for the first time and found three faults that this branch had brought in. All three are put right; nothing else changes.

### 1. The four "Totals by Unit and month" reports open again

Reports › Total Income, Total Rent, Total Utilities and Total Paid Income did not open on this branch since round 4 (08/11): the page showed an error. In `backend/src/property_rental/reports_api.py` the route line for these reports had been left above the Birthdays function, so the Totals function had no address. The line is back above `totals`. Checked in the review app: Total Income opens with its Units and months.

### 2. The Home read keeps four earlier fixes (migration 20270714_365)

Round 4 added the "Paid on time" and "Birthdays" cards with migration 20270710_361. That step replaced the Home read (`app.home_page`) with a whole new text written from an old version (migration 222), so the four changes made after it were lost on this branch:

| Earlier step | What it does | What was wrong on this branch |
|---|---|---|
| 20270319_238 (DL-098, owner 26/10 "Meters decide") | The "Refund due by" to-do of a Unit with no Meter counts from the final inspection alone | The to-do did not show for such a Unit |
| 20270323_242 (V1-060) | A Refund draft the read does not understand counts as waiting with no amount | One such draft stopped the whole Home page |
| 20270324_243 (V1-060 speed) | The two Invoice lists are read once | Slower Home page; same figures |
| 20270408_258 (DL-116, owner 31/10) | A Unit not for rent is not counted | It was counted in the Units card and in the missing Meter readings |

Migration 20270714_365 follows 20270713_364. It reads the function text the database holds, puts the seven exact texts of those four steps back (each old text must be there exactly once) and checks that the Paid on time card and the Birthdays section are still there. After it, the Home read is the same as before round 4 plus the three round 4 additions, with the same owner, privileges and settings. Read only: no table, row, amount or document changes. Forward-only. Migration 361 is not edited, because it is already applied on the test computers.

Rule for later steps on this branch: change a database function from the text the database holds (as migrations 364 and 365 do). Never replace it with a whole text copied from an old migration.

### 3. Two tests brought up to date

- `test_local_run_scripts.py`: the list of local scripts names `seed-design-data.sh` (round 6b).
- `test_lease_timeline_restricted_migration.py`: a person who may read Leases only gets the same History steps as before, and each step now carries the name of the person who recorded it (round 5b, "History names the person").

Tests: new database tests `test_home_page_earlier_fixes_migration.py` (four); the earlier tests of the four steps pass again (`test_final_settlement_preview_migration.py`, `test_v1_060_release_migration.py`, `test_unit_for_rent_migration.py`, `test_reports_home_migration.py`); `test_report_totals.py` passes again.

## Round 10: Home card rows, the menu colour, the Payments cards (12/11/2026)

Owner 12/11 10:47 ("Large screen, Laptop, iPad: why don't you arrange 5 columns per row for card? The background colour of the navigation menu should fill to the bottom of the page") and 11:03 ("Why is the height of the cards in the Payments page short (1 line) even on a large screen? Rename the card Late-payment charges to Late-payment").

| What | Before | After | Where |
|---|---|---|---|
| Home cards per row | Four per row on a computer (15 cards = 4 + 4 + 4 + 3), three on a tablet; the Financial summary 3 + 2 | Five per row from an iPad up (700 px): the Financial summary is one row of five and the fifteen cards are three rows of five. A phone keeps two per row. With fewer cards (a role that sees fewer) no card is alone: one left over makes the last six 3 + 3, two left over make the last seven 4 + 3 | `shell/layouts.tsx` (`CardGrid five`), `shell/screens.css` (`.ui-kpis.ui-five`), `home/HomeScreen.tsx`, `home/OwnerMoney.tsx` |
| A name beside its number | A long word could break in the middle beside the number ("Customer / s owe") in a narrow card | The name is as wide as its longest word. In a narrow card the name keeps most of the width: a short count stays beside it and an amount goes under it, at the right. On an upright iPad the text is a little smaller and the amount scales with the card, so twelve characters ("$999,999.99") show in full | `shell/screens.css` (`.ui-kpi-head`, the card's own size rules) |
| The icon circle of a Home card | Shown on a computer | Shown on a large screen; left out on a laptop and an iPad, where five cards per row leave no room for it | Existing narrow-card rule |
| Tasks cards | Four per row | Unchanged (there are four) | - |
| Menu colour | The menu stays in the window while the page scrolls, but the column under it was the page colour, which showed in a picture of a long page | The whole column is painted in the menu colour, to the bottom of the page, also with the menu collapsed. Not where the menu is a drawer, and not on paper | `shell/shell.css` (`.shell`) |
| Payments card name | Late-payment charges | Late-payment (the Khmer name is unchanged). The "Paid for" column of the list uses the same name. The Receipt page line ("Late-payment charge") and the Reports register are unchanged | `payments/text.ts` |
| Payments cards on a large screen | One line each whenever the window was under 1000 px tall, or when fewer than eight rows of the list would show; a browser window on a 1080 px screen is about 950 px tall, so the first rule caught it, and with eleven cards in three rows the second rule caught the taller screens | From 1600 px wide the eleven cards are two rows (six and five). They are full height while six rows of the list show on the first screen; otherwise the name and the amount share one line and the note stays under them; one line each only when even that leaves fewer than three rows (a window under about 850 px tall). When the table area would hold fewer than four rows the page scrolls as usual and the headings stick | `shell/tableFit.ts` (`largeCardsLook`), `shell/screens.css` (`.ui-kpis-pay`, `body.ui-mid`) |
| Other list pages on a large screen | One line cards under 1000 px tall | The same large-screen rule: full-height cards while six rows show (Invoices at 1920 × 1080: full cards, five rows in the table area) | `shell/tableFit.ts` |
| Laptop screens (under 1600 px wide) | One-line cards under 1000 px tall or under eight rows | Unchanged | - |

Measured on the review data (Payments, 18 payments): 2560 × 1300 full cards, 5 rows; 1920 × 1200 full cards, 4 rows; 1920 × 1080 name and amount on one line with the note, 4 rows; 1920 × 950 the same, 4 rows, the page scrolls; 1920 × 820 one line each, 4 rows; 1440 × 900 one line each, 5 rows (as before).

Trade-off told to the owner: in a browser window on a 1080 px screen (about 950 px tall) the list showed six rows with one-line cards; with the taller cards it shows four at a time.

Checks: the screen check now fails when a five-in-a-row grid does not hold five cards in its first row from 700 px, and when the menu colour does not fill its column on a wide screen. Tests TEST-FE-1940 (`shell/layouts.test.tsx`), TEST-FE-1941 (`shell/tableFit.test.ts`); TEST-FE-1925, 1907 and 1937 extended.

## Round 11: each Home card opens the part it counts (12/11/2026)

Owner 12/11 14:41: "check all card is link to correct place. if all pass, start payment".

### What the check found

Every card on Home was clicked on the review app (15 cards and the 5 Financial summary cards, as the Owner). All 20 opened the right page. None opened the part the card counts: the page showed its whole list, so the number on the card and the list did not match. The Birthdays card opened the Customers list, which has no birthdays. Four Financial summary cards opened Profit and loss whatever they showed, and "Spent this month" opened the Budget page where budgets are typed.

Design v81 opens a filtered view from its money, Lease and Meter cards (`kpi('invoices','open')`, `'month:paid'`, `'overdue'`, `kpi('leases','ending')`, `kpi('readings','missing')`), a Birthdays page from the Birthdays card, and the statement behind each Financial summary card. The app now does the same, and does it for the other cards too (Units, Viewing requests, Short stays, Notices, Problem reports, Low stock, Attendance), where the design opens the whole page.

### How it works

The part is a word in the address: `#/invoices?show=overdue`. The page reads the word when it opens and each time such an address is opened again, so a second card works while the page is on screen. A part chosen by hand on the page is written to the address too, without a new history step, so Back from a record returns to the same part and the address can be kept as a bookmark. An unknown word is ignored. Shared code: `shell/useHashPage.ts` (`useShowFromAddress`, `useHashShow`, `showInAddress`, `hashForShow`). Display only: no read, rule, permission or figure changed.

| Home card | Opens | What shows there | Where |
|---|---|---|---|
| Vacant Units | `#/units?show=vacant` | The Vacant card, every floor and type | `units/UnitsList.tsx` |
| Viewing requests waiting | `#/visitreqs?show=waiting` | The Awaiting first contact card | `telegram/TelegramPages.tsx` |
| Leases ending soon | `#/leases?show=ending` | The Ending soon card | `leases/LeasesList.tsx` |
| Short stay bookings | `#/shortstays?show=booked` | The Bookings list on status Booked | `shortstays/ShortStaysPage.tsx` |
| Short stays checked in | `#/shortstays?show=checked_in` | The Bookings list on status Checked in | `shortstays/ShortStaysPage.tsx` |
| Pending payment | `#/invoices?show=open` | The Total unpaid card, every type | `invoices/InvoicesList.tsx` |
| Paid this month | `#/invoices?show=paid&period=month` | The Total paid card for Invoices due this month | `invoices/InvoicesList.tsx` |
| Overdue | `#/invoices?show=overdue` | The Total overdue card | `invoices/InvoicesList.tsx` |
| Approvals | `#/approvals` | The page (it has one view: everything waiting) | - |
| Meter readings missing | `#/utilities?show=missing` | This month, every floor, "Only not read" ticked | `utilities/UtilitiesPage.tsx` |
| Notices due | `#/letters?show=due` | The Notices due card | `letters/LettersPage.tsx` |
| Problem reports | `#/problems?show=open` | The Open tab, every kind and type | `problems/ProblemReportsPage.tsx` |
| Birthdays | `#/customers?show=birthdays` | The coming birthdays above the Customers list | `customers/Birthdays.tsx` (new) |
| Low stock | `#/products?show=low` | Only the products low on stock and still sold | `products/ProductsPage.tsx` |
| Attendance | `#/attendance?show=day` | The daily sheet | `hr/AttendancePage.tsx` |
| Cash and bank today | `#/statements?show=balance-sheet` | Balance sheet, today | `ledger/LedgerPage.tsx` |
| Customers owe, Owed over 30 days | `#/statements?show=customer-aging` | Accounts receivable aging | `ledger/LedgerPage.tsx` |
| Spent this month | `#/statements?show=budget` | Budget vs actual, this month | `ledger/LedgerPage.tsx` |
| Profit this year | `#/statements?show=profit-and-loss` | Profit and loss, this month with the year to date | `ledger/LedgerPage.tsx` |

### New on the pages

- **Short stays › Bookings: a status row.** "All n · Booked n · Checked in n", and any other status a booking has (Checked out, Cancelled, No-show), each with its count. The list had no way to show one status, so the two Home cards had nothing to open. With no booking of the chosen status the list says "No bookings with this status."
- **Products: "All n · Low stock n".** Low stock counts what Home counts: products the server marks low and that are still sold. With none it says "No product is low on stock."
- **Customers: the coming birthdays.** A card right under the page title (so it is on the first screen of a phone too), only while the address asks for it: "Today and the next 7 days" (the same people Home counts) and "Later this month". Each line has the name, Primary Tenant or Occupant, the Unit (a link), the day and month and "today", "tomorrow" or "in n days", and an arrow to the Customer. The year and the age never show. "Hide" closes it. It uses the read that already exists (`GET /properties/{id}/birthdays`, with the right to read Customers). The design has a Birthdays tab; a list fits what the read gives (the next birthday of each person), and a full tab can come with the Customers batch.
- **Financial statements** read the statement the address names first, so opening a card does not read Profit and loss before it.

### Checked on the review app (12/11/2026, Owner, 1440 × 900)

Meter readings missing: before the reading day the Utilities page has no list to enter readings (it opens on the reading day, an existing rule), so the card lands on This month with the line "Reading day is 24/11/2026. The list to enter the readings opens that day." On the reading day it lands on the list of Meters not read yet.

Each card was clicked and its number compared with the list it opens: Leases ending soon 4 and 4 rows; Short stay bookings 2 and 2 rows; Short stays checked in 1 and 1 row; Pending payment $1,130.00 and "Total unpaid $1,130.00" with 3 rows; Paid this month $5,948.47 and "Total paid $5,948.47" under This month; Overdue $1,130.00 with 3 rows; Low stock 3 and 3 rows; Birthdays 4 and 4 lines. Back returns to Home from every card. No page error.

### Every difference from design v81 left, with its reason

| Design v81 | App | Why |
|---|---|---|
| Birthdays is its own page | A list above the Customers list | The read gives the coming birthdays only; no new page or menu item is added outside a module batch |
| Units, Viewing requests, Notices and Repairs cards open the whole page | They open the part the card counts | The owner's check: the list must match the number on the card |

"Paid this month" opens the paid Invoices due this month, as in the design: the card's amount adds the Invoices due this month that are paid, not the money received this month, so the Invoices list is the list that matches it. Approvals opens the page, as in the design: it shows only what is waiting.

Tests: TEST-FE-1942 (Home card addresses), 1943 (Financial summary), 1944 (the shared address code), 1945 (Invoices), 1946 (Short stays status row), 1947 (Products), 1948 (Birthdays list), 1949 (Units), 2120 (Leases), 2121 (Utilities), 2122 (Financial statements), 2123 (Problem reports), 2124 (Notices), 2125 (Viewing requests), 2126 (Attendance), 2127 (Customers page). TEST-FE-928, 1912, 1294 and 1931 now expect the new addresses.

## Round 12: module batch 2, Payments (12/11/2026)

Owner 12/11 14:41: "check all card is link to correct place. if all pass, start payment". The card links passed (round 11), so Payments is the second module batch, after Home. Its three screens are the Payments list, Receive payment and the Receipt page. Layout and display only: what the form checks and sends, every read, every rule and every figure are unchanged, and there is no database step.

### What changed

| Screen | Before | Now | Where |
|---|---|---|---|
| Receive payment | A title inside the page, the form in one card, a small Customer line under the Customer field | The shared page head: "Back to Payments" on top, the title as the page's heading, the sentence under it. The shared form layout: the fields card on the left, two short fields per row (one per row on a phone), and the design's side column on the right, which stays in view while the fields scroll: the payer's Customer card and the card "Exchange rate for riel" | `payments/ReceivePayment.tsx`, `shell/layouts.tsx` (`FormLayout` can name its form) |
| Customer card beside the form | Not there | The same card as on the approved Lease page: name with the Lease status, "Primary Tenant · Unit", phone, Paid on time, Customer Credit, Unpaid Invoices, "Open Customer". It shows once a Customer is chosen. A payer without a Lease (a short-stay guest) shows the Unit alone; a deactivated Customer says so | `customers/CustomerSideCard.tsx` (new, shared; the Lease page's card now uses it), `payments/PayerCard.tsx` (new) |
| "Exchange rate for riel" | The rate showed only as a line under the amount when Riel was chosen | A card, always: the ABA sell rate with its time, the server's markup ("Plus 0.5%"), the app rate ("4,113 ៛ = $1.00"), the typed amount in riel (or, for riel, its worth in US dollars), and for each unpaid item "To pay $350.00 in riel" with how the amount is reached ("$350.00 × 4,113 ៛ = 1,439,550 ៛", and ", rounded up" when it was). Every figure is the server's or uses the form's own rounding; the markup is read from the server's answer, never typed into the screen. With no rate the card says "Not available" and to record in US dollars. The form asks the server for the rate once when it opens (before: only when Riel was chosen); it is the same preview of one dollar, which saves nothing and needs the right to receive payments | `payments/RielRateCard.tsx` (new), `payments/paymentsClient.ts` (`khrRate` also reads the published rate, its time and the markup) |
| Receipt page | Title and buttons in a plain row, the sheet and three cards | The shared page head: "Back to Payments" on top, "Receipt RCP260018" as the page's heading with its status and "Name · Unit · amount", Print Receipt and Reprint on the right. The shared record layout: the sheet on the left (about 60%), and on the right "Paid for", the payer's Customer card, "Reprints" and the note | `payments/ReceiptPage.tsx` |
| "Paid for" on the Receipt page | A bare date under an Invoice line | "Due date 17/11/2026": the line says what the date is | same |
| Buttons, switches and number cards on a short desktop screen | The tighter look made buttons 38 px, switch buttons 36 px and number cards 42 px tall; a switch button was 42 px (40 px on a phone) | Everything a person presses is at least 44 px tall on every screen size. The tighter look still saves room in the spacing | `shell/screens.css` |
| Invoice number in "Paid for" | A 19 px tall link | Pressed on a 44 px area, in the same place | same |

The Payments list keeps its structure, which already matches the design (title with the date range and Receive payment, the period switch, the number cards, the list with All and Not matched). Only its buttons, switches and cards grew to 44 px.

### The 44 px rule and the list on a laptop

The screen check found 36 to 42 px tall buttons, switches and number cards on the Payments list at 1366 × 768 and 1440 × 900, where the page uses the tighter look of round 3. The owner's rule (08/11/2026 06:55, point 4) fails a button, link or tab under 44 × 44 px, so the tighter look no longer makes them shorter. This is a shared rule: every list page gets it. Cost on the Payments list at 1440 × 900: the list area is about 20 px shorter and still shows five rows before it scrolls. At 1366 × 768 the page scrolls as before.

The check itself learned one thing: a document sheet (an Invoice, a Receipt) is drawn scaled to its column, so its frame always holds a box of the paper's own width. The check now fails a sheet only when the sheet as drawn runs past its frame.

### Earlier forms of Payments (open question 1)

Each action of the folded "Earlier forms" box under the page was checked against the rebuilt screens. The box stays, because these actions exist only there:

- Match money that is left on a payment to an Invoice, and take a match back.
- Reverse a payment.
- Customer Credit: keep an overpayment as Credit, use Credit on an Invoice, take either back.
- Refund in US dollars, and a refund that came back.

Receiving a payment, the list, the Receipt and Reprint are in the rebuilt screens. Design v81 has a Match page for a payment that is not matched yet. Moving the actions above is new screens over money actions, so it is its own step: see `01_UI_AUDIT_REPORT.md`, open question 16.

### History

A Receipt never changes, so the Receipt page has no History list, in the design or the app. Its only later steps are reprints, and the "Reprints" card names the person, the time and the reason of each. A payment's other steps (a match, a reversal) show on the Customer's full statement.

### Sheets

`/mnt/project-files/ui-design/module-sheets/`: `sheet-payments-<w>.png` (the list, This month), `sheet-receive-<w>.png` (Receive payment with Sok Dara · U203 chosen and $350.00 typed) and `sheet-receipt-<w>.png` (Receipt RCP260018: Rent, Services and a Deposit) at 390, 768, 1366, 1440 and 1920 (design left, app right). The review app has no riel rate source, so the rate card reads "Not available" on the sheets; its look with a rate was checked with a stubbed answer and is covered by TEST-FE-2129.

Measured at 1440 × 900 (design | app): form card and side column 61% and 39% | 60% and 40%; the side column starts level with the form card, both. On the list: switch buttons 36 | 44 px, the Receive payment button 38 | 44 px, number cards 35 | 44 px (the owner's 44 px rule wins over the design's tighter look). On the form: the currency switch 42 | 44 px, buttons 44 px, both.

### Every difference from design v81 left, with its reason

| Screen | Part | Design v81 | App | Why |
|---|---|---|---|---|
| List | Line beside the title | "01/11/2026 to 03/11/2026 · As of 10:30" | The date range | The top bar shows the day and the time on every page |
| List | Number cards | Eight, with "Move-out charges" and "Late-payment charges" | Eleven with icons: Short stay, Products, Damage and Other charges in place of Move-out charges; "Late-payment" | The owner's rounds 9 and 10 (12/11/2026) |
| List | Height of the switches, the Receive payment button and the number cards on a laptop | 36, 38 and 35 px | 44 px | The owner's 44 px rule |
| List | Under the list | Nothing | The folded "Earlier forms" box | Actions that exist only there (see above) |
| Receive payment | Back link | "Back to Home" (the design was opened from Home) | "Back to Payments" | The page's parent, as on every form and record page (batch 1) |
| Receive payment | Notice "Example values are filled in so you can try the steps." | Shown | Not shown | A notice of the design file only |
| Receive payment | Hint under the amount | "Commas for thousands, a dot for cents. Example: 1,234.50" | No hint | The app's dollar field takes digits and a dot only, so the hint would be untrue. Taking commas changes what the form checks (01, open question 19) |
| Receive payment | Amount field | "$" in its own box, the number on the right | "$" inside the field, the number on the left | The shared money field, as on the approved New Lease form |
| Receive payment | Reference field | "ABA transaction ID" | "Transaction number or reference" | The app's name of the field since V1-058; it is for every method but cash, not only ABA |
| Receive payment | Proof | "Upload proof" (a photo or PDF of the transfer) | Not there | A payment has no place to keep a file yet (01, open question 17) |
| Receive payment | Payer note | Not there | Kept | A field the payment already stores (what the payer wrote in the transfer) |
| Receive payment | Title of the tick list | "My profile" | "What this money pays for" | A text mix-up in the design file |
| Receive payment, Receipt | Customer card, line under the name | "Primary Tenant · U203 · One Bedroom" | "Primary Tenant · U203" | The same card as the approved Lease page; the Unit type is on the Unit page |
| Receive payment, Receipt | Customer card, under Unpaid Invoices | "Nothing unpaid." when $0.00 | The amount alone | The same card as the approved Lease page |
| Receive payment | Rate card on the review app | A rate | "Not available" | The app has no rate source yet (01, open question 14). With a rate the card shows the design's lines |
| Receive payment | Time of the rate | "Automatic, 03/11/2026, 08:00" | "Automatic, 12/11/2026 08:00" | The app's one way to write a moment |
| Receipt | Buttons | "Move to correct Unit", Print Receipt, Reprint | Print Receipt, Reprint | Moving a payment to another Unit is not an app function; it is a money action that needs its own rule (01, open question 18) |
| Receipt | Under a "Paid for" line | The moment the payment was received | "Due date" and the Invoice's Due Date | The Receipt read gives no time per line; the received time is on the sheet |
| Receipt | Parts of a Rent Invoice | One line | Rent and Services under the Invoice | The owner's round 9 (12/11/2026) |

### Tests and checks

Tests: TEST-FE-2128 (Receive payment on the shared layout with the Customer card), 2129 and 2130 (the rate card with a rate, without one and while it is read), 2131 (the client reads the published rate, its time and the markup), 2132 (the payer's Customer card), 2133 (the Receipt page on the shared layout), 2134 (44 px in the tighter look; a form page names its form), all in `frontend/src/payments/PaymentsBatch.test.tsx`. TEST-FE-1921 (the Lease page's Customer card) passes on the shared card. TEST-FE-1938 now expects "Due date". The screen check has three new screens, `payments`, `receive-payment` and `receipt`, with the recorded answers in `frontend/e2e/fixtures/payments.har.json`: 10 screens × 5 sizes pass.

## Round 13: module batch 3, Invoices (13/11/2026)

The owner approved the Payments batch on 13/11/2026 ("test passed") and asked for the next module. The Invoices list, one Invoice, New Invoice, New Quotation and one Quotation were put beside design v81 at the five sizes.

### What changed

- **One Invoice, the head.** The shared page head of the approved Lease page: "Back to Invoices" on top, the Invoice number as the page title with its status chip, the line "type · Customer · Unit" under it, and the buttons on the right: Receive payment, Print Invoice, Adjust and Void. "Manager only" stands beside Adjust and Void as text, not inside the button (the owner's rule from batch 1).
- **One Invoice, the body.** The sheet on the left, the side column on the right (the shared two-column layout of the Lease and Receipt pages).
- **One Invoice, the Customer card.** The same Customer card as the Lease, Receive payment and Receipt pages: name, Lease role and Unit, phone, Paid on time, Customer Credit and Unpaid Invoices. Under it: "Open Lease" and "All Invoices for" the Unit.
- **One Invoice, History.** Each step names the person (the owner's rule "History names the person for every step on every page"): "Draft saved by …", "Issued by …", "Adjusted by …: reason", "Voided by …: reason". An Invoice that the automatic billing issued says "Issued by automatic billing". To show the names, the one-Invoice read of the API now also returns the account name of each person who made, issued, adjusted or voided the Invoice (`actor_names`). It is display only: no stored value, rule or permission changed.
- **New Invoice, New Quotation, one Quotation.** The same shared page head: Back on top, the title, the line under it and the buttons on the right.
- **Customer card, Unpaid Invoices.** The amount-owed box now sits on the warm warning ground. Its brown label had 4.27:1 contrast on the grey ground; it now has 4.84:1 (the 4.5:1 rule).
- **Invoices list.** Already close to the design after rounds 9 and 10; not changed.

### Every difference from design v81 left, with its reason

| Screen | Part | Design v81 | App | Why |
|---|---|---|---|---|
| One Invoice | Late-payment charge card and "Write off" | Shown on the overdue sample | Not there | The late-payment charge becomes its own Invoice and write-off rules come in the clean-up phase (owner 12/11/2026, rules review). Not built yet |
| One Invoice | "Unpaid Invoices and charges" list inside the Customer card | Each unpaid Invoice listed | The total | The same card as the approved Lease and Payments pages |
| One Invoice | "Printed by …" in History | Shown | Not shown | The one-Invoice read gives no print steps; adding them is more than a display change |
| One Invoice | A draft Invoice | A details card instead of the sheet | Not changed | The sample data has no draft to check against; left for a later round |
| New Quotation | Back link | "Back to Home" (the design was opened from Home) | "Back to Quotations" | The page's parent, as on every form page |
| New Quotation | Line about validity | "Valid 7 days, until 10/11/2026" | The Settings rule in words | The form does not know the issue day before saving |
| Every page | "Earlier forms" box | Not there | Folded under the page | Billing runs and Due Date settings exist only there until Settings and Home take them over |

### Tests and checks

Tests: TEST-FE-2135 (the Invoice page head and its button order with "Manager only"), 2136 (History names the person), 2137 (the shared Customer card on the Invoice page) in `frontend/src/invoices/InvoicesPage.test.tsx`; TEST-FE-2138 (New Quotation and one Quotation use the shared head) in `frontend/src/quotations/QuotationsPage.test.tsx`. The backend test `test_v1_045_typed_sources_keep_category_and_controlling_id_together` checks the names in the one-Invoice read. The screen check has three new screens, `invoices`, `invoice` and `new-quotation`, with recorded answers in `frontend/e2e/fixtures/invoices.har.json`: 13 screens × 5 sizes pass. The screen check now skips the inside of a folded `<details>` box (Chromium gives its content boxes although nothing is drawn).

## Round 14: module batch 4, Utilities (13/11/2026)

The owner approved the Invoices batch on 13/11/2026 ("Invoice screen is ok"). The readings list (on a normal day and on reading day), the Meters tab and one meter were put beside design v81 at the five sizes. The review app's reading-day pictures were taken with the browser clock set to 24/11/2026; nothing in the database was changed for them.

### What changed

- **Import** is the page's button on the right of the head, as in the design. Before, it sat at the end of the filter row. It shows when it did before: on reading day for a person who may save readings, and before the reading day in the test app only.
- **Add meter** is the page's button on the right of the head on the Meters tab. "Manager only" stands beside it as text. Before, a "Manager" badge was inside the button, which the owner's batch 1 rule does not allow. Report broken and Replace meter on a meter page follow the same rule.
- **The type switch** says "Electricity 3 to read" (the design's words) instead of "Electricity 1/3"; when every meter of the type is read it says "all read".
- **The progress line** has the chip "15 to read" beside "31 of 46 meters read", as in the design.
- **One meter** has the shared record head: "Back to Meters" on top, the serial as the page's heading with its status, the line "type · Unit · Customer" under it, and the buttons on the right.
- **Shell head**: the buttons in the head sit in one row with a gap, and a "Manager only" note is centred on its button (shared; the other pages had one button there).

### Every difference from design v81 left, with its reason

| Screen | Part | Design v81 | App | Why |
|---|---|---|---|---|
| Readings | Line under the title | "Meter readings and meters for CHETANA Residence" | "Meter readings and meters" | The Property's name is in the side menu on every page |
| Readings | Notice "Example of reading day 24/11/2026" | Shown | Not shown | A notice of the design file only; the app shows "Read every meter, including empty rooms" under the progress line |
| Readings | Date of the last reading | Once, in the column title | Under each reading | Meters put in or replaced during the month have another last date |
| Readings | Column "Consumption" | "Consumption" | "Used" | The app's word, shorter on a phone; not changed without the owner |
| Readings | Unit line | The Customer's name | "No Lease now." on the review app | Sample data: the review app's Units have no Lease; with a Lease the name shows |
| Meters | Number cards | Four small cards in one line, with "Estimates" | Three cards with icons and notes, no "Estimates" | The shared card of the approved Payments and Home pages; an "Estimates" card is not in the app yet and is left for a later round |
| Meters | Column "Installation date" | "Installation date" | "Put in on" | The app's words; not changed without the owner |
| All | "Earlier forms" box | Not there | Folded under the page | Rates, corrections and move-in or move-out readings exist only there |

### Tests and checks

Tests: TEST-FE-2139 (Import in the head on reading day, the "to read" chip), TEST-FE-2140 (Add meter in the head with "Manager only" beside it; the meter page's record head and its buttons) in `frontend/src/utilities/UtilitiesPage.test.tsx`. TEST-FE-874 now expects "2 to read". The screen check has three new screens, `utilities`, `meters` and `meter`, with recorded answers in `frontend/e2e/fixtures/utilities.har.json`: 16 screens × 5 sizes pass. Layout and display only; no backend change, no database step.

## Main merge: ABA QR payment method (PR #34, DL-227) (13/11/2026)

Main's PR #34 is merged into `ui-v81`. Its migration `20270723_392` and this branch's head `20270718_367` are joined by `20270724_400` (no change of its own; forward-only). The two sides touch different tables: 392 changes only the Payment Methods (`aba_qr`) and the functions that save them; none of 360-369 touch them.

Settings, Business, Payment Methods: the edit dialog has a new switch, "Use for ABA QR payments", under "Staff can use it on new Receipts". The marked method shows an "ABA QR" chip in the list. Only one method can have it: ticking it on another method says "{method} is used for ABA QR payments now. Saving moves it to this method.", and the save takes the mark off the first one. A method that is off cannot have it ("Turn this method on to use it for ABA QR payments."). The server keeps the same rules (DL-227).

Tests: TEST-FE-2141 (the dialog and the list) in `frontend/src/settings/BusinessTab.test.tsx`, TEST-FE-2142 (reading and sending `aba_qr`) in `frontend/src/propertyClient.test.tsx`.

## Round 15: module batch 5, Approvals (13/11/2026)

Owner 13/11 15:02: "all good" after the Utilities pictures, so Approvals started.

### What changed

| Part | Before | Now | Where |
|---|---|---|---|
| Row button | "Open" | "Review", as in design v81 | `approvals/ApprovalsPage.tsx`, `ap_review` |
| Review window | For, Amount, Prepared, Reason (small, grey) | The reason is normal text; a Refund also shows "Refund method" (the method's name, read from the refund methods) and "Reference" (the note on the draft), as in design v81 | `DraftFacts`, `ap_method`, `ap_ref` |
| List, "For" column | The Customer's name small and grey even with no Unit above it | With no Unit, the name is normal text | `ApprovalsPage.tsx` |

The refund methods are read once with the list. If that read fails, the "Refund method" line is left out; nothing else changes.

### Every difference from design v81 left, with its reason

| Part | Design v81 | App | Reason |
|---|---|---|---|
| Card and chip word | Waiting | Pending approval | Owner decision 3 (03_WORDING_REVIEW) |
| Tabs | Financial approvals, Field reports (Later), Short-stay approvals | No tabs | Short-stay approvals went with DL-222; Field reports from Telegram are not built |
| Column name | Purpose | For | The column holds the Unit and the Customer; "For" is plainer |
| Draft number | DR-0007 under the draft's name | The reason under the draft's name | Drafts have no number in the app |
| Refund of Customer Credit | Unit and Customer | Customer only | The server's summary names no Unit for a Credit |

### Tests and checks

Test: TEST-FE-2143 in `frontend/src/approvals/ApprovalsPage.test.tsx` (Review button, Refund method and Reference, a failed read of the methods, a Customer with no Unit). TEST-FE-933, 934 and 936 press "Review" now. The screen check has a new screen, `approvals`, with recorded answers in `frontend/e2e/fixtures/approvals.har.json` (one Refund of Customer Credit waits): 18 screens × 5 sizes pass. Layout and display only; no backend change, no database step.

## Round 16: module batch 6, Reservations (14/11/2026)

Owner 13/11 18:59: "Ok" (Approvals approved). The Leasing screen thread owns Bookings, Viewing requests, Short stays and Housekeeping, so this batch is Reservations only (it had no changes there on any branch).

### What changed

| Part | Before | Now | Where |
|---|---|---|---|
| Long stays head | Title "Reservations", a sub-line, then the tabs (the word Reservations twice) | The tab row is the head, the page's button at its right, as on Invoices; also on Leases and Move-outs | `shell/AppShell.tsx` `TABBED_HEAD` |
| List on an iPad standing up | Six columns, the deposit and status cut off at the right | Reserved on folds under the Customer below 1024px | `reservations/ReservationsList.tsx`, `ui-reslist` in `shell/screens.css` |
| List on a phone | A wide table cut after the Customer | One card a Reservation: Unit and status, the Customer and Reserved on, then Expires and the deposit | the same |
| Reservation page head | Page title "Reservations", then the record title, buttons, the tabs, then "Back" below them | One head: Back on top, "Reservation · U408" with its status, the buttons on the right; no tabs above it (as on the Unit and Lease pages) | `reservations/ReservationDetail.tsx`, shared `PageHeader` |
| History | What happened and when, with no person | Each step names the person: "By <name>", "Approved by <name>" for the extension; the first step stays at the bottom of the newest-first list | `ReservationDetail.tsx`; server read `reservation_api.py` (names only, nothing stored changes) |
| Security Deposit card | "Accepted $450.00, different amount approved" (the full deposit set beside the 20% suggestion for the first payment, so the note was wrong almost every time) | "Full Security Deposit $450.00", the name New Reservation uses, with no note | `ReservationDetail.tsx`, `full_deposit` |
| Back link | A Reservation opened from the list said "Back to Home" (a hidden page's heading was read) | "Back to Reservations": only a heading on show counts | `shell/backNav.tsx` `currentPageLabel` |

The person's name comes from the account that recorded each step (`app.user_accounts.display_name`), read with the Reservation as the Lease page does since 08/11. The response gets `made_by_name`, `actor_name` on each receipt, cancellation and deposit outcome, and `approved_by_name` on the extension. No stored data, rule, permission or field name changes.

### Every difference from design v81 left, with its reason

| Part | Design v81 | App | Reason |
|---|---|---|---|
| Place in the menu | Bookings › Reservations, with Viewing requests | Long stays › Reservations, Leases, Move-outs | The menu order is the Leasing screen thread's (owner 13/11) |
| New Reservation | A full page with a "Next step" box | A side window | The window was approved in V1-060 B6 and keeps the deposit and the Reservation in one save |
| Result column | A separate column | The result under the status chip | One column fewer fits an iPad |
| Reservation facts | Three columns with the Unit's type and floor and the Customer's phone | A two-column list | The Reservation read has no type, floor or phone; adding them is a server change for little gain |
| Customer card on the Reservation page | Customer card with Paid on time and Credit | Not shown | Those come from the Customer page; the Customer link opens it |

### Tests and checks

Tests: TEST-FE-2145 (one head, Back on top, History names), TEST-FE-2146 (Reserved on under the Customer, phone-card classes) in `frontend/src/reservations/ReservationsPage.test.tsx`; TEST-FE-2147 (Back ignores a hidden page's heading) in `frontend/src/shell/backNav.test.tsx`. TEST-FE-839 expects "Full Security Deposit". The server test `test_reservation_worker_migration.py` expects the names. The screen check has two new screens, `reservations` and `reservation`, with recorded answers in `frontend/e2e/fixtures/reservations.har.json` (made-up Reservations; one leftover test Unit with a non-Unit number was taken out of the list answer): 20 screens × 5 sizes pass.
