import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {PracticeAccessGate} from './PracticeAccessGate';
import {hostedWorkspaceRequested} from './hosted-workspace';
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { WorkspaceAuth, nativeWorkspaceAuthAvailable, type WorkspaceAuthPlugin } from "../../clients/capture/src/native/workspace-auth-plugin";
import {AppleHostedStatus as StatusScreen} from "./AppleHostedStatus";
import { EncounterWorkspace } from "./EncounterWorkspace";
import { parseNativeAuthState, parseNativeToken, sameNativeState, type NativeAuthState } from "./native-auth";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import {nativeSceneSignal,notifyNativeWorkspaceForeground} from './native-workspace-foreground';

type Session = {
  plugin: WorkspaceAuthPlugin; active: boolean; epoch: number; pending: boolean;
  current: NativeAuthState | null; refresh: () => Promise<void>;
  foreground:boolean; lastAction:"signIn"|"signOut"|null;
};

export function NativeAuthenticatedWorkspace({ plugin = WorkspaceAuth, available = nativeWorkspaceAuthAvailable(), createIdentity }: {
  plugin?: WorkspaceAuthPlugin; available?: boolean;
  createIdentity?: (state: NativeAuthState, isCurrent: () => boolean) => AuthenticatedWorkspaceIdentity;
}) {
  const [state, setState] = useState<NativeAuthState | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const session = useRef<Session | null>(null);
  const currentIdentity=useRef<AuthenticatedWorkspaceIdentity|null>(null);
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
  currentIdentity.current=identity;
  useLayoutEffect(()=>{
    // Readiness can arrive while the app is inactive, before an observer exists.
    // Retain that scene state for the newly mounted encounter observer.
    if(identity&&session.current?.active&&!session.current.foreground)
      notifyNativeWorkspaceForeground(identity,false);
  },[identity]);

  useLayoutEffect(() => {
    const scope: Session = { plugin, active: true, epoch: 0, pending: false, current: null, refresh: async () => {},foreground:true,lastAction:null };
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
        if (!scope.pending && (next.phase === "ready" || next.phase === "signedOut")) scope.lastAction = null;
        setState(previous => previous && sameNativeState(previous, next) ? previous : next);
        setFailed(false);
      } catch { invalidate(); }
    };
    let reading:Promise<void>|null=null;
    scope.refresh = () => {
      if (!scope.active || scope.pending || !scope.foreground) return Promise.resolve();
      if(reading)return reading;
      const started = scope.epoch;
      const read=async()=>{try {
        const value = await plugin.getState();
        if (scope.active && !scope.pending && scope.epoch === started) accept(value);
      } catch { if (scope.active && !scope.pending && scope.epoch === started) invalidate(); }};
      const pending=read();reading=pending;
      void pending.finally(()=>{if(reading===pending)reading=null;});return pending;
    };
    if (available) {
      void plugin.addListener("authStateChanged", accept).then(handle => {
        if (!scope.active) return handle.remove();
        remove = () => handle.remove();
        return scope.refresh();
      }).catch(invalidate);
    }
    let resumeReading:Promise<void>|null=null;
    let sceneEpoch=0;
    const scene=(active:boolean)=>{
      if(!scope.active||!available)return;
      const captured=currentIdentity.current;
      if(!active){
        sceneEpoch++;
        scope.foreground=false;scope.epoch++;
        if(captured)notifyNativeWorkspaceForeground(captured,false);return;
      }
      const alreadyForeground=scope.foreground;
      scope.foreground=true;
      if(!alreadyForeground||!resumeReading)sceneEpoch++;
      if(resumeReading)return;
      const verify=async()=>{
        // Settle a read begun before backgrounding, then obtain a fresh native
        // state. Neither a late pre-background reply nor another owner resumes work.
        while(scope.active&&scope.foreground&&!scope.pending){
          const selectedScene=sceneEpoch;
          if(reading)await reading;
          if(!scope.active||!scope.foreground||scope.pending)return;
          const before=scope.current;
          await scope.refresh();
          if(!scope.active||!scope.foreground||scope.pending)return;
          if(selectedScene!==sceneEpoch)continue;
          if(before?.phase==='ready'&&scope.current&&sameNativeState(before,scope.current)&&
            captured&&captured===currentIdentity.current)notifyNativeWorkspaceForeground(captured,true);
          return;
        }
      };
      const pending=verify();resumeReading=pending;
      void pending.finally(()=>{if(resumeReading===pending)resumeReading=null;});
    };
    let nativeSceneKnown=false;
    const resume = () => { if(nativeSceneKnown)return;if (document.visibilityState === "visible") scene(true);else if(document.visibilityState==='hidden')scene(false); };
    const nativeScene=(event:Event)=>{const active=nativeSceneSignal(event);if(active!==null){nativeSceneKnown=true;scene(active);}};
    document.addEventListener("visibilitychange", resume);
    window.addEventListener?.('cosmas:native-scene-state',nativeScene);
    const timer = available ? window.setInterval(() => { void scope.refresh(); }, 5_000) : undefined;
    return () => {
      scope.active = false; scope.epoch++; scope.current = null;
      if (timer !== undefined) window.clearInterval(timer);
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener?.('cosmas:native-scene-state',nativeScene);
      void remove?.().catch(() => {});
    };
  }, [plugin, available]);

  async function act(action: "signIn" | "signOut") {
    const scope = session.current;
    if (!scope?.active || scope.pending || !available || scope.plugin !== plugin) return;
    // Close access synchronously, including token promises already in flight.
    scope.lastAction = action;
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
  if (state?.phase === "unavailable" || failed) return <StatusScreen title="Sign-in needs attention"
    detail="This installation could not verify your account. Try signing in again, or reopen the app. Your private workspace stays closed until verification succeeds.">
    <div className="row account-controls" aria-label="Account recovery">
      <button className="button" onClick={() => void act("signIn")}>Sign in again</button>
      <button className="button secondary" onClick={() => void act("signOut")}>Sign out</button>
    </div>
  </StatusScreen>;
  if (!state || state.phase === "loading") return <StatusScreen title="Checking your session"
    detail="Your workspace will open after your account is verified." role="status" />;
  const pending = state.phase === "signOutPending";
  const signInRecovery = pending && session.current?.plugin === plugin && session.current.lastAction === "signIn";
  return <StatusScreen role={pending ? "alert" : "status"} title={signInRecovery ? "Sign-in didn’t finish" : pending ? "Finish signing out" : "Sign in to CosmaBot"}
    detail={signInRecovery ? "Your workspace stays closed. Try signing in again to safely clear the unfinished attempt and verify your account." :
      pending ? "Your workspace is closed. Reconnect and finish signing out before continuing." :
      "Sign in with your invited account to start a private note and meet your team."}>
    <button className="button" onClick={() => void act(pending && !signInRecovery ? "signOut" : "signIn")}>
      {signInRecovery ? "Try signing in again" : pending ? "Retry sign-out" : "Sign in"}
    </button>
  </StatusScreen>;
}
