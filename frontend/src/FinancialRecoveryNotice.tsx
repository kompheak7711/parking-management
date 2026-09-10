import type { FinancialCommandOperation } from "./financialContracts";
import type { FinancialRecoveryState } from "./financialRecovery";

export const FINANCIAL_ACTION_LABELS: Record<
  FinancialCommandOperation,
  string
> = {
  leaseWarningRecord: "Record Lease violation warning",
  rentNonpaymentOpen: "Open Rent nonpayment case",
  rentNonpaymentEvent: "Record Rent nonpayment event",
  paymentRecord: "Record payment",
  allocationPost: "Post allocation",
  allocationReverse: "Reverse allocation",
  paymentReverse: "Reverse payment",
  receiptReprint: "Reprint original receipt",
  creditRecognize: "Recognize credit",
  creditReverse: "Reverse credit recognition",
  creditApply: "Apply credit",
  creditApplicationReverse: "Reverse credit application",
  refundCreate: "Record USD refund",
  refundReturn: "Record verified USD return",
  refundReturnReverse: "Reverse return correction",
};

interface Props {
  id: string;
  state: FinancialRecoveryState | null;
  busy: boolean;
  onReviewPending: () => void;
  pendingLink?: { href: string; label: string };
}

export function FinancialRecoveryNotice({
  id,
  state,
  busy,
  onReviewPending,
  pendingLink,
}: Props) {
  let message: string;
  switch (state?.kind) {
    case "ready":
      message = "No unresolved financial action.";
      break;
    case "pending":
      message =
        "An earlier action has an unresolved outcome. New financial actions are blocked. Review its original details before deciding whether to send the same action again.";
      break;
    case "other-property":
      message =
        "A financial action is unresolved in another Property. Select that Property to review its original outcome.";
      break;
    case "foreign":
      message =
        "A saved action belongs to another workflow. Financial actions remain blocked until that workflow resolves its original outcome.";
      break;
    case "unavailable":
      message =
        "Financial action recovery is unavailable. New financial actions are blocked. Authorized record views remain available.";
      break;
    case "invalidated":
      message =
        "This workspace is no longer current. Select the current Property again.";
      break;
    default:
      message = "Checking saved financial actions.";
  }
  return (
    <section
      id={id}
      className="information-card financial-recovery"
      aria-label="Financial action recovery"
      tabIndex={-1}
    >
      <h3>Financial action recovery</h3>
      <p role="status">{message}</p>
      {state?.kind === "other-property" && (
        <p>Property reference: {state.propertyId}</p>
      )}
      {state?.kind === "pending" && (
        <>
          <dl className="financial-facts">
            <dt>Original action</dt>
            <dd>{FINANCIAL_ACTION_LABELS[state.command.operation]}</dd>
            <dt>Property reference</dt>
            <dd>{state.command.propertyId}</dd>
            <dt>Original request reference</dt>
            <dd>{state.command.key}</dd>
          </dl>
          {pendingLink ? (
            <a href={pendingLink.href}>{pendingLink.label}</a>
          ) : (
            <button type="button" disabled={busy} onClick={onReviewPending}>
              Review original action
            </button>
          )}
        </>
      )}
    </section>
  );
}
