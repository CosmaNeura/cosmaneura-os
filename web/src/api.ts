const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type QueueItem = {
  id: string;
  lane: string;
  state: string;
  proposed_message: string | null;
  revision_id: string | null;
  patient_link_id: string | null;
};

export type Seed = {
  box_id: string;
  owner_id: string;
  agents: Record<string, string>;
};

async function req<T>(
  path: string,
  init: RequestInit & { boxId?: string; actorId?: string } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (init.boxId) headers.set("X-Box-Id", init.boxId);
  if (init.actorId) headers.set("X-Actor-Principal-Id", init.actorId);
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  seed: () => req<Seed>("/synth/seed", { method: "POST" }),
  queue: (boxId: string) => req<QueueItem[]>("/queue", { boxId }),
  decide: (boxId: string, actorId: string, ticketId: string, kind: string) =>
    req<{ decision: string; operation_id?: string }>(`/tickets/${ticketId}/decide`, {
      method: "POST",
      boxId,
      actorId,
      body: JSON.stringify({ kind }),
    }),
  edit: (boxId: string, actorId: string, ticketId: string, body: string) =>
    req(`/tickets/${ticketId}/edit`, {
      method: "POST",
      boxId,
      actorId,
      body: JSON.stringify({ body }),
    }),
  timeline: (boxId: string, ticketId: string) =>
    req<Array<{ event_type: string; outcome: string | null; created_at: string | null }>>(
      `/tickets/${ticketId}/timeline`,
      { boxId },
    ),
  close: (boxId: string, actorId: string, ticketId: string) =>
    req(`/tickets/${ticketId}/close`, { method: "POST", boxId, actorId }),
};
