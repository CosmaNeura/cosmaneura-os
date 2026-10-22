import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {PracticeAccessGate} from './PracticeAccessGate';
import {hostedWorkspaceRequested} from './hosted-workspace';
import { OrganizationSwitcher, SignIn, UserButton, useAuth } from "@clerk/react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { BetaIdentityAdmin } from "./BetaIdentityAdmin";
import { api, COMPACT_LOCAL, type ApiIdentity, type QueueItem, type Seed } from "./api";
import { EncounterWorkspace } from "./EncounterWorkspace";
import { WORKSPACE_BUILD } from "./workspace-api";

export type AppRuntimeMode = "synth_os" | "early_adopter_beta" | "unconfigured";

export function resolveRuntimeMode(
  configuredMode: string | undefined,
  isDevelopment: boolean,
): AppRuntimeMode {
  if (configuredMode === "synth_os" || configuredMode === "early_adopter_beta") {
    return configuredMode;
  }
  return configuredMode === undefined && isDevelopment ? "synth_os" : "unconfigured";
}

const runtimeMode = resolveRuntimeMode(import.meta.env.VITE_COSMAS_ENV, import.meta.env.DEV);

type StatusScreenProps = {
  title: string;
  detail: string;
  role?: "alert" | "status";
  children?: ReactNode;
};

export function StatusScreen({ title, detail, role = "alert", children }: StatusScreenProps) {
  return (
    <main className="shell">
      <h1 className="brand">Cosmas OS</h1>
      <section className="panel" role={role}>
        <h2>{title}</h2>
        <p>{detail}</p>
        {children}
      </section>
    </main>
  );
}

export function BlockedRuntime({ mode }: { mode: Exclude<AppRuntimeMode, "synth_os"> }) {
  return (
    <StatusScreen
      title={
        mode === "early_adopter_beta"
          ? "Beta login is not configured"
          : "App mode is not configured"
      }
      detail="This build is intentionally offline. It will not contact the API until the approved beta identity provider and runtime configuration are installed."
    />
  );
}

function synthIdentity(seed: Seed): ApiIdentity {
  return { mode: "synth_os", boxId: seed.box_id, actorId: seed.owner_id };
}

type QueueSession = {
  identity: ApiIdentity;
  items: QueueItem[];
};

type OwnerQueueProps = {
  bootstrap: () => Promise<QueueSession>;
  clinicName: string;
  lede: string;
  headerActions?: ReactNode;
  afterQueue?: (identity: ApiIdentity) => ReactNode;
};

