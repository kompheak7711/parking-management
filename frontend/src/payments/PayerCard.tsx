// UI v81 module batch 2 (Payments, owner 12/11/2026): the Customer card beside Receive payment
// and beside a Receipt, as in design v81. It is the shared card of the Lease page
// (customers/CustomerSideCard.tsx); here the Customer is the payer. The chip and the role line
// come from the payer's newest signed Lease when there is one. Display only.

import type { CustomerApi } from "../customerClient";
import type { CustomerLedgerApi } from "../customerLedgerClient";
import { CustomerSideCard } from "../customers/CustomerSideCard";
import type { InvoicesData } from "../invoices/invoicesData";
import { kindOf, renewedIds } from "../leases/leasesData";
import { LeaseChip } from "../leases/LeasesList";
import { lt } from "../leases/text";
import type { reportsApi } from "../reportsClient";
import type { Language } from "../signInText";

/** What the card reads; the Payments page passes it on from the app. */
export interface PayerCardReads {
  customerApi: Pick<CustomerApi, "get">;
  ledgerApi?: Pick<CustomerLedgerApi, "read">;
  actorId?: string;
  reports?: Pick<typeof reportsApi, "customerPaidOnTime">;
  mayCustomers: boolean;
  mayInvoices: boolean;
}

export function PayerCard({
  language,
  propertyId,
  customerId,
  data,
  today,
  reads,
  headingId,
}: {
  language: Language;
  propertyId: string;
  customerId: string;
  data: InvoicesData | null;
  today: string;
  reads: PayerCardReads;
  headingId: string;
}) {
  const leases = data?.leases ?? [];
  const leaseId = data?.customerLeases.get(customerId);
  const lease = leases.find((entry) => entry.lease_id === leaseId);
  const unit = data?.customerUnits.get(customerId) ?? "";
  return (
    <CustomerSideCard
      actorId={reads.actorId}
      chip={
        lease === undefined ? undefined : (
          <LeaseChip
            kind={kindOf(
              lease,
              today,
              renewedIds([...leases]).has(lease.lease_id),
            )}
            language={language}
          />
        )
      }
      customerApi={reads.customerApi}
      customerId={customerId}
      fallbackName={data?.names.get(customerId) ?? "—"}
      headingId={headingId}
      language={language}
      ledgerApi={reads.ledgerApi}
      mayCustomers={reads.mayCustomers}
      mayInvoices={reads.mayInvoices}
      propertyId={propertyId}
      reports={reads.reports}
      role={
        leaseId !== undefined && unit !== ""
          ? lt(language, "cu_role", unit)
          : unit
      }
    />
  );
}
