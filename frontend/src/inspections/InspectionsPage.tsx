// UI v81 round 2 (owner 07/11/2026): Property › Inspections, the menu item of design v81.
// Owner 16/11/2026 ("Both, list first"): the page lists the Property's move-out inspections and
// the Unit checks sent from the Staff bot, newest first, each with links to its Lease, Unit and
// Problem reports. The Joint Inspection at move-in and move-out (DL-201) is built later and adds
// to this page. Needs "Read Units" (the menu item's right); the server checks it again.

import { useCallback, useEffect, useRef, useState } from "react";

import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { hashForPage } from "../shell/navigation";
import type { Language } from "../signInText";
import {
  type ProblemsApi,
  ProblemsError,
  type PropertyInspections,
  problemsApi as defaultProblemsApi,
} from "../problems/problemsClient";

// Khmer is new and needs the native check.
const TEXT = {
  loading: ["Loading inspections…", "កំពុងផ្ទុកការត្រួតពិនិត្យ…"],
  failed: [
    "The inspections could not be loaded.",
    "មិនអាចផ្ទុកការត្រួតពិនិត្យបានទេ។",
  ],
  right: [
    "You need the right Read Units to see inspections.",
    "អ្នកត្រូវមានសិទ្ធិ អានបន្ទប់ ដើម្បីមើលការត្រួតពិនិត្យ។",
  ],
  retry: ["Try again", "ព្យាយាមម្ដងទៀត"],
  mo_t: ["Move-out inspections", "ការត្រួតពិនិត្យពេលចាកចេញ"],
  mo_none: [
    "No move-out inspection yet. It is recorded on the Lease's Move-out page.",
    "មិនទាន់មានការត្រួតពិនិត្យពេលចាកចេញទេ។ វាត្រូវកត់ត្រានៅលើទំព័រចាកចេញរបស់កិច្ចសន្យា។",
  ],
  uc_t: ["Unit checks", "ការត្រួតពិនិត្យបន្ទប់"],
  uc_none: [
    "No Unit check yet. Staff send Unit checks from the Telegram Staff bot.",
    "មិនទាន់មានការត្រួតពិនិត្យបន្ទប់ទេ។ បុគ្គលិកផ្ញើការត្រួតពិនិត្យបន្ទប់ពីបូតបុគ្គលិក Telegram។",
  ],
  col_date: ["Date", "កាលបរិច្ឆេទ"],
  col_unit: ["Unit", "បន្ទប់"],
  col_lease: ["Lease", "កិច្ចសន្យា"],
  col_tenant: ["Tenant", "អ្នកជួល"],
  col_findings: ["Findings", "លទ្ធផល"],
  col_kind: ["Kind", "ប្រភេទ"],
  col_by: ["Checked by", "ត្រួតពិនិត្យដោយ"],
  col_reports: ["Problem reports", "របាយការណ៍បញ្ហា"],
  k_REGULAR: ["Regular check", "ការត្រួតពិនិត្យធម្មតា"],
  k_AFTER_REPAIR: ["After repair", "បន្ទាប់ពីជួសជុល"],
  all_good: ["All good", "ល្អទាំងអស់"],
  open: ["Open", "បើក"],
} as const;

function t(language: Language, key: keyof typeof TEXT): string {
  return TEXT[key][language === "en" ? 0 : 1];
}

