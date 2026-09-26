export const COMPACT_LOCAL = import.meta.env.VITE_COMPACT_LOCAL === "true" &&
  import.meta.env.VITE_COSMAS_ENV === "synth_os";
const API_BASE = COMPACT_LOCAL ? "" :
  import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://localhost:8000";

export type QueueItem = {
  id: string;
  lane: string;
  state: string;
  proposed_message: string | null;
  revision_id: string | null;
  patient_link_id: string | null;
  execution_status?: string | null;
};

export type Seed = {
  box_id: string;
  owner_id: string;
  agents: Record<string, string>;
};

export type DemoSeed = Seed & { ticket_id: string };

export type ApiIdentity =
  | { mode: "synth_os"; boxId: string; actorId: string }
  | {
      mode: "early_adopter_beta";
      getToken: (options: { skipCache: true }) => Promise<string | null>;
    };

export type BetaIdentitySummary = {
  clerk_subject: string;
  display_name: string;
  active: boolean;
  principal_state: string;
  is_owner: boolean;
};

type RequestOptions = Omit<RequestInit, "headers"> & {
  headers?: HeadersInit;
  identity?: ApiIdentity;
};

async function addIdentityHeaders(headers: Headers, identity: ApiIdentity): Promise<void> {
  if (identity.mode === "synth_os") {
    headers.set("X-Box-Id", identity.boxId);
    headers.set("X-Actor-Principal-Id", identity.actorId);
    return;
  }

  // Beta authority comes only from a newly obtained Clerk session token. Never
  // allow caller-selected identity headers to accompany a beta request.
  headers.delete("X-Box-Id");
  headers.delete("X-Actor-Principal-Id");

  let token: string | null;
  try {
    token = await identity.getToken({ skipCache: true });
  } catch {
    throw new Error("Secure session is unavailable. Sign in again.");
  }
  if (!token || token.trim() !== token) {
    throw new Error("Secure session is unavailable. Sign in again.");
  }
  headers.set("Authorization", `Bearer ${token}`);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { identity, ...init } = options;
  const headers = new Headers(options.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (identity) await addIdentityHeaders(headers, identity);

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: identity?.mode === "early_adopter_beta" ? "omit" : init.credentials,
    headers,
  });
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // Preserve non-JSON error bodies.
    }
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  seedDemoQueue: () => request<DemoSeed>("/synth/demo-queue", { method: "POST" }),
  queue: (identity: ApiIdentity) => request<QueueItem[]>("/queue", { identity }),
  decide: (
    identity: ApiIdentity,
    ticketId: string,
    kind: "approve" | "reject" | "escalate",
    expectedRevisionId: string,
  ) =>
    request<{ decision: string; operation_id?: string }>(`/tickets/${ticketId}/decide`, {
      method: "POST",
      identity,
      body: JSON.stringify({ kind, expected_revision_id: expectedRevisionId }),
    }),
  edit: (identity: ApiIdentity, ticketId: string, body: string) =>
    request(`/tickets/${ticketId}/edit`, {
      method: "POST",
      identity,
      body: JSON.stringify({ body }),
    }),
  timeline: (identity: ApiIdentity, ticketId: string) =>
    request<Array<{ event_type: string; outcome: string | null; created_at: string | null }>>(
      `/tickets/${ticketId}/timeline`,
      { identity },
    ),
  close: (identity: ApiIdentity, ticketId: string) =>
    request(`/tickets/${ticketId}/close`, { method: "POST", identity }),
  purgeRetention: (identity: ApiIdentity) =>
    request<{ receipts: Array<{ artifact_id: string }> }>("/retention/purge", {
      method: "POST",
      identity,
    }),
  listBetaIdentities: (identity: ApiIdentity) =>
    request<BetaIdentitySummary[]>("/admin/identities", { identity }),
  bindBetaIdentity: (
    identity: ApiIdentity,
    body: { clerk_subject: string; display_name: string; evidence_ref: string },
  ) =>
    request<{ status: "bound" }>("/admin/identities/bind", {
      method: "POST",
      identity,
      body: JSON.stringify(body),
    }),
  deactivateBetaIdentity: (
    identity: ApiIdentity,
    body: { clerk_subject: string; evidence_ref: string },
  ) =>
    request<{ status: "deactivated" }>("/admin/identities/deactivate", {
      method: "POST",
      identity,
      body: JSON.stringify(body),
    }),
  reactivateBetaIdentity: (
    identity: ApiIdentity,
    body: { clerk_subject: string; evidence_ref: string },
  ) =>
    request<{ status: "reactivated" }>("/admin/identities/reactivate", {
      method: "POST",
      identity,
      body: JSON.stringify(body),
    }),
  transferBetaOwnership: (
    identity: ApiIdentity,
    body: { clerk_subject: string; evidence_ref: string },
  ) =>
    request<{ status: "transferred" }>("/admin/owner/transfer", {
      method: "POST",
      identity,
      body: JSON.stringify(body),
    }),
};
