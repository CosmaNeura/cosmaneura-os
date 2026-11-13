import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {NativeEnrollmentEntry} from './NativeEnrollmentEntry';
import {NativePracticeConnection,nativePracticeConnectionAvailable,type NativePracticeConnectionPlugin} from '../../clients/capture/src/native/practice-connection-plugin';
import {nativeEnrollmentCapabilities,nativeAccountEntryRequested} from './native-enrollment';
import {PracticeAccessGate} from './PracticeAccessGate';
import {NativeAccountControls} from './NativeAccountControls';
import {hostedWorkspaceRequested} from './hosted-workspace';
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { WorkspaceAuth, nativeWorkspaceAuthAvailable, type WorkspaceAuthPlugin } from "../../clients/capture/src/native/workspace-auth-plugin";
import {AppleHostedStatus as StatusScreen} from "./AppleHostedStatus";
import { EncounterWorkspace } from "./EncounterWorkspace";
import { parseNativeAuthState, parseNativeToken, sameNativeState, type NativeAuthState } from "./native-auth";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import {nativeSceneSignal,notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {hasUnsavedWork} from './unsaved-work';
import {nativeSignInUnavailableDetail} from './production-review-copy';

type Session = {
  plugin: WorkspaceAuthPlugin; active: boolean; epoch: number; pending: boolean;
  identityEpoch:number;
  actionEpoch:number;
  current: NativeAuthState | null; refresh: () => Promise<void>;
  foreground:boolean; lastAction:"signIn"|"signOut"|null;
};

export function NativeAuthenticatedWorkspace({ plugin = WorkspaceAuth, available = nativeWorkspaceAuthAvailable(), createIdentity,
  practicePlugin=NativePracticeConnection,practiceConnectionAvailable=nativePracticeConnectionAvailable() }: {
  plugin?: WorkspaceAuthPlugin; available?: boolean;
  practicePlugin?:NativePracticeConnectionPlugin;practiceConnectionAvailable?:boolean;
  createIdentity?: (state: NativeAuthState, isCurrent: () => boolean) => AuthenticatedWorkspaceIdentity;
}) {
  const [state, setState] = useState<NativeAuthState | null>(null);
  const [failed, setFailed] = useState(false);
  const [busyAction, setBusyAction] = useState<"signIn" | "signOut" | null>(null);
  const busy = busyAction !== null;
  const [connectingPractice,setConnectingPractice]=useState(()=>nativeAccountEntryRequested(practiceConnectionAvailable));
  const [practiceCanConnect,setPracticeCanConnect]=useState(false);
  const session = useRef<Session | null>(null);
  const currentIdentity=useRef<AuthenticatedWorkspaceIdentity|null>(null);
  useLayoutEffect(()=>{
    let active=true;setPracticeCanConnect(false);
    // A native-only capability read never calls the enrollment service. Missing
    // complete host ports never offer a practice-enrollment action.
    if(practiceConnectionAvailable)void practicePlugin.capabilities().then(value=>{
      if(active)setPracticeCanConnect(nativeEnrollmentCapabilities(value));
    }).catch(()=>{if(active)setPracticeCanConnect(false);});
    return()=>{active=false;};
  },[practicePlugin,practiceConnectionAvailable]);
  const identity = useMemo(() => {
    if (state?.phase !== "ready" || !state.identity) return null;
    const scope = session.current;
    const expected = state;
    const identityEpoch=scope?.identityEpoch;
    const stillCurrent = () => Boolean(scope?.active && !scope.pending && session.current === scope &&
      scope.identityEpoch===identityEpoch&&scope.current && sameNativeState(scope.current, expected));
    async function getToken(_options: { skipCache: true }) {
      try {
        if (!stillCurrent()) throw new Error();
        const result = await plugin.getToken({ expectedRevision: expected.revision });
        if (!stillCurrent()) throw new Error();
        return parseNativeToken(result, expected.revision);
      } catch { throw new Error("Native session unavailable"); }
    }
    return createIdentity ? createIdentity(expected, stillCurrent) : { mode: "clerk_jwt" as const, getToken,
      nativeSession: {revision:expected.revision,isCurrent:stillCurrent,
        userId:expected.identity!.userId,sessionId:expected.identity!.sessionId,organizationId:expected.identity!.organizationId} };
  }, [state, plugin, createIdentity]);
  currentIdentity.current=identity;
  useLayoutEffect(()=>{
    // Readiness can arrive while the app is inactive, before an observer exists.
    // Retain that scene state for the newly mounted encounter observer.
    if(identity&&session.current?.active&&!session.current.foreground)
      notifyNativeWorkspaceForeground(identity,false);
  },[identity]);

  useLayoutEffect(() => {
    const scope: Session = { plugin, active: true, epoch: 0, identityEpoch:0,actionEpoch:0,pending: false, current: null, refresh: async () => {},foreground:true,lastAction:null };
    session.current = scope;
    setState(null); setFailed(false); setBusyAction(null);
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
    let readingEpoch:number|null=null;
    scope.refresh = () => {
      if (!scope.active || scope.pending || !scope.foreground) return Promise.resolve();
      // A read begun before an account action cannot serve as its final check.
      // Drain it, then obtain a fresh native state for the current owner.
      if(reading)return readingEpoch === scope.epoch ? reading : reading.then(()=>scope.refresh());
      const started = scope.epoch;
      const read=async()=>{try {
        const value = await plugin.getState();
        if (scope.active && !scope.pending && scope.epoch === started) accept(value);
      } catch { if (scope.active && !scope.pending && scope.epoch === started) invalidate(); }};
      const pending=read();reading=pending;readingEpoch=started;
      void pending.finally(()=>{if(reading===pending){reading=null;readingEpoch=null;}});return pending;
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
    if (!scope?.active || !available || scope.plugin !== plugin) return;
    // The native owners already allow sign-out to fence an unfinished sign-in.
    // This is the only overlapping action; neither late completion nor a second
    // cancellation may clear the newer owner's pending state.
    if (scope.pending && !(action === "signOut" && scope.lastAction === "signIn")) return;
    const actionEpoch = ++scope.actionEpoch;
    const ownsAction = () => scope.active && session.current === scope && scope.actionEpoch === actionEpoch;
    // Close access synchronously, including token promises already in flight.
    scope.lastAction = action;
    scope.pending = true; scope.epoch++; scope.current = null;
    setState(null); setFailed(false); setBusyAction(action);
    try { await plugin[action](); }
    catch { if (ownsAction()) setFailed(true); }
    finally {
      if (ownsAction()) {
        scope.pending = false;
        await scope.refresh();
        if (ownsAction()) setBusyAction(null);
      }
    }
  }

  function connectPractice(){
    const owner=session.current;if(!owner?.active||owner.pending||!practiceCanConnect||hasUnsavedWork())return;
    // Explicitly fence the old renderer before any account/issuer transition.
    owner.pending=true;owner.epoch++;owner.identityEpoch++;owner.current=null;setState(null);setConnectingPractice(true);
  }
  function returnFromPractice(){
    const owner=session.current;setConnectingPractice(false);
    if(owner?.active){owner.pending=false;void owner.refresh();}
  }
  if(connectingPractice)return <NativeEnrollmentEntry plugin={practicePlugin} available={practiceConnectionAvailable} readyPractices onReturn={returnFromPractice}/>;

  if (!available || state?.phase === "disabled") return <StatusScreen title="Sign-in isn't available in this build"
    detail={nativeSignInUnavailableDetail()} />;
  if (busy || state?.phase === "signingIn") {
    const signingIn = busy ? busyAction === "signIn" : state?.phase === "signingIn";
    return <StatusScreen title={signingIn ? "Finish signing in" : "Signing out"}
      detail={signingIn ? "Complete sign-in in the secure window. If it has closed or stopped responding, cancel this attempt and try again." :
        "Your workspace is closed while sign-out finishes."} role="status">
      {signingIn && <button className="button secondary" onClick={() => void act("signOut")}>Cancel sign-in</button>}
    </StatusScreen>;
  }

  if (state?.phase === "ready" && identity) {
    const clearNative=plugin.clearAccountCredentials
      ? async()=>{try{await plugin.clearAccountCredentials!();}finally{await act("signOut");}}
      : undefined;
    const controls=<NativeAccountControls key={state.revision} identity={identity} onSignOut={()=>void act("signOut")}
      onConnectPractice={practiceCanConnect?connectPractice:undefined} clearNativeCredentials={clearNative}/>;
    return hostedWorkspaceRequested()
      ? <WorkspaceCompatibilityGate identity={identity} accountControls={controls}><PracticeAccessGate key={state.revision} identity={identity} accountControls={controls} prefetchTeam>{access=><EncounterWorkspace authenticated={identity}
          accountControls={<NativeAccountControls key={state.revision} identity={identity} displayName={access.displayName} practiceName={access.practiceName}
            onSignOut={()=>void act("signOut")} onConnectPractice={practiceCanConnect?connectPractice:undefined} clearNativeCredentials={clearNative}/>} practiceAccess={access}/>}</PracticeAccessGate></WorkspaceCompatibilityGate>
      : <EncounterWorkspace key={state.revision} authenticated={identity} accountControls={controls}/>;
  }
  if (state?.phase === "unavailable" || failed) return <StatusScreen title="Sign-in needs attention"
    detail="This installation could not verify your account. Try signing in again, or reopen the app. Your private workspace stays closed until verification succeeds.">
    <div className="row account-controls" aria-label="Account recovery">
      <button className="button" onClick={() => void act("signIn")}>Sign in again</button>
      <button className="button secondary" onClick={() => void act("signOut")}>Log out</button>
    </div>
  </StatusScreen>;
  if (!state || state.phase === "loading") return <StatusScreen title="Checking your session"
    detail="Your workspace will open after your account is verified." role="status" />;
  const pending = state.phase === "signOutPending";
  const signInRecovery = pending && session.current?.plugin === plugin && session.current.lastAction === "signIn";
  return <StatusScreen role={pending ? "alert" : "status"} title={signInRecovery ? "Sign-in didn’t finish" : pending ? "Finish signing out" : "Sign in to CosmaBot"}
    detail={signInRecovery ? "Close any unfinished sign-in window, then try again. Your workspace stays closed until your account is verified." :
      pending ? "Your workspace is closed. Reconnect and finish signing out before continuing." :
      "Sign in with your invited account to start a private note and meet your team."}>
    <button className="button" onClick={() => void act(pending && !signInRecovery ? "signOut" : "signIn")}>
      {signInRecovery ? "Try signing in again" : pending ? "Retry sign-out" : "Sign in"}
    </button>
    {!pending&&practiceCanConnect&&<button className="button secondary" onClick={connectPractice}>Connect practice</button>}
  </StatusScreen>;
}
