// V1-058 R3 Move-out: Record hand-back (DESIGN.md "Move-out (round 3)", step Hand-back). It
// records the real day the keys came back, ends every open Occupancy and sets the Unit's
// condition. A Lease still running at its End Date is ended on that End Date first, as signed
// (BR-LEASE-023): the database records a move-out only for a terminated Lease (decided by
// Claude under the owner's 2026-10-23 22:30 rule; no money rule changes). Each request keeps
// one identity while its values stay the same, so Try again sends the very same request.

import { FormEvent, useRef, useState } from "react";

import {
  LeaseConflictError,
  LeaseRequestError,
  type LeaseApi,
  type LeaseResource,
} from "../leaseClient";
import { Problem, useValuesIdentity } from "../leases/LeaseDialogs";
import { DateInput } from "../shell/DateInput";
import { dayText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Dialog } from "../shell/ui";
import type { Language } from "../signInText";
import type { UnitApi } from "../unitClient";
import { monthText } from "../utilities/text";
import {
  MoveOutConflictError,
  MoveOutNotAllowedError,
  MoveOutRequestError,
  type MoveOutApi,
  type MoveOutRecord,
  type OpenOccupancy,
  type UnitCondition,
} from "./moveoutClient";
import { mt } from "./text";

// What the records keep, in English like every stored record.
const MOVE_OUT_AUTHORITY =
  "Recorded in the app by the signed-in user (leases.move_out)";
const TERMINATE_AUTHORITY =
  "Approved in the app by the signed-in Owner or Manager (leases.terminate)";
const END_PROVISION =
  "Signed Lease: the Lease ends on its End Date (BR-LEASE-023)";
const END_GROUNDS =
  "The Lease reached its End Date and the Parking was handed back";
const END_NO_NOTICE =
  "No landlord notice: the Lease ended on its End Date as signed";
const END_REASON = "Lease ended on its End Date";
const END_EVIDENCE = "Hand-back recorded in the app on or after the End Date";
const HAND_BACK_REASON = "Parking handed back";
const CONDITIONS: UnitCondition[] = [
  "CLEANING",
  "UNDER_MAINTENANCE",
  "OUT_OF_SERVICE",
];

type Outcome = "unknown" | "refused" | null;

/** The Rent rule for the month of hand-back (owner, 03/10/2026), said before saving. */
export function rentRuleText(language: Language, day: string): string {
  const after = Number(day.slice(8, 10)) >= 5;
  return mt(
    language,
    after ? "rent_after5" : "rent_before5",
    dayText(day),
    monthText(language, day),
  );
}

/** The first day a hand-back may be recorded: the last move-in, and for a running Lease its End Date. */
export function firstHandBackDay(
  lease: LeaseResource,
  open: OpenOccupancy[],
): string {
  const days = open.map((occupancy) => occupancy.move_in_date);
  if (lease.status === "SIGNED" && lease.end_date !== null)
    days.push(lease.end_date);
  return days.sort().at(-1) ?? lease.start_date ?? "";
}