function OwnerQueue({ bootstrap, clinicName, lede, headerActions, afterQueue }: OwnerQueueProps) {
  const [identity, setIdentity] = useState<ApiIdentity | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [editText, setEditText] = useState<Record<string, string>>({});
  const [timeline, setTimeline] = useState<
    Record<string, Array<{ event_type: string; outcome: string | null }>>
  >({});
  const startup = useRef<ReturnType<OwnerQueueProps["bootstrap"]> | null>(null);

  async function refresh(currentIdentity: ApiIdentity) {
    const queue = await api.queue(currentIdentity);
    setItems(queue);
  }

  useEffect(() => {
    if (!COMPACT_LOCAL || !identity || !items.some(item => ["pending", "running"].includes(item.execution_status ?? ""))) return;
    let active = true;
    const timer = window.setInterval(() => {
      void api.queue(identity).then(queue => { if (active) setItems(queue); })
        .catch(() => { if (active) setError("The local worker is unavailable. Your approval is saved; do not resend."); });
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [identity, items]);

  useEffect(() => {
    // React StrictMode replays effects in development. Reuse the same request so
    // one page load does not seed twice or issue duplicate beta API requests.
    startup.current ??= bootstrap();
    let active = true;
    void startup.current
      .then(({ identity: loadedIdentity, items: loadedItems }) => {
        if (!active) return;
        setIdentity(loadedIdentity);
        setItems(loadedItems);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        setError(cause instanceof Error ? cause.message : "Failed to load");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
    // The organization wrapper is keyed by active Org, so each mounted queue
    // intentionally consumes exactly one bootstrap function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function act(
    item: QueueItem,
    kind: "approve" | "edit" | "reject" | "escalate" | "close",
  ) {
    if (!identity || pending) return;
    setError(null);
    setPending(true);
    try {
      if (kind === "edit") {
        const body = editText[item.id] ?? item.proposed_message ?? "";
        await api.edit(identity, item.id, body);
      } else if (kind === "close") {
        await api.close(identity, item.id);
      } else {
        if (!item.revision_id) throw new Error("Current action revision is unavailable");
        await api.decide(identity, item.id, kind, item.revision_id);
      }
      await refresh(identity);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Action failed");
    } finally {
      setPending(false);
    }
  }

  async function showTimeline(item: QueueItem) {
    if (!identity || pending) return;
    setError(null);
    setPending(true);
    try {
      const events = await api.timeline(identity, item.id);
      setTimeline((previous) => ({ ...previous, [item.id]: events }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to load history");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="shell">
      <div className="row app-header">
        <h1 className="brand">Cosmas OS</h1>
        {headerActions}
      </div>
      <p className="lede">{lede}</p>

      <section className="panel">
        <div className="row">
          <strong>Clinic</strong>
          <span className="meta">{loading ? "Loading…" : identity ? clinicName : "Unavailable"}</span>
        </div>
        <p className="meta">
          People and agents are ready. Infrastructure details stay off this screen.
        </p>
      </section>

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}

      {loading ? (
        <section className="panel" role="status">
          Loading work…
        </section>
      ) : !error && items.length === 0 ? (
        <section className="panel">
          <p>No open work. Refresh to check the queue again.</p>
          <button
            type="button"
            disabled={pending || !identity}
            onClick={() => identity && refresh(identity)}
          >
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
            {item.execution_status === "unknown" && (
              <p role="alert">Needs review: the outcome is uncertain. No automatic resend will occur.</p>
            )}
            {item.execution_status === "pending" && <p>Approved and waiting for the local worker.</p>}
            {item.execution_status === "running" && <p>Processing the approved synthetic action.</p>}
            {item.state === "pending_approval" ? (
              <>
                <textarea
                  rows={3}
                  style={{ width: "100%" }}
                  value={editText[item.id] ?? item.proposed_message ?? ""}
                  onChange={(event) =>
                    setEditText((previous) => ({ ...previous, [item.id]: event.target.value }))
                  }
                />
                <div className="row" style={{ marginTop: "0.75rem" }}>
                  <button
                    className="primary"
                    type="button"
                    disabled={pending}
                    onClick={() => act(item, "approve")}
                  >
                    Approve
                  </button>
                  <button type="button" disabled={pending} onClick={() => act(item, "edit")}>
                    Save edit
                  </button>
                  <button type="button" disabled={pending} onClick={() => act(item, "reject")}>
                    Reject
                  </button>
                  <button type="button" disabled={pending} onClick={() => act(item, "escalate")}>
                    Escalate
                  </button>
                </div>
              </>
            ) : (
              <div className="row">
                {["confirmed", "sent", "rejected", "escalated", "failed"].includes(
                  item.state,
                ) ? (
                  <button
                    className="primary"
                    type="button"
                    disabled={pending}
                    onClick={() => act(item, "close")}
                  >
                    Close
                  </button>
                ) : null}
                <button type="button" disabled={pending} onClick={() => showTimeline(item)}>
                  Show history
                </button>
              </div>
            )}
            {timeline[item.id] ? (
              <ul className="timeline">
                {timeline[item.id].map((event, index) => (
                  <li key={`${event.event_type}-${index}`}>
                    <strong>{event.event_type}</strong>
                    {event.outcome ? ` — ${event.outcome}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        ))
      )}
      {!loading && identity ? afterQueue?.(identity) : null}
    </main>
  );
}

async function loadSyntheticQueue(): Promise<QueueSession> {
  const seed = await api.seedDemoQueue();
  const identity = synthIdentity(seed);
  return { identity, items: await api.queue(identity) };
}

function SyntheticQueue() {
  return (
    <OwnerQueue
      bootstrap={loadSyntheticQueue}
      clinicName="Northside Synth Clinic"
      lede="Practice work queue for synthetic Insurance ArtifactChase. Review the proposed message, then approve, edit, reject, or escalate."
    />
  );
}

export function isValidClerkOrganizationId(value: string | null | undefined): value is string {
  return typeof value === "string" && value.length <= 255 && /^org_[A-Za-z0-9]+$/.test(value);
}

type BetaTokenGetter = Extract<ApiIdentity, { mode: "early_adopter_beta" }>["getToken"];

function BetaOrganizationQueue({ getToken }: { getToken: BetaTokenGetter }) {
  async function loadBetaQueue(): Promise<QueueSession> {
    const identity: ApiIdentity = { mode: "early_adopter_beta", getToken };
    return { identity, items: await api.queue(identity) };
  }

  return (
    <OwnerQueue
      bootstrap={loadBetaQueue}
      clinicName="Cosmas Beta Lab"
      lede="Synthetic-only beta work queue. Use invented data only—never clinic or patient information. Review the proposed message, then approve, edit, reject, or escalate."
      headerActions={
        <div className="row account-controls" aria-label="Account and organization">
          <OrganizationSwitcher hidePersonal />
          <UserButton />
        </div>
      }
      afterQueue={(identity) =>
        identity.mode === "early_adopter_beta" ? (
          <BetaIdentityAdmin identity={identity} />
        ) : null
      }
    />
  );
}

function SignedInWorkspace({ getToken }: { getToken: BetaTokenGetter }) {
  const active = useRef(true);
  const tokenGetter = useRef(getToken);
  tokenGetter.current = getToken;
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const identity = useMemo(() => ({mode: "clerk_jwt" as const, getToken: async (options: { skipCache: true }) => {
    if (!active.current) return null;
    const token = await tokenGetter.current(options);
    return active.current ? token : null;
  }}), []);
  const controls=<div className="row account-controls" aria-label="Account and organization">
    <OrganizationSwitcher hidePersonal /><UserButton /></div>;
  return hostedWorkspaceRequested()
    ? <WorkspaceCompatibilityGate identity={identity} accountControls={controls}><PracticeAccessGate identity={identity} accountControls={controls} prefetchTeam>{access=><EncounterWorkspace authenticated={identity} accountControls={controls} practiceAccess={access}/>}</PracticeAccessGate></WorkspaceCompatibilityGate>
    : <EncounterWorkspace authenticated={identity} accountControls={controls}/>;
}

export function ClerkBetaApp({ workspace = false }: { workspace?: boolean }) {
  const auth = useAuth();

  if (!auth.isLoaded) {
    return (
      <StatusScreen
        title="Checking your session"
        detail="Cosmas is waiting for the login service before loading any work."
        role="status"
      />
    );
  }

  if (auth.isSignedIn !== true) {
    return (
      <main className="shell">
        <h1 className="brand">Cosmas OS</h1>
        <p className="lede">Sign in with your invited Cosmas Beta Lab account.</p>
        <SignIn routing="hash" />
      </main>
    );
  }

  const accountControls = <div className="row account-controls" aria-label="Account and organization">
    <OrganizationSwitcher hidePersonal /><UserButton />
  </div>;

  if (!isValidClerkOrganizationId(auth.orgId)) {
    return (
      <StatusScreen
        title="Choose an organization"
        detail="Select your practice's organization. If it isn't listed, accept your invitation or use the account menu to sign in with your invited account."
      >
        {accountControls}
      </StatusScreen>
    );
  }

  if (typeof auth.getToken !== "function" || (workspace && (!auth.sessionId || !auth.userId))) {
    return (
      <StatusScreen
        title="Secure session unavailable"
        detail="Use the account menu to sign out, then sign in again. No work has been loaded."
      >
        {accountControls}
      </StatusScreen>
    );
  }

  if (workspace) {
    return <SignedInWorkspace key={`${auth.userId}:${auth.sessionId}:${auth.orgId}`} getToken={auth.getToken} />;
  }

  return (
    <BetaOrganizationQueue
      key={`${auth.sessionId}:${auth.orgId}`}
      getToken={auth.getToken}
    />
  );
}

export function App({ runtimeMode: selectedMode = runtimeMode }: { runtimeMode?: AppRuntimeMode }) {
  const [showProof, setShowProof] = useState(false);
  if (selectedMode !== "synth_os") return <BlockedRuntime mode={selectedMode} />;
  if (WORKSPACE_BUILD && !showProof) return <EncounterWorkspace onExit={import.meta.env.VITE_SHOW_EXECUTION_PROOF==='true'?() => setShowProof(true):undefined} />;
  if (WORKSPACE_BUILD) return <><div className="workspace-return"><button onClick={() => setShowProof(false)}>Open encounter notebook</button></div><SyntheticQueue /></>;
  return <SyntheticQueue />;
}
