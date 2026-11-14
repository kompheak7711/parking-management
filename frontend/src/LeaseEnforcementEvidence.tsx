import { FinancialFacts } from "./FinancialEvidence";
import { financialObject, type FinancialObject } from "./financialContracts";
import { financialMoney, financialTimestamp } from "./financialUi";
import {
  ENFORCEMENT_EVENTS,
  enforcementValue,
} from "./leaseEnforcementContract";

const fields: Record<string, string> = {
  id: "Record reference",
  property_id: "Property reference",
  lease_id: "Lease reference",
  customer_id: "Customer reference",
  invoice_id: "Invoice reference",
  invoice_number: "Invoice number",
  rent_invoice_line_id: "Rent line reference",
  due_date: "Rent due date",
  due_date_snapshot: "Original Rent due date",
  case_id: "Existing case reference",
  rent_nonpayment_case_id: "Case reference",
  warning_sequence: "Warning sequence",
  violation_date: "Violation date",
  warning_date: "Warning date",
  violation_description: "Violation description",
  lease_provision: "Lease provision",
  communication_record: "Communication record",
  reason: "Reason",
  event_date: "Event date",
  notice_document_reference: "Warning Notice document reference",
  authorization_reference: "Authorization reference",
  occurred_at: "Recorded at",
  actor_id: "Recorded by",
  opened_at: "Case opened at",
  opened_by: "Case opened by",
  event_count: "Recorded event count",
};
export function EnforcementAssessment({
  value,
  current = true,
}: {
  value: unknown;
  current?: boolean;
}) {
  const row = financialObject(value),
    amount = financialObject(row.remaining_rent);
  return (
    <section
      aria-label={
        current ? "Current Rent assessment" : "Original recorded assessment"
      }
    >
      <h5>
        {current ? "Current Rent assessment" : "Original recorded assessment"}
      </h5>
      <FinancialFacts
        rows={[
          ["Rent remaining", financialMoney(amount.minor_units)],
          ["Invoice status", enforcementValue(row.invoice_status)],
          ["Days overdue", enforcementValue(row.days_overdue)],
          [
            "Business date (Asia/Phnom_Penh)",
            enforcementValue(row.business_date),
          ],
          ["Assessed at", financialTimestamp(row.as_of)],
          [
            "Rent source currently applicable",
            row.source_applicable ? "Yes" : "No",
          ],
          [
            "Day-10 notice eligible",
            row.ten_day_notice_eligible ? "Yes" : "No",
          ],
          [
            "Day-20 notice eligible",
            row.twenty_day_warning_eligible ? "Yes" : "No",
          ],
          [
            "Day-25 notice eligible",
            row.twenty_five_day_notice_eligible ? "Yes" : "No",
          ],
          [
            "Day-30 termination letter eligible",
            row.thirty_day_default_eligible ? "Yes" : "No",
          ],
          ["Cure eligible", row.cure_eligible ? "Yes" : "No"],
          [
            "Day-10 notice already recorded",
            row.ten_day_notice_recorded ? "Yes" : "No",
          ],
          [
            "Day-20 notice already recorded",
            row.warning_recorded ? "Yes" : "No",
          ],
          [
            "Day-25 notice already recorded",
            row.twenty_five_day_notice_recorded ? "Yes" : "No",
          ],
          [
            "Termination letter already recorded",
            row.serious_default_recorded ? "Yes" : "No",
          ],
          [
            "Tenant bot link (notices go by themselves)",
            row.telegram_linked ? "Yes" : "No",
          ],
        ]}
      />
      {!current && (
        <p>
          This is the original recorded evidence. Refresh the current case to
          see its latest balance and eligibility.
        </p>
      )}
    </section>
  );
}
export function EnforcementFacts({
  value,
  current = false,
}: {
  value: FinancialObject;
  current?: boolean;
}) {
  return (
    <>
      <FinancialFacts
        rows={Object.entries(fields)
          .filter(([key]) => Object.hasOwn(value, key))
          .map(([key, label]) => [
            label,
            key.endsWith("_at")
              ? financialTimestamp(value[key])
              : enforcementValue(value[key]),
          ])}
      />
      {value.event_kind !== undefined && (
        <p>
          Event:{" "}
          {
            ENFORCEMENT_EVENTS[
              value.event_kind as keyof typeof ENFORCEMENT_EVENTS
            ]
          }
        </p>
      )}
      {value.remaining_rent_usd_cents !== undefined && (
        <p>
          Rent remaining when recorded:{" "}
          {financialMoney(value.remaining_rent_usd_cents)}
        </p>
      )}
      {value.assessment !== undefined && (
        <EnforcementAssessment value={value.assessment} current={current} />
      )}
    </>
  );
}
export function EnforcementReadStatus({
  busy,
  error,
}: {
  busy: boolean;
  error: string | null;
}) {
  return (
    <>
      {busy && <p role="status">Loading authorized records…</p>}
      {error && <p role="alert">{error}</p>}
    </>
  );
}