export function HandBackDialog({
  language,
  lease,
  open,
  terminationEventId,
  today,
  leaseApi,
  unitApi,
  moveOutApi,
  names,
  onClose,
  onSaved,
  onConflict,
}: {
  language: Language;
  lease: LeaseResource;
  open: OpenOccupancy[];
  /** The termination of a terminated Lease; null for a Lease that ends at its End Date now. */
  terminationEventId: string | null;
  today: string;
  leaseApi: Pick<LeaseApi, "terminate">;
  unitApi: Pick<UnitApi, "get">;
  moveOutApi: Pick<MoveOutApi, "record">;
  names: ReadonlyMap<string, string>;
  onClose: () => void;
  onSaved: (record: MoveOutRecord) => void;
  onConflict: () => void;
}) {
  const first = firstHandBackDay(lease, open);
  const [day, setDay] = useState(today);
  const [keys, setKeys] = useState(true);
  const [condition, setCondition] = useState<UnitCondition>("CLEANING");
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const endIdentity = useValuesIdentity();
  const moveIdentity = useValuesIdentity();
  // Kept for the life of the dialog, so Try again sends the same versions it sent before.
  const ended = useRef<{ eventId: string; version: number } | null>(
    terminationEventId === null
      ? null
      : { eventId: terminationEventId, version: lease.version },
  );
  const unitVersion = useRef<number | null>(null);
  const endsToo = terminationEventId === null;
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(day) && day >= first && day <= today;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!valid) {
      setProblem(mt(language, "st2_bad", dayText(first)));
      return;
    }
    setProblem(null);
    setBusy(true);
    setOutcome(null);
    const evidence = keys ? "Keys returned: all" : "Keys returned: not all";
    const reason = note.trim() === "" ? HAND_BACK_REASON : note.trim();
    void (async () => {
      if (ended.current === null) {
        const source = {
          actual_termination_date: lease.end_date ?? day,
          governing_event_reference: "BR-LEASE-023",
          reason: END_REASON,
          context: {
            basis: "SIGNED_LEASE_OTHER" as const,
            signed_lease_provision: END_PROVISION,
            approved_grounds: END_GROUNDS,
            management_authorization_reference: TERMINATE_AUTHORITY,
            // Fixed, so Try again ends the Lease with the same request whatever is ticked.
            evidence_reference: END_EVIDENCE,
            notice_required: false,
            notice_exception_reason: END_NO_NOTICE,
          },
        };
        const chosen = endIdentity(JSON.stringify([lease.version, source]));
        const terminated = await leaseApi.terminate(
          lease,
          { event_id: chosen.id, ...source },
          chosen.key,
        );
        ended.current = { eventId: chosen.id, version: terminated.version };
      }
      unitVersion.current ??= (await unitApi.get(lease.unit_id)).version;
      const termination = ended.current;
      const values = {
        termination_event_id: termination.eventId,
        expected_lease_version: termination.version,
        expected_unit_version: unitVersion.current,
        actual_move_out_date: day,
        unit_condition: condition,
        occupancies: open.map((occupancy) => ({
          occupancy_id: occupancy.occupancy_id,
          expected_version: occupancy.version,
        })),
        reason,
        authorization_reference: MOVE_OUT_AUTHORITY,
        evidence_reference: evidence,
        supersedes_event_id: null,
      };
      const step = moveIdentity(JSON.stringify(values));
      return moveOutApi.record(
        lease.property_id,
        lease.lease_id,
        { event_id: step.id, ...values },
        step.key,
      );
    })()
      .then(onSaved)
      .catch((error: unknown) => {
        if (
          error instanceof LeaseConflictError ||
          error instanceof MoveOutConflictError
        ) {
          onConflict();
          return;
        }
        // Only a clear refusal says "not saved"; anything else (no answer, the Unit read
        // failing after the Lease ended) may have saved a step.
        setOutcome(
          error instanceof LeaseRequestError ||
            error instanceof MoveOutRequestError ||
            error instanceof MoveOutNotAllowedError
            ? "refused"
            : "unknown",
        );
      })
      .finally(() => {
        setBusy(false);
      });
  }

  return (
    <Dialog
      busy={busy}
      closeLabel={mt(language, "close")}
      onClose={onClose}
      onSubmit={submit}
      submitLabel={
        busy
          ? mt(language, "saving")
          : outcome === "unknown"
            ? mt(language, "try_again")
            : mt(language, "st2_ok")
      }
      title={`${mt(language, "st2_btn")} · ${lease.unit_number}`}
    >
      {outcome !== null && (
        <div className="ui-notice warn" role="alert">
          <Icon name="alert" />
          <p>{mt(language, outcome)}</p>
        </div>
      )}
      <div className="ui-field">
        <label htmlFor="hb-day">
          {mt(language, "st2_date")}
          <span className="req">{mt(language, "required")}</span>
        </label>
        <DateInput
          language={language}
          invalid={problem !== null}
          id="hb-day"
          max={today}
          min={first}
          onChange={(value) => {
            setDay(value);
            setProblem(null);
          }}
          value={day}
        />
        <p className="help">{mt(language, "st2_date_help")}</p>
        <Problem message={problem} />
        {valid && <p className="ui-small">{rentRuleText(language, day)}</p>}
      </div>
      <fieldset className="ui-radios">
        <legend>{mt(language, "st2_who")}</legend>
        {open.map((occupancy) => (
          <label className="ui-chk" key={occupancy.occupancy_id}>
            <input checked disabled type="checkbox" />
            <span>
              {names.get(occupancy.customer_id) ??
                occupancy.customer_id.slice(0, 8)}
            </span>
          </label>
        ))}
      </fieldset>
      <div className="ui-field">
        <label className="ui-chk">
          <input
            checked={keys}
            onChange={(event) => {
              setKeys(event.target.checked);
            }}
            type="checkbox"
          />
          <span>{mt(language, "st2_keys")}</span>
        </label>
      </div>
      <div className="ui-field">
        <label htmlFor="hb-unit">{mt(language, "st2_unit")}</label>
        <select
          id="hb-unit"
          onChange={(event) => {
            setCondition(event.target.value as UnitCondition);
          }}
          value={condition}
        >
          {CONDITIONS.map((value) => (
            <option key={value} value={value}>
              {mt(language, `cond_${value}`)}
            </option>
          ))}
        </select>
      </div>
      <div className="ui-field">
        <label htmlFor="hb-note">{mt(language, "st2_note")}</label>
        <input
          autoComplete="off"
          id="hb-note"
          maxLength={500}
          onChange={(event) => {
            setNote(event.target.value);
          }}
          value={note}
        />
      </div>
      {endsToo && lease.end_date !== null && (
        <p className="ui-small">
          {mt(language, "st2_ends_too", dayText(lease.end_date))}
        </p>
      )}
      <p className="ui-small ui-muted">{mt(language, "st2_c")}</p>
    </Dialog>
  );
}
