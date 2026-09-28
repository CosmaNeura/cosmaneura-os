import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {PracticeAccessGate} from './PracticeAccessGate';
import {hostedWorkspaceRequested} from './hosted-workspace';
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { WorkspaceAuth, nativeWorkspaceAuthAvailable, type WorkspaceAuthPlugin } from "../../clients/capture/src/native/workspace-auth-plugin";
import { StatusScreen } from "./App";
import { EncounterWorkspace } from "./EncounterWorkspace";
import { parseNativeAuthState, parseNativeToken, sameNativeState, type NativeAuthState } from "./native-auth";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";

type Session = {
  plugin: WorkspaceAuthPlugin; active: boolean; epoch: number; pending: boolean;
  current: NativeAuthState | null; refresh: () => Promise<void>;
};

export function NativeAuthenticatedWorkspace({ plugin = WorkspaceAuth, available = nativeWorkspaceAuthAvailable(), createIdentity }: {
  plugin?: WorkspaceAuthPlugin; available?: boolean;
  createIdentity?: (state: NativeAuthState, isCurrent: () => boolean) => AuthenticatedWorkspaceIdentity;
}) {
  const [state, setState] = useState<NativeAuthState | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const session = useRef<Session | null>(null);
  const identity = useMemo(() => {
    if (state?.phase !== "ready" || !state.identity) return null;
    const scope = session.current;
    const expected = state;
    const stillCurrent = () => Boolean(scope?.active && !scope.pending && session.current === scope &&
      scope.current && sameNativeState(scope.current, expected));
    async function getToken(_options: { skipCache: true }) {
      try {
        if (!stillCurrent()) throw new Error();
        const result = await plugin.getToken({ expectedRevision: expected.revision });
        if (!stillCurrent()) throw new Error();
        return parseNativeToken(result, expected.revision);
      } catch { throw new Error("Native session unavailable"); }
    }
    return createIdentity ? createIdentity(expected, stillCurrent) : { mode: "clerk_jwt" as const, getToken,
      nativeSession: {revision:expected.revision,isCurrent:stillCurrent} };
  }, [state, plugin, createIdentity]);

  useLayoutEffect(() => {
    const scope: Session = { plugin, active: true, epoch: 0, pending: false, current: null, refresh: async () => {} };
    session.current = scope;
    setState(null); setFailed(false); setBusy(false);
    let remove: (() => Promise<void>) | undefined;
    const invalidate = () => {
      if (!scope.active) return;
      scope.epoch++; scope.current = null; setState(null); setFailed(true);
    };
    const accept = (value: unknown) => {
      if (!scope.active) return;
      try {
        const next = parseNativeAuthState(value);
        // One native revision cannot describe two identities or phases.
        if (scope.current?.revision === next.revision && !sameNativeState(scope.current, next)) {
          throw new Error("Native session unavailable");
        }
        scope.epoch++;
        scope.current = next;
        setState(previous => previous && sameNativeState(previous, next) ? previous : next);
        setFailed(false);
      } catch { invalidate(); }
    };
    scope.refresh = async () => {
      if (!scope.active || scope.pending) return;
      const started = scope.epoch;
      try {
        const value = await plugin.getState();
        if (scope.active && !scope.pending && scope.epoch === started) accept(value);
      } catch { if (scope.active && !scope.pending && scope.epoch === started) invalidate(); }
    };
    if (available) {
      void plugin.addListener("authStateChanged", accept).then(handle => {
        if (!scope.active) return handle.remove();
        remove = () => handle.remove();
        return scope.refresh();
      }).catch(invalidate);
    }
    const resume = () => { if (document.visibilityState === "visible" && available) void scope.refresh(); };
    document.addEventListener("visibilitychange", resume);
    const timer = available ? window.setInterval(() => { void scope.refresh(); }, 5_000) : undefined;
    return () => {
      scope.active = false; scope.epoch++; scope.current = null;
      if (timer !== undefined) window.clearInterval(timer);
      document.removeEventListener("visibilitychange", resume);
      void remove?.().catch(() => {});
    };
  }, [plugin, available]);

  async function act(action: "signIn" | "signOut") {
    const scope = session.current;
    if (!scope?.active || scope.pending || !available || scope.plugin !== plugin) return;
    // Close access synchronously, including token promises already in flight.
    scope.pending = true; scope.epoch++; scope.current = null;
    setState(null); setFailed(false); setBusy(true);
    try { await plugin[action](); }
    catch { if (scope.active) setFailed(true); }
    finally {
      scope.pending = false;
      if (scope.active) { await scope.refresh(); if (scope.active) setBusy(false); }
    }
  }

  if (!available || state?.phase === "disabled") return <StatusScreen title="Sign-in isn't available in this build"
    detail="Use the approved test build to sign in to your workspace." />;
  if (busy || state?.phase === "signingIn") return <StatusScreen title="Updating your secure session"
    detail="Complete or cancel the sign-in window to return to Cosmas." role="status" />;

  if (state?.phase === "ready" && identity) {
    const controls=<button className="button secondary" onClick={() => void act("signOut")}>Sign out</button>;
    return hostedWorkspaceRequested()
      ? <WorkspaceCompatibilityGate identity={identity} accountControls={controls}><PracticeAccessGate key={state.revision} identity={identity} accountControls={controls}>{access=><EncounterWorkspace authenticated={identity} accountControls={controls} practiceAccess={access}/>}</PracticeAccessGate></WorkspaceCompatibilityGate>
      : <EncounterWorkspace key={state.revision} authenticated={identity} accountControls={controls}/>;
  }
  if (state?.phase === "unavailable" || failed) return <StatusScreen title="Secure session is unavailable"
    detail="Try signing in again. If the problem continues, reopen the app. Your workspace stays closed until your account is verified.">
    <div className="row account-controls" aria-label="Account recovery">
      <button className="button" onClick={() => void act("signIn")}>Sign in again</button>
      <button className="button secondary" onClick={() => void act("signOut")}>Sign out</button>
    </div>
  </StatusScreen>;
  if (!state || state.phase === "loading") return <StatusScreen title="Checking your session"
    detail="Your workspace will open after your account is verified." role="status" />;
  const pending = state.phase === "signOutPending";
  return <StatusScreen title={pending ? "Finish signing out" : "Sign in to Cosmas"}
    detail={pending ? "Your workspace is closed. Reconnect and finish signing out before continuing." :
      "Use your invited account to open your private workspace."}>
    <button className="button" onClick={() => void act(pending ? "signOut" : "signIn")}>
      {pending ? "Retry sign-out" : "Sign in"}
    </button>
  </StatusScreen>;
}
