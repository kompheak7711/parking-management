// General Ledger phase 6 step 6: the Chart of accounts tab. Its address #/chart/opening opens
// Opening balances (mock-up lopen, from the Chart's "Opening balances" button); every other
// address is the chart or one account.

import { useHashDetail } from "../shell/useHashPage";
import type { Language } from "../signInText";
import type { LedgerApi } from "./ledgerClient";
import { LedgerPage, OPENING } from "./LedgerPage";
import type { OpeningApi } from "./openingClient";
import { OpeningBalances } from "./OpeningPage";

export function ChartPage({
  language,
  propertyId,
  active,
  capabilities,
  api,
  openingApi,
}: {
  language: Language;
  propertyId: string;
  active: boolean;
  capabilities: ReadonlySet<string> | null;
  api?: LedgerApi;
  openingApi?: OpeningApi;
}) {
  const detail = useHashDetail("chart");
  if (detail === OPENING && propertyId !== "") {
    return (
      <OpeningBalances
        active={active}
        api={openingApi}
        canEdit={
          capabilities === null || capabilities.has("ledger.opening_balances")
        }
        language={language}
        propertyId={propertyId}
      />
    );
  }
  return (
    <LedgerPage
      active={active}
      api={api}
      capabilities={capabilities}
      language={language}
      propertyId={propertyId}
      tab="chart"
    />
  );
}
