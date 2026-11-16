// UI v81 pilot (owner 08/11/2026 06:55): the Customer card of the Lease page, under Deposits, as
// in design v81: the Primary Tenant's name with the Lease's status chip, the role and Unit, the
// phone, "Paid on time" (migration 20270711_362), the Customer Credit and the Unpaid Invoices
// (the Customer's ledger position), and "Open Customer". Display only: it reads, it changes
// nothing. The card itself is shared (customers/CustomerSideCard.tsx); the Payments pages show
// the same card for the payer.

import type { CustomerApi } from "../customerClient";
import type { CustomerLedgerApi } from "../customerLedgerClient";
import { CustomerSideCard } from "../customers/CustomerSideCard";
import type { LeaseResource } from "../leaseClient";
import type { reportsApi } from "../reportsClient";
import type { Language } from "../signInText";
import type { LeaseKind } from "./leasesData";
import { LeaseChip } from "./LeasesList";
import { lt } from "./text";

export interface LeaseCustomerCardProps {
  language: Language;
  lease: LeaseResource;
  kind: LeaseKind;
  propertyId: string;
  customerApi: Pick<CustomerApi, "get">;
  /** The Customer's ledger position (Credit, Unpaid Invoices); left out, the rows say so. */
  ledgerApi?: Pick<CustomerLedgerApi, "read">;
  actorId?: string;
  /** "Paid on time"; left out, the row says so. */
  reports?: Pick<typeof reportsApi, "customerPaidOnTime">;
  mayCustomers: boolean;
  mayInvoices: boolean;
}

export function LeaseCustomerCard({
  language,
  lease,
  kind,
  propertyId,
  customerApi,
  ledgerApi,
  actorId,
  reports,
  mayCustomers,
  mayInvoices,
}: LeaseCustomerCardProps) {
  return (
    <CustomerSideCard
      actorId={actorId}
      chip={<LeaseChip kind={kind} language={language} />}
      customerApi={customerApi}
      customerId={lease.primary_tenant_id}
      fallbackName={lease.primary_tenant_name}
      headingId="lease-customer"
      language={language}
      ledgerApi={ledgerApi}
      mayCustomers={mayCustomers}
      mayInvoices={mayInvoices}
      propertyId={propertyId}
      reports={reports}
      role={lt(language, "cu_role", lease.unit_number)}
    />
  );
}
