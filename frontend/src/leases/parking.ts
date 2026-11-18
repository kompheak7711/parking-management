// Parking Step 4 (owner 2026-10-30): on Parking the vehicle, not a person, moves in. The people
// lists of Property Rental ("Other occupants", "Add occupant", "Who moves in", per-person Move
// out) stay in the code behind this flag, so later Property Rental fixes still copy.
export const PEOPLE_MOVE_IN = false as boolean;

// Parking Step 5 (owner 2026-10-30): Parking has no pet deposit, no Parking inventory, no room
// features, no home-only fields (Size, Bedrooms, Bathrooms, View, Kitchen) and no move-out
// cleaning charge. The screens stay in the code behind these flags; the tables, functions and
// routes stay too, so later Property Rental fixes still copy. Rows that show data already in a
// database stay data-driven: an existing pet deposit or cleaning charge still shows and settles.
export const PET_DEPOSIT = false as boolean;
export const UNIT_INVENTORY = false as boolean;
export const ROOM_FEATURES = false as boolean;
export const HOME_FIELDS = false as boolean;
export const CLEANING_CHARGE = false as boolean;

// Parking Step 6 (owner 2026-11-17, "Yes, as recommended"): the parts Property Rental added in
// V1.1 and V1.2 that Parking does not use. Their pages, Home cards and Settings tabs are hidden;
// the code, tables, functions and routes stay, so later Property Rental fixes still copy.
export const GENERAL_LEDGER = false as boolean;
export const HR = false as boolean;
export const TELEGRAM = false as boolean;
// Short stays, with Housekeeping and the Booking sites.
export const SHORT_STAYS = false as boolean;
// Products, stock and Quotations.
export const PRODUCTS = false as boolean;
export const PROBLEM_REPORTS = false as boolean;
// The V1.1 Regular services (Settings › Monthly services).
export const MONTHLY_SERVICES = false as boolean;
export const ABA_QR = false as boolean;
