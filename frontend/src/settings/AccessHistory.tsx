// Administration review fix 10 (owner 13/11/2026): Users and access › History shows the list of
// access changes itself (who added a user, gave a role, reset a sign-in, …), newest first, in
// place of a note that pointed to the earlier English forms.

import { useEffect, useState } from "react";

import type { AuthorizationHistoryEvent } from "../adminClient";
import { momentText } from "../shell/format";
import { Icon } from "../shell/icons";
import { Chip } from "../shell/ui";
import type { Language } from "../signInText";
import { type SettingsTextKey, sst } from "./text";
import type { UsersApi } from "./UsersTab";

/** The server's access actions (audit_events "identity.*"), in plain words. */
const ACTIONS: Readonly<Record<string, SettingsTextKey>> = {
  "identity.account.created": "ah_created",
  "identity.account.updated": "ah_updated",
  "identity.account.disabled": "ah_disabled",
  "identity.account.one_time_password_given": "ah_otp",
  "identity.account.sessions_revoked": "ah_sessions",
  "identity.role_assignment.created": "ah_role_given",
  "identity.role_assignment.removed": "ah_role_removed",
  "identity.role_bundle.created": "ah_role_made",
  "identity.role_bundle.updated": "ah_role_changed",
  "identity.settings_access.given": "ah_settings_given",
  "identity.settings_access.removed": "ah_settings_removed",
};

/** An action the list does not know yet: "identity.account.locked" → "Account locked". */
function plainAction(action: string): string {
  const words = action
    .replace(/^identity\./, "")
    .replace(/[._]+/g, " ")
    .trim()
    .toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function AccessHistory({
  api,
  language,
  propertyId,
  active,
  myUserId,
}: {
  api: UsersApi;
  language: Language;
  propertyId: string;
  active: boolean;
  myUserId: string | null;
}) {
  const [events, setEvents] = useState<AuthorizationHistoryEvent[] | null>(
    null,
  );
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!active || propertyId === "") return;
    let current = true;
    setFailed(false);
    api
      .load(propertyId)
      .then((loaded) => {
        if (!current) return;
        setNames(
          new Map(
            loaded.users.map((user) => [user.user_id, user.display_name]),
          ),
        );
        // The server lists the oldest first; the newest change is the one people look for.
        setEvents([...loaded.authorizationHistory].reverse());
      })
      .catch(() => {
        if (!current) return;
        setEvents(null);
        setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [api, propertyId, active]);

  const person = (id: string) => {
    const name = names.get(id);
    if (name === undefined) return "—";
    return id === myUserId ? sst(language, "ah_you", name) : name;
  };

  return (
    <section aria-labelledby="access-history-title" className="ui-card pad0">
      <h2 className="ui-sr" id="access-history-title">
        {sst(language, "ac_history")}
      </h2>
      {failed ? (
        <div className="ui-notice warn" role="status">
          <Icon name="alert" />
          <p>{sst(language, "ah_failed")}</p>
        </div>
      ) : events === null ? (
        <p className="ui-empty" role="status">
          {sst(language, "ah_loading")}
        </p>
      ) : events.length === 0 ? (
        <p className="ui-empty">{sst(language, "ah_none")}</p>
      ) : (
        <div className="ui-tablewrap">
          <table className="ui-table ui-rowcards">
            <thead>
              <tr>
                <th scope="col">{sst(language, "ah_when")}</th>
                <th scope="col">{sst(language, "ah_who")}</th>
                <th scope="col">{sst(language, "ah_what")}</th>
                <th scope="col">{sst(language, "ah_user")}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const when = momentText(event.occurred_at);
                const key = ACTIONS[event.action];
                return (
                  <tr key={event.event_id}>
                    <td className="ui-num">
                      {when.slice(0, 10)}{" "}
                      <span className="ui-sub2">{when.slice(11)}</span>
                    </td>
                    <td data-label={sst(language, "ah_who")}>
                      {person(event.actor_id)}
                    </td>
                    <td>
                      {key === undefined ? (
                        <span lang="en">{plainAction(event.action)}</span>
                      ) : (
                        sst(language, key)
                      )}
                      {event.outcome !== "completed" && (
                        <>
                          {" "}
                          <Chip tone="warn">{sst(language, "ah_refused")}</Chip>
                        </>
                      )}
                    </td>
                    <td data-label={sst(language, "ah_user")}>
                      {person(event.target_id)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="ui-tfoot">{sst(language, "ah_note")}</p>
    </section>
  );
}
