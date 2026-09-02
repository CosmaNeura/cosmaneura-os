import { useEffect, useState, useTransition } from "react";
import { api, type QueueItem, type Seed } from "./api";

export function App() {
  const [seed, setSeed] = useState<Seed | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editText, setEditText] = useState<Record<string, string>>({});
  const [timeline, setTimeline] = useState<Record<string, Array<{ event_type: string; outcome: string | null }>>>({});
  const [pending, startTransition] = useTransition();

  async function refresh(s: Seed) {
    const q = await api.queue(s.box_id);
    setItems(q);
  }

  useEffect(() => {
    startTransition(async () => {
      try {
        const s = await api.seed();
        setSeed(s);
        await refresh(s);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    });
  }, []);

  async function act(item: QueueItem, kind: string) {
    if (!seed) return;
    setError(null);
    try {
      if (kind === "edit") {
        const body = editText[item.id] ?? item.proposed_message ?? "";
        await api.edit(seed.box_id, seed.owner_id, item.id, body);
      } else if (kind === "close") {
        await api.close(seed.box_id, seed.owner_id, item.id);
      } else {
        await api.decide(seed.box_id, seed.owner_id, item.id, kind);
      }
      await refresh(seed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function showTimeline(item: QueueItem) {
    if (!seed) return;
    const t = await api.timeline(seed.box_id, item.id);
    setTimeline((prev) => ({ ...prev, [item.id]: t }));
  }

  return (
    <main className="shell">
      <h1 className="brand">Cosmas OS</h1>
      <p className="lede">
        Practice work queue for synthetic Insurance ArtifactChase. Review the proposed
        message, then approve, edit, reject, or escalate.
      </p>

      <section className="panel">
        <div className="row">
          <strong>Clinic</strong>
          <span className="meta">{seed ? "Northside Synth Clinic" : pending ? "Loading…" : "Unavailable"}</span>
        </div>
        <p className="meta">People and agents are ready. Infrastructure details stay off this screen.</p>
      </section>

      {error ? <p className="error">{error}</p> : null}

      {items.length === 0 ? (
        <section className="panel">
          <p>No open work. Run the demo seed CLI to create a chase, then refresh.</p>
          <button type="button" onClick={() => seed && refresh(seed)}>
            Refresh
          </button>
        </section>
      ) : (
        items.map((item) => (
          <article className="panel ticket" key={item.id}>
            <h2>
              Insurance information request{" "}
              <span className="status">{item.state.replaceAll("_", " ")}</span>
            </h2>
            <p className="meta">Lane: {item.lane.replaceAll("_", " ")}</p>
            <div className="message">{item.proposed_message}</div>
            {item.state === "pending_approval" ? (
              <>
                <textarea
                  rows={3}
                  style={{ width: "100%" }}
                  value={editText[item.id] ?? item.proposed_message ?? ""}
                  onChange={(e) => setEditText((prev) => ({ ...prev, [item.id]: e.target.value }))}
                />
                <div className="row" style={{ marginTop: "0.75rem" }}>
                  <button className="primary" type="button" onClick={() => act(item, "approve")}>
                    Approve
                  </button>
                  <button type="button" onClick={() => act(item, "edit")}>
                    Save edit
                  </button>
                  <button type="button" onClick={() => act(item, "reject")}>
                    Reject
                  </button>
                  <button type="button" onClick={() => act(item, "escalate")}>
                    Escalate
                  </button>
                </div>
              </>
            ) : (
              <div className="row">
                {item.state === "confirmed" || item.state === "sent" ? (
                  <button className="primary" type="button" onClick={() => act(item, "close")}>
                    Close
                  </button>
                ) : null}
                <button type="button" onClick={() => showTimeline(item)}>
                  Show history
                </button>
              </div>
            )}
            {timeline[item.id] ? (
              <ul className="timeline">
                {timeline[item.id].map((ev, idx) => (
                  <li key={`${ev.event_type}-${idx}`}>
                    <strong>{ev.event_type}</strong>
                    {ev.outcome ? ` — ${ev.outcome}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        ))
      )}
    </main>
  );
}
