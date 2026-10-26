// V1-058 R7b-1: the read of System health (GET /api/v1/operations/status, V1-059). It needs
// operations.status.read (the Owner and Manager bundles) and holds no secret or Customer detail.

export interface HealthRecord {
  last_attempt_at?: string | null;
  last_outcome?: string | null;
  last_failure_code?: string | null;
  last_success_at?: string | null;
  backup_id?: string | null;
  schema_revision?: string | null;
  revision?: string | null;
}

export interface HealthWarning {
  code: string;
  /** The server's own English words. */
  message: string;
  critical: boolean;
}

export interface HealthStatus {
  build_version: string | null;
  environment: string | null;
  generated_at: string;
  database: "ok" | "unavailable" | "not_configured";
  backup: HealthRecord | null;
  offhost_daily: HealthRecord | null;
  offhost_weekly: HealthRecord | null;
  restore_test: HealthRecord | null;
  migration: HealthRecord | null;
  last_check_at: string | null;
  schema_revision: string | null;
  scheduled_jobs: {
    billing_last_success_at: string | null;
    reservation_expiration_last_success_at: string | null;
  };
  telegram: {
    configured: boolean;
    last_delivery_outcome: string | null;
    last_attempt_at: string | null;
  };
  warnings: HealthWarning[];
}

export class HealthNotAllowedError extends Error {
  constructor() {
    super("Your account cannot see System health.");
    this.name = "HealthNotAllowedError";
  }
}

export class HealthUnavailableError extends Error {
  constructor() {
    super("System health is not available right now.");
    this.name = "HealthUnavailableError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isWarning(value: unknown): value is HealthWarning {
  return (
    isObject(value) &&
    typeof value.code === "string" &&
    typeof value.message === "string" &&
    typeof value.critical === "boolean"
  );
}

export interface HealthApi {
  status: () => Promise<HealthStatus>;
}

export const healthApi: HealthApi = {
  status: async () => {
    let response: Response;
    try {
      response = await fetch("/api/v1/operations/status", {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
    } catch {
      throw new HealthUnavailableError();
    }
    if (response.status === 401 || response.status === 403) {
      throw new HealthNotAllowedError();
    }
    if (!response.ok) throw new HealthUnavailableError();
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      throw new HealthUnavailableError();
    }
    const data = isObject(body) ? body.data : null;
    if (
      !isObject(data) ||
      typeof data.generated_at !== "string" ||
      typeof data.database !== "string" ||
      !isObject(data.scheduled_jobs) ||
      !isObject(data.telegram) ||
      !Array.isArray(data.warnings) ||
      !data.warnings.every(isWarning)
    ) {
      throw new HealthUnavailableError();
    }
    return data as unknown as HealthStatus;
  },
};
