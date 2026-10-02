import type {SessionPrepAnalysis} from "./session-prep-analysis-contract";
import {MembershipAnalysisPanel} from "./MembershipAnalysisPanel";
import {PracticeAccessPanel} from './PracticeAccessPanel';
import type {PracticeAccessContext} from './PracticeAccessGate';
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { ReviewedTeamDraft } from "./TeamSetupPanel";
import { TeamConfigurationFlow } from "./TeamConfigurationFlow";
import {accountIdentityApi} from "./account-identity-api";
import {assertCurrentDesktopSession} from "./workspace-auth-headers";
import {validActivityContext,type AiActivityContext,type AiActivitySelection} from "./model-activity-contract";
import { SettingsHub } from "./SettingsHub";
import { WelcomeActions } from './WelcomeActions';
import {ChiefStartActions,InitialTeamAction} from './ChiefStartActions';
import {coreConnectionApi} from './core-connection-api';
import type {CoreConnectionCommand} from './core-connection-contract';
import { CoreConnectionPanel, CORE_CONNECTION_BUILD, CONNECTION_ONBOARDING_BUILD } from "./CoreConnectionPanel";
import { normalizeTeamConfiguration, setupChange, validTeamConfiguration, type SetupProjection } from "./team-setup-request";
import { hasUnsavedWork, useUnsavedWork } from "./unsaved-work";
import { openDraftStore, privateDraftScope, DraftStoreError, type DraftStore } from "./draft-store";
import { DraftJournal, editorAddress, notebookDraft as makeNotebookDraft, teamDraft as recoveryTeamDraft, type RecoveryOffer } from "./draft-journal";
import { EditorRecoveryContext, type EditorRecoveryAccess } from "./editor-recovery";
import { AccountRecoveryContext, type AccountRecoveryAccess } from "./account-recovery";
import { supportsSkill, requireRecoveryScope, validRecoveryScope } from "./workspace-api";
import { BotAvatar } from "./BotAvatar";
import { TeamWorkPanel } from "./TeamWorkPanel";
import { HandoffReviewPanel } from "./HandoffReviewPanel";
import {modelWorkApi} from "./model-work-api";
import {conversationFromEntry, exactModelObservation, modelActive, modelRequestHash, modelStateLabel, validModelOperation, type HandoffRetryObservation, type ModelOperation, type ModelRequestObservation, type PreviousModelRequest} from "./model-work-request";
import { NoteReview } from "./NoteReview";
import { FollowUpWork } from "./FollowUpWork";
import { PracticeWork } from "./PracticeWork";
import { PracticeHub } from "./PracticeHub";
import { VendorWorkspaceMount } from "./VendorWorkMount";
import { PortalSetupMount, PORTAL_SETUP_BUILD } from "./PortalSetupMount";
import { FinanceWorkspaceMount, FINANCE_WORK_BUILD } from "./FinanceWorkMount";
import { PortalWorkspaceMount, PORTAL_WORK_BUILD } from "./PortalWorkMount";
import { FinanceSetupMount, FINANCE_SETUP_BUILD } from "./FinanceSetupMount";
import { VendorSetupMount, VENDOR_SETUP_BUILD } from "./VendorSetupMount";
import { MembershipWorkspaceMount, MEMBERSHIP_WORK_BUILD } from "./MembershipWorkMount";
import { WorkRoutines } from "./WorkRoutines";
import { ROUTINES_BUILD } from "./routine-api";
import {EncounterWorkSummary} from "./EncounterWorkSummary";
import { EncounterSources } from "./EncounterSources";
import { CapturePanel } from "./CapturePanel";
import { ExistingScribeSourcePanel } from './ExistingScribeSourcePanel';
import {InboxAnalysisPanel} from "./InboxAnalysisPanel";
import type {InboxDraftSelection} from "./inbox-analysis-contract";
import {ResearchWorkspace} from "./ResearchWorkspace";
import { CoreRecordLink } from "./CoreRecordLink";
import { SchedulingPanel } from "./SchedulingPanel";
import { SCHEDULING_BUILD } from "./scheduling-api";
import { SCHEDULING_LOGIN_BUILD } from "./scheduling-login-api";
import { GoogleConnectionPanel } from './GoogleConnectionPanel';
import { GoogleMessageMount } from './GoogleMessageMount';
import { GOOGLE_MESSAGE_BUILD } from './google-message-api';
import type {GoogleMessageSaved} from './google-message-recovery';
import {vendorSha256} from './vendor-contract';
import { GOOGLE_CONNECTION_BUILD } from './google-connection-api';
import { MicrosoftConnectionPanel } from './MicrosoftConnectionPanel';
import { MICROSOFT_CONNECTION_BUILD } from './microsoft-connection-api';
import { SchedulingConnectionPanel } from "./SchedulingConnectionPanel";
import { APPOINTMENTS_BUILD } from "./appointment-api";
import { EncounterPrepPanel } from "./EncounterPrepPanel";
import { SessionPrepPanel } from "./SessionPrepPanel";
import { ENCOUNTER_PREP_BUILD } from "./encounter-prep-api";
import { CAPTURE_CORRECTIONS_BUILD, CAPTURE_NOTES_BUILD, CAPTURE_WORKSPACE_BUILD } from "./capture-api";
import type { CaptureDraft } from "./capture-notes-api";
import { withObservedCaptureDraft } from "./capture-review-state";
import { workspaceApi, WorkspaceApiError, botAddress, type AppendInput,
  type AuthenticatedWorkspaceIdentity, type DraftHandoff, type FollowUpOperation, type NoteOperation, type ProviderTeam, type TeamConfiguration, type TeamSaveInput, type Workspace, type WorkspaceEntry, type WorkspaceEncounter, type WorkspaceIdentity } from "./workspace-api";
import "./encounter-workspace.css";

export type PendingSave = NoteOperation | FollowUpOperation | { type: "entry"; body: AppendInput } | ModelOperation |
  { type: "team"; body: TeamSaveInput } |
  { type: "link"; body: { expected_revision: number; idempotency_key: string; ticket_id: string } };

const isFollowUpRecovery = (draft: RecoveryOffer["draft"]) => draft.kind === "workspace" && draft.pending?.type.startsWith("followUp") === true;

