import { useEffect, useMemo, useState } from "react";
import { financialRecovery, type FinancialRecovery } from "./financialRecovery";
import type { FinancialScope } from "./financialClient";
import type {
  FinancialObject,
  EnforcementCommandOperation,
} from "./financialContracts";
import type { FinancialCommandRequest } from "./financialUi";
import { useFinancialTask } from "./financialUiContext";
import {
  enforcementClient,
  readEnforcement,
  type EnforcementClient,
} from "./leaseEnforcementClient";
import {
  ENFORCEMENT_COMMAND_CAPABILITIES,
  type EnforcementCapabilities,
  type EnforcementRead,
} from "./leaseEnforcementContract";

export interface EnforcementServices {
  reads: EnforcementClient;
  recovery: FinancialRecovery;
}
export const defaultEnforcementServices: EnforcementServices = {
  reads: enforcementClient,
  recovery: financialRecovery,
};
export interface EnforcementWorkflowProps {
  scope: FinancialScope;
  capabilities: EnforcementCapabilities;
  services: EnforcementServices;
  leaseId: string;
  revision: number;
  ready: boolean;
  busy: boolean;
  review: (
    request: FinancialCommandRequest,
    source: FinancialObject | null,
    onRecorded: () => void,
  ) => void;
  onDirty: (value: boolean) => void;
  confirmDiscard: () => boolean;
}
export function enforcementAllowed(
  caps: EnforcementCapabilities,
  operation: EnforcementCommandOperation,
): boolean {
  return caps[ENFORCEMENT_COMMAND_CAPABILITIES[operation]];
}
/** Hide an old record immediately, before the next effect replaces its request. */
export function useEnforcementRead(
  scope: FinancialScope,
  input: EnforcementRead | null,
  revision: number,
  services: EnforcementServices,
) {
  const serialized = JSON.stringify(input);
  const request = useMemo(
    () => JSON.parse(serialized) as EnforcementRead | null,
    [serialized],
  );
  const key = `${String(revision)}:${serialized}`;
  const [snapshot, setSnapshot] = useState<{
    key: string;
    data: FinancialObject;
  } | null>(null);
  const { run, busy, error, cancel } = useFinancialTask(scope, revision);
  useEffect(() => {
    setSnapshot(null);
    if (request !== null)
      void run(
        (s) => readEnforcement(s, request, services.reads),
        (data) => {
          setSnapshot({ key, data });
        },
      );
    return cancel;
  }, [request, key, run, cancel, services]);
  return { data: snapshot?.key === key ? snapshot.data : null, busy, error };
}
export function useEnforcementDraft(
  dirty: boolean,
  onDirty: (value: boolean) => void,
) {
  useEffect(() => {
    onDirty(dirty);
    return () => {
      onDirty(false);
    };
  }, [dirty, onDirty]);
}
