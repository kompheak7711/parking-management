// V1-058 R7b-6c: the Services a new Lease picks (DESIGN.md "Rates and services": "The New Lease
// form groups Services by type"). A type marked "Only one per Lease" offers one choice with None
// first; a "One or more" type, and Services with no type, offer tick boxes. A Service can be
// picked only when one approval period covers the whole Lease; one that starts later is greyed
// with its start date. Trash Collection is chosen by default.

import type {
  ServiceSetting,
  ServiceSettings,
} from "../settings/serviceSettingsClient";

export interface ServiceChoice {
  service: ServiceSetting;
  /** The approval period that covers the whole Lease; null when none does. */
  approvalPeriodId: string | null;
  /** The first day it can start when it starts after the Start Date; otherwise null. */
  startsLater: string | null;
  /** The monthly rate on the Start Date, in cents; null when no rate is set yet. */
  rateCents: number | null;
}

export interface ServiceGroup {
  /** null: Services with no type. */
  typeId: string | null;
  /** null for Services with no type: the screen names that group. */
  nameEn: string | null;
  nameKm: string | null;
  onePerLease: boolean;
  choices: ServiceChoice[];
}

/** The rate in force on the Start Date (the last one that starts on or before it). */
export function rateOn(service: ServiceSetting, start: string): number | null {
  let found: number | null = null;
  for (const rate of service.rates) {
    if (rate.effective_date <= start) found = rate.monthly_rate_usd_cents;
  }
  return found;
}

function choiceOf(
  service: ServiceSetting,
  start: string,
  end: string,
): ServiceChoice {
  const covering = service.approval_periods.find(
    (period) =>
      period.effective_from <= start &&
      (period.effective_through === null || period.effective_through >= end),
  );
  const later = service.approval_periods
    .filter((period) => period.effective_from > start)
    .map((period) => period.effective_from)
    .sort()[0];
  return {
    service,
    approvalPeriodId: covering?.approval_period_id ?? null,
    startsLater: covering === undefined ? (later ?? null) : null,
    rateCents: rateOn(service, start),
  };
}

/**
 * The Services grouped by type, in the order of the Settings list; no type comes last. A
 * removed type keeps its group while Services still have it: the server still allows only one
 * of an "Only one" type.
 */
export function serviceGroups(
  settings: ServiceSettings,
  start: string,
  end: string,
): ServiceGroup[] {
  const groups: ServiceGroup[] = settings.service_types.map((type) => ({
    typeId: type.service_type_id,
    nameEn: type.name_en,
    nameKm: type.name_km,
    onePerLease: type.one_per_lease,
    choices: [],
  }));
  const other: ServiceGroup = {
    typeId: null,
    nameEn: null,
    nameKm: null,
    onePerLease: false,
    choices: [],
  };
  for (const service of settings.services) {
    const group =
      groups.find((item) => item.typeId === service.service_type_id) ?? other;
    group.choices.push(choiceOf(service, start, end));
  }
  return [...groups, other].filter((group) => group.choices.length > 0);
}

function dayBefore(day: string): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

export interface RenewedTerm {
  property_service_id: string;
  applicable_from: string;
  applicable_through: string | null;
}

/**
 * What is chosen when the form opens, among the Services open for these dates: the Services the
 * renewed Lease still had on its End Date when there is one, otherwise Trash Collection. At most
 * one of each "Only one" type (the latest one the renewed Lease had).
 */
export function defaultChosen(
  settings: ServiceSettings,
  start: string,
  end: string,
  renewed: { terms: readonly RenewedTerm[]; endDate: string | null } | null,
): Set<string> {
  const groups = serviceGroups(settings, start, end);
  const open = new Set(
    groups
      .flatMap((group) => group.choices)
      .filter((choice) => choice.approvalPeriodId !== null)
      .map((choice) => choice.service.service_id),
  );
  let wanted: string[];
  if (renewed !== null) {
    // In force on the old End Date (or, without one, the day before the new start).
    const cutoff = renewed.endDate ?? dayBefore(start);
    wanted = [...renewed.terms]
      .filter(
        (term) =>
          term.applicable_through === null || term.applicable_through >= cutoff,
      )
      .sort((a, b) => a.applicable_from.localeCompare(b.applicable_from))
      .map((term) => term.property_service_id);
  } else {
    wanted = settings.services
      .filter((item) => item.service_code === "TRASH_COLLECTION")
      .map((item) => item.service_id);
  }
  let chosen = new Set<string>();
  for (const id of wanted) {
    if (!open.has(id)) continue;
    const group = groups.find((item) =>
      item.choices.some((choice) => choice.service.service_id === id),
    );
    if (group !== undefined) chosen = choose(chosen, group, id, true);
  }
  return chosen;
}

/** Choosing one Service of an "Only one" type leaves out the others of that type. */
export function choose(
  chosen: ReadonlySet<string>,
  group: ServiceGroup,
  serviceId: string | null,
  on: boolean,
): Set<string> {
  const next = new Set(chosen);
  if (group.onePerLease) {
    for (const item of group.choices) next.delete(item.service.service_id);
    if (serviceId !== null) next.add(serviceId);
    return next;
  }
  if (serviceId !== null) {
    if (on) next.add(serviceId);
    else next.delete(serviceId);
  }
  return next;
}

/**
 * V1-061 (owner 2026-10-29, DL-110, "Ticked and locked"): the chosen Services with every Service
 * the Unit requires ticked. In an "Only one per Lease" group the required Service replaces the
 * others.
 */
export function withRequired(
  chosen: ReadonlySet<string>,
  groups: ServiceGroup[],
  required: ReadonlySet<string>,
): Set<string> {
  let next = new Set(chosen);
  for (const group of groups) {
    for (const choice of group.choices) {
      if (required.has(choice.service.service_id))
        next = choose(next, group, choice.service.service_id, true);
    }
  }
  return next;
}