export function EncounterWorkspace({ onExit, authenticated, accountControls, practiceAccess, draftStorage = openDraftStore }: {
  onExit?: () => void; authenticated?: AuthenticatedWorkspaceIdentity; accountControls?: ReactNode;
  practiceAccess?:PracticeAccessContext;
  draftStorage?: (options: { scope: string; native: boolean }) => Promise<DraftStore>;
}) {
  const [inboxSelection,setInboxSelection]=useState<InboxDraftSelection|null>(null);
  const [inboxNavigation,setInboxNavigation]=useState<{selection:InboxDraftSelection;identity:WorkspaceIdentity;generation:number}|null>(null);
  const inboxNavigationConsumed=useRef<object|null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [encounters, setEncounters] = useState<WorkspaceEncounter[] | null>(null);
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [team, setTeam] = useState<ProviderTeam | null>(null);
  const [teamDraft, setTeamDraft] = useState<TeamConfiguration | null>(null);
  const [setupApproval, setSetupApproval] = useState<ReviewedTeamDraft | null>(null);
  const [setupProjection, setSetupProjection] = useState<SetupProjection | null>(null);
  const [setupEpoch, setSetupEpoch] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [googleMessageOpen,setGoogleMessageOpen]=useState(false);
  const googleVisitSelection=useRef(false);
  const googleReturn=useRef(GOOGLE_CONNECTION_BUILD&&['#google-connected','#google-sign-in'].includes(window.location.hash));
  const microsoftReturn=useRef(MICROSOFT_CONNECTION_BUILD&&['#microsoft-connected','#microsoft-sign-in'].includes(window.location.hash));
  const schedulingReturn=useRef(SCHEDULING_LOGIN_BUILD&&['#scheduling-connected','#scheduling-sign-in'].includes(window.location.hash));
  const [settingsEntry,setSettingsEntry]=useState<'home'|'connections'|'core'|'scheduling'|'microsoft'|'google'>('home');
  const [connectionLocks, setConnectionLocks] = useState({google:false,googleMessages:false,microsoft:false,scheduling:false,core:false,messaging:false, payments:false, portals:false, inbox:false});
  const activityEnabled = import.meta.env.VITE_AI_ACTIVITY_ENABLED === "true";
  const [activityProof,setActivityProof] = useState<{identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;generation:number;context:AiActivityContext}|null>(null);
  const [activityBusy,setActivityBusy] = useState(false),[activityContextBusy,setActivityContextBusy] = useState(false);
  const activityNavigation = useRef<AbortController|null>(null);
  const [activityContextError,setActivityContextError] = useState(''),[activityAttempt,setActivityAttempt] = useState(0);
  const connectionEditorsLocked = Object.values(connectionLocks).some(Boolean);
  const [accessBusy,setAccessBusy]=useState(false);
  const [scribeSourceBusy,setScribeSourceBusy]=useState(false);
  const [handoffReviewPending,setHandoffReviewPending]=useState(false);
  const [reviewHandoffId,setReviewHandoffId]=useState<string|null>(null);
  const connectionNavigationLocked = connectionEditorsLocked || activityBusy || accessBusy || scribeSourceBusy || handoffReviewPending;
  const [practiceOpen, setPracticeOpen] = useState(false);
  const [practiceOpened, setPracticeOpened] = useState(false);
  const [captureNavigationLocked, setCaptureNavigationLocked] = useState(false);
  const [selected, setSelected] = useState<string>("visit_prep");
  const [researchEntry,setResearchEntry]=useState(false);
  const [entryIntent,setEntryIntent]=useState<"record"|"recording"|"chief"|"fax"|null>(null);
  const faxWorkRef=useRef<HTMLDivElement|null>(null);
  const [focusFaxWork,setFocusFaxWork]=useState(false);
  const notebookRef=useRef<HTMLTextAreaElement|null>(null);
  const chiefNotebookFocus=useRef<{workspace:string;generation:number}|null>(null);
  const [questionFocus,setQuestionFocus]=useState(0);
  const [recordingSourceRequest,setRecordingSourceRequest]=useState(0);
  const [savedResearchChat,setSavedResearchChat]=useState(false);
  const [stage, setStage] = useState("Before");
  const [panel, setPanel] = useState("Notebook");
  const materialRef=useRef<HTMLDivElement>(null);
  const materialScroll=useRef<Record<string,number>>({});
  const [briefViewed,setBriefViewed]=useState<{workspace:string;owner:AuthenticatedWorkspaceIdentity;teamRevision:number;at:string}|null>(null);
  const [mobilePanel, setMobilePanel] = useState("Conversation");
  const [note, setNote] = useState("");
  const [thought, setThought] = useState("");
  const [prepSelection,setPrepSelection]=useState<{scope:symbol;selection:SessionPrepAnalysis}|null>(null);
  const [prepEpoch,setPrepEpoch]=useState(0);
  const questionRef=useRef<HTMLTextAreaElement|null>(null);
  const [evidence, setEvidence] = useState("");
  const [source, setSource] = useState("");
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<PendingSave | null>(null);
  const [modelObservation,setModelObservation]=useState<{receipt:ModelRequestObservation|HandoffRetryObservation;observedAt:string}|null>(null);
  const [replacementDraft,setReplacementDraft]=useState<{content:string;role:string;acknowledged:boolean}|null>(null);
  const [modelHashes,setModelHashes]=useState<Record<string,string>>({});
  const modelBusy=useRef(false);
  const [previousModelRequest,setPreviousModelRequest]=useState<PreviousModelRequest|null>(null);
  const notebookDraft=(w:Workspace,n:string,t:string,e:string,s:string,p:PendingSave|null)=>makeNotebookDraft(w,n,t,e,s,p,previousModelRequest);
  const [captureDraftLocked, setCaptureDraftLocked] = useState(false);
  const [observedCaptureDraft, setObservedCaptureDraft] = useState<CaptureDraft | null>(null);
  const [captureRequest, setCaptureRequest] = useState(0);
  const [confirmCaptureExit, setConfirmCaptureExit] = useState(false);
  const journal = useRef<{ scope: string; serverScope: string; value: DraftJournal } | null>(null);
  const [recoveryOffers, setRecoveryOffers] = useState<RecoveryOffer[]>([]);
  const [recoveryState, setRecoveryState] = useState<"" | "saving" | "saved" | "failed">("");
  const [recoveryEpoch, setRecoveryEpoch] = useState(0);
  const generation = useRef(0);
  const connectionGeneration = generation.current;
  const reportAccessBusy = useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setAccessBusy(blocked);
  },[connectionGeneration]);
  const reportGoogleBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.google===blocked?previous:{...previous,google:blocked});
  }, [connectionGeneration]);
  const reportGoogleMessageBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.googleMessages===blocked?previous:{...previous,googleMessages:blocked});
  }, [connectionGeneration]);
  const reportMicrosoftBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.microsoft===blocked?previous:{...previous,microsoft:blocked});
  },[connectionGeneration]);
  const reportSchedulingBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.scheduling===blocked?previous:{...previous,scheduling:blocked});
  },[connectionGeneration]);
  const reportCoreBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.core===blocked?previous:{...previous,core:blocked});
  },[connectionGeneration]);
  const reportMessagingBusy = useCallback((blocked:boolean) => {
    if (generation.current === connectionGeneration) setConnectionLocks(previous => previous.messaging === blocked ? previous : {...previous, messaging:blocked});
  }, [connectionGeneration]);
  const reportPaymentsBusy = useCallback((blocked:boolean) => {
    if (generation.current === connectionGeneration) setConnectionLocks(previous => previous.payments === blocked ? previous : {...previous, payments:blocked});
  }, [connectionGeneration]);
  const reportPortalsBusy = useCallback((blocked:boolean) => {
    if (generation.current === connectionGeneration) setConnectionLocks(previous => previous.portals === blocked ? previous : {...previous, portals:blocked});
  }, [connectionGeneration]);
  const reportInboxBusy = useCallback((blocked:boolean) => {
    if (generation.current === connectionGeneration) setConnectionLocks(previous => previous.inbox === blocked ? previous : {...previous, inbox:blocked});
  }, [connectionGeneration]);
  const reportActivityBusy = useCallback((blocked:boolean) => {
    if (generation.current === connectionGeneration) setActivityBusy(blocked);
  }, [connectionGeneration]);
  const recoveryView = useRef({workspace,note,pending}); recoveryView.current = {workspace,note,pending};
  const previousIdentity = useRef(authenticated);
  const currentTeam = useRef(team);
  currentTeam.current = team;
  const currentTeamDraft = useRef(teamDraft);
  currentTeamDraft.current = teamDraft;
  const conversationEnd = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "CosmasOS · Provider Team";
    return () => { generation.current++; activityNavigation.current?.abort(); journal.current?.value.close(); journal.current = null; document.title = previousTitle; };
  }, []);
  useEffect(() => {
    if (previousIdentity.current !== authenticated) { previousIdentity.current = authenticated; clear(); }
  }, [authenticated]);
  useEffect(()=>{
    if(googleReturn.current&&authenticated){
      googleReturn.current=false;
      history.replaceState(history.state,'',window.location.pathname+window.location.search);
      setSettingsEntry('google');setSettingsOpen(true);
    }
    if(microsoftReturn.current&&authenticated){
      microsoftReturn.current=false;
      history.replaceState(history.state,'',window.location.pathname+window.location.search);
      setSettingsEntry('microsoft');setSettingsOpen(true);
    }
    if(schedulingReturn.current&&authenticated){
      schedulingReturn.current=false;
      history.replaceState(history.state,'',window.location.pathname+window.location.search);
      setSettingsEntry('scheduling');setSettingsOpen(true);
    }
  },[authenticated]);
  useEffect(() => { conversationEnd.current?.scrollIntoView?.({ block: "nearest" }); }, [workspace?.revision, pending]);
  useEffect(()=>{let cancelled=false;if(pending?.type==='ask')void modelRequestHash(pending.body).then(hash=>{if(!cancelled)setModelHashes({[pending.body.idempotency_key]:hash});}).catch(()=>{if(!cancelled)setModelHashes({});});
    else setModelHashes({});return()=>{cancelled=true;};},[pending]);
  useEffect(() => {
    if (!practiceOpen || !authenticated || team) return;
    let cancelled = false;
    const current = generation.current;
    void workspaceApi.team(authenticated).then(value => {
      if (!cancelled && current === generation.current) {
        setTeam(value); setTeamDraft(previous => previous ?? structuredClone(value.configuration));
        void recoverAfterRead(value, null, current);
      }
    }).catch(cause => { if (!cancelled && current === generation.current) failure(cause); });
    return () => { cancelled = true; };
  }, [practiceOpen, authenticated, team]);
  useLayoutEffect(()=>{
    const element=materialRef.current;if(!element||!workspace)return;
    const key=`${workspace.id}:${panel}`;
    element.scrollTop=materialScroll.current[key]??0;
    return()=>{materialScroll.current[key]=element.scrollTop;};
  },[workspace?.id,panel]);
  useEffect(() => { if (selectedSource) document.getElementById(`source-${selectedSource}`)?.focus(); }, [panel, selectedSource]);
  useEffect(() => {
    if (selectedResult && !reviewHandoffId && mobilePanel === "Conversation" && !settingsOpen) {
      const result = document.getElementById(`turn-${selectedResult}`);
      if(result && !result.closest("[hidden]")){
        result.scrollIntoView?.({ block: "center" }); result.focus(); setSelectedResult(null);
      }
    }
  }, [selectedResult, selected, savedResearchChat, mobilePanel, workspace?.revision, settingsOpen, reviewHandoffId]);
  useEffect(() => {
    if (!reviewHandoffId || settingsOpen || practiceOpen) return;
    const heading=document.querySelector<HTMLElement>('.handoff-review h3');
    heading?.scrollIntoView?.({block:'start'});heading?.focus();
  },[reviewHandoffId,workspace?.id,settingsOpen,practiceOpen]);
  useEffect(() => {
    if (!workspace || !identity || busy || conflict || handoffReviewPending || !(workspace.entries.some(modelActive)||workspace.handoffs?.some(h =>
      ["queued", "running"].includes(h.status) || (h.result_entry_id && !workspace.entries.some(e => e.id === h.result_entry_id))))) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>|undefined,reading=false,controller:AbortController|null=null;
    const visible=()=>document.visibilityState!=='hidden';
    const poll = async () => {
      if(cancelled||reading||!visible())return;
      reading=true;controller=new AbortController();
      try {
        const latest = await workspaceApi.read(identity, workspace.id,controller.signal);
        if (cancelled||controller.signal.aborted) return;
        if(latest.id!==workspace.id||latest.revision<workspace.revision)throw new WorkspaceApiError(503);
        const noteRevision = (value: Workspace) => value.entries.filter(e => e.kind === "scratchpad").at(-1)?.revision ?? 0;
        if (noteRevision(latest) !== noteRevision(workspace)) {
          setConflict(true); setError("The saved notebook changed while your bot was working. Load the latest version to compare it with your unsaved text.");
        }
        setWorkspace(latest);
      } catch (cause) { if (!cancelled&&!controller.signal.aborted) modelFailure(cause); }
      finally{reading=false;}
      if (!cancelled&&visible()) timer = setTimeout(poll, 5000);
    };
    const visibility=()=>{clearTimeout(timer);if(document.visibilityState==='hidden')controller?.abort();else timer=setTimeout(poll,5000);};
    document.addEventListener('visibilitychange',visibility);visibility();
    return () => { cancelled = true; clearTimeout(timer);controller?.abort();document.removeEventListener('visibilitychange',visibility); };
  }, [workspace, identity, busy, pending, conflict, handoffReviewPending]);

  function checkRecoveryOwner(value: ProviderTeam) {
    if (!authenticated) return;
    const scope = requireRecoveryScope(value);
    if (journal.current && journal.current.serverScope !== scope) throw new WorkspaceApiError(403);
  }
  async function prepareRecovery(currentTeam: ProviderTeam, currentWorkspace: Workspace | null, current: number, reloadParent = false) {
    if (!authenticated) return;
    checkRecoveryOwner(currentTeam);
    const serverScope = requireRecoveryScope(currentTeam);
    const scope = await privateDraftScope(serverScope, import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000");
    if (current !== generation.current) return;
    if (journal.current?.scope !== scope) {
      journal.current?.value.close(); journal.current = null;
      const store = await draftStorage({ scope, native: import.meta.env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED === "true" });
      if (current !== generation.current) { store.close(); return; }
      journal.current = { scope, serverScope, value: new DraftJournal(store) };
    }
    const active = journal.current.value;
    const addresses = ["team", ...(currentWorkspace ? [`workspace:${currentWorkspace.id}`,
      editorAddress(currentWorkspace.id,"private-note"),editorAddress(currentWorkspace.id,"core-note"),editorAddress(currentWorkspace.id,"transcript")] : [])];
    const offers: RecoveryOffer[] = [];
    for (const address of addresses) {
      if (active.has(address) && !reloadParent) continue;
      const draft = await active.load(address);
      if (current !== generation.current || journal.current?.value !== active) return;
      if (draft && (draft.kind === "team" || draft.kind === "workspace")) offers.push({ address, draft });
    }
    setRecoveryOffers(previous => [...previous.filter(offer => !reloadParent || !addresses.includes(offer.address)), ...offers]);
    setRecoveryState(""); setRecoveryEpoch(value => value + 1);
  }
  async function recoverAfterRead(value: ProviderTeam, currentWorkspace: Workspace | null, current: number, reloadParent = false) {
    try { await prepareRecovery(value, currentWorkspace, current, reloadParent); }
    catch (cause) { if (current === generation.current) {
      if (cause instanceof WorkspaceApiError && cause.status === 403) failure(cause);
      else setRecoveryState("failed");
    } }
  }
  useEffect(() => {
    const active = journal.current?.value;
    if (!active || busy || pending || recoveryOffers.length || recoveryState === "failed" ||
        authenticated && (!validRecoveryScope(team?.recovery_scope) || journal.current?.serverScope !== team?.recovery_scope)) return;
    const current = generation.current;
    let canceled = false;
    const writes: Promise<void>[] = [];
    if (team && teamDraft && active.has("team")) writes.push(active.persist("team", recoveryTeamDraft(team, teamDraft, null)));
    if (workspace && active.has(`workspace:${workspace.id}`)) writes.push(active.persist(`workspace:${workspace.id}`, notebookDraft(workspace, note, thought, evidence, source, null)));
    if (!writes.length) return;
    setRecoveryState("saving");
    void Promise.all(writes).then(() => { if (!canceled && current === generation.current) setRecoveryState("saved"); })
      .catch(() => { if (!canceled && current === generation.current) setRecoveryState("failed"); });
    return () => { canceled = true; };
  // State transitions do not trigger another storage write. The inputs do.
  }, [workspace, team, teamDraft, note, thought, evidence, source, busy, pending, recoveryOffers, recoveryEpoch]);

  async function restoreDraft(offer: RecoveryOffer) {
    if (busy || pending || !authenticated) return;
    const draft = offer.draft, current = generation.current;
    setBusy(true);
    try {
      // Access can change while the offer is on screen. Recheck before displaying
      // its private contents, including the current encounter/patient boundary.
      const latestTeam = await workspaceApi.team(authenticated);
      if (current !== generation.current) return;
      if (!latestTeam.recovery_scope || latestTeam.recovery_scope !== team?.recovery_scope) throw new WorkspaceApiError(403);
      const latest = draft.kind === "workspace" ? await workspaceApi.read(authenticated, draft.workspaceId) : null;
      if (current !== generation.current) return;
      setTeam(latestTeam);
      if (draft.kind === "team") {
        setTeamDraft(draft.configuration); setSettingsOpen(true); setPracticeOpen(false);
        if (draft.pending) setPending({ type: "team", body: draft.pending });
        else if (latestTeam.revision !== draft.baseRevision) setConflict(true);
      } else if (latest && workspace?.id === draft.workspaceId) {
        setWorkspace(latest); setNote(draft.note); setThought(draft.thought); setEvidence(draft.evidence); setSource(draft.source);
        const material = isFollowUpRecovery(draft) ? "Work" : draft.pending && ["note","review","coreNoteLink"].includes(draft.pending.type) ? "Review" : "Notebook";
        setSettingsOpen(false); setPracticeOpen(false); setPanel(material); setMobilePanel(material);
        if (draft.pending) setPending(draft.pending);
        else if (latest.revision !== draft.baseRevision) setConflict(true);
        setPreviousModelRequest(draft.previous_model_request??((draft.pending?.type==='ask'||draft.pending?.type==='retry')?draft.pending.previous_model_request:null)??null);
      } else return;
      setRecoveryOffers(previous => previous.filter(value => value.address !== offer.address));
      setMessage("Recovered this device's draft. Check it against the current saved history before continuing. Unconfirmed requests are retried only when you choose.");
    } catch (cause) { if (current === generation.current) failure(cause); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function discardRecovered(offer: RecoveryOffer) {
    if (busy || pending || offer.draft.pending) return;
    const current = generation.current; setBusy(true);
    try {
      await journal.current?.value.persist(offer.address, null);
      if (current === generation.current) setRecoveryOffers(previous => previous.filter(value => value.address !== offer.address));
    } catch { if (current === generation.current) setRecoveryState("failed"); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function exitWorkspace(discard: boolean) {
    if (connectionNavigationLocked) {
      setError("Save or recover your unfinished edits before closing. Unconfirmed requests are retained.");
      return;
    }
    if (!discard && (hasUnsavedWork() || recoveryOffers.length)) { setConfirmCaptureExit(true); return; }
    const active = journal.current?.value, current = generation.current;
    if (active) {
      setBusy(true);
      try {
        // Keep unconfirmed requests for explicit reconciliation after reopening.
        for (const [address, record] of active.records) {
          const body = record.value?.body as { kind?: unknown; pending?: unknown } | undefined;
          // Editors own nested requests and proof history; workspace close cannot discard them.
          if (body?.kind === "account-editor" || body?.kind === "editor") continue;
          if (!body?.pending) await active.persist(address, null);
        }
      } catch { if (current === generation.current) { setRecoveryState("failed"); setBusy(false); } return; }
    }
    if (current === generation.current) { clear(); onExit?.(); }
  }

  function clear() {
    generation.current++;activityNavigation.current?.abort();activityNavigation.current=null;
    journal.current?.value.close(); journal.current = null; setRecoveryOffers([]); setRecoveryState("");
    setSetupApproval(null); setSetupProjection(null);
    setInboxSelection(null);setWorkspace(null); setEncounters(null); setIdentity(null); setTeam(null); setTeamDraft(null); setSettingsOpen(false);
    setPracticeOpen(false); setPracticeOpened(false); setCaptureNavigationLocked(false);
    setConnectionLocks({google:false,googleMessages:false,microsoft:false,scheduling:false,core:false,messaging:false, payments:false, portals:false, inbox:false});
    setGoogleMessageOpen(false);googleVisitSelection.current=false;
    setAccessBusy(false);setActivityProof(null);setActivityBusy(false);setActivityContextBusy(false);setActivityContextError('');
    chiefNotebookFocus.current=null;
    setEntryIntent(null);setRecordingSourceRequest(0);setNote(""); setThought(""); setEvidence(""); setSource(""); setSelectedSource(null); setSelectedResult(null);
    setPending(null); setConflict(false); setMessage(""); setError(""); setBusy(false);
    setModelObservation(null);setReplacementDraft(null);setModelHashes({});
    setPreviousModelRequest(null);
    modelBusy.current=false;
    setCaptureDraftLocked(false); setConfirmCaptureExit(false);
    setCaptureRequest(0); setObservedCaptureDraft(null);
    setResearchEntry(false);
    setReviewHandoffId(null);setHandoffReviewPending(false);
  }
  function failure(cause: unknown) {
    if (cause instanceof WorkspaceApiError && [401, 403, 404, 426].includes(cause.status)) {
      clear(); setError(cause.status === 426 ? "Update required for this team configuration. Private content is withheld; encrypted drafts and exact unconfirmed requests remain on this device." : "Workspace access is unavailable. Private content has been cleared from this view.");
    } else {
      if (cause instanceof WorkspaceApiError && cause.code === "workspace_recovery_unavailable") setRecoveryState("failed");
      setError(cause instanceof WorkspaceApiError ? cause.message : "The request could not be confirmed. Retry when the local service is available.");
      if (cause instanceof WorkspaceApiError && cause.status === 409) { setConflict(true); setPending(null); setSetupApproval(null); setSetupEpoch(value => value + 1); }
      if (cause instanceof WorkspaceApiError && [400, 422].includes(cause.status)) setPending(null);
    }
  }
  async function loadEncounters() {
    if (!authenticated || pending || busy) return;
    const current = ++generation.current; setBusy(true); setError("");
    try {
      const result = await workspaceApi.catalog(authenticated);
      if (current === generation.current) setEncounters(result);
    } catch (cause) { if (current === generation.current) failure(cause); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function open(appointmentId?: string, coreSelection?: CoreConnectionCommand, incoming?:InboxDraftSelection, recordVisit = false) {
    if (pending || busy) return;
    if ((coreSelection || incoming) && (locked || captureNavigationLocked || captureDraftLocked || hasUnsavedWork())) {
      setError('Save or recover unfinished work before opening a notebook. Your text and requests are retained.'); return;
    }
    recordVisit = recordVisit || !incoming && entryIntent === "record";
    const useRecording = !recordVisit && !incoming && entryIntent === "recording";
    const startChief = !recordVisit && !useRecording && !incoming && entryIntent === "chief";
    const startFax = !recordVisit && !useRecording && !incoming && entryIntent === "fax";
    chiefNotebookFocus.current=null;
    const preserveTeamDraft = !!team && !!teamDraft && JSON.stringify(teamDraft) !== JSON.stringify(team.configuration);
    const current = ++generation.current; setBusy(true); setError("");
    try {
      let selected: {workspace_id:string;appointment_id:string}|undefined;
      if (coreSelection) {
        if (!authenticated) throw new WorkspaceApiError(401);
        const opened = await coreConnectionApi.read(authenticated,coreSelection);
        if (current !== generation.current) return;
        if (!opened.workspace) throw new WorkspaceApiError(502);
        selected = opened.workspace;
      }
      const result = incoming && authenticated ? {identity:authenticated,workspace:await workspaceApi.read(authenticated,incoming.workspace_id),team:await workspaceApi.team(authenticated)} : authenticated ? selected ? await workspaceApi.openExisting(authenticated,selected) : await workspaceApi.open(authenticated, appointmentId) : await workspaceApi.open();
      if (current !== generation.current) return;
      checkRecoveryOwner(result.team);
      if(incoming&&(result.workspace.id!==incoming.workspace_id||result.workspace.revision!==incoming.expected_revision))throw new WorkspaceApiError(409,'source_changed');
      setInboxSelection(incoming??null);
      if(incoming){
        const coworker=result.team.configuration.bots.find(b=>b.role==='custom'&&b.skills?.includes('inbox_review')&&b.enabled&&!b.retired&&!b.blocked_capabilities?.includes('model_answer'));
        if(coworker)setSelected(botAddress(coworker));
        setPracticeOpen(false);setMobilePanel('Conversation');
      }
      setIdentity(result.identity); setWorkspace(result.workspace); setTeam(result.team);
      setPreviousModelRequest(null);
      setThought('');setEvidence('');setSource('');setModelObservation(null);setReplacementDraft(null);setModelHashes({});
      setObservedCaptureDraft(null);setSelectedSource(null);setSelectedResult(null);setCaptureRequest(recordVisit ? 1 : 0);setRecordingSourceRequest(useRecording?1:0);setEntryIntent(null);setStage('Before');setPanel('Notebook');
      if (recordVisit || useRecording) {
        const recorder = result.team.configuration.bots.find(item => item.role === "scribe" && !item.retired && !item.instance_id);
        if (recorder) setSelected(botAddress(recorder));
        setMobilePanel("Notebook");
      }
      if(startChief){
        const chief=result.team.configuration.bots.find(item=>item.role==='chief'&&!item.instance_id&&!item.retired);
        if(chief){setSelected(botAddress(chief));chiefNotebookFocus.current={workspace:result.workspace.id,generation:current};}
        else setMessage('Chief is not available on this team. Your notebook is still available.');
        setMobilePanel('Notebook');
      }
      if(startFax){setPanel('Work');setMobilePanel('Work');setFocusFaxWork(true);}
      if (researchEntry && !recordVisit && !useRecording && !incoming) {
        const researcher=result.team.configuration.bots.find(item=>item.role==='research'&&!item.retired);
        if(researcher){setSelected(botAddress(researcher));setMobilePanel('Conversation');setSavedResearchChat(false);}
        else setMessage('Research is not on this team yet. Add it in Team settings.');
      }
      if (!preserveTeamDraft) setTeamDraft(structuredClone(result.team.configuration));
      setNote(result.workspace.entries.filter(e => e.kind === "scratchpad").at(-1)?.content ?? "");
      setSettingsOpen(false);
      await recoverAfterRead(result.team, result.workspace, current);
      if(googleVisitSelection.current&&current===generation.current){googleVisitSelection.current=false;setSettingsEntry('google');setGoogleMessageOpen(true);setSettingsOpen(true);}
    } catch (cause) { if (current === generation.current) {
      failure(cause);
      if(coreSelection && cause instanceof WorkspaceApiError && cause.code==='core_existing_recording_conflict')
        setError('The Scribe recording does not match this visit’s notebook. Ask your practice administrator to review the match.');
      else if(coreSelection && cause instanceof WorkspaceApiError && cause.code==='core_scribe_encounter_unavailable')
        setError('Scribe encounters could not be loaded. Try again, or open your saved visit from the encounter list.');
      else if (coreSelection && !(cause instanceof WorkspaceApiError && [401,403,404,426].includes(cause.status)))
        setError('The notebook could not be confirmed. View your appointments and select it again; an existing notebook will be reused.');
    } }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function save(operation: PendingSave) {
    if(operation.type==='ask'||operation.type==='retry'){await saveModel(operation,'submit');return;}
    const access = authenticated || identity;
    if (!access || busy || (operation.type !== "team" && (!workspace || !identity))) return;
    const current = generation.current;
    setPending(operation); setBusy(true); setError(""); setMessage("");
    let transmitted = false;
    try {
      const active = journal.current?.value;
      if (authenticated) {
        const scope = requireRecoveryScope(team);
        if (!active || journal.current?.serverScope !== scope || recoveryOffers.length || recoveryState === "failed") throw new Error("Device draft recovery unavailable");
        if (operation.type === "team" && team) await active.persist("team", recoveryTeamDraft(team, operation.body.configuration, operation));
        else if (workspace) await active.persist(`workspace:${workspace.id}`, notebookDraft(workspace, note, thought, evidence, source, operation));
        if (current !== generation.current) return;
      }
      transmitted = true;
      if (operation.type === "team") {
        const result = await workspaceApi.saveTeam(access, operation.body);
        if (current !== generation.current) return;
        checkRecoveryOwner(result);
        // A committed idempotent receipt can describe an older configuration.
        // Keep its exact request until the current team is independently read.
        const latest = await workspaceApi.team(access);
        if (current !== generation.current) return;
        checkRecoveryOwner(latest);
        if (latest.revision < result.revision) throw new WorkspaceApiError(503);
        if (active) await active.persist("team", null);
        if (current !== generation.current) return;
        currentTeam.current = latest; currentTeamDraft.current = structuredClone(latest.configuration);
        setTeam(latest); setTeamDraft(currentTeamDraft.current); setSettingsOpen(false); setSetupApproval(null); setSetupProjection(null);
        setMessage(`Team settings saved · revision ${result.revision}.${latest.revision !== result.revision ? ` Current team revision ${latest.revision} is shown.` : ""}`);
      } else {
        if (!workspace || !identity) return;
        const result = operation.type === "entry" ? await workspaceApi.append(identity, workspace.id, operation.body) :
          operation.type === "note" ? await workspaceApi.saveNote(identity, workspace.id, operation.body) :
          operation.type === "coreNoteLink" ? await workspaceApi.linkCoreNote(identity, workspace.id, operation.body) :
          operation.type === "review" ? await workspaceApi.reviewNote(identity, workspace.id, operation.noteId, operation.body) :
          operation.type === "followUpPropose" ? await workspaceApi.proposeFollowUp(identity, workspace.id, operation.body) :
          operation.type === "followUpDecision" ? await workspaceApi.decideFollowUp(identity, workspace.id, operation.ticketId, operation.body) :
          operation.type === "followUpComplete" ? await workspaceApi.completeFollowUp(identity, workspace.id, operation.ticketId, operation.body) :
          await workspaceApi.link(identity, workspace.id, operation.body);
        if (current !== generation.current) return;
        if (active && workspace) await active.persist(`workspace:${workspace.id}`, notebookDraft(result.workspace, note,
          operation.type === "entry" && operation.body.kind === "conversation" ? "" : thought,
          operation.type === "entry" && operation.body.kind === "evidence" ? "" : evidence,
          operation.type === "entry" && operation.body.kind === "evidence" ? "" : source, null));
        if (current !== generation.current) return;
        setWorkspace(result.workspace);
        if (operation.type === "coreNoteLink") { setPanel("Review"); setMobilePanel("Review"); }
        if (operation.type === "entry" && operation.body.kind === "conversation") setThought("");
        if (operation.type === "entry" && operation.body.kind === "evidence") { setEvidence(""); setSource(""); }
        setMessage(`Saved revision ${result.entry_revision}.`);
      }
      setPending(null); setConflict(false);
    } catch (cause) {
      if (current === generation.current) {
        if (!transmitted) { if (!pending) setPending(null); setRecoveryState("failed"); setError("The request was not sent. Recheck this device's draft storage before saving."); }
        else failure(cause);
      }
    }
    finally { if (current === generation.current) setBusy(false); }
  }
  function modelFailure(cause:unknown){
    if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)){failure(cause);return;}
    setError(cause instanceof WorkspaceApiError?cause.message:"The model request could not be confirmed. Its exact request is retained; check the saved result.");
  }
  function mergeModelRead(latest:Workspace,latestTeam:ProviderTeam){
    const savedNote=(value:Workspace|null)=>value?.entries.filter(e=>e.kind==='scratchpad').at(-1)?.content??'';
    const noteChanged=savedNote(latest)!==savedNote(workspace)&&note!==savedNote(latest);
    const editedTeam=!!team&&!!teamDraft&&JSON.stringify(teamDraft)!==JSON.stringify(team.configuration);
    const teamChanged=!!team&&latestTeam.revision!==team.revision&&editedTeam;
    setWorkspace(latest);setTeam(latestTeam);
    if(!editedTeam)setTeamDraft(structuredClone(latestTeam.configuration));
    if(noteChanged||teamChanged){setConflict(true);setError('The saved notebook or team changed. Your unsaved text and settings are retained; load the latest version and compare before saving.');}
  }
  async function saveModel(operation:ModelOperation,mode:'submit'|'resolve'){
    if(!workspace||!identity||busy||modelBusy.current||!validModelOperation(operation))return;
    modelBusy.current=true;
    const current=generation.current,id=workspace.id,active=journal.current?.value;
    setBusy(true);setError('');setMessage('');let transmitted=false;
    try{
      if(authenticated){
        if(!active||journal.current?.serverScope!==requireRecoveryScope(team)||recoveryOffers.length||recoveryState==='failed')throw new Error('Private draft storage unavailable');
        await active.persist(`workspace:${id}`,notebookDraft(workspace,note,thought,evidence,source,operation));
        if(current!==generation.current)return;
      }
      setPending(operation);setModelObservation(null);setReplacementDraft(null);transmitted=true;
      if(operation.previous_model_request)setPreviousModelRequest(operation.previous_model_request);
      const receipt=mode==='resolve'?await modelWorkApi.resolve(identity,id,operation):operation.type==='ask'?await workspaceApi.ask(identity,id,operation.body):await workspaceApi.retryHandoff(identity,id,operation.handoffId,operation.body);
      if(current!==generation.current)return;
      if(!await exactModelObservation(receipt,id,operation))throw new WorkspaceApiError(503);
      const latest=await workspaceApi.read(identity,id);
      if(current!==generation.current)return;
      const latestTeam=await workspaceApi.team(identity);if(current!==generation.current)return;checkRecoveryOwner(latestTeam);
      const anchor='saved_entry' in receipt?receipt.saved_entry?.revision:receipt.recorded?Math.max(receipt.recorded.workspace_revision,receipt.recorded.result_entry?.revision??0):null;
      if(latest.id!==id||latest.revision<workspace.revision||anchor!==null&&anchor!==undefined&&latest.revision<anchor)throw new WorkspaceApiError(503);
      const settled=receipt.outcome==='saved'||receipt.outcome==='recorded';
      const nextThought=settled&&operation.type==='ask'&&thought===operation.body.content?'':thought;
      if(settled&&active){await active.persist(`workspace:${id}`,makeNotebookDraft(latest,note,nextThought,evidence,source,null,operation.previous_model_request??previousModelRequest));if(current!==generation.current)return;}
      mergeModelRead(latest,latestTeam);
      if(settled){setPending(null);setThought(nextThought);setModelObservation(null);setMessage(receipt.outcome==='saved'?'Conversation saved.':'Draft request recorded. Its current lifecycle is shown separately.');}
      else {setModelObservation({receipt,observedAt:latest.model_observed_at??new Date().toISOString()});setMessage('The exact request is retained. Checking a result does not start model work.');}
    }catch(cause){if(current===generation.current){if(!transmitted){setRecoveryState('failed');setError('No new request was sent. The previous request and your forms are retained. Recheck private draft storage.');}else modelFailure(cause);}}
    finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
  async function replaceModelRequest(){
    if(!workspace||!team||!replacementDraft||!modelObservation||(pending?.type!=='ask'&&pending?.type!=='retry')||busy||modelBusy.current)return;
    const old=pending,receipt=modelObservation.receipt;
    if(old.type==='ask'&&(old.body.research_analysis||old.body.inbox_analysis||old.body.membership_analysis||old.body.session_prep_analysis))return; // A new selected analysis requires its own packet review and consent.
    if(receipt.outcome!=='not_found'&&!['unknown','failed','abandoned'].includes(receipt.outcome))return;
    if(old.origin!=='durable_admission_v1'&&!replacementDraft.acknowledged)return;
    const current=generation.current;
    modelBusy.current=true;setBusy(true);
    try{
      const latestTeam=await workspaceApi.team(identity!);if(current!==generation.current)return;checkRecoveryOwner(latestTeam);
      const latest=await workspaceApi.read(identity!,workspace.id);if(current!==generation.current)return;
      const prior:PreviousModelRequest={workspace_id:workspace.id,operation:old.type==='ask'?{type:'ask',body:structuredClone(old.body)}:{type:'retry',handoffId:old.handoffId,body:structuredClone(old.body)},
        request_sha256:await modelRequestHash(old.body),outcome:receipt.outcome,observed_at:modelObservation.observedAt,origin:old.origin??'legacy_unknown',legacy_uncertainty_acknowledged:replacementDraft.acknowledged};
      let next:ModelOperation;
      if(old.type==='ask'){
        const bot=latestTeam.configuration.bots.find(b=>botAddress(b)===replacementDraft.role);if(!bot?.enabled||bot.retired)throw new WorkspaceApiError(409,'bot_unavailable');
        next={type:'ask',model_contract:1,origin:'durable_admission_v1',previous_model_request:prior,body:{expected_revision:latest.revision,team_revision:latestTeam.revision,
          idempotency_key:crypto.randomUUID(),role:replacementDraft.role,content:replacementDraft.content}};
      }else{
        const handoff=latest.handoffs?.find(h=>h.id===old.handoffId);if(!handoff||handoff.attempt_count>=3)throw new WorkspaceApiError(409);
        next={type:'retry',handoffId:old.handoffId,model_contract:1,origin:'durable_admission_v1',previous_model_request:prior,
          body:{expected_revision:latest.revision,previous_attempt_id:handoff.attempt_id,idempotency_key:crypto.randomUUID()}};
      }
      if(current!==generation.current||!validModelOperation(next))return;
      // saveModel keeps the old pending request until this replacement CAS succeeds.
      modelBusy.current=false;
      await saveModel(next,'submit');
    }catch(cause){if(current===generation.current)modelFailure(cause);}
    finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
  async function prepareNewSelectedAnalysis(){
    if(!workspace||!identity||busy||modelBusy.current||pending?.type!=='ask'||!(pending.body.research_analysis||pending.body.inbox_analysis||pending.body.membership_analysis||pending.body.session_prep_analysis)||!modelObservation||!replacementDraft?.acknowledged||!['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome))return;
    const old=pending,current=generation.current,active=journal.current?.value;if(!active||recoveryBlocked)return;
    modelBusy.current=true;setBusy(true);
    try{
      const prior:PreviousModelRequest={workspace_id:workspace.id,operation:{type:'ask',body:structuredClone(old.body)},request_sha256:await modelRequestHash(old.body),outcome:modelObservation.receipt.outcome,observed_at:modelObservation.observedAt,origin:old.origin??'legacy_unknown',legacy_uncertainty_acknowledged:true};
      await active.persist(`workspace:${workspace.id}`,makeNotebookDraft(workspace,note,thought,evidence,source,null,prior));if(current!==generation.current)return;
      setPending(null);setPreviousModelRequest(prior);setModelObservation(null);setReplacementDraft(null);setSelected(old.body.role);setSavedResearchChat(false);
      if(old.body.session_prep_analysis){setPrepSelection(null);setPrepEpoch(value=>value+1);}
      if(old.body.inbox_analysis){setInboxSelection(null);setPracticeOpened(true);setPracticeOpen(true);}
      setMessage(old.body.session_prep_analysis?'Previous request retained. Open the current Session Prep brief and include it in chat before sending a new question. Nothing has been sent.':old.body.membership_analysis?'Previous Membership/Billing request retained. Review the current record and consent to a new review from this coworker.':old.body.inbox_analysis?'Previous Inbox request retained. Review the current message and encounter in Incoming messages, then consent to a new draft.':'Previous analysis request retained. Review a saved source packet and question, then consent to a new model request. Nothing has been sent.');
    }catch(cause){if(current===generation.current)modelFailure(cause);}finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
  async function checkEntryResult(entry:WorkspaceEntry){
    if(!workspace||!identity||busy||modelBusy.current||entry.model_request?.request.kind!=='conversation')return;
    const metadata=entry.model_request,request=metadata.request;
    if(request.kind!=='conversation')return;
    const body=conversationFromEntry(entry);if(!body)return;const operation:ModelOperation={type:'ask',body};
    const current=generation.current;modelBusy.current=true;setBusy(true);setError('');
    try{
      if(!validModelOperation(operation)||await modelRequestHash(operation.body)!==metadata.request_sha256)throw new WorkspaceApiError(503);
      const receipt=await modelWorkApi.resolve(identity,workspace.id,operation);
      if(current!==generation.current)return;
      const latest=await workspaceApi.read(identity,workspace.id),latestTeam=await workspaceApi.team(identity);
      if(current!==generation.current)return;checkRecoveryOwner(latestTeam);
      if(latest.id!==workspace.id||latest.revision<workspace.revision||'saved_entry' in receipt&&receipt.saved_entry&&latest.revision<receipt.saved_entry.revision)throw new WorkspaceApiError(503);
      mergeModelRead(latest,latestTeam);setMessage(receipt.outcome==='saved'?'The exact saved response was verified.':'Saved request state checked. No model work was started.');
    }catch(cause){if(current===generation.current)modelFailure(cause);}
    finally{if(current===generation.current){modelBusy.current=false;setBusy(false);}}
  }
  function useCoreDraft(draft: CaptureDraft) {
    if (!workspace || busy || pending || conflict || draft.status !== "draft" || !draft.note_ref || !draft.transcript_ref || !draft.note_sha256) return;
    void save({type: "coreNoteLink", body: {expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(),
      base_note_id: workspace.note?.latest?.id ?? null, source: {
        session_id: draft.session_id, scribe_source_id: draft.scribe_source_id, source_sha256: draft.source_sha256,
        schema_ref: draft.schema_ref, transcript_ref: draft.transcript_ref, note_ref: draft.note_ref, note_sha256: draft.note_sha256,
        ...(draft.capture_gap_review ? {capture_gap_review: draft.capture_gap_review} : {}),
        ...(draft.notebook_source ? {notebook_source: draft.notebook_source} : {}),
        ...(draft.reviewed_source ? {reviewed_source: draft.reviewed_source} : {}),
      }}});
  }
  function append(kind: AppendInput["kind"], content: string, sourceLabel?: string) {
    if (!workspace || !content.trim() || pending || conflict) return;
    void save({ type: "entry", body: { expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(), kind, content,
      ...(sourceLabel ? { source_label: sourceLabel } : {}) } });
  }
  function ask(content = thought) {
    if (!workspace || !team?.revision || !content.trim() || pending || conflict || !team.configuration.bots.find(b => botAddress(b) === selected)?.enabled) return;
    void save({ type: "ask", model_contract:1,origin:'durable_admission_v1',body: { expected_revision: workspace.revision, team_revision: team.revision,
      idempotency_key: crypto.randomUUID(), role: selected, content, ...(selectedPrep?{session_prep_analysis:structuredClone(selectedPrep)}:{}) } });
  }
  function prepareChiefQuestion(prompt:string){
    if(locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked||!team?.revision||!team.llm.enabled||
      bot?.role!=='chief'||!bot.enabled||bot.retired||bot.blocked_capabilities?.includes('model_answer')||thought.trim()||
      note!==latestNote||!chiefSavedContext)return;
    setThought(prompt);setMobilePanel('Conversation');setQuestionFocus(value=>value+1);
  }
  async function refresh() {
    const access = authenticated || identity;
    if (!access || busy || pending) return;
    const current = generation.current; setBusy(true); setError(""); setSetupApproval(null); setSetupEpoch(value => value + 1);
    try {
      const [latest, latestTeam] = await Promise.all([workspace ? workspaceApi.read(access, workspace.id) : Promise.resolve(null), workspaceApi.team(access)]);
      if (current !== generation.current) return;
      checkRecoveryOwner(latestTeam);
      setWorkspace(latest); setTeam(latestTeam); setConflict(false);setPrepEpoch(value=>value+1);
      setMessage("Latest saved history and team loaded. Your unsaved text and settings are preserved; compare them before saving.");
      // Keep the account editor controller and its retained input alive while rechecking parent addresses.
      await recoverAfterRead(latestTeam, latest, current, recoveryState === "failed");
    } catch (cause) { if (current === generation.current) failure(cause); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function refreshHandoffReview() {
    const access=authenticated||identity;
    if(!access||!workspace||busy||pending||captureNavigationLocked||captureDraftLocked||recoveryBlocked)
      throw new WorkspaceApiError(503);
    const current=generation.current,wid=workspace.id,revision=workspace.revision;
    setBusy(true);setError('');
    try {
      const [latest,latestTeam]=await Promise.all([workspaceApi.read(access,wid),workspaceApi.team(access)]);
      if(current!==generation.current)throw new WorkspaceApiError(401);
      if(latest.id!==wid||latest.revision<revision)throw new WorkspaceApiError(503);
      checkRecoveryOwner(latestTeam);
      setWorkspace(latest);setTeam(latestTeam);setConflict(false);
      setMessage('Current saved draft loaded. Your change request is preserved for review.');
    }catch(cause){if(current===generation.current)failure(cause);throw cause;}
    finally{if(current===generation.current)setBusy(false);}
  }
  async function recheckRecovery() {
    const access = authenticated || identity;
    if (!access || busy) return;
    const current = generation.current; setBusy(true);
    try {
      const value = await workspaceApi.team(access);
      if (current !== generation.current) return;
      checkRecoveryOwner(value);
      await prepareRecovery(value, workspace, current, !pending && recoveryState === "failed");
      if (current !== generation.current) return;
      setTeam(value); setTeamDraft(previous => previous ?? structuredClone(value.configuration));
      setError("");
    } catch (cause) { if (current === generation.current) {
      failure(cause);
      if (current === generation.current) setRecoveryState("failed");
    } }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function openSettings(entry:'home'|'connections'|'core'='home') {
    if (connectionNavigationLocked || busy || pending && pending.type !== "team") return;
    setSettingsEntry(entry); setPracticeOpen(false); setSettingsOpen(true);
    if (team && teamDraft) return;
    const access = authenticated || identity;
    if (!access) return;
    const current = generation.current; setBusy(true); setError("");
    try {
      const value = await workspaceApi.team(access);
      if (current !== generation.current) return;
      setTeam(value); setTeamDraft(structuredClone(value.configuration));
      await recoverAfterRead(value, null, current);
    } catch (cause) { if (current === generation.current) failure(cause); }
    finally { if (current === generation.current) setBusy(false); }
  }
  async function refreshRoutineTeam() {
    const access = authenticated || identity;
    if (!access) throw new WorkspaceApiError(401);
    const current = generation.current;
    let value: ProviderTeam;
    try {
      value = await workspaceApi.team(access);
      if (authenticated) {
        const scope = requireRecoveryScope(value);
        if (journal.current && journal.current.serverScope !== scope) throw new WorkspaceApiError(403);
      }
    } catch (cause) { if (current === generation.current) failure(cause); throw cause; }
    if (current !== generation.current) throw new WorkspaceApiError(401);
    const previousTeam = currentTeam.current;
    // A background read must not replace a newer confirmed save or an edited draft.
    if (previousTeam && previousTeam.revision > value.revision) return;
    if (previousTeam && previousTeam.revision !== value.revision && currentTeamDraft.current &&
      JSON.stringify(currentTeamDraft.current) !== JSON.stringify(previousTeam.configuration)) {
      setConflict(true); setError("Your saved team changed. Unsaved settings are preserved; load the latest team and compare before saving.");
    }
    currentTeam.current = value;
    setTeam(value); setTeamDraft(previous => !previous || JSON.stringify(previous) === JSON.stringify(previousTeam?.configuration)
      ? structuredClone(value.configuration) : previous);
  }
  function receiveSetupTeam(value: ProviderTeam, projection: SetupProjection) {
    checkRecoveryOwner(value);
    const previous = currentTeam.current;
    if (previous && previous.revision > value.revision) return;
    if (previous && value.revision !== previous.revision && currentTeamDraft.current &&
        JSON.stringify(currentTeamDraft.current) !== JSON.stringify(previous.configuration)) {
      setConflict(true); setError("Your saved team changed. Unsaved settings are preserved; load the latest team and compare before saving.");
    }
    currentTeam.current = value; setTeam(value); setSetupProjection(projection);
    setTeamDraft(draft => !draft || JSON.stringify(draft) === JSON.stringify(previous?.configuration) ? structuredClone(value.configuration) : draft);
  }
  function saveTeam() {
    if (!team || !teamDraft || !validTeamConfiguration(teamDraft)) return;
    const approval = setupApproval?.revision === team.revision && setupApproval.configurationKey === JSON.stringify(teamDraft) ? setupApproval.review : null;
    if (setupChange(team.configuration, teamDraft) && !approval) { setError("Run the invented rehearsal and review the current draft before saving these capability changes."); return; }
    void save({ type: "team", body: { expected_revision: team.revision, idempotency_key: crypto.randomUUID(), configuration: normalizeTeamConfiguration(teamDraft),
      ...(approval ? {setup_review: approval} : {}) } });
  }
  function closeSettings() {
    if (connectionNavigationLocked) return;
    setPracticeOpen(false);
    if (!team?.configuration.bots.some(b => botAddress(b) === selected)) setSelected("scribe");
    setSettingsOpen(false);
  }
  function openMessagingWork(){
    if(connectionNavigationLocked||locked||captureNavigationLocked||captureDraftLocked||!authenticated)return;
    setPracticeOpen(false);setSettingsOpen(false);setResearchEntry(false);
    if(workspace){setPanel('Work');setMobilePanel('Work');setFocusFaxWork(true);}
    else {setEntryIntent('fax');void loadEncounters();}
  }
  useEffect(()=>{
    if(focusFaxWork&&workspace&&!settingsOpen&&!practiceOpen&&panel==='Work'){
      faxWorkRef.current?.focus();faxWorkRef.current?.scrollIntoView?.({block:'start'});setFocusFaxWork(false);
    }
  },[focusFaxWork,workspace,settingsOpen,practiceOpen,panel]);
  const recoveryBlocked = !!authenticated && (!validRecoveryScope(team?.recovery_scope) ||
    !journal.current || journal.current.serverScope !== team?.recovery_scope || recoveryState === "failed");
  const baseLocked = busy || !!pending || conflict || !!recoveryOffers.length || recoveryState === "failed" || recoveryBlocked;
  const actionLocked = baseLocked || scribeSourceBusy;
  const locked = actionLocked || handoffReviewPending;
  const reviewWorkspace = workspace ? withObservedCaptureDraft(workspace, observedCaptureDraft) : null;
  const bot = team?.configuration.bots.find(b => botAddress(b) === selected);
  const template = team?.members.find(b => botAddress(b) === selected);
  const prepAvailable=!!(bot&&supportsSkill(bot,"encounter_prep")&&ENCOUNTER_PREP_BUILD&&authenticated&&team?.capture?.prep_enabled&&
    template?.capabilities.some(capability=>capability.key==="core.session_prep.read"&&capability.state==="enabled"&&capability.contract==="core.session-prep.brief.v1"));
  const prepScope=useMemo(()=>Symbol(),[workspace?.id,authenticated,selected,team?.revision,bot?.enabled,bot?.include_evidence,prepAvailable,prepEpoch]);
  const selectedPrep=prepAvailable&&prepSelection?.scope===prepScope?prepSelection.selection:null;
  useEffect(()=>{if(selectedPrep)questionRef.current?.focus();},[selectedPrep]);
  const visitPrepReader = bot?.role === "visit_prep" && ENCOUNTER_PREP_BUILD && !!authenticated && !!team?.capture?.prep_enabled;
  const scribe = bot?.role === "scribe" ? bot : team?.configuration.bots.find(b => b.role === "scribe" && !b.instance_id);
  useEffect(() => {
    // Explicit fax navigation wins when settings closes. Completing that focus
    // does not trigger another recording scroll; only these navigation events do.
    if (bot?.role === "scribe" && !settingsOpen && !practiceOpen && !focusFaxWork)
      document.querySelector('[aria-label="Scribe recording"]')?.scrollIntoView?.({block: "start"});
  }, [selected, workspace?.id, settingsOpen, practiceOpen]);
  const latestNote = workspace?.entries.filter(e => e.kind === "scratchpad").at(-1)?.content ?? "";
  const chiefSavedContext=!!bot&&!!workspace?.entries.some(entry=>entry.content.trim()&&
    (entry.kind==='scratchpad'&&entry.content===latestNote&&bot.include_notebook||
      (entry.kind==='evidence'||entry.kind==='synthetic_source'||
        entry.kind==='google_message'&&entry.google_source_state==='current')&&bot.include_evidence));
  const initialTeamUnchanged=!!team&&!!teamDraft&&JSON.stringify(teamDraft)===JSON.stringify(team.configuration);
  useEffect(()=>{if(questionFocus)questionRef.current?.focus();},[questionFocus]);
  useEffect(()=>{
    const request=chiefNotebookFocus.current;
    if(!request||locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)return;
    chiefNotebookFocus.current=null;
    if(request.generation===generation.current&&request.workspace===workspace?.id&&bot?.role==='chief'&&
      !settingsOpen&&!practiceOpen&&panel==='Notebook'&&mobilePanel==='Notebook')notebookRef.current?.focus();
  },[locked,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked,workspace?.id,bot?.role,settingsOpen,practiceOpen,panel,mobilePanel]);
  // Activity is read-only: its own busy navigation lock is excluded here so the
  // final selection can still inspect independently retained unsaved work.
  useUnsavedWork(handoffReviewPending || accessBusy || connectionEditorsLocked || !!pending || !!recoveryOffers.length || recoveryState === "saving" || captureNavigationLocked || note !== latestNote || !!thought || !!evidence || !!source ||
    !!team && !!teamDraft && JSON.stringify(teamDraft) !== JSON.stringify(team.configuration));
  useEffect(()=>{
    if(!inboxNavigation||inboxNavigationConsumed.current===inboxNavigation)return;
    if(inboxNavigation.identity!==authenticated||inboxNavigation.generation!==generation.current||!practiceOpen){setInboxNavigation(null);return;}
    // The source panel has finished its fresh read. Wait for its navigation lock
    // to clear in the parent before applying the ordinary unsaved-work guard.
    if(connectionEditorsLocked||busy||recoveryState==='saving')return;
    inboxNavigationConsumed.current=inboxNavigation;setInboxNavigation(null);
    void open(undefined,undefined,inboxNavigation.selection);
  },[inboxNavigation,authenticated,practiceOpen,connectionEditorsLocked,busy,recoveryState]);
  const latestSourceRevision = Math.max(0, ...(workspace?.entries.filter(e => ["scratchpad", "evidence", "synthetic_source"].includes(e.kind)).map(e => e.revision) ?? []));
  const editorJournal = journal.current?.value;
  const editorWorkspace = workspace?.id, editorScope = team?.recovery_scope;
  const accountScopeReady = !!editorJournal && validRecoveryScope(editorScope) && journal.current?.serverScope === editorScope;
  const accountAccess = useMemo<AccountRecoveryAccess | null | undefined>(() => {
    if (!authenticated) return undefined;
    // A transient parent write failure disables editing, but must not replace this scoped controller.
    if (!accountScopeReady || !editorJournal || !validRecoveryScope(editorScope)) return null;
    return {journal:editorJournal, recoveryScope:editorScope, async authorize() {
      const current = generation.current;
      const latest = await workspaceApi.team(authenticated);
      if (current !== generation.current || requireRecoveryScope(latest) !== editorScope ||
          journal.current?.value !== editorJournal) throw new WorkspaceApiError(403);
    }};
  }, [authenticated, editorJournal, editorScope, accountScopeReady]);
  const activityContext = activityEnabled && authenticated && activityProof?.identity === authenticated &&
    activityProof.journal === editorJournal && activityProof.generation === generation.current &&
    activityProof.context.recovery_scope === editorScope && accountScopeReady ? activityProof.context : null;
  const activityBlocked = locked || connectionEditorsLocked || captureNavigationLocked || captureDraftLocked || recoveryState === "saving";
  const activityLive = useRef({authenticated,editorJournal,editorScope,settingsOpen,practiceOpen,activityContext,activityBlocked,workspace,note});
  activityLive.current = {authenticated,editorJournal,editorScope,settingsOpen,practiceOpen,activityContext,activityBlocked,workspace,note};
  useEffect(() => {
    let cancelled=false;const current=generation.current,controller=new AbortController();
    setActivityProof(null);setActivityContextError('');setActivityContextBusy(false);
    const isCurrent=()=>!cancelled && current===generation.current && activityLive.current.authenticated===authenticated &&
      activityLive.current.editorJournal===editorJournal && activityLive.current.editorScope===editorScope;
    if(activityEnabled && authenticated && accountAccess && editorJournal && validRecoveryScope(editorScope) && settingsOpen && !practiceOpen){
      setActivityContextBusy(true);
      void(async()=>{
        await accountAccess.authorize();if(!isCurrent())return;
        const account=await accountIdentityApi.read(authenticated,controller.signal);if(!isCurrent())return;
        if(account.recovery_scope!==editorScope)throw new WorkspaceApiError(403);
        const context={box_id:account.box_id,owner_id:account.actor_id,recovery_scope:account.recovery_scope};
        if(!validActivityContext(context))throw new WorkspaceApiError(503);
        setActivityProof({identity:authenticated,journal:editorJournal,generation:current,context});
      })().catch(cause=>{if(!isCurrent())return;
        setActivityContextError('AI activity access could not be checked. Your current drafts are retained.');
        if(cause instanceof WorkspaceApiError && [401,403,404,426].includes(cause.status))failure(cause);
      }).finally(()=>{if(isCurrent())setActivityContextBusy(false);});
    }
    return()=>{cancelled=true;controller.abort();};
  },[activityEnabled,authenticated,accountAccess,editorJournal,editorScope,settingsOpen,practiceOpen,connectionGeneration,activityAttempt]);

  async function openActivityEncounter(selection:AiActivitySelection) {
    const auth=authenticated,context=activityContext,active=editorJournal,current=generation.current;
    const origin=workspace?.id;
    if(!auth || !context || !active)throw new WorkspaceApiError(403);
    const navigation=new AbortController();activityNavigation.current?.abort();activityNavigation.current=navigation;
    const sameAccount=()=>current===generation.current && activityLive.current.authenticated===auth &&
      activityLive.current.editorJournal===active && activityLive.current.editorScope===context.recovery_scope;
    const check=()=>{
      if(navigation.signal.aborted)throw new WorkspaceApiError(503);
      if(!sameAccount() || activityLive.current.activityContext!==context)throw new WorkspaceApiError(403);
      try{assertCurrentDesktopSession(auth);}catch{throw new WorkspaceApiError(401);}
      const view=activityLive.current;
      if(!view.settingsOpen || view.practiceOpen || view.activityBlocked || view.workspace?.id!==origin)throw new WorkspaceApiError(503);
      if(selection.workspace_id!==origin && hasUnsavedWork()){
        setError('Save or recover unfinished work before opening another encounter. Your current text and requests are retained.');
        throw new WorkspaceApiError(503);
      }
    };
    const authorize=async()=>{
      check();const latestTeam=await workspaceApi.team(auth,navigation.signal);check();
      if(requireRecoveryScope(latestTeam)!==context.recovery_scope)throw new WorkspaceApiError(403);
      const account=await accountIdentityApi.read(auth,navigation.signal);check();
      if(account.box_id!==context.box_id || account.actor_id!==context.owner_id || account.recovery_scope!==context.recovery_scope)throw new WorkspaceApiError(403);
      return latestTeam;
    };
    const existingEntry=(value:Workspace)=>{
      if(value.id!==selection.workspace_id || value.appointment_id!==selection.appointment_id)throw new WorkspaceApiError(403);
      const entry=value.entries.find(item=>item.id===selection.entry_id);
      if(!entry || !['conversation','handoff_result'].includes(entry.kind))throw new WorkspaceApiError(503);
      return entry;
    };
    try{
      let latestTeam=await authorize();
      let latest=await workspaceApi.read(auth,selection.workspace_id,navigation.signal);check();existingEntry(latest);
      const offers:RecoveryOffer[]=[];
      if(selection.workspace_id!==origin){
        const addresses=[`workspace:${latest.id}`,editorAddress(latest.id,'private-note'),editorAddress(latest.id,'core-note'),editorAddress(latest.id,'transcript')];
        for(const address of addresses){
          const draft=await active.load(address);check();
          if(draft && (draft.kind==='team'||draft.kind==='workspace'))offers.push({address,draft});
        }
        // Device reads confer no authority. Recheck the account and source after them.
        latestTeam=await authorize();latest=await workspaceApi.read(auth,selection.workspace_id,navigation.signal);check();
      }
      const entry=existingEntry(latest);
      const finalAccount=await accountIdentityApi.read(auth,navigation.signal);check();
      if(finalAccount.box_id!==context.box_id || finalAccount.actor_id!==context.owner_id || finalAccount.recovery_scope!==context.recovery_scope)throw new WorkspaceApiError(403);
      const before=currentTeam.current,draft=currentTeamDraft.current;
      if(before && latestTeam.revision<before.revision)throw new WorkspaceApiError(503);
      if(before && draft && latestTeam.revision!==before.revision && JSON.stringify(draft)!==JSON.stringify(before.configuration)){
        setConflict(true);setError('Your saved team changed. Unsaved settings are retained; load the latest team and compare before opening activity.');
        throw new WorkspaceApiError(503);
      }
      const member=latestTeam.members.find(item=>entry.reply?.agent_id
        ? item.agent_id===entry.reply.agent_id && item.role===entry.reply.role
        : !item.instance_id && item.role===entry.reply?.role);
      const address=entry.model_request?.bot.address ?? (member ? botAddress(member) : undefined);
      if(!address || !latestTeam.configuration.bots.some(bot=>botAddress(bot)===address))throw new WorkspaceApiError(503);
      if(selection.workspace_id===origin && latest.revision<(activityLive.current.workspace?.revision??0))throw new WorkspaceApiError(503);
      check();currentTeam.current=latestTeam;setTeam(latestTeam);
      if(!draft || JSON.stringify(draft)===JSON.stringify(before?.configuration)){
        currentTeamDraft.current=structuredClone(latestTeam.configuration);setTeamDraft(currentTeamDraft.current);
      }
      if(selection.workspace_id!==origin){
        setIdentity(auth);setNote(latest.entries.filter(item=>item.kind==='scratchpad').at(-1)?.content??'');
        setThought('');setEvidence('');setSource('');setPreviousModelRequest(null);setModelObservation(null);setReplacementDraft(null);setModelHashes({});
        setObservedCaptureDraft(null);setSelectedSource(null);setCaptureRequest(0);setStage('Before');setPanel('Notebook');
        setRecoveryOffers(previous=>[...previous,...offers]);setRecoveryEpoch(value=>value+1);
      }else{
        const savedBefore=activityLive.current.workspace?.entries.filter(item=>item.kind==='scratchpad').at(-1)?.content??'';
        const savedAfter=latest.entries.filter(item=>item.kind==='scratchpad').at(-1)?.content??'';
        if(savedBefore!==savedAfter && activityLive.current.note!==savedBefore)setConflict(true);
        else if(activityLive.current.note===savedBefore)setNote(savedAfter);
      }
      setWorkspace(latest);setSelected(address);if(entry.reply?.role==='research'||entry.model_request?.bot.role==='research')setSavedResearchChat(true);setSelectedResult(entry.id);setMobilePanel('Conversation');setSettingsOpen(false);setPracticeOpen(false);setError('');
    }catch(cause){
      if(sameAccount() && cause instanceof WorkspaceApiError && [401,403,404,426].includes(cause.status))failure(cause);
      else if(sameAccount() && cause instanceof DraftStoreError)setRecoveryState('failed');
      throw cause;
    }finally{navigation.abort();if(activityNavigation.current===navigation)activityNavigation.current=null;}
  }
  const editorReady = !!editorWorkspace && ["private-note","core-note","transcript"].every(kind =>
    editorJournal?.has(`editor:${editorWorkspace}:${kind}`));
  const editorAccess = useMemo<EditorRecoveryAccess | null | undefined>(() => {
    if (!authenticated) return undefined;
    if (recoveryBlocked || !editorJournal || !editorWorkspace || !editorReady) return null;
    return {journal:editorJournal,workspaceId:editorWorkspace, async authorize() {
      const current = generation.current;
      const team = await workspaceApi.team(authenticated);
      if (current !== generation.current || team.recovery_scope !== editorScope) throw new WorkspaceApiError(403);
      const latest = await workspaceApi.read(authenticated,editorWorkspace);
      if (current !== generation.current || journal.current?.value !== editorJournal) throw new WorkspaceApiError(403);
      const view = recoveryView.current;
      if (view.workspace?.id !== latest.id) throw new WorkspaceApiError(403);
      const saved = view.workspace.entries.filter(e=>e.kind === "scratchpad").at(-1)?.content ?? "";
      if (latest.revision !== view.workspace.revision && view.note !== saved) setConflict(true);
      setWorkspace(latest);
      return latest;
    }, denied(cause) {
      if (cause && typeof cause === "object" && "status" in cause && [401,403,404].includes(Number(cause.status))) {
        failure(new WorkspaceApiError(Number(cause.status)));
      }
    }};
  },[authenticated,editorScope,editorJournal,editorWorkspace,editorReady,recoveryBlocked]);
  const turns = workspace?.entries.filter(e => ["conversation", "handoff_result"].includes(e.kind)
    && (e.model_request?e.model_request.bot.address===selected:e.reply&&(e.reply.agent_id ? e.reply.agent_id === template?.agent_id
      : !bot?.instance_id && e.reply.role === bot?.role))) ?? [];
  const localModelPending=pending?.type==='ask'||pending?.type==='retry'?pending:null;
  const localQuestionRepresented=pending?.type==='ask'&&workspace?.entries.some(entry=>entry.model_request?.request.kind==='conversation'&&
    entry.model_request.request.idempotency_key===pending.body.idempotency_key&&entry.model_request.request_sha256===modelHashes[pending.body.idempotency_key]);
  function retryTeamTask(handoff:DraftHandoff) {
    if(workspace)void save({type:"retry",model_contract:1,origin:"durable_admission_v1",handoffId:handoff.id,
      body:{expected_revision:workspace.revision,previous_attempt_id:handoff.attempt_id,idempotency_key:crypto.randomUUID()}});
  }
  function reviewTeamResult(handoff:DraftHandoff) {
    if(handoffReviewPending||!handoff.result_entry_id)return;
    const reviewable=typeof handoff.result_sha256==='string'&&/^[0-9a-f]{64}$/.test(handoff.result_sha256);
    setReviewHandoffId(reviewable?handoff.id:null);
    setSettingsOpen(false);setPracticeOpen(false);setMobilePanel("Conversation");
    setSelected(handoff.recipient_key??handoff.recipient_role);
    if(handoff.recipient_role==='research')setSavedResearchChat(true);
    setSelectedResult(reviewable?null:handoff.result_entry_id);
  }
  function prepareFreshHandoff(feedback:string) {
    if(!workspace||busy||pending||captureNavigationLocked||captureDraftLocked||recoveryBlocked)return;
    const chief=team?.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
    if(!chief){setError('Enable Chief in Team settings before starting fresh work. Your change request is retained.');return;}
    const fresh='Prepare fresh assignments using the current saved encounter sources.'+(feedback?'\nPlease preserve these requested changes: '+feedback:'');
    setThought(previous=>previous.trim()?previous+'\n\n'+fresh:fresh);
    setSelected(botAddress(chief));setReviewHandoffId(null);setHandoffReviewPending(false);
    setSettingsOpen(false);setPracticeOpen(false);setSelectedResult(null);setMobilePanel('Conversation');
    setQuestionFocus(value=>value+1);
  }
  function receiveGoogleSource(latest:Workspace){
    const current=recoveryView.current;
    if(current.workspace?.id!==latest.id||current.workspace.revision>latest.revision)return;
    const before=current.workspace.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'';
    const after=latest.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'';
    if(before!==after&&current.note!==before)setConflict(true);
    else if(current.note===before)setNote(after);
    setWorkspace(latest);
  }
  async function refreshGoogleVisit(){
    if(!authenticated||!workspace)throw new WorkspaceApiError(403);
    const current=generation.current,id=workspace.id;
    const latest=await workspaceApi.read(authenticated,id);
    if(current!==generation.current||recoveryView.current.workspace?.id!==id)throw new WorkspaceApiError(403);
    receiveGoogleSource(latest);
  }
  async function prepareGoogleChief(source:GoogleMessageSaved){
    if(!authenticated||!workspace||locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)return;
    const current=generation.current,id=workspace.id;setBusy(true);
    try{
      const latest=await workspaceApi.read(authenticated,id);
      if(current!==generation.current||recoveryView.current.workspace?.id!==id)return;
      const entry=latest.entries.find(item=>item.id===source.entry_id&&item.revision===source.entry_revision&&item.kind==='google_message'&&item.google_source_state==='current');
      if(!entry||await vendorSha256(new TextEncoder().encode(entry.content))!==source.content_sha256)throw new WorkspaceApiError(409,'google_message_source_changed');
      const chief=team?.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
      if(!chief)throw new WorkspaceApiError(409,'bot_unavailable');
      receiveGoogleSource(latest);
      const prompt='Review the human-selected email source '+source.entry_id+' and prepare appropriate private assignments. Preserve the existing clinical note; ask me about missing details before proposing outside actions.';
      setThought(previous=>previous.trim()?previous+'\n\n'+prompt:prompt);
      setSelected(botAddress(chief));setSelectedResult(null);setSelectedSource(source.entry_id);
      setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');setQuestionFocus(value=>value+1);
    }catch(cause){if(current===generation.current)failure(cause);}
    finally{if(current===generation.current)setBusy(false);}
  }

  return <EditorRecoveryContext.Provider value={editorAccess}><main className="team-workspace" data-settings-open={settingsOpen && !practiceOpen} data-settings-navigation-locked={connectionNavigationLocked}>
    <aside className="team-sidebar">
      <div className="team-brand"><span className="team-logo" aria-hidden="true">✳</span>cosmas<span>OS</span></div>
      <p className="team-sidebar-label">YOUR WORKSPACE</p>
      <button className={`team-nav-item ${!settingsOpen ? "active" : ""}`} disabled={connectionNavigationLocked} onClick={closeSettings}><span aria-hidden="true">▤</span> Encounter</button>
      <div className="team-roster-heading"><p className="team-sidebar-label">PROVIDER TEAM</p>
        {team && <button className="team-icon-button" disabled={connectionNavigationLocked || busy || !!pending && pending.type !== "team"} onClick={() => void openSettings()} aria-label="Configure Provider Team">⚙</button>}</div>
      <nav aria-label="Provider Team" className="team-roster">{team?.members.map(member => {
        const address = botAddress(member);
        const config = team.configuration.bots.find(b => botAddress(b) === address)!;
        return <button key={address} disabled={connectionNavigationLocked} aria-pressed={selected === address} onClick={() => { setPracticeOpen(false); setSelectedResult(null); setSelected(address); setSettingsOpen(false); setMobilePanel(member.role === "scribe" ? "Notebook" : "Conversation"); if (member.role === "scribe") setPanel("Notebook"); }}>
          <BotAvatar role={member.role} /><span><strong>{config.name}</strong>
            <small><i className={config.enabled && team.revision ? "ready" : "paused"} />{config.retired ? "Retired · history kept" : !team.revision ? "Set up your team" : !config.enabled ? "Paused" : config.blocked_capabilities?.includes("model_answer") ? "AI answers blocked" : "On"}</small></span>
        </button>;
      })}</nav>
      <div className="team-sidebar-bottom"><p><span className="team-local-dot" />{authenticated ? "Signed-in workspace" : "Local workspace"}</p><small>Invented data · private to you</small></div>
    </aside>
    <div className="team-main">
      <header className={`team-topbar${accountControls ? " team-topbar-authenticated" : ""}`}><span>Provider workspace <span className="team-divider">/</span> {practiceOpen ? "Practice work" : settingsOpen ? "Team settings" : "Encounter"}</span>
        <div className="row"><button className="team-subtle" onClick={() => void exitWorkspace(false)}>{onExit ? "Open execution proof" : "Close notebook"}</button>
          {(authenticated || identity) && <button disabled={connectionNavigationLocked || busy || !!pending && pending.type !== "team"} onClick={() => void openSettings()}>Team settings</button>}
          {(authenticated || identity) && <button disabled={connectionNavigationLocked || !practiceOpen && (busy || !!pending || captureDraftLocked || captureNavigationLocked)}
          onClick={() => { setPracticeOpen(!practiceOpen); setPracticeOpened(true); }}>{practiceOpen ? "Back to notebook" : "Practice work"}</button>}
          <span className="team-pill">Synthetic preview</span>{accountControls}</div></header>
      {confirmCaptureExit && <div className="team-recovery" role="status">
        <p>There is unsaved or unconfirmed work. Closing can lose unsaved text. Work already submitted may still finish; reopen to check it.</p>
        <button onClick={() => setConfirmCaptureExit(false)}>Keep editing</button>
        <button disabled={busy} onClick={() => void exitWorkspace(true)}>Close anyway</button>
      </div>}
      {recoveryOffers.map(offer => <div className="team-recovery" role="status" key={offer.address}>
        <p>{isFollowUpRecovery(offer.draft) ? "A follow-up request was interrupted. Its exact action is retained on this device." : offer.draft.kind === "workspace" && offer.draft.pending?.type === "note" ? "A private note save was interrupted. Its exact request is retained on this device." : <>A {offer.draft.kind === "team" ? "team settings" : "notebook"} draft is saved on this device.</>}
          {offer.draft.pending ? " Its last save is unconfirmed. Restore it and retry the same request before making changes." : " Restore it to compare with the latest saved version, or discard this local draft."}
          {" Restoring replaces the current editor text."}</p>
        <button disabled={busy || !!pending} onClick={() => void restoreDraft(offer)}>{isFollowUpRecovery(offer.draft) ? "Restore follow-up request" : offer.draft.kind === "workspace" && offer.draft.pending?.type === "note" ? "Restore private note save" : `Restore ${offer.draft.kind === "team" ? "team" : "notebook"} draft`}</button>
        {!offer.draft.pending && <button disabled={busy || !!pending} onClick={() => void discardRecovered(offer)}>Discard local draft</button>}
      </div>)}
      {recoveryState === "failed" && <div className="team-recovery" role="alert"><p>This device's draft storage could not be checked. Existing drafts are retained. Recheck recovery before editing or saving.</p>
        <button disabled={busy} onClick={() => void recheckRecovery()}>Recheck draft recovery</button></div>}
      {recoveryState === "saving" && <p className="team-fine" role="status">Saving notebook and team drafts on this device…</p>}
      {recoveryState === "saved" && <p className="team-fine">Working copies saved on this device. Save a note version separately for review.</p>}
      {practiceOpen && error && <div className="team-banner error" role="alert">{error}</div>}
      {practiceOpened && (authenticated || identity) && <AccountRecoveryContext.Provider value={accountAccess}><fieldset disabled={recoveryBlocked} hidden={!practiceOpen} style={{border:0,padding:0,margin:0,minWidth:0}}><PracticeHub identity={(authenticated || identity)!} onDenied={failure} onBusyChange={reportInboxBusy} onDraftInbox={authenticated?selection=>{setInboxNavigation({selection,identity:authenticated,generation:generation.current});}:undefined}><PracticeWork identity={(authenticated || identity)!}
        onChanged={() => { if (workspace) setConflict(true); }} onAccessLost={failure} />
        {ROUTINES_BUILD && authenticated && team && team.revision > 0 && <WorkRoutines identity={authenticated} team={team} onAccessLost={failure} onRefreshTeam={refreshRoutineTeam} />}
        {authenticated && team?.revision === 0 && <div className="team-banner"><p>Set up your private team to schedule work briefs.</p><button onClick={() => void openSettings()}>Set up your team</button></div>}</PracticeHub></fieldset></AccountRecoveryContext.Provider>}
      <div hidden={practiceOpen}>
      {error && <div className="team-banner error" role="alert">{error}</div>}
      {message && <div className="team-banner" role="status">{message}</div>}
      {conflict && <div className="team-recovery"><p>Your text has not been overwritten. Load the latest history and team, compare changes, then save a new revision.</p>
        <button disabled={busy} onClick={() => void refresh()}>Load latest — keep my text</button></div>}
      {pending && !localModelPending && !busy && <div className="team-recovery"><p>The previous save is unconfirmed. Retry before editing; the same request will be reused.</p>
        <button disabled={recoveryBlocked} onClick={() => void save(pending)}>Retry same save</button></div>}
      {localModelPending&&<section className="team-recovery" aria-label="Unconfirmed model request"><p>The retained request is unconfirmed. Check its saved result; checking never starts another model call.</p>
        {localModelPending.type==='ask'&&localModelPending.body.research_analysis&&<details className="research-model-selection"><summary>Retained selected-source request</summary><p>{localModelPending.body.content}</p><p>Only this exact question and saved public-source selection belong to this key.</p><ul>{localModelPending.body.research_analysis.entries.map(anchor=><li key={anchor.entry_id}>Saved packet revision {anchor.entry_revision} · {anchor.entry_id}<small>Lookup {anchor.run_id} · save proof {anchor.save_request_sha256}</small></li>)}</ul></details>}
        {localModelPending.type==='ask'&&localModelPending.body.session_prep_analysis&&<details><summary>Retained Session Prep question</summary><p>{localModelPending.body.content}</p><p>This request includes the selected Session Prep brief, version {localModelPending.body.session_prep_analysis.brief_version}. Checking its result retains that exact selection.</p></details>}
        {localModelPending.type==='ask'&&localModelPending.body.membership_analysis&&<details><summary>Retained Membership/Billing review request</summary><p>{localModelPending.body.content}</p><p>This exact selected {localModelPending.body.membership_analysis.kind} record and consent belong to the saved request. A new review requires current evidence and fresh consent.</p></details>}
        {localModelPending.type==='ask'&&localModelPending.body.inbox_analysis&&<details><summary>Retained Inbox draft request</summary><p>{localModelPending.body.content}</p><p>Message {localModelPending.body.inbox_analysis.item_id}, source {localModelPending.body.inbox_analysis.source_id}, local version {localModelPending.body.inbox_analysis.item_version}. This exact selection and consent belong to the saved request.</p></details>}
        {modelObservation&&<p>Last verified result: {modelObservation.receipt.outcome.replaceAll('_',' ')}. {modelObservation.receipt.outcome==='not_found'?(localModelPending.origin==='durable_admission_v1'?
          'No admission for this key was recorded as of the read. Sending this saved request reuses the same key and body.':'The earlier provider outcome is unknown. An absent legacy record does not prove it was never sent.'):
          'An unknown or failed outcome does not establish remote cancellation or refund the attempt.'}</p>}
        <button disabled={busy||recoveryBlocked} onClick={()=>void saveModel(localModelPending,'resolve')}>Check saved result</button>
        {modelObservation?.receipt.outcome==='not_found'&&localModelPending.origin==='durable_admission_v1'&&<button disabled={busy||recoveryBlocked}
          onClick={()=>void saveModel(localModelPending,'submit')}>Send this saved request</button>}
        {modelObservation&&!(localModelPending.type==='ask'&&(localModelPending.body.research_analysis||localModelPending.body.inbox_analysis||localModelPending.body.membership_analysis||localModelPending.body.session_prep_analysis))&&['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome)&&<button disabled={busy||recoveryBlocked} onClick={()=>setReplacementDraft({
          content:localModelPending.type==='ask'?localModelPending.body.content:'',role:localModelPending.type==='ask'?localModelPending.body.role:selected,acknowledged:false})}>Start another attempt</button>}
        {localModelPending.type==='ask'&&(localModelPending.body.research_analysis||localModelPending.body.inbox_analysis||localModelPending.body.membership_analysis||localModelPending.body.session_prep_analysis)&&modelObservation&&['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome)&&<div className="research-model-recovery">
          <label><input type="checkbox" checked={replacementDraft?.acknowledged??false} disabled={busy||recoveryBlocked} onChange={event=>setReplacementDraft({content:localModelPending.body.content,role:localModelPending.body.role,acknowledged:event.target.checked})}/>I understand the earlier model outcome may remain unconfirmed.</label>
          <button disabled={busy||recoveryBlocked||!replacementDraft?.acknowledged} onClick={()=>void prepareNewSelectedAnalysis()}>Review sources for a new request</button>
        </div>}
        {replacementDraft&&!(localModelPending.type==='ask'&&(localModelPending.body.research_analysis||localModelPending.body.inbox_analysis||localModelPending.body.membership_analysis||localModelPending.body.session_prep_analysis))&&<div><p>A new attempt uses a new key and the current saved context. The prior exact binding is retained in the local transition record; this does not resolve an earlier uncertain provider outcome.</p>
          {localModelPending.type==='ask'&&<><label>Bot for new attempt<select value={replacementDraft.role} disabled={busy} onChange={e=>setReplacementDraft({...replacementDraft,role:e.target.value})}>
            {team?.configuration.bots.filter(b=>!b.retired&&b.enabled).map(b=><option key={botAddress(b)} value={botAddress(b)}>{b.name}</option>)}</select></label>
            <label>Review new question<textarea maxLength={4000} value={replacementDraft.content} disabled={busy} onChange={e=>setReplacementDraft({...replacementDraft,content:e.target.value})}/></label></>}
          {localModelPending.origin!=='durable_admission_v1'&&<label><input type="checkbox" checked={replacementDraft.acknowledged} disabled={busy} onChange={e=>setReplacementDraft({...replacementDraft,acknowledged:e.target.checked})}/>
            I understand the earlier provider outcome is unknown and this explicitly supersedes the local request.</label>}
          <button disabled={busy||recoveryBlocked||localModelPending.origin!=='durable_admission_v1'&&!replacementDraft.acknowledged||localModelPending.type==='ask'&&!replacementDraft.content.trim()}
            onClick={()=>void replaceModelRequest()}>Send new attempt</button><button disabled={busy} onClick={()=>setReplacementDraft(null)}>Keep previous request</button></div>}
      </section>}
      {!localModelPending&&previousModelRequest&&<details className="team-recovery"><summary>Previous request retained as superseded history</summary>
        <p>The previous {previousModelRequest.operation.type==='ask'?'question':'draft retry'} was last checked as {previousModelRequest.outcome.replaceAll('_',' ')} at {previousModelRequest.observed_at}. Its original body and binding remain on this device. A later request does not resolve that earlier provider uncertainty.</p></details>}
      {activityEnabled && settingsOpen && activityContextBusy && <p className="team-fine" role="status">Checking optional AI activity access…</p>}
      {activityEnabled && settingsOpen && activityContextError && <div className="team-banner error" role="alert"><p>{activityContextError}</p><button disabled={locked || activityContextBusy} onClick={()=>setActivityAttempt(value=>value+1)}>Recheck AI activity access</button></div>}
      {(authenticated || identity) && <SettingsHub key={generation.current} open={settingsOpen} navigationLocked={connectionNavigationLocked}
        onOpenMessagingWork={authenticated?openMessagingWork:undefined} messagingWorkLabel={workspace?'Open fax work for this visit':'Choose a visit for fax work'}
        messagingWorkBlocked={locked||captureNavigationLocked||captureDraftLocked}
        initialScreen={settingsEntry} guidedConnections={CONNECTION_ONBOARDING_BUILD} connectionIdentity={authenticated ?? undefined} onConnectionAccessLost={failure}
        members={authenticated&&practiceAccess?<PracticeAccessPanel identity={authenticated} access={practiceAccess} onBusyChange={reportAccessBusy}/>:undefined}
        google={GOOGLE_CONNECTION_BUILD&&authenticated?<AccountRecoveryContext.Provider value={accountAccess}>
          <GoogleConnectionPanel identity={authenticated} onBusyChange={reportGoogleBusy} onAuthenticationLost={failure}
            messageWorkLocked={locked||captureNavigationLocked||captureDraftLocked||connectionLocks.googleMessages}
            onOpenMessageWork={GOOGLE_MESSAGE_BUILD?()=>setGoogleMessageOpen(true):undefined}
            messageWork={GOOGLE_MESSAGE_BUILD&&googleMessageOpen?controls=><GoogleMessageMount identity={authenticated}
              workspace={workspace?{id:workspace.id,label:workspace.label,revision:workspace.revision}:null}
              currentSources={workspace?.entries.filter(entry=>entry.kind==='google_message'&&!!entry.google_source_state)
                .map(entry=>({entry_id:entry.id,state:entry.google_source_state!}))}
              locked={locked||captureNavigationLocked||captureDraftLocked||connectionLocks.google}
              recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked||connectionLocks.google}
              onBusyChange={reportGoogleMessageBusy} onAuthenticationLost={failure} onSaved={receiveGoogleSource}
              onRequestFullMailAccess={controls.requestFullMailAccess} fullMailAccessBusy={controls.fullMailAccessBusy}
              onRefreshVisit={refreshGoogleVisit} onAskChief={source=>void prepareGoogleChief(source)}
              onChooseVisit={()=>{if(locked||connectionNavigationLocked)return;googleVisitSelection.current=true;setSettingsOpen(false);void loadEncounters();}}/>:undefined}/>
        </AccountRecoveryContext.Provider>:undefined}
        microsoft={MICROSOFT_CONNECTION_BUILD&&authenticated?<MicrosoftConnectionPanel identity={authenticated} onBusyChange={reportMicrosoftBusy} onAuthenticationLost={failure}/>:undefined}
        scheduling={SCHEDULING_LOGIN_BUILD&&authenticated?<SchedulingConnectionPanel identity={authenticated} onBusyChange={reportSchedulingBusy} onAuthenticationLost={failure}/>:undefined}
        core={CORE_CONNECTION_BUILD&&authenticated?<CoreConnectionPanel identity={authenticated} onBusyChange={reportCoreBusy} onAuthenticationLost={failure} openBlocked={locked||captureNavigationLocked||captureDraftLocked} onOpenNotebook={command=>open(undefined,command)}/>:undefined}
        teamSummary={team?.revision ? `${team.configuration.bots.filter(bot => !bot.retired).length} coworkers · Names, instructions & preferences` : 'Choose your coworkers and make them yours'}
        teamDirty={!!team && !!teamDraft && JSON.stringify(teamDraft) !== JSON.stringify(team.configuration)} onClose={closeSettings}
        team={team && teamDraft ? <TeamConfigurationFlow key={setupEpoch} identity={(authenticated || identity)!}
          team={team} draft={teamDraft} setDraft={setTeamDraft} selected={selected} setSelected={setSelected}
          locked={activityContext ? activityBlocked : locked} setupAvailable={setupProjection?.team_revision === team.revision}
          activity={activityContext && settingsOpen && !practiceOpen ? {context:activityContext,onOpenEncounter:openActivityEncounter,onBusyChange:reportActivityBusy} : undefined}
          reviewRequired={setupChange(team.configuration, teamDraft) && !(setupApproval?.revision === team.revision && setupApproval.configurationKey === JSON.stringify(teamDraft))}
          onCurrentTeam={receiveSetupTeam} onReviewChange={setSetupApproval} onAccessLost={failure}
          onSave={saveTeam} onClose={closeSettings} onRefresh={() => void refresh()} /> : <div className="team-banner" role="status">
          {busy ? "Loading your private team…" : <button onClick={() => void openSettings()}>Retry loading team</button>}</div>}
        messaging={VENDOR_SETUP_BUILD ? <AccountRecoveryContext.Provider value={accountAccess}>
          <fieldset disabled={locked || recoveryBlocked} style={{border:0,padding:0,margin:0,minWidth:0}}>
            <VendorSetupMount presentation="focused" onBusyChange={reportMessagingBusy} identity={(authenticated || identity)!} onDenied={failure} />
          </fieldset>
        </AccountRecoveryContext.Provider> : undefined}
        payments={FINANCE_SETUP_BUILD ? <AccountRecoveryContext.Provider value={accountAccess}>
          <fieldset disabled={locked || recoveryBlocked} style={{border:0,padding:0,margin:0,minWidth:0}}>
            <FinanceSetupMount presentation="focused" onBusyChange={reportPaymentsBusy} identity={(authenticated || identity)!} onDenied={failure} />
          </fieldset>
        </AccountRecoveryContext.Provider> : undefined}
        portals={PORTAL_SETUP_BUILD ? <AccountRecoveryContext.Provider value={accountAccess}>
          <fieldset disabled={locked || recoveryBlocked} style={{border:0,padding:0,margin:0,minWidth:0}}>
            <PortalSetupMount presentation="focused" onBusyChange={reportPortalsBusy} identity={(authenticated || identity)!} onDenied={failure} />
          </fieldset>
        </AccountRecoveryContext.Provider> : undefined}
      />}
      {!workspace ? <section hidden={settingsOpen} className={`team-welcome${encounters ? " team-welcome-choosing" : ""}`}><p className="team-kicker">{encounters ? "YOUR VISITS" : "YOUR PRACTICE"}</p>
        <h1>{researchEntry ? "Choose a visit for Research" : entryIntent==="fax" ? "Choose a visit for fax work" : entryIntent==="chief" ? "Choose a visit for Chief" : entryIntent==="record" ? "Choose the visit to record" : entryIntent==="recording" ? "Choose the recorded visit" : encounters ? "Your encounters" : "Ready for your next visit?"}</h1><p>{researchEntry ? "Keep trial results and source evidence with the right encounter." : entryIntent==='fax' ? "Keep the fax document, recipient and delivery status with the right visit." : entryIntent==='chief' ? "Start with typed notes and prepare your next step." : encounters ? "Record a visit, or open its notes." : "Start with notes, record a conversation, or pick up an existing visit."}</p>
        <WelcomeActions showConnections={!!authenticated&&CONNECTION_ONBOARDING_BUILD} compact={!!encounters}
          connectionsDisabled={busy||!!pending||connectionNavigationLocked} encounterDisabled={busy||!!pending}
          encounterLabel={busy?'Loading…':encounters?'Refresh encounters':authenticated?'Choose an encounter':'Open synthetic encounter'}
          onConnections={()=>void openSettings('connections')} onEncounter={()=>{setResearchEntry(false);setEntryIntent(null);void (authenticated?loadEncounters():open());}}
          onRecord={authenticated?()=>{setResearchEntry(false);setEntryIntent("record");void loadEncounters();}:undefined}
          onRecording={authenticated?()=>{setResearchEntry(false);setEntryIntent("recording");void loadEncounters();}:undefined}
          onChief={authenticated?()=>{setResearchEntry(false);setEntryIntent('chief');void loadEncounters();}:undefined}
          onResearch={authenticated?()=>{setResearchEntry(true);setEntryIntent(null);void loadEncounters();}:undefined}/>
        {!encounters && <div className="team-welcome-roles"><BotAvatar role="scribe" large /><BotAvatar role="visit_prep" large /><BotAvatar role="follow_up" large /><BotAvatar role="chief" large /><BotAvatar role="research" large /><span>Scribe · Visit Prep · Follow-up · Chief · Research</span></div>}
        {authenticated && encounters && <section aria-label="Available encounters" className="team-encounter-picker">
          {CORE_CONNECTION_BUILD && <p><button className="team-subtle"
            disabled={busy || !!pending || connectionNavigationLocked} onClick={() => void openSettings('core')}><span aria-hidden="true">🗓️ </span>Find another visit</button></p>}
          {encounters.length ? encounters.map(encounter => <article className="team-encounter-row" key={encounter.appointment_id}>
            <button className="team-encounter-option" disabled={busy || !!pending} onClick={() => void open(encounter.appointment_id)}>
              <strong>{encounter.label}</strong><span>{entryIntent==="fax"?"Open fax work":entryIntent==="chief"?"Open notes with Chief":entryIntent==="record"?"Continue to recording consent":entryIntent==="recording"?"Review the existing recording":encounter.workspace_id ? "Open saved notes" : "Open visit"}</span>
            </button>
            {CAPTURE_WORKSPACE_BUILD && (!team || team.capture?.enabled) && <button className="team-primary team-record-visit" aria-label={`Record ${encounter.label}`}
              disabled={busy || !!pending} onClick={() => void open(encounter.appointment_id, undefined, undefined, true)}><span aria-hidden="true">🎙️ </span>Record visit</button>}
          </article>) : <p>No confirmed encounters are available for this account. Connect your practice to find its appointments.</p>}
        </section>}
        <p className="team-fine">Notes and private drafts do not need email or calendar setup.</p>
      </section> : <>
        <section hidden={settingsOpen} className="team-encounter-heading"><div><p className="team-kicker">ENCOUNTER NOTEBOOK</p><h1>{workspace.label}</h1>
          <p>Private encounter notebook</p>
          <button className="team-subtle" disabled={busy || !!pending || handoffReviewPending} onClick={() => void refresh()}>Refresh encounter</button>
          {import.meta.env.VITE_COSMANEURA_RECORD_ENABLED === "true" && authenticated && team?.capture?.enabled &&
            <CoreRecordLink key={workspace.id} identity={authenticated} workspaceId={workspace.id}
              locked={busy || !!pending || captureNavigationLocked || recoveryBlocked} onDenied={failure} />}</div>
          {bot?.role !== "scribe" && <nav aria-label="Encounter stage" className="team-stages">{["Before", "During", "After"].map(value => <button key={value} aria-pressed={stage === value} onClick={() => { setStage(value); if (value === "After") { setPanel("Review"); setMobilePanel("Review"); } }}>{value}</button>)}</nav>}
        </section>
        {team?.revision===0&&<div hidden={settingsOpen} className="team-initial-action"><InitialTeamAction
          names={team.configuration.bots.filter(item=>item.enabled&&!item.retired).map(item=>item.name)}
          locked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} unchanged={initialTeamUnchanged}
          onUse={()=>{if(initialTeamUnchanged&&!locked&&!connectionNavigationLocked&&!captureNavigationLocked&&!captureDraftLocked)saveTeam();}}
          onSettings={()=>void openSettings()}/></div>}
        {CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled &&
          <CapturePanel key={workspace.id} workspaceId={workspace.id} identity={authenticated} encounterLabel={workspace.label}
            notesEnabled={CAPTURE_NOTES_BUILD && team.capture.notes_enabled === true} onDraftLock={setCaptureDraftLocked} onNavigationLock={setCaptureNavigationLocked}
            correctionsEnabled={CAPTURE_CORRECTIONS_BUILD && team.capture.corrections_enabled === true}
            scratchpad={workspace.entries.filter(e => e.kind === "scratchpad").at(-1)} notebookDirty={note !== latestNote}
            taskBot={scribe ? {selection: {address: botAddress(scribe), team_revision: team.revision},
              name: scribe.name, enabled: scribe.enabled && team.revision > 0, includeNotebook: scribe.include_notebook} : undefined}
            openRequest={locked || settingsOpen || practiceOpen ? 0 : captureRequest} preferencesScope={team.recovery_scope}
            onNotebook={() => { setPanel("Notebook"); setMobilePanel("Notebook"); }}
            onReviewDraft={useCoreDraft} onCurrentDraft={setObservedCaptureDraft} reviewLocked={locked} />}
        {CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled && !settingsOpen && !practiceOpen &&
          <ExistingScribeSourcePanel key={`scribe-source:${workspace.id}`} workspace={workspace} identity={authenticated}
            openRequest={settingsOpen||practiceOpen?0:recordingSourceRequest}
            locked={baseLocked || captureNavigationLocked || captureDraftLocked || note !== latestNote}
            onBusyChange={setScribeSourceBusy} onAccessLost={failure} onSaved={latest=>{
              setWorkspace(previous=>previous?.id===latest.id&&previous.revision<=latest.revision?latest:previous);
              if(latest.id===workspace.id&&latest.revision>=workspace.revision&&note===latestNote)
                setNote(latest.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'');
              setPanel('Sources');setMobilePanel('Sources');
            }}/>}
        {bot?.role === "scribe" && !(CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled) && !settingsOpen &&
          <section className="capture-panel" aria-label="Scribe recording"><header>
            <div className="capture-heading"><h2><span aria-hidden="true">🎙️</span> {bot.name} recording</h2>
              <p className="capture-description">Record a visit here and review Scribe’s draft afterward.</p>
              <div className="capture-state" role="status">Recording needs a connection</div>
              <p className="capture-description">Connect Scribe for this practice to use the recorder.</p></div>
            <button className="team-primary capture-record" disabled={locked || connectionNavigationLocked} onClick={() => void openSettings('connections')}>Set up recording</button>
          </header></section>}
        <div hidden={settingsOpen}>
        <TeamWorkPanel handoffs={workspace.handoffs??[]} entries={workspace.entries} locked={locked} onRetry={retryTeamTask} onReview={reviewTeamResult}/>
        {identity && reviewHandoffId && workspace.handoffs?.some(h=>h.id===reviewHandoffId) &&
          <HandoffReviewPanel key={`${workspace.id}:${reviewHandoffId}`} workspace={workspace}
            handoff={workspace.handoffs.find(h=>h.id===reviewHandoffId)!} identity={identity}
            locked={actionLocked||captureNavigationLocked||captureDraftLocked}
            recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked}
            onPendingChange={setHandoffReviewPending}
            onAccessLost={failure} onRefresh={refreshHandoffReview}
            onFreshAssignment={prepareFreshHandoff}
            onSaved={latest=>setWorkspace(previous=>previous?.id===latest.id&&previous.revision<=latest.revision?latest:previous)}
            onClose={()=>{if(!handoffReviewPending)setReviewHandoffId(null);}}
            onRevisionPrepared={id=>{setReviewHandoffId(id);setHandoffReviewPending(false);}}/>}
        <nav className={`team-mobile-tabs${bot?.role === "scribe" ? " team-scribe-tabs" : ""}`} aria-label={bot?.role === "scribe" ? "Visit view" : "Mobile encounter view"}>
          {(bot?.role === "scribe" ? ["Notebook", "Conversation", "Review"] : ["Conversation", "Notebook", "Sources", "Review", "Work"]).map(value => <button key={value} aria-pressed={mobilePanel === value}
            onClick={() => { setMobilePanel(value); if (value !== "Conversation") setPanel(value); }}>{bot?.role === "scribe" ? ({Notebook:"Visit notes",Conversation:"Ask Scribe",Review:"Review note"})[value] : value}</button>)}
          {bot?.role === "scribe" && <details className="team-visit-more"><summary>More</summary><div>{["Sources", "Work"].map(value => <button key={value} aria-pressed={mobilePanel === value}
            onClick={event => {setPanel(value); setMobilePanel(value); const menu = event.currentTarget.closest('details'); if (menu) menu.open = false;}}>{value === "Sources" ? "Saved sources" : "Follow-up work"}</button>)}</div></details>}
        </nav>
        <div className="team-content" data-mobile-panel={mobilePanel} data-scribe-focus={bot?.role === "scribe" ? "true" : undefined}><section className="team-conversation" aria-label="Encounter conversation">
          <header className="team-conversation-header"><BotAvatar role={bot?.role ?? "scribe"}
            active={busy && pending?.type === "ask" && pending.body.role === selected||workspace.entries.some(e=>modelActive(e)&&e.model_request?.bot.address===selected)}
            enabled={!!bot?.enabled && !bot.retired && !!team?.revision && !settingsOpen && !practiceOpen} />
            <div><h2>{bot?.name ?? "Your team"}</h2><p>{template?.description}</p></div>
            <button className="team-subtle" onClick={() => setSettingsOpen(true)}>Skills & settings</button></header>
          {prepAvailable && bot && authenticated && team &&
            <SessionPrepPanel key={prepEpoch} workspaceId={workspace.id} identity={authenticated}
              bot={{address: botAddress(bot), team_revision: team.revision}}
              enabled={bot.enabled && bot.include_evidence && team.revision > 0} locked={locked} onAccessLost={failure}
              onBriefViewed={at=>setBriefViewed(at?{workspace:workspace.id,owner:authenticated,teamRevision:team.revision,at}:null)}
              selected={!!selectedPrep} onSelect={team.llm.enabled&&!bot.blocked_capabilities?.includes("model_answer")?
                selection=>setPrepSelection(selection?{scope:prepScope,selection}:null):undefined} />}
          {bot && supportsSkill(bot, "encounter_prep") && ENCOUNTER_PREP_BUILD && authenticated && team?.capture?.prep_enabled &&
            <details className={prepAvailable?"team-additional-prep":undefined} open={prepAvailable?undefined:true}>
            <summary hidden={!prepAvailable}>Other saved visit context</summary><EncounterPrepPanel workspaceId={workspace.id} identity={authenticated}
              bot={{address: botAddress(bot), team_revision: team.revision}} name={bot.name}
              enabled={bot.enabled && bot.include_evidence && team.revision > 0} locked={locked}
              entryRevision={workspace.revision} workEnabled={team.capture.prep_work_enabled===true} onAccessLost={failure}
              onChanged={revision=>{if(revision!==workspace.revision){setConflict(true);void refresh();}}} /></details>}
          {bot && supportsSkill(bot, "calendar_availability") && SCHEDULING_BUILD && authenticated && team && (team.scheduling?.enabled || APPOINTMENTS_BUILD) &&
            <SchedulingPanel workspaceId={workspace.id} identity={authenticated}
              bot={{address: botAddress(bot), team_revision: team.revision}} name={bot.name}
              enabled={!!team.scheduling?.enabled && bot.enabled && bot.include_evidence && team.revision > 0} locked={locked} onAccessLost={failure} />}
          {bot&&supportsSkill(bot,"membership_review")&&authenticated&&team&&<MembershipAnalysisPanel
            key={`${workspace.id}:${workspace.revision}:${team.revision}:${selected}`} identity={authenticated} workspaceId={workspace.id} workspaceRevision={workspace.revision}
            teamRevision={team.revision} botAddress={botAddress(bot)} enabled={bot.enabled&&!bot.retired&&team.revision>0}
            modelEnabled={team.llm.enabled&&!bot.blocked_capabilities?.includes('model_answer')} locked={locked||captureNavigationLocked||captureDraftLocked}
            onDenied={failure} onOpenWork={()=>{if(locked||captureNavigationLocked||captureDraftLocked)return;setPanel("Work");setMobilePanel("Work");}}
            onSubmit={async body=>{if(locked||captureNavigationLocked||captureDraftLocked||!body.membership_analysis||body.expected_revision!==workspace.revision||body.team_revision!==team.revision||body.role!==botAddress(bot))return;
              await saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body},'submit');}}/>}
          {inboxSelection&&inboxSelection.workspace_id===workspace.id&&authenticated&&team&&<InboxAnalysisPanel
            key={`${workspace.id}:${inboxSelection.analysis.source_id}:${inboxSelection.analysis.item_version}:${team.revision}:${workspace.revision}:${selected}`}
            selection={inboxSelection} workspace={workspace} team={team} selected={selected} locked={locked||captureNavigationLocked||captureDraftLocked}
            onSelect={setSelected} onClose={()=>setInboxSelection(null)} onSetup={()=>void openSettings()}
            onSubmit={async body=>{if(locked||captureNavigationLocked||captureDraftLocked||!body.inbox_analysis||body.expected_revision!==workspace.revision||body.team_revision!==team.revision)return;
              await saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body},'submit');}}/>}
          {bot?.role === "research" && <>{authenticated && team ? <ResearchWorkspace key={`${workspace.id}:${botAddress(bot)}`}
            identity={authenticated} workspaceId={workspace.id} workspaceRevision={workspace.revision} bot={{address:botAddress(bot),team_revision:team.revision}}
            enabled={bot.enabled&&!bot.retired&&team.revision>0} locked={locked||captureNavigationLocked||captureDraftLocked}
            analysis={{workspace,model:team.llm,modelBlocked:bot.blocked_capabilities?.includes('model_answer'),onSubmit:async body=>{
              if(locked||captureNavigationLocked||captureDraftLocked||!team.llm.enabled||!bot.enabled||bot.retired||bot.blocked_capabilities?.includes('model_answer')||body.role!==botAddress(bot)||body.expected_revision!==workspace.revision||body.team_revision!==team.revision||!body.research_analysis)return;
              setSavedResearchChat(true);await saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body},'submit');
            }}}
            onDenied={failure} onChanged={revision=>{if(revision!==workspace.revision){setConflict(true);void refresh();}}}/>
            : <p className="research-status">Sign in to use private Research settings and check public source connections.</p>}
            <button className="team-subtle" aria-expanded={savedResearchChat} onClick={()=>setSavedResearchChat(value=>!value)}>Saved encounter conversation</button></>}
          <div hidden={bot?.role==='research'&&!savedResearchChat || visitPrepReader&&!turns.length&&pending?.type!=='ask'} className="team-messages" aria-live="polite" aria-relevant="additions">
            {!turns.length && !visitPrepReader && <div className="team-conversation-empty"><BotAvatar role={bot?.role ?? "scribe"} large greeting={!busy}
              enabled={!!bot?.enabled && !bot.retired && !!team?.revision && !settingsOpen && !practiceOpen} />
              <h3>{stage === "Before" ? "A clear start to the visit" : stage === "During" ? "Space to think and take notes" : "Keep the next step in view"}</h3>
              <p>{team?.llm.enabled ? "Ask a question, organize your notes, or think through the next step. Your team works from the saved context you choose." : "Review saved sources with your team. Advanced skills will connect here as their services become ready."}</p>
              {bot?.role!=='chief'&&<button disabled={locked || !team?.revision || !bot?.enabled} onClick={() => ask(template?.prompt)}>{template?.prompt ?? "Review this encounter"}<span aria-hidden="true"> ↗</span></button>}</div>}
            {turns.map(entry => <div className="team-turn" key={entry.id} id={`turn-${entry.id}`} tabIndex={-1}><article className="team-human-message"><small>{entry.kind === "handoff_result" ? "Brief from Chief" : "You"}</small><p>{entry.content}</p></article>
              {entry.reply && <article className="team-bot-message"><header><BotAvatar role={entry.reply.role} />
                <strong>{entry.reply.agent_name}</strong><span className="team-pill">{entry.reply.backend === "azure_gpt41_work_status_v1" ? "Saved work status" : entry.reply.backend === "azure_gpt41_unavailable" ? "GPT-4.1 unavailable" : entry.reply.backend.startsWith("azure_gpt41") ? "GPT-4.1" : "Local review"}</span>{(entry.kind === "handoff_result" || entry.model_request?.request.kind==='conversation'&&(entry.model_request.request.inbox_analysis||entry.model_request.request.membership_analysis)) && <span className="team-pill pending">Unreviewed draft</span>}</header>
                <p>{entry.reply.content}</p><div className="team-citations">{entry.reply.citations.map((citation, index) => ["membership_work","payment_work"].includes(citation.kind)?<button key={citation.entry_id} onClick={()=>{setPanel("Work");setMobilePanel("Work");}}>[{index+1}] {citation.label} · r{citation.revision}</button>:["inbox_message","inbox_triage","session_prep"].includes(citation.kind)?<span key={citation.entry_id}>[{index+1}] {citation.label} · r{citation.revision}</span>:<button key={citation.entry_id}
                  onClick={() => { setPanel("Sources"); setMobilePanel("Sources"); setSelectedSource(citation.entry_id); }}>[{index + 1}] {citation.label} <span>r{citation.revision}</span></button>)}</div>
                <small className="team-fine">Context through revision {entry.reply.context_revision}{latestSourceRevision > entry.reply.context_revision ? " · Newer sources available — ask again to review them" : ""}</small>
              </article>}
              {!entry.reply&&entry.model_request&&<article className="team-bot-message"><header><BotAvatar role={entry.model_request.bot.role} active={modelActive(entry)}/>
                <strong>{entry.model_request.bot.name}</strong></header><p>{modelStateLabel(entry.model_request.admission.state)}</p>
                <p className="team-fine">A saved request is not a completed draft or clinical evidence.</p>
                {entry.model_request.request.kind==='conversation'&&<button disabled={busy||recoveryBlocked} onClick={()=>void checkEntryResult(entry)}>Check saved result</button>}</article>}

            </div>)}
            {pending?.type === "ask" && !localQuestionRepresented && <div className="team-turn"><article className="team-human-message"><small>You · {busy?'request in progress':'unconfirmed request'}</small><p>{pending.body.content}</p></article>
              {busy && <p className="team-thinking" role="status">{team?.configuration.bots.find(b => botAddress(b) === pending.body.role)?.name} is {team?.llm.enabled ? "thinking" : "reviewing"}…</p>}</div>}
            <div ref={conversationEnd} />
          </div>
          <div hidden={bot?.role==='research'&&!savedResearchChat} className="team-composer-wrap">
            {bot?.role==='chief'&&!!team?.revision&&<ChiefStartActions locked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked||!bot.enabled||!!bot.retired}
              modelEnabled={team.llm.enabled&&!bot.blocked_capabilities?.includes('model_answer')} sourceAllowed={bot.include_notebook||bot.include_evidence}
              hasSavedContext={chiefSavedContext} notesDirty={note!==latestNote} hasQuestion={!!thought.trim()}
              canDelegate={!bot.blocked_capabilities?.includes('private_draft_handoff')} onChoose={prepareChiefQuestion}/>}
            {!team?.revision ? <p className="team-fine">You can save notes now. Use your team above to start a conversation.</p> :
            <form className="team-composer" onSubmit={event => { event.preventDefault(); ask(); }}>
              {selectedPrep&&<div className="session-prep-included" role="status"><span>Session Prep included · v{selectedPrep.brief_version}</span>
                <button type="button" className="team-subtle" disabled={locked} onClick={()=>setPrepSelection(null)} aria-label="Remove Session Prep from this question">Remove</button></div>}
              <label className="team-sr-only" htmlFor="team-question">Thought or question</label>
              <textarea ref={questionRef} id="team-question" rows={2} maxLength={4000} disabled={locked || !bot?.enabled} value={thought} onChange={e => setThought(e.target.value)} placeholder={bot?.retired ? `${bot.name} is retired. Saved history remains available.` : bot?.enabled ? `Ask ${bot.name} about this encounter…` : `${bot?.name} is paused. Enable in settings.`} />
              <div><span>{bot?.name} <span className="team-fine">· {selectedPrep?"saved encounter + selected brief":"saved encounter only"}</span></span><button className="team-send" disabled={locked || !thought.trim() || !bot?.enabled} aria-label="Send message">↑</button></div>
            </form>}
            <p className="team-fine">{bot?.blocked_capabilities?.includes("model_answer") ? "AI answers are unavailable for this teammate. You can still check saved sources." : team?.llm.enabled ? "Ask about this visit. Check the answer and its sources before using it." : "Saved notes are available. AI chat needs a service connection."} {CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled ? "Use the Scribe visit controls for consented recording." : "Recording is not connected."}</p>
          </div>
        </section><aside className="team-notebook-panel">
          <nav aria-label="Encounter materials" className="team-material-tabs">{["Notebook", "Sources", "Review", "Work"].map(value => <button key={value} aria-pressed={panel === value} onClick={() => setPanel(value)}>{value}</button>)}</nav>
          <div className="team-task-context" aria-label="Current task"><strong>{({Notebook:"Visit notebook",Sources:"Check saved sources",Review:"Review visit note",Work:"Drafts and human follow-up"} as Record<string,string>)[panel]}</strong>
            <span>{panel==='Work'?'Confirm who owns the next action.':panel==='Sources'?'Read the material behind the note.':panel==='Review'?'Save the note, then record your review.':'Save your jottings, then review the visit note.'}</span></div>
          <div className="team-material-content" ref={materialRef}>
            {panel==='Work'&&<EncounterWorkSummary workspace={reviewWorkspace!} identity={authenticated||identity||undefined} locked={locked||connectionNavigationLocked}
              onReview={()=>{setPanel('Review');setMobilePanel('Review');}} onPracticeWork={()=>{setPracticeOpen(true);setPracticeOpened(true);}} onAccessLost={failure}/>}
            <div hidden={panel !== "Review"}><NoteReview key={workspace.id} active={panel === "Review"} workspace={reviewWorkspace!} locked={locked || captureDraftLocked}
              onSave={operation => void save(operation)} onSources={() => { setPanel("Sources"); setMobilePanel("Sources"); }} /></div>
            <div hidden={panel !== "Work"}><FollowUpWork key={workspace.id} workspace={reviewWorkspace!} locked={locked || captureDraftLocked}
              onSave={operation => void save(operation)} onReview={() => {setPanel("Review");setMobilePanel("Review");}} /></div>
            {panel === "Notebook" && <>
              <div className="team-task-actions"><div className="team-notebook-title"><h2>Jotted notes</h2><span className="team-pill">{note === latestNote ? "Saved" : "Not saved to notebook"}</span></div>
                <button className="team-primary" disabled={locked || !note.trim()} onClick={()=>append("scratchpad",note)}>Save notebook revision</button></div>
              {stage === "During" && !(CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled) && <div className="team-capture"><span>Recording awaits Scribe connection</span><button disabled>Start recording</button><button disabled>Voice instruction</button></div>}
              <p className="team-fine">Your working notebook. Shape the visit note in Review when you are ready.</p>
              <form onSubmit={event => { event.preventDefault(); append("scratchpad", note); }}><label className="team-sr-only" htmlFor="team-notebook">Jotted notes</label>
                <textarea ref={notebookRef} id="team-notebook" className="workspace-notepad team-notepad" rows={14} maxLength={20000} value={note} disabled={locked} onChange={e => setNote(e.target.value)} placeholder="Type or paste intake details, visit notes, or questions…" />
                <p className="team-fine">Your bots use saved notebook entries. Working copies on this device are separate from saved entries.</p></form>
              <details className="team-history"><summary>Saved notebook history</summary>{workspace.entries.filter(e => e.kind === "scratchpad").map(e => <article key={e.id}><small>Revision {e.revision}</small><p>{e.content}</p></article>)}</details>
            </>}
            {panel === "Sources" && <EncounterSources workspace={workspace} selectedSource={selectedSource} locked={locked}
              briefViewedAt={briefViewed?.workspace===workspace.id&&briefViewed.owner===authenticated&&briefViewed.teamRevision===team?.revision?briefViewed.at:undefined}
              onPrep={team?.configuration.bots.some(member=>member.role==='visit_prep'&&member.enabled)?()=>{const reader=team.configuration.bots.find(member=>member.role==='visit_prep'&&member.enabled)!;setSelected(botAddress(reader));setMobilePanel('Conversation');}:undefined}
              source={source} evidence={evidence} setSource={setSource} setEvidence={setEvidence}
              onSave={() => append("evidence", evidence, source)} onNotebook={() => { setPanel("Notebook"); setMobilePanel("Notebook"); }} />}
            {panel === "Work" && <>
              <h2>Linked work</h2><p className="team-fine">Existing work and approvals stay together. Private notes are not copied.</p>
              {workspace.entries.filter(e => e.kind === "work_link").map(e => <article className="team-work-card" key={e.id}>{e.ticket ? <><span className="team-kicker">EXISTING WORK</span><h3>{e.ticket.lane.replaceAll("_", " ")}</h3><span className="team-pill">{e.ticket.state.replaceAll("_", " ")}</span></> : "Linked work is no longer available in this encounter."}</article>)}
              {workspace.work_candidates.filter(t => !workspace.follow_ups?.some(f => f.ticket_id === t.id) && !workspace.entries.some(e => e.ticket?.id === t.id)).map(t => <button className="team-link-work" key={t.id} disabled={locked} onClick={() => void save({ type: "link", body: { expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(), ticket_id: t.id } })}>Link existing {t.lane.replaceAll("_", " ")} work</button>)}
              {authenticated && <div ref={faxWorkRef} tabIndex={-1} aria-label="Messaging and fax work"><VendorWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked}
                onChanged={()=>{setConflict(true);void refresh();}} /></div>}
              {authenticated && FINANCE_WORK_BUILD && <FinanceWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked} />}
              {authenticated && PORTAL_WORK_BUILD && <PortalWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked} />}
              {authenticated && MEMBERSHIP_WORK_BUILD && <MembershipWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked} />}
              {!authenticated && <p className="team-fine">Open a signed workspace to prepare and review messages and faxes.</p>}</>}
          </div>
        </aside></div></div>
      </>}
      </div>
    </div>
  </main></EditorRecoveryContext.Provider>;
}
