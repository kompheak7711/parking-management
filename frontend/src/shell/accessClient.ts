// V1-058 R1b: what the signed-in person may use, read once after sign-in so the menu shows only
// those items (UI-008). Display only; every route still checks the capability.

export interface CapabilityAccess {
  capability: string;
  property_ids: string[];
}

export interface ActorAccess {
  actor_id: string;
  capabilities: CapabilityAccess[];
}

export interface ActorAccessApi {
  read(signal: AbortSignal): Promise<ActorAccess>;
}

export class ActorAccessUnavailableError extends Error {
  constructor() {
    super("The account's access could not be read.");
    this.name = "ActorAccessUnavailableError";
  }
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

/** Accepts only the documented shape; anything else counts as unreadable. */
export function parseActorAccess(body: unknown): ActorAccess {
  if (typeof body !== "object" || body === null) {
    throw new ActorAccessUnavailableError();
  }
  const data = (body as { data?: unknown }).data;
  if (typeof data !== "object" || data === null) {
    throw new ActorAccessUnavailableError();
  }
  const { actor_id: actorId, capabilities } = data as {
    actor_id?: unknown;
    capabilities?: unknown;
  };
  if (typeof actorId !== "string" || !Array.isArray(capabilities)) {
    throw new ActorAccessUnavailableError();
  }
  const parsed = capabilities.map((grant: unknown) => {
    if (typeof grant !== "object" || grant === null) {
      throw new ActorAccessUnavailableError();
    }
    const { capability, property_ids: propertyIds } = grant as {
      capability?: unknown;
      property_ids?: unknown;
    };
    if (typeof capability !== "string" || !isStringArray(propertyIds)) {
      throw new ActorAccessUnavailableError();
    }
    return { capability, property_ids: propertyIds };
  });
  return { actor_id: actorId, capabilities: parsed };
}

export function createActorAccessApi(
  fetchImplementation: typeof fetch = (input, init) => fetch(input, init),
): ActorAccessApi {
  return {
    async read(signal) {
      let response: Response;
      try {
        response = await fetchImplementation("/api/v1/identity/me/access", {
          credentials: "include",
          headers: { Accept: "application/json" },
          signal,
        });
      } catch {
        throw new ActorAccessUnavailableError();
      }
      if (!response.ok) throw new ActorAccessUnavailableError();
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        throw new ActorAccessUnavailableError();
      }
      return parseActorAccess(body);
    },
  };
}

export const actorAccessApi = createActorAccessApi();