export function InspectionsPage({
  language,
  active = true,
  api = defaultProblemsApi,
  propertyId = "",
}: {
  language: Language;
  /** Whether the page is on screen; the list is read when it first is. */
  active?: boolean;
  api?: ProblemsApi;
  propertyId?: string;
}) {
  const [data, setData] = useState<PropertyInspections | null>(null);
  const [problem, setProblem] = useState<"failed" | "right" | null>(null);
  const sequence = useRef(0);

  const load = useCallback(() => {
    if (propertyId === "") return;
    const operation = ++sequence.current;
    setProblem(null);
    void api
      .inspections(propertyId)
      .then((found) => {
        if (operation === sequence.current) setData(found);
      })
      .catch((error: unknown) => {
        if (operation !== sequence.current) return;
        setProblem(
          error instanceof ProblemsError && error.status === 403
            ? "right"
            : "failed",
        );
      });
  }, [api, propertyId]);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  return (
    <>
      {problem !== null && (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{t(language, problem)}</p>
          {problem === "failed" && (
            <button className="ui-btn" onClick={load} type="button">
              {t(language, "retry")}
            </button>
          )}
        </div>
      )}
      {data === null && problem === null && (
        <p className="ui-muted" role="status">
          {t(language, "loading")}
        </p>
      )}
      {data !== null && (
        <div className="ui-stack">
          <section aria-labelledby="insp-mo" className="ui-card">
            <h2 id="insp-mo">
              {t(language, "mo_t")}{" "}
              <span className="ui-count ui-num">{data.move_outs.length}</span>
            </h2>
            {data.move_outs.length === 0 ? (
              <p className="ui-empty">{t(language, "mo_none")}</p>
            ) : (
              <div className="ui-tablewrap">
                <table className="ui-table fit ui-pcards ui-insptable">
                  <thead>
                    <tr>
                      <th scope="col">{t(language, "col_date")}</th>
                      <th scope="col">{t(language, "col_unit")}</th>
                      <th scope="col">{t(language, "col_lease")}</th>
                      <th scope="col">{t(language, "col_tenant")}</th>
                      <th className="r" scope="col">
                        {t(language, "col_findings")}
                      </th>
                      <th scope="col">
                        <span className="ui-sr">{t(language, "open")}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.move_outs.map((row) => (
                      <tr key={row.inspection_id}>
                        <td className="ui-num pc-small">
                          {dayText(row.inspection_date)}
                        </td>
                        <td className="pc-name">
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("units", row.unit_id)}
                          >
                            {row.unit_number}
                          </a>
                        </td>
                        <td className="ui-num pc-small">
                          {row.lease_number ?? "—"}
                        </td>
                        <td className="pc-full">{row.tenant_name ?? "—"}</td>
                        <td className="r ui-num pc-small">
                          <span className="pc-label">
                            {t(language, "col_findings")}:{" "}
                          </span>
                          {row.findings}
                        </td>
                        <td className="r pc-end">
                          <a
                            className="ui-btn"
                            href={hashForPage("moveout", row.lease_id)}
                          >
                            {t(language, "open")}
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section aria-labelledby="insp-uc" className="ui-card">
            <h2 id="insp-uc">
              {t(language, "uc_t")}{" "}
              <span className="ui-count ui-num">{data.unit_checks.length}</span>
            </h2>
            {data.unit_checks.length === 0 ? (
              <p className="ui-empty">{t(language, "uc_none")}</p>
            ) : (
              <div className="ui-tablewrap">
                <table className="ui-table fit ui-pcards ui-insptable">
                  <thead>
                    <tr>
                      <th scope="col">{t(language, "col_date")}</th>
                      <th scope="col">{t(language, "col_unit")}</th>
                      <th scope="col">{t(language, "col_kind")}</th>
                      <th scope="col">{t(language, "col_by")}</th>
                      <th scope="col">{t(language, "col_reports")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.unit_checks.map((row) => (
                      <tr key={row.check_id}>
                        <td className="ui-num pc-small">
                          {dayText(row.check_date)}
                        </td>
                        <td className="pc-name">
                          <a
                            className="ui-no ui-num"
                            href={hashForPage("units", row.unit_id)}
                          >
                            {row.unit_number}
                          </a>
                        </td>
                        <td className="pc-small">
                          {t(language, `k_${row.kind}`)}
                        </td>
                        <td className="pc-small">
                          {language === "km" && row.checked_by_km !== null
                            ? row.checked_by_km
                            : row.checked_by_en}
                        </td>
                        <td className="wrap pc-full">
                          {row.reports.length === 0
                            ? t(language, "all_good")
                            : row.reports.map((report, index) => (
                                <span key={report.report_id}>
                                  {index > 0 && ", "}
                                  <a
                                    className="ui-num"
                                    href={hashForPage(
                                      "problems",
                                      `pr:${report.report_id}`,
                                    )}
                                  >
                                    {report.report_number}
                                  </a>
                                </span>
                              ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
