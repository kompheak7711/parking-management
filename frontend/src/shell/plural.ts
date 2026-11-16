// UI v81 (B4): "1 days" reads "1 day". English only: Khmer words have no plural. The count is
// a whole number standing alone, so "21 days" and "$1 days" are left as they are.

const NOUNS =
  "days|nights|months|weeks|years|items|times|lines|places|hours|minutes|readings|meters|rooms|payments|bills|advances|records|people|Invoices|Receipts|Units|Customers|Leases|stays|requests|reports|entries|scans";

const SINGULAR: Record<string, string> = { people: "person", entries: "entry" };

const ONE = new RegExp(`(^|[^\\d.,$])1 (${NOUNS})\\b`, "g");

export function singular(text: string): string {
  return text.replace(
    ONE,
    (_, before: string, noun: string) =>
      `${before}1 ${SINGULAR[noun] ?? noun.slice(0, -1)}`,
  );
}
