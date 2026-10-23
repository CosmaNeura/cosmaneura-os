import {WorkspaceDialog} from './WorkspaceDialog';
import {WorkspaceSession} from './session/workspace-session';
import {useWorkspaceSession} from './session/use-workspace-session';
import type {ConfirmedClinicalModelContext,PendingSave} from './session/model';
export type {PendingSave} from './session/model';
import {WorkspaceNavIcon} from './WorkspaceNavIcon';
import {teamConfigurationChanged} from './team-configuration-diff';
import {VisitCatalog} from './VisitCatalog';
import {consumeWorkspaceStartupTeam} from './workspace-team-read';
import {workspaceProtocolGeneration} from './workspace-protocol';
import {WorkspaceMarkdown} from './WorkspaceMarkdown';
import {readWorkspaceRoute,workspaceRouteHash,type WorkspaceRoute} from './workspace-route';
import {deferredWorkspacePanel} from './DeferredWorkspacePanel';
import type {SessionPrepAnalysis} from "./session-prep-analysis-contract";
import {PracticeAccessPanel} from './PracticeAccessPanel';
import {WorkspaceConnectionRecoveryContext,type PracticeAccessContext} from './PracticeAccessGate';
import { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { TeamConfigurationFlow } from "./TeamConfigurationFlow";
import {accountIdentityApi} from "./account-identity-api";
import {assertCurrentDesktopSession} from "./workspace-auth-headers";
import {subscribeNativeWorkspaceForeground} from './native-workspace-foreground';
import {useMobileChatFrame} from './MobileChatFrame';
import {validActivityContext,type AiActivityContext,type AiActivitySelection} from "./model-activity-contract";
import { SettingsHub } from "./SettingsHub";
import { WelcomeActions } from './WelcomeActions';
import {PracticeHome} from './PracticeHome';
import {PrivateRecordingPanel,type PrivateNotebookResult} from './PrivateRecordingPanel';
import {prewarmPrivateRecordingNative} from './private-recording-runtime';
import {RecordingVisitPanel} from './RecordingVisitPanel';
import {PrivateDraftLinkPanel} from './PrivateDraftLinkPanel';
import {SavedRecordingTranscriptionPanel} from './SavedRecordingTranscriptionPanel';
import {ChiefStartActions,InitialTeamAction} from './ChiefStartActions';
import type {CoreConnectionCommand} from './core-connection-contract';
import { CoreConnectionPanel, CORE_CONNECTION_BUILD, CONNECTION_ONBOARDING_BUILD } from "./CoreConnectionPanel";
import { setupChange, validTeamConfiguration, type SetupProjection } from "./team-setup-request";
import { hasUnsavedWork, useUnsavedWork } from "./unsaved-work";
import { openDraftStore, DraftStoreError, type DraftStore } from "./draft-store";
import { DraftJournal, editorAddress, notebookDraft as makeNotebookDraft, type RecoveryOffer } from "./draft-journal";
import { EditorRecoveryContext, type EditorRecoveryAccess } from "./editor-recovery";
import { AccountRecoveryContext, type AccountRecoveryAccess } from "./account-recovery";
import { supportsSkill, requireRecoveryScope, validRecoveryScope } from "./workspace-api";
import { BotAvatar } from "./BotAvatar";
import { TeamWorkPanel } from "./TeamWorkPanel";
import { HandoffReviewPanel } from "./HandoffReviewPanel";
import {modelActive, modelStateLabel, type ModelOperation} from "./model-work-request";
import { NoteReview } from "./NoteReview";
import { FollowUpWork } from "./FollowUpWork";
import { VendorWorkspaceMount } from "./VendorWorkMount";
import { PortalSetupMount, PORTAL_SETUP_BUILD } from "./PortalSetupMount";
import { FinanceWorkspaceMount, FINANCE_WORK_BUILD } from "./FinanceWorkMount";
import { PortalWorkspaceMount, PORTAL_WORK_BUILD } from "./PortalWorkMount";
import { FinanceSetupMount, FINANCE_SETUP_BUILD } from "./FinanceSetupMount";
import { VendorSetupMount, VENDOR_SETUP_BUILD } from "./VendorSetupMount";
import { MembershipWorkspaceMount, MEMBERSHIP_WORK_BUILD } from "./MembershipWorkMount";
import { ROUTINES_BUILD } from "./routine-api";
import {EncounterWorkSummary} from "./EncounterWorkSummary";
import { EncounterSources } from "./EncounterSources";
import { CapturePanel } from "./CapturePanel";
import { ExistingScribeSourcePanel } from './ExistingScribeSourcePanel';
import {ClinicalTeamDraftsPanel} from './ClinicalTeamDraftsPanel';
import {clinicalNoteSnapshotSize,clinicalTeamDirectionsError,clinicalTeamDirectionsSupported,clinicalRequestDisplay,clinicalTeamRequestAlreadySaved,parseClinicalTeamRequest,noteSelection} from './clinical-team-contract';
import type {ShareSavedNoteInput} from './clinical-team-contract';
import type {InboxDraftSelection} from "./inbox-analysis-contract";
import {ResearchPanelLoader} from "./ResearchPanelLoader";
import {ConnectorToolsPanel} from './ConnectorToolsPanel';
import {AgentResearchReviewPanel} from './AgentResearchReviewPanel';
import {validateAgentResearchRecovery, type AgentResearchRecoveryAccess} from './agent-research-recovery';
import { CoreRecordLink } from "./CoreRecordLink";
import { SchedulingPanel } from "./SchedulingPanel";
import { SCHEDULING_BUILD } from "./scheduling-api";
import {SchedulingPatientPanel} from './SchedulingPatientPanel';
import {SCHEDULING_PATIENT_BUILD} from './scheduling-patient-api';
import { SCHEDULING_LOGIN_BUILD } from "./scheduling-login-api";
import { GoogleConnectionPanel } from './GoogleConnectionPanel';
import { GoogleMessageMount } from './GoogleMessageMount';
import {GoogleCalendarMount} from './GoogleCalendarMount';
import {GOOGLE_CALENDAR_BUILD} from './google-calendar-api';
import type {GoogleCalendarSaved} from './google-calendar-recovery';
import { GOOGLE_MESSAGE_BUILD } from './google-message-api';
import type {GoogleMessageSaved} from './google-message-recovery';
import {EFaxSourceReviewMount} from './EFaxSourceReviewMount';
import {FaxSourceReviewMount} from './FaxSourceReviewMount';
import {FAX_INBOUND_SOURCE_BUILD,validFaxSourceOffer,type FaxSourceOffer,type FaxSourceReceipt} from './fax-inbound-source-api';
import {faxInboundApi,type FaxPending} from './fax-inbound-api';
import {EFAX_INBOUND_SOURCE_BUILD,validEFaxSourceOffer,type EFaxSourceOffer,type EFaxSourceReceipt} from './efax-inbound-source-api';
import {efaxInboundApi,efaxMissing,type EFaxPending} from './efax-inbound-api';
import {vendorCanonical} from './vendor-contract';
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
  type AuthenticatedWorkspaceIdentity, type DraftHandoff, type ProviderTeam, type Workspace, type WorkspaceEntry, type WorkspaceIdentity } from "./workspace-api";
import "./encounter-workspace.css";


const MembershipAnalysisPanel=deferredWorkspacePanel(()=>import('./MembershipAnalysisPanel').then(module=>module.MembershipAnalysisPanel),'Membership review');
const InboxAnalysisPanel=deferredWorkspacePanel(()=>import('./InboxAnalysisPanel').then(module=>module.InboxAnalysisPanel),'Inbox review');
const PracticeWork=deferredWorkspacePanel(()=>import('./PracticeWork').then(module=>module.PracticeWork),'Practice work');
const PracticeHub=deferredWorkspacePanel(()=>import('./PracticeHub').then(module=>module.PracticeHub),'Practice');
const WorkRoutines=deferredWorkspacePanel(()=>import('./WorkRoutines').then(module=>module.WorkRoutines),'Work briefs');

const isFollowUpRecovery = (draft: RecoveryOffer["draft"]) => draft.kind === "workspace" && draft.pending?.type.startsWith("followUp") === true;
const phoneLayout = () => window.matchMedia?.('(max-width: 600px)')?.matches ?? false;

export function EncounterWorkspace({ onExit, authenticated, accountControls, practiceAccess, draftStorage = openDraftStore }: {
  onExit?: () => void; authenticated?: AuthenticatedWorkspaceIdentity; accountControls?: ReactNode;
  practiceAccess?:PracticeAccessContext;
  draftStorage?: (options: { scope: string; native: boolean }) => Promise<DraftStore>;
}) {
  const [session]=useState(()=>new WorkspaceSession({initialPage:authenticated?'home':'visits',navigation:{initialRoute:readWorkspaceRoute(window.location.hash)}}));
  const {phoneNoteTask,reviewHandoffId,handoffReviewPending,selectedResult,savedResearchChat,settingsOpen,practicePage,practiceOpen,practiceOpened,selected,panel,mobilePanel,stage,entryIntent,researchEntry,settingsEntry,inboxSelection,privateRecordingBusy,privateRecordingEntry,savedRecordingEntry,savedRecordingNotebook,privateRecordings,privateRecordingListEpoch,privateRecordingRequest,clinicalPreparing,homeBusy,setupApproval,setupProjection,setupEpoch,confirmTeamExit,teamSaveExit,identity,connectionError,busy,pending,conflict,message,error,readRetry,
    workspace,encounters,team,teamDraft,note,thought,evidence,source,previousModelRequest,clinicalShareCheck,modelObservation,replacementDraft,modelHashes,schedulingObservation,recoveryOffers,recoveryState,recoveryEpoch}=useWorkspaceSession(session);
  const {setPhoneNoteTask,setReviewHandoffId,setHandoffReviewPending,setSelectedResult,setSavedResearchChat,setSettingsOpen,setPracticePage,setPracticeOpen,setPracticeOpened,setSelected,setPanel,setMobilePanel,setStage,setEntryIntent,setResearchEntry,setSettingsEntry,setInboxSelection,setPrivateRecordingBusy,setPrivateRecordingEntry,setSavedRecordingEntry,setSavedRecordingNotebook,setPrivateRecordingListEpoch,setPrivateRecordingRequest,setClinicalPreparing,setHomeBusy,setSetupApproval,setSetupProjection,setSetupEpoch,setConfirmTeamExit,setTeamSaveExit,setIdentity,setConnectionError,setBusy,setConflict,setMessage,setError,generation,
    setWorkspace,setTeam,setTeamDraft,setNote,setThought,setEvidence,setSource,setPreviousModelRequest,setClinicalShareCheck,setModelObservation,setReplacementDraft,setModelHashes,setSchedulingObservation,setRecoveryOffers,setRecoveryState,setRecoveryEpoch}=session;
  const connectionRecovery=useContext(WorkspaceConnectionRecoveryContext);
  const recoveredConnection=useRef({identity:authenticated,sequence:connectionRecovery&&connectionRecovery.identity===authenticated?connectionRecovery.sequence:0});
  const [inboxNavigation,setInboxNavigation]=useState<{selection:InboxDraftSelection;identity:WorkspaceIdentity;generation:number}|null>(null);
  const inboxNavigationConsumed=useRef<object|null>(null);
  const [recordingMinimized,setRecordingMinimized]=useState(false);
  const savedRecordingHost=useRef<HTMLDivElement>(null);
  const recordingHome=useRef<HTMLDivElement|null>(null),recordingHost=useRef<HTMLDivElement|null>(null),previousRecordingOpen=useRef(false);
  const [googleMessageOpen,setGoogleMessageOpen]=useState(false);
  const [googleCalendarOpen,setGoogleCalendarOpen]=useState(false);
  const [faxSourceOffer,setFaxSourceOffer]=useState<{identity:AuthenticatedWorkspaceIdentity;generation:number;workspaceId:string;document:EFaxSourceOffer;request:Extract<EFaxPending,{kind:'acquire'}>}|null>(null);
  const [providerFaxSourceOffer,setProviderFaxSourceOffer]=useState<{identity:AuthenticatedWorkspaceIdentity;generation:number;workspaceId:string;document:FaxSourceOffer;request:Extract<FaxPending,{kind:'acquire'}>}|null>(null);
  const [providerFaxSourceBusy,setProviderFaxSourceBusy]=useState(false);
  const [faxSourceBusy,setFaxSourceBusy]=useState(false);
  const googleVisitSelection=useRef<'message'|'calendar'|false>(false);
  const googleReturn=useRef(GOOGLE_CONNECTION_BUILD&&['#google-connected','#google-sign-in'].includes(window.location.hash));
  const microsoftReturn=useRef(MICROSOFT_CONNECTION_BUILD&&['#microsoft-connected','#microsoft-sign-in'].includes(window.location.hash));
  const schedulingReturn=useRef(SCHEDULING_LOGIN_BUILD&&['#scheduling-connected','#scheduling-sign-in'].includes(window.location.hash));
  const [connectionLocks, setConnectionLocks] = useState({google:false,googleMessages:false,googleCalendar:false,microsoft:false,scheduling:false,core:false,messaging:false, payments:false, portals:false, inbox:false});
  const activityEnabled = import.meta.env.VITE_AI_ACTIVITY_ENABLED === "true";
  const [activityProof,setActivityProof] = useState<{identity:AuthenticatedWorkspaceIdentity;journal:DraftJournal;generation:number;context:AiActivityContext}|null>(null);
  const [activityBusy,setActivityBusy] = useState(false),[activityContextBusy,setActivityContextBusy] = useState(false);
  const {activityNavigation}=session;
  const [activityContextError,setActivityContextError] = useState(''),[activityAttempt,setActivityAttempt] = useState(0);
  const connectionEditorsLocked = Object.values(connectionLocks).some(Boolean);
  const [accessBusy,setAccessBusy]=useState(false);
  const [scribeSourceBusy,setScribeSourceBusy]=useState(false);
  const [schedulingPatientBusy,setSchedulingPatientBusy]=useState(false);
  const [agentResearchBusy,setAgentResearchBusy]=useState(false);
  const {preparation:clinicalPreparation,safety:clinicalSafety}=session.clinical;
  const viewNavigationLocked = connectionEditorsLocked || activityBusy || accessBusy || scribeSourceBusy || handoffReviewPending || schedulingPatientBusy || agentResearchBusy || faxSourceBusy || providerFaxSourceBusy || clinicalPreparing;
  const connectionNavigationLocked = !!privateRecordingEntry || privateRecordingBusy || viewNavigationLocked;
  const sidebar=useRef<HTMLElement>(null),navigation=useRef<HTMLElement>(null);
  const [navigationHeight,setNavigationHeight]=useState(80);
  useLayoutEffect(()=>{
    if(!phoneLayout())return;
    window.scrollTo?.({top:0,left:0,behavior:'instant'});
    if(sidebar.current)sidebar.current.scrollTop=0;
  },[practicePage,settingsOpen,practiceOpen,workspace?.id]);
  useLayoutEffect(()=>{
    const nav=navigation.current;if(!nav)return;
    const measure=()=>setNavigationHeight(nav.getBoundingClientRect().height);
    measure();
    if(typeof ResizeObserver==='undefined')return;
    const observer=new ResizeObserver(measure);observer.observe(nav);return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    const closed=previousRecordingOpen.current&&!privateRecordingEntry;previousRecordingOpen.current=!!privateRecordingEntry;
    if(closed&&authenticated&&practicePage==='home'&&!settingsOpen&&!practiceOpen){
      const target=recordingHome.current?.querySelector<HTMLElement>('[aria-label="Saved private recordings"]')??recordingHome.current;
      target?.focus({preventScroll:true});target?.scrollIntoView?.({block:'start'});
    }
  },[privateRecordingEntry,authenticated,practicePage,settingsOpen,practiceOpen]);
  useLayoutEffect(()=>{
    if(!privateRecordingEntry||recordingMinimized||!phoneLayout())return;
    // The native pane owns entry focus and scrolling inside its safe-area frame.
    if(privateRecordingEntry.identity.mode==='clerk_jwt'&&privateRecordingEntry.identity.nativeSession)return;
    // Opening or returning to the same pane changes presentation only. The
    // recorder stays mounted and its consent, audio and pending work stay put.
    recordingHost.current?.querySelector<HTMLElement>('h1')?.focus({preventScroll:true});
    recordingHost.current?.scrollIntoView?.({block:'start'});
  },[privateRecordingEntry,recordingMinimized]);
  const [captureNavigationLocked, setCaptureNavigationLocked] = useState(false);
  const [scribeRecordingOpen,setScribeRecordingOpen]=useState(false);
  const faxWorkRef=useRef<HTMLDivElement|null>(null);
  const [focusFaxWork,setFocusFaxWork]=useState(false);
  const notebookRef=useRef<HTMLTextAreaElement|null>(null);
  const chiefNotebookFocus=useRef<{workspace:string;generation:number}|null>(null);
  const [questionFocus,setQuestionFocus]=useState(0);
  const [recordingSourceRequest,setRecordingSourceRequest]=useState(0);
  const materialRef=useRef<HTMLDivElement>(null);
  const materialScroll=useRef<Record<string,number>>({});
  const [briefViewed,setBriefViewed]=useState<{workspace:string;owner:AuthenticatedWorkspaceIdentity;teamRevision:number;at:string}|null>(null);
  const conversationHeaderRef=useRef<HTMLElement|null>(null);
  const [teamWorkExpanded,setTeamWorkExpanded]=useState(()=>!phoneLayout());
  const [phoneChatToolsOpen,setPhoneChatToolsOpen]=useState(false);
  const [clinicalTeamExpanded,setClinicalTeamExpanded]=useState(false);
  const chiefReviewReturn=session.review.returnTarget;
  const chiefReviewReturnFocus=useRef<typeof chiefReviewReturn.current>(null);
  const clinicalTeamRef=useRef<HTMLDetailsElement|null>(null);
  const clinicalTeamFocus=useRef<{owner:AuthenticatedWorkspaceIdentity;workspaceId:string;generation:number}|null>(null);
  useEffect(()=>{setPhoneChatToolsOpen(false);setClinicalTeamExpanded(false);setPhoneNoteTask(null);clinicalTeamFocus.current=null;chiefReviewReturn.current=null;chiefReviewReturnFocus.current=null;clinicalPreparation.current=null;setClinicalPreparing(false);},[authenticated,workspace?.id]);
  const [draftNoteIntent,setDraftNoteIntent]=useState<{workspaceId:string;content:string}|null>(null);
  const [reviewState,setReviewState]=useState<'editing'|'review'|'saved'>('editing');
  const {currentThought,modelBusy}=session.models;currentThought.current=thought;
  function updateThought(value:string){session.models.updateThought(value);}
  const [prepSelection,setPrepSelection]=useState<{scope:symbol;selection:SessionPrepAnalysis}|null>(null);
  const [prepEpoch,setPrepEpoch]=useState(0);
  const questionRef=useRef<HTMLTextAreaElement|null>(null);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const notebookDraft=(w:Workspace,n:string,t:string,e:string,s:string,p:PendingSave|null,previous=previousModelRequest)=>{
    const task=phoneNoteTask&&phoneNoteTask.owner===authenticated&&phoneNoteTask.owner===previousIdentity.current&&phoneNoteTask.generation===generation.current&&
      phoneNoteTask.workspaceId===w.id&&phoneNoteTask.scope===journal.current?.scope?phoneNoteTask:null;
    return makeNotebookDraft(w,n,t,e,s,p,previous,task?{contract:'chief-note-task.compose.v1',note_id:task.selection.note_id,
      note_version:task.selection.note_version,content_hash:task.selection.content_hash,source_fingerprint:task.selection.source_fingerprint}:null);
  };
  const [captureDraftLocked, setCaptureDraftLocked] = useState(false);
  const [observedCaptureDraft, setObservedCaptureDraft] = useState<CaptureDraft | null>(null);
  const [captureRequest, setCaptureRequest] = useState(0);
  const [confirmCaptureExit, setConfirmCaptureExit] = useState(false);
  const {journal,draftsSuspended}=session.recovery;
  useLayoutEffect(()=>{recoveredConnection.current={identity:authenticated,sequence:connectionRecovery&&connectionRecovery.identity===authenticated?connectionRecovery.sequence:0};setConnectionError(null);},[authenticated]);
  useEffect(()=>{
    if(!authenticated||connectionRecovery?.identity!==authenticated||recoveredConnection.current.identity!==authenticated||
      connectionRecovery.sequence<=recoveredConnection.current.sequence||connectionRecovery.phase!=='ready'||connectionRecovery.busy||
      workspaceProtocolGeneration(authenticated)!==connectionRecovery.generation||
      authenticated.mode==='desktop_native'&&!authenticated.isCurrent()||
      authenticated.mode==='clerk_jwt'&&authenticated.nativeSession&&!authenticated.nativeSession.isCurrent())return;
    recoveredConnection.current.sequence=connectionRecovery.sequence;
    // A connection retry never resolves a save, clears a conflict, or replaces working text.
    setConnectionError(previous=>previous?.identity===authenticated&&previous.generation<=connectionRecovery.generation?null:previous);
  },[authenticated,connectionRecovery?.identity,connectionRecovery?.sequence,connectionRecovery?.generation,connectionRecovery?.phase,connectionRecovery?.busy]);
  const connectionGeneration = generation.current;
  const reportAccessBusy = useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setAccessBusy(blocked);
  },[connectionGeneration]);
  const reportProviderFaxSourceBusy = useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setProviderFaxSourceBusy(blocked);
  },[connectionGeneration]);
  const reportFaxSourceBusy = useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setFaxSourceBusy(blocked);
  },[connectionGeneration]);
  const reportGoogleBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.google===blocked?previous:{...previous,google:blocked});
  }, [connectionGeneration]);
  const reportGoogleMessageBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.googleMessages===blocked?previous:{...previous,googleMessages:blocked});
  }, [connectionGeneration]);
  const reportGoogleCalendarBusy = useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.googleCalendar===blocked?previous:{...previous,googleCalendar:blocked});
  },[connectionGeneration]);
  const reportMicrosoftBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.microsoft===blocked?previous:{...previous,microsoft:blocked});
  },[connectionGeneration]);
  const reportSchedulingBusy = useCallback((blocked:boolean) => {
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.scheduling===blocked?previous:{...previous,scheduling:blocked});
  },[connectionGeneration]);
  const reportSchedulingObservation=useCallback(()=>{
    if(generation.current===connectionGeneration)setSchedulingObservation(value=>value+1);
  },[connectionGeneration]);
  const reportSchedulingPatientBusy=useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setSchedulingPatientBusy(blocked);
  },[connectionGeneration]);
  const reportAgentResearchBusy=useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setAgentResearchBusy(blocked);
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
  const currentIdentity=useRef(identity);currentIdentity.current=identity;
  const currentTeam = useRef(team);
  currentTeam.current = team;
  const currentTeamDraft = useRef(teamDraft);
  currentTeamDraft.current = teamDraft;
  const conversationEnd = useRef<HTMLDivElement>(null);
  function closeDraftJournal(){session.recovery.close();}
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "CosmasOS · Provider Team";
    return () => { session.invalidate(); activityNavigation.current?.abort(); closeDraftJournal(); document.title = previousTitle; };
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
  useEffect(() => {
    if(authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession)return;
    conversationEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [authenticated,workspace?.revision, pending]);
  useEffect(()=>session.models.observePendingHash(),[pending]);
  useEffect(() => {
    if (!authenticated || team) return;
    let cancelled = false;
    const current = generation.current;
    const controller=new AbortController();
    const startup=consumeWorkspaceStartupTeam(practiceAccess?.startupTeam,authenticated);
    void (startup?Promise.resolve(startup):workspaceApi.team(authenticated,controller.signal)).then(value => {
      if (!cancelled && current === generation.current) {
        setTeam(value); setTeamDraft(previous => previous ?? structuredClone(value.configuration));
        void recoverAfterRead(value, null, current);
      }
    }).catch(cause => { if (!cancelled && current === generation.current) failure(cause); });
    return () => { cancelled = true;controller.abort(); };
  }, [authenticated, team]);
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
  const fastObservationOwner = useRef<{identity:typeof identity;workspaceId:string}|null>(null);
  useEffect(() => {
    if (!workspace || !identity || busy || conflict || handoffReviewPending || !(workspace.entries.some(modelActive)||workspace.handoffs?.some(h =>
      ["queued", "running"].includes(h.status) || (h.result_entry_id && !workspace.entries.some(e => e.id === h.result_entry_id))))) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>|undefined,reading=false,controller:AbortController|null=null;
    const nativeOwner=authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?authenticated:null;
    let nativeVisible=nativeOwner?.nativeSession?.isCurrent()??false;
    const visible=()=>nativeOwner?nativeVisible&&nativeOwner.nativeSession!.isCurrent():document.visibilityState!=='hidden';
    const poll = async () => {
      if(cancelled||reading||!visible())return;
      reading=true;controller=new AbortController();
      fastObservationOwner.current={identity,workspaceId:workspace.id};
      try {
        const latest = await workspaceApi.read(identity, workspace.id,controller.signal);
        if (cancelled||controller.signal.aborted||!visible()) return;
        if(latest.id!==workspace.id||latest.revision<workspace.revision)throw new WorkspaceApiError(503);
        const noteRevision = (value: Workspace) => value.entries.filter(e => e.kind === "scratchpad").at(-1)?.revision ?? 0;
        if (noteRevision(latest) !== noteRevision(workspace)) {
          setConflict(true); setError("The saved notebook changed while your bot was working. Load the latest version to compare it with your unsaved text.");
        }
        setWorkspace(latest);
      } catch (cause) { if (!cancelled&&!controller.signal.aborted&&visible()) modelFailure(cause); }
      finally{
        reading=false;
        if (!cancelled&&visible()) {
          const delay=foregroundRequested?0:5000;foregroundRequested=false;
          timer = setTimeout(poll,delay);
        }
      }
    };
    // Reuse a healthy in-flight observation. If returning while an aborted
    // hidden read settles, request one immediate read after its settlement.
    let foregroundRequested = false;
    const foreground=()=>{
      clearTimeout(timer);
      if(!visible()){foregroundRequested=false;controller?.abort();return;}
      if(reading){foregroundRequested=controller?.signal.aborted===true;return;}
      foregroundRequested=false;void poll();
    };
    const visibility=()=>foreground();
    const removeNative=nativeOwner?subscribeNativeWorkspaceForeground(nativeOwner,()=>{
      nativeVisible=true;foreground();
    },()=>{
      nativeVisible=false;foregroundRequested=false;clearTimeout(timer);controller?.abort();
    }):null;
    if(!nativeOwner){
      document.addEventListener('visibilitychange',visibility);
      window.addEventListener?.('focus',foreground);
    }
    // Surface short completions sooner; unchanged repeats remain bounded at five seconds.
    if(visible())timer=setTimeout(poll,fastObservationOwner.current?.identity===identity&&fastObservationOwner.current.workspaceId===workspace.id?5000:2000);
    return () => { cancelled = true; clearTimeout(timer);controller?.abort();removeNative?.();document.removeEventListener('visibilitychange',visibility);window.removeEventListener?.('focus',foreground); };
  }, [workspace, identity, authenticated, busy, pending, conflict, handoffReviewPending]);

  function recoveryRead(value:ProviderTeam,currentWorkspace:Workspace|null,current:number,reloadParent=false){
    return {authenticated,team:value,workspace:currentWorkspace,generation:current,reloadParent,
      apiBase:import.meta.env.VITE_API_BASE||'http://127.0.0.1:8000',
      native:import.meta.env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED==='true',draftStorage};
  }
  function prepareRecovery(value:ProviderTeam,currentWorkspace:Workspace|null,current:number,reloadParent=false){
    return session.recovery.prepare(recoveryRead(value,currentWorkspace,current,reloadParent));
  }
  function recoverAfterRead(value:ProviderTeam,currentWorkspace:Workspace|null,current:number,reloadParent=false){
    return session.recovery.afterRead(recoveryRead(value,currentWorkspace,current,reloadParent),failure);
  }
  function recoveryOwner(){return {authenticated,currentAuthenticated:()=>previousIdentity.current,currentTeam:()=>currentTeam.current};}
  function flushScheduledDraft(){session.recovery.flush(recoveryOwner());}
  useEffect(() => {
    draftsSuspended.current = false;
    const suspend = (inactive:boolean) => { draftsSuspended.current = inactive; if(inactive)flushScheduledDraft(); };
    const nativeOwner = authenticated?.mode === 'clerk_jwt' && authenticated.nativeSession ? authenticated : null;
    if (nativeOwner) return subscribeNativeWorkspaceForeground(nativeOwner, () => suspend(false), () => suspend(true));
    const visibility = () => suspend(document.visibilityState === 'hidden');
    const pagehide = () => suspend(true);
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener?.('pagehide', pagehide);
    window.addEventListener?.('pageshow', visibility);
    visibility();
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener?.('pagehide', pagehide);
      window.removeEventListener?.('pageshow', visibility);
    };
  }, [authenticated]);
  useEffect(() => session.recovery.schedule(recoveryOwner(),retained=>notebookDraft(workspace!,note,thought,evidence,source,retained)),
  // State transitions do not trigger another storage write. The inputs do.
  [workspace, team, teamDraft, note, thought, evidence, source, busy, pending, recoveryOffers, recoveryEpoch, phoneNoteTask]);

  function restoreDraft(offer:RecoveryOffer){return session.recovery.restore(offer,{authenticated,failure,show:view=>{
    if(view.kind==='team'){setSettingsOpen(true);setPracticeOpen(false);return;}
    setPracticePage('notebook');
    if(view.noteTask){setPhoneNoteTask(view.noteTask);if(view.helper)setSelected(view.helper);setPhoneChatToolsOpen(false);setClinicalTeamExpanded(true);}
    setSettingsOpen(false);setPracticeOpen(false);setPanel(view.material==='Conversation'?'Notebook':view.material);setMobilePanel(view.material);
  }});}
  function discardRecovered(offer:RecoveryOffer){return session.recovery.discard(offer);}
  function exitWorkspace(discard:boolean){return session.recovery.exit(discard,{
    navigationLocked:connectionNavigationLocked,hasUnsavedWork,confirm:()=>setConfirmCaptureExit(true),clear,onExit,
  });}

  function clear() {
    setConnectionError(null);
    setSavedRecordingEntry(null);
    session.clear();
    setSetupApproval(null); setSetupProjection(null);
    setInboxSelection(null);setSettingsOpen(false);
    setPracticeOpen(false); setPracticeOpened(false); setCaptureNavigationLocked(false);
    setSchedulingPatientBusy(false);setAgentResearchBusy(false);setHomeBusy(false);setPracticePage(authenticated?"home":"visits");
    setConnectionLocks({google:false,googleMessages:false,googleCalendar:false,microsoft:false,scheduling:false,core:false,messaging:false, payments:false, portals:false, inbox:false});
    setGoogleMessageOpen(false);setGoogleCalendarOpen(false);googleVisitSelection.current=false;
    setAccessBusy(false);setActivityProof(null);setActivityBusy(false);setActivityContextBusy(false);setActivityContextError('');
    chiefNotebookFocus.current=null;
    setEntryIntent(null);setRecordingSourceRequest(0);setSelectedSource(null); setSelectedResult(null);
    setClinicalShareCheck(null);
    setModelObservation(null);setReplacementDraft(null);setModelHashes({});
    modelBusy.current=false;
    setCaptureDraftLocked(false); setConfirmCaptureExit(false);
    setCaptureRequest(0); setObservedCaptureDraft(null);
    setResearchEntry(false);
    setReviewHandoffId(null);setHandoffReviewPending(false);
  }
  function lifecycleContext(){return {authenticated,connectionRecovery,clear,
    recoveryFailed:()=>setRecoveryState('failed'),
    invalidateSetup:()=>{setSetupApproval(null);setSetupEpoch(value=>value+1);}};}
  function failure(cause:unknown,retry?:()=>Promise<void>){session.lifecycle.failure(cause,lifecycleContext(),retry);}
  function recheckSyntheticConnection(){
    return session.lifecycle.recheckSyntheticConnection(lifecycleContext(),connectionNavigationLocked||captureNavigationLocked||captureDraftLocked);
  }
  function navigationContext():import('./session/navigation').NavigationContext{return {...loadingContext(),viewNavigationLocked,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked,minimizeRecording:()=>setRecordingMinimized(true),hasUnsavedWork,replaceRoute:target=>history.replaceState(history.state,'',workspaceRouteHash(target)),openPrivateNotebook,loadEncounters,currentTeam};}
  function goHome(){session.navigation.goHome(navigationContext());}
  function clearPageError(){session.navigation.clearPageError({hasUnsavedWork});}
  function goNotebook(){session.navigation.goNotebook(navigationContext());}
  function openPrivateNotebook(result:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam},view:'default'|'notebook'='default'){
    return session.loading.openPrivate(result,{authenticated,recoverAfterRead,beforeOpen:()=>setSavedRecordingEntry(null),show:current=>{
      setObservedCaptureDraft(null);setSelectedSource(null);setSelectedResult(null);setCaptureRequest(0);setRecordingSourceRequest(0);
      setSelected(botAddress(result.team.configuration.bots.find(bot=>bot.role==='chief'&&!bot.retired)??result.team.configuration.bots[0]));
      setPanel('Notebook');setMobilePanel(view==='notebook'?'Notebook':phoneLayout()?'Conversation':'Notebook');setStage('Before');setSettingsOpen(false);setPracticeOpen(false);setPracticePage('notebook');
      chiefNotebookFocus.current={workspace:result.workspace.id,generation:current};
    }});
  }
  async function loadEncounters(skipTeamExit=false) {
    if (!authenticated || homeBusy) return;
    if(!skipTeamExit&&settingsOpen&&team&&teamDraft&&teamConfigurationChanged(team.configuration,teamDraft)){leaveTeamSettings(()=>void loadEncounters(true));return;}
    await session.loading.catalog({authenticated,failure,retry:()=>loadEncounters(),
      begin:()=>{const token=++routeSequence.current;routeApplying.current=false;routeReady.current=true;setRecordingMinimized(true);return token;},
      currentNavigation:()=>routeSequence.current,refreshRecordings:()=>setPrivateRecordingListEpoch(value=>value+1),
      show:()=>{setPracticePage('visits');setSettingsOpen(false);setPracticeOpen(false);}});
  }
  function open(appointmentId?:string,coreSelection?:CoreConnectionCommand,incoming?:InboxDraftSelection,recordVisit=false){
    return session.loading.open({...loadingContext(),locked,captureNavigationLocked,captureDraftLocked,hasUnsavedWork,
      begin:()=>{chiefNotebookFocus.current=null;},resetCapture:(record,useRecording)=>{setObservedCaptureDraft(null);setSelectedSource(null);setSelectedResult(null);setCaptureRequest(record?1:0);setRecordingSourceRequest(useRecording?1:0);},
      focusChief:(workspace,generation)=>{chiefNotebookFocus.current={workspace,generation};},focusFax:()=>setFocusFaxWork(true),showResearch:()=>setSavedResearchChat(false),
      afterOpen:()=>{if(googleVisitSelection.current){const service=googleVisitSelection.current;googleVisitSelection.current=false;setSettingsEntry('google');setGoogleMessageOpen(service==='message');setGoogleCalendarOpen(service==='calendar');setSettingsOpen(true);}},
      retryRead:authenticated?()=>loadEncounters():identity?refresh:recheckSyntheticConnection,
    },appointmentId,coreSelection,incoming,recordVisit);
  }
  function saveContext():import('./session/saves').SaveContext {
    const savedRecordingForSave=savedRecordingEntry;
    return {authenticated,notebookDraft,failure,saveModel,
      teamSaved:latest=>{currentTeam.current=latest;currentTeamDraft.current=structuredClone(latest.configuration);setSettingsOpen(false);setSetupApproval(null);setSetupProjection(null);},
      coreNoteLinked:(latest,owner,scope)=>{setPanel('Review');setMobilePanel('Review');
        if(savedRecordingForSave?.identity===owner&&savedRecordingForSave.workspaceId===latest.id&&scope===savedRecordingForSave.scope)setSavedRecordingNotebook(savedRecordingForSave);},
    };}
  function save(operation:PendingSave,mode:'submit'|'resolve'='submit',authorityCurrent?:()=>boolean){return session.saves.save(operation,saveContext(),mode,authorityCurrent);}
  function closeRejectedClinicalShare(){return session.saves.closeRejectedClinicalShare({authenticated,notebookDraft});}
  function modelFailure(cause:unknown){session.lifecycle.modelFailure(cause,lifecycleContext());}
  function modelContext(){return {authenticated,notebookDraft,modelFailure};}
  function saveModel(operation:ModelOperation,mode:'submit'|'resolve',confirmed?:ConfirmedClinicalModelContext){
    return session.models.save(operation,mode,modelContext(),confirmed);
  }
  function replaceModelRequest(){return session.models.replace(modelContext());}
  function prepareNewSelectedAnalysis(){return session.models.prepareSelectedAnalysis({...modelContext(),recoveryBlocked,show:target=>{setSelected(target.role);setSavedResearchChat(false);if(target.kind==='prep'){setPrepSelection(null);setPrepEpoch(value=>value+1);}if(target.kind==='inbox'){setInboxSelection(null);setPracticeOpened(true);setPracticeOpen(true);}}});}
  function prepareNewClinicalDrafts(){return session.clinical.prepareReplacement(clinicalContext());}
  function checkEntryResult(entry:WorkspaceEntry){return session.models.checkEntryResult(entry,modelContext());}
  function useCoreDraft(draft:CaptureDraft){void session.saves.useCoreDraft(draft,saveContext());}
  function append(kind:AppendInput['kind'],content:string,sourceLabel?:string){void session.saves.append(kind,content,sourceLabel,saveContext());}
  function ask(content=thought){void session.models.ask(selected,selectedPrep,modelContext(),content);}
  function prepareChiefQuestion(prompt:string){
    if(locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked||!team?.revision||!team.llm.enabled||
      bot?.role!=='chief'||!bot.enabled||bot.retired||bot.blocked_capabilities?.includes('model_answer')||thought.trim()||
      note!==latestNote||!chiefSavedContext)return;
    setPhoneNoteTask(null);setThought(prompt);setMobilePanel('Conversation');setPhoneChatToolsOpen(false);setQuestionFocus(value=>value+1);
  }
  function loadingContext(){return {authenticated,failure,recoverAfterRead,prepareRecovery};}
  function refresh(){return session.loading.refresh({...loadingContext(),recordingBlocked:!!privateRecordingEntry||privateRecordingBusy,
    invalidateSetup:()=>{setSetupApproval(null);setSetupEpoch(value=>value+1);},invalidatePrep:()=>setPrepEpoch(value=>value+1)});}
  function refreshHandoffReview(){return session.loading.refreshHandoff({authenticated,failure,blocked:captureNavigationLocked||captureDraftLocked||recoveryBlocked});}
  function recheckRecovery(){return session.loading.recheckRecovery(loadingContext());}
  function openSettings(entry:'home'|'connections'|'core'='home'){return session.navigation.openSettings(navigationContext(),entry);}
  async function refreshRoutineTeam(){await session.team.refresh({authenticated,failure});currentTeam.current=session.getSnapshot().team;currentTeamDraft.current=session.getSnapshot().teamDraft;}
  function receiveSetupTeam(value:ProviderTeam,projection:SetupProjection){session.team.receive(value,{authenticated},projection);currentTeam.current=session.getSnapshot().team;currentTeamDraft.current=session.getSnapshot().teamDraft;}
  function saveTeam(){void session.team.save(saveContext());}
  function leaveTeamSettings(next:()=>void){session.team.leave(settingsOpen,next);}
  function finishTeamExit(){session.team.finishExit();}
  function discardTeamExit(){return session.team.discardExit();}
  function closeSettings() {
    if (viewNavigationLocked) return;
    leaveTeamSettings(()=>{setPracticeOpen(false);if(!team?.configuration.bots.some(b=>botAddress(b)===selected))setSelected('scribe');setSettingsOpen(false);});
  }
  useEffect(()=>{if(teamSaveExit&&!busy&&!pending&&team&&teamDraft&&!teamConfigurationChanged(team.configuration,teamDraft))finishTeamExit();},[teamSaveExit,busy,pending,team,teamDraft]);
  function openMessagingWork(){
    if(connectionNavigationLocked||locked||captureNavigationLocked||captureDraftLocked||!authenticated)return;
    setPracticeOpen(false);setSettingsOpen(false);setResearchEntry(false);
    if(visitLinked&&workspace){setPracticePage('notebook');setPanel('Work');setMobilePanel('Work');setFocusFaxWork(true);}
    else {setEntryIntent('fax');void loadEncounters();}
  }
  useEffect(()=>{
    if(focusFaxWork&&workspace&&!settingsOpen&&!practiceOpen&&panel==='Work'){
      faxWorkRef.current?.focus();faxWorkRef.current?.scrollIntoView?.({block:'start'});setFocusFaxWork(false);
    }
  },[focusFaxWork,workspace,settingsOpen,practiceOpen,panel]);
  const recoveryBlocked = !!authenticated && (!validRecoveryScope(team?.recovery_scope) ||
    !journal.current || journal.current.serverScope !== team?.recovery_scope || recoveryState === "failed");
  const baseLocked = busy || clinicalPreparing || !!pending || conflict || recoveryState === "failed" || recoveryBlocked;
  const actionLocked = baseLocked || scribeSourceBusy;
  const lockedWithoutAgentResearch = actionLocked || handoffReviewPending || schedulingPatientBusy;
  const locked = lockedWithoutAgentResearch || agentResearchBusy;
  clinicalSafety.current={busy,pending,blocked:conflict||recoveryBlocked||recoveryState==='failed'||!!recoveryOffers.length||scribeSourceBusy||handoffReviewPending||
    schedulingPatientBusy||agentResearchBusy||captureNavigationLocked||captureDraftLocked||connectionEditorsLocked||activityBusy||accessBusy||faxSourceBusy||providerFaxSourceBusy||!!privateRecordingEntry||privateRecordingBusy};
  const reviewWorkspace = workspace ? withObservedCaptureDraft(workspace, observedCaptureDraft) : null;
  const bot = team?.configuration.bots.find(b => botAddress(b) === selected);
  const template = team?.members.find(b => botAddress(b) === selected);
  const phoneChief=phoneLayout()&&bot?.role==='chief';
  const phoneChiefConversation=phoneChief&&mobilePanel==='Conversation';
  const chiefNoteCompose=bot?.role==='chief'&&mobilePanel==='Conversation'&&!!phoneNoteTask&&phoneNoteTask.owner===authenticated&&phoneNoteTask.owner===previousIdentity.current&&
    phoneNoteTask.generation===generation.current&&phoneNoteTask.workspaceId===workspace?.id&&phoneNoteTask.scope===journal.current?.scope&&
    !!authenticated&&(authenticated.mode!=='clerk_jwt'||!authenticated.nativeSession||authenticated.nativeSession.isCurrent());
  const phoneChiefToolsVisible=phoneChiefConversation&&(phoneChatToolsOpen||viewNavigationLocked&&!chiefNoteCompose);
  const visitLinked=!!workspace?.appointment_id;
  const prepAvailable=!!(visitLinked&&bot&&supportsSkill(bot,"encounter_prep")&&ENCOUNTER_PREP_BUILD&&authenticated&&team?.capture?.prep_enabled&&
    template?.capabilities.some(capability=>capability.key==="core.session_prep.read"&&capability.state==="enabled"&&capability.contract==="core.session-prep.brief.v1"));
  const prepScope=useMemo(()=>Symbol(),[workspace?.id,authenticated,selected,team?.revision,bot?.enabled,bot?.include_evidence,prepAvailable,prepEpoch]);
  const selectedPrep=prepAvailable&&prepSelection?.scope===prepScope?prepSelection.selection:null;
  useEffect(()=>{if(selectedPrep)questionRef.current?.focus();},[selectedPrep]);
  const visitPrepReader = visitLinked && bot?.role === "visit_prep" && ENCOUNTER_PREP_BUILD && !!authenticated && !!team?.capture?.prep_enabled;
  const scribe = bot?.role === "scribe" ? bot : team?.configuration.bots.find(b => b.role === "scribe" && !b.instance_id);
  useEffect(() => {
    // Explicit fax navigation wins when settings closes. Completing that focus
    // does not trigger another recording scroll; only these navigation events do.
    if (bot?.role === "scribe" && !settingsOpen && !practiceOpen && !focusFaxWork)
      document.querySelector('[aria-label="Scribe recording"]')?.scrollIntoView?.({block: "start"});
  }, [selected, workspace?.id, settingsOpen, practiceOpen]);
  const latestNote = workspace?.entries.filter(e => e.kind === "scratchpad").at(-1)?.content ?? "";
  useEffect(()=>{
    const request=clinicalTeamFocus.current;
    if(!request||!clinicalTeamExpanded||bot?.role!=='chief'||mobilePanel!=='Conversation'||settingsOpen||practiceOpen)return;
    clinicalTeamFocus.current=null;
    if(request.owner!==authenticated||request.owner!==previousIdentity.current||request.workspaceId!==workspace?.id||request.generation!==generation.current)return;
    if(chiefNoteCompose){questionRef.current?.focus({preventScroll:true});return;}
    const heading=clinicalTeamRef.current?.querySelector<HTMLElement>('h3');
    const scrollHeading=nativeChat&&phoneChiefToolsVisible?clinicalTeamRef.current?.closest('.team-conversation-tools')?.querySelector<HTMLElement>('.chief-tools-heading'):heading;
    scrollHeading?.scrollIntoView?.({block:'start'});heading?.focus({preventScroll:true});
  },[authenticated,workspace?.id,selected,clinicalTeamExpanded,mobilePanel,settingsOpen,practiceOpen,phoneChiefToolsVisible,chiefNoteCompose]);
  function openClinicalTeamDrafts(noteId:string,prepare=true,expected?:{owner:AuthenticatedWorkspaceIdentity;scope:string;generation:number;selection:ShareSavedNoteInput;content:string},inComposer=false){
    if(expected){
      const latest=recoveryView.current.workspace,saved=latest?.note?.latest,selection=expected.selection;
      if(expected.owner!==authenticated||expected.owner!==previousIdentity.current||currentIdentity.current!==identity||expected.generation!==generation.current||
        expected.scope!==journal.current?.scope||!latest||latest.id!==workspace?.id||!saved||latest.revision!==selection.expected_revision||
        saved.id!==selection.note_id||saved.version!==selection.note_version||saved.content_hash!==selection.content_hash||saved.source_fingerprint!==selection.source_fingerprint||saved.content!==expected.content)return;
      try{assertCurrentDesktopSession(expected.owner);if(expected.owner.mode==='clerk_jwt'&&expected.owner.nativeSession&&!expected.owner.nativeSession.isCurrent())return;}catch{return;}
    }
    if(!authenticated||!team||!workspace||locked||captureNavigationLocked||captureDraftLocked||note!==latestNote||workspace.note?.latest?.id!==noteId||workspace.note.latest.sources_changed)return;
    const chief=team.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
    if(!chief)return;
    clinicalTeamFocus.current={owner:authenticated,workspaceId:workspace.id,generation:generation.current};
    setSelected(botAddress(chief));setReviewHandoffId(null);setSettingsOpen(false);setPracticeOpen(false);setSelectedResult(null);
    setMobilePanel('Conversation');setPhoneChatToolsOpen(!inComposer);setClinicalTeamExpanded(true);
    if(inComposer&&expected){setPhoneNoteTask({...expected,workspaceId:workspace.id});setQuestionFocus(value=>value+1);}
    if(prepare)void prepareClinicalDrafts(noteSelection(workspace.note.latest,workspace.revision)).catch(()=>{});
  }
  function clinicalContext():import('./session/clinical').ClinicalContext {return {...modelContext(),locked,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,recoveryBlocked,latestNote,previousIdentity,privateRecordingLive,currentIdentity,recoveryView,currentTeam,failure,save,saveModel,showReplacement:role=>{setSelected(role);setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');setPhoneChatToolsOpen(true);setClinicalTeamExpanded(true);}};}
  function prepareClinicalDrafts(input:ShareSavedNoteInput){return session.clinical.prepare(input,clinicalContext());}
  function returnToPhoneChat(){setPhoneChatToolsOpen(false);setQuestionFocus(value=>value+1);}
  function requestScribeDraft(){
    if(!workspace||!scribe?.enabled||scribe.retired||!scribe.include_notebook||scribe.blocked_capabilities?.includes('model_answer')||!team?.llm.enabled||locked||!note.trim()||captureNavigationLocked||captureDraftLocked)return;
    if(note!==latestNote){setDraftNoteIntent({workspaceId:workspace.id,content:note});append('scratchpad',note);return;}
    setSelected(botAddress(scribe));setPanel('Review');setMobilePanel('Review');
    void saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body:{expected_revision:workspace.revision,team_revision:team.revision,
      idempotency_key:crypto.randomUUID(),role:botAddress(scribe),content:'Draft a clinical note from my saved notebook notes. Preserve the stated facts and uncertainty, do not invent missing information, and flag anything requiring my review.'}},'submit');
  }
  useEffect(()=>{
    if(!draftNoteIntent||busy)return;
    setDraftNoteIntent(null);
    if(workspace?.id===draftNoteIntent.workspaceId&&latestNote===draftNoteIntent.content&&!pending&&!conflict&&!recoveryBlocked)requestScribeDraft();
  },[draftNoteIntent,busy,workspace?.revision,pending,conflict,recoveryBlocked]);
  const {ready:routeReady,applying:routeApplying,sequence:routeSequence,route}=session.navigation;
  function applyRoute(target:WorkspaceRoute){return session.navigation.applyRoute(target,navigationContext());}
  useEffect(()=>{
    if(!team||recoveryBlocked||routeReady.current||routeApplying.current)return;
    const target=readWorkspaceRoute(window.location.hash);if(target)void applyRoute(target);else routeReady.current=true;
  },[team,recoveryBlocked]);
  useEffect(()=>{const back=()=>{const target=readWorkspaceRoute(window.location.hash);if(target)void applyRoute(target);};
    window.addEventListener?.('popstate',back);return()=>window.removeEventListener?.('popstate',back);
  },[authenticated,workspace?.id,team,busy,pending,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked]);
  useEffect(()=>{
    if(!routeReady.current||routeApplying.current||!team||practicePage==='notebook'&&!workspace)return;
    const hash=workspaceRouteHash(route());if(window.location.hash===hash)return;
    if(!window.location.hash.startsWith('#cosmas/'))history.replaceState(history.state,'',hash);else history.pushState(history.state,'',hash);
  },[practicePage,settingsOpen,practiceOpen,workspace?.id,selected,mobilePanel,team]);
  useEffect(()=>{
    const closeMenus=(event:MouseEvent|KeyboardEvent)=>document.querySelectorAll<HTMLDetailsElement>('details[data-menu][open]').forEach(menu=>{
      if(event instanceof KeyboardEvent&&event.key==='Escape'){menu.open=false;menu.querySelector<HTMLElement>('summary')?.focus();}
      else if(event instanceof MouseEvent&&!menu.contains(event.target as Node))menu.open=false;
    });
    document.addEventListener('click',closeMenus);document.addEventListener('keydown',closeMenus);
    return()=>{document.removeEventListener('click',closeMenus);document.removeEventListener('keydown',closeMenus);};
  },[]);
  const chiefSavedContext=!!bot&&!!workspace?.entries.some(entry=>entry.content.trim()&&
    (entry.kind==='scratchpad'&&entry.content===latestNote&&bot.include_notebook||
      (entry.kind==='evidence'||entry.kind==='synthetic_source'||
        entry.kind==='google_message'&&entry.google_source_state==='current'||entry.kind==='google_calendar'&&entry.calendar_source_state==='current'||
        entry.kind==='efax_inbound_source'&&entry.fax_source_state==='current'||entry.kind==='fax_inbound_source'&&entry.practice_fax_source_state==='current')&&bot.include_evidence));
  const initialTeamUnchanged=!!team&&!!teamDraft&&JSON.stringify(teamDraft)===JSON.stringify(team.configuration);
  useEffect(()=>{if(questionFocus)questionRef.current?.focus(authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?{preventScroll:true}:undefined);},[questionFocus]);
  useEffect(()=>{
    if(authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession||!phoneLayout()||!workspace||practicePage!=='notebook'||mobilePanel!=='Conversation'||settingsOpen||practiceOpen||clinicalTeamExpanded&&phoneChatToolsOpen)return;
    const owner=authenticated,current=generation.current;
    const scroll=()=>{if(previousIdentity.current===owner&&generation.current===current&&questionRef.current!==document.activeElement)
      conversationHeaderRef.current?.scrollIntoView?.({block:'start'});};
    if(!window.requestAnimationFrame){scroll();return;}
    const frame=window.requestAnimationFrame(scroll);
    return ()=>window.cancelAnimationFrame?.(frame);
  },[authenticated,workspace?.id,practicePage,mobilePanel,settingsOpen,practiceOpen,clinicalTeamExpanded,phoneChatToolsOpen]);
  useEffect(()=>{
    const request=chiefNotebookFocus.current;
    if(!request||locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)return;
    chiefNotebookFocus.current=null;
    if(request.generation===generation.current&&request.workspace===workspace?.id&&bot?.role==='chief'&&
      !settingsOpen&&!practiceOpen&&panel==='Notebook'&&mobilePanel==='Notebook')notebookRef.current?.focus();
  },[locked,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked,workspace?.id,bot?.role,settingsOpen,practiceOpen,panel,mobilePanel]);
  // Activity is read-only: its own busy navigation lock is excluded here so the
  // final selection can still inspect independently retained unsaved work.
  useUnsavedWork(privateRecordingBusy || !!privateRecordingEntry || agentResearchBusy || handoffReviewPending || accessBusy || connectionEditorsLocked || !!pending || !!recoveryOffers.length || recoveryState === "saving" || captureNavigationLocked || note !== latestNote || !!thought || !!evidence || !!source ||
    !!team && !!teamDraft && teamConfigurationChanged(team.configuration,teamDraft));
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
      const latest = await workspaceApi.team(authenticated);
      // This controller follows the owner/API scope across encounter navigation.
      // A notebook change does not revoke an in-flight Home recovery check.
      if (requireRecoveryScope(latest) !== editorScope ||
          journal.current?.value !== editorJournal) throw new WorkspaceApiError(403);
    }};
  }, [authenticated, editorJournal, editorScope, accountScopeReady]);
  const privateRecordingPlatform = authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?'ios':'desktop';
  const privateRecordingLive=session.recording.live;
  privateRecordingLive.current={authenticated,editorJournal,editorScope,generation:generation.current};
  const recordingCurrent=session.recording.isCurrent;
  useEffect(()=>{
    if(!CAPTURE_WORKSPACE_BUILD||!authenticated||!accountScopeReady||!journal.current||
        authenticated.mode!=='clerk_jwt'||!authenticated.nativeSession?.isCurrent())return;
    const {scope}=journal.current,revision=authenticated.nativeSession.revision;
    // This prepares account-bound native admission while Home is usable. It
    // requests neither microphone access nor consent and starts no recording.
    void prewarmPrivateRecordingNative({scope,revision}).catch(()=>{});
  },[authenticated,accountScopeReady,editorJournal,editorScope]);
  const privateRecordingGeneration=generation.current;
  useEffect(()=>{
    if(!authenticated||!accountAccess||!accountScopeReady||!journal.current)return;
    return session.recording.list(authenticated,privateRecordingPlatform);
  },[authenticated,accountAccess,accountScopeReady,privateRecordingPlatform,privateRecordingListEpoch,privateRecordingGeneration]);
  function recordingContext():import('./session/recording').RecordingContext{return {authenticated,authorize:accountAccess?.authorize??null,captureEnabled:CAPTURE_WORKSPACE_BUILD,locked,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked,expand:()=>setRecordingMinimized(false),showNotebook:()=>{setSettingsOpen(false);setPracticeOpen(false);setPracticePage('notebook');},openNotebook:result=>openPrivateNotebook(result,'notebook')};}
  function startPrivateRecording(input:{title:string;prepareNotebook:(title?:string)=>Promise<PrivateNotebookResult>}){session.recording.start(input,recordingContext());}
  function startNotebookRecording(){session.recording.startNotebook(recordingContext());}
  function returnPrivateRecordingNotebook(entry:NonNullable<typeof privateRecordingEntry>,result:PrivateNotebookResult){return session.recording.returnNotebook(entry,result,recordingContext());}
  function reopenPrivateRecording(recordingId:string){session.recording.reopen(recordingId,recordingContext());}
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
      setWorkspace(latest);setSelected(address);if(entry.reply?.role==='research'||entry.model_request?.bot.role==='research')setSavedResearchChat(true);setSelectedResult(entry.id);setMobilePanel('Conversation');setSettingsOpen(false);setPracticeOpen(false);setPracticePage('notebook');setError('');
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
    return {journal:editorJournal,workspaceId:editorWorkspace,recoveryScope:editorScope, async authorize() {
      const current = generation.current;
      const team = await workspaceApi.team(authenticated);
      if (current !== generation.current || team.recovery_scope !== editorScope) throw new WorkspaceApiError(403);
      const latest = await workspaceApi.read(authenticated,editorWorkspace);
      if (current !== generation.current || journal.current?.value !== editorJournal) throw new WorkspaceApiError(403);
      const view = recoveryView.current;
      if (view.workspace?.id !== latest.id) throw new WorkspaceApiError(403);
      const saved = view.workspace.entries.filter(e=>e.kind === "scratchpad").at(-1)?.content ?? "";
      if (latest.revision !== view.workspace.revision && view.note !== saved && (latest.entries.filter(e=>e.kind === "scratchpad").at(-1)?.content ?? "") !== saved) setConflict(true);
      setWorkspace(latest);
      return latest;
    }, denied(cause) {
      if (cause && typeof cause === "object" && "status" in cause && [401,403,404].includes(Number(cause.status))) {
        failure(new WorkspaceApiError(Number(cause.status)));
      }
    }};
  },[authenticated,editorScope,editorJournal,editorWorkspace,editorReady,recoveryBlocked]);
  const agentResearchRecovery = useMemo<AgentResearchRecoveryAccess | null>(() => {
    if (!editorAccess || !editorWorkspace) return null;
    const address = editorAddress(editorWorkspace,'agent-research-review');
    return {async authorize(){await editorAccess.authorize();}, async load(){
      const value=await editorAccess.journal.load(address);
      if(value===null)return null;
      if(value?.kind!=='editor'||value.editor!=='agent-research-review')throw new DraftStoreError('integrity');
      return validateAgentResearchRecovery(value.data,editorWorkspace);
    },async persist(value){await editorAccess.journal.persist(address,value===null?null:{kind:'editor',
      workspaceId:editorWorkspace,editor:'agent-research-review',data:value,pending:value.pending?.revision_id??null});}};
  },[editorAccess,editorWorkspace]);
  const turns = workspace?.entries.filter(e => ["conversation", "handoff_result"].includes(e.kind)
    && (e.model_request?e.model_request.bot.address===selected:e.reply&&(e.reply.agent_id ? e.reply.agent_id === template?.agent_id
      : !bot?.instance_id && e.reply.role === bot?.role))) ?? [];
  function savedDraftReviewLabel(entry:WorkspaceEntry):string {
    const matches=workspace?.handoffs?.filter(h=>h.result_entry_id===entry.id)??[];
    if(matches.length!==1)return "Unreviewed draft";
    const handoff=matches[0],review=handoff.review;
    if(handoff.review_status==='stale')return "Review needs updating";
    if(handoff.status!=='completed'||handoff.review_status!=='current'||!review||
      review.attempt_id!==handoff.attempt_id||review.result_entry_id!==entry.id||
      review.result_sha256!==handoff.result_sha256)return "Unreviewed draft";
    return review.decision==='accepted'?"Draft accepted":"Changes requested";
  }
  const localModelPending=pending?.type==='ask'||pending?.type==='retry'?pending:null;
  const clinicalModelPending=localModelPending?.type==='ask'?parseClinicalTeamRequest(localModelPending.body.content):null;
  const nativeChatOwner=authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?authenticated:null;
  const nativePrivateNote=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&workspace?.private_draft?.state==='unlinked'&&!visitLinked;
  const nativeHome=!!nativeChatOwner&&phoneLayout()&&practicePage==='home'&&!settingsOpen&&!practiceOpen&&!privateRecordingEntry&&!savedRecordingEntry;
  const nativeConversationPending=bot?.role==='chief'&&localModelPending?.type==='ask'&&localModelPending.body.role===selected&&
    !localModelPending.body.research_analysis&&!localModelPending.body.inbox_analysis&&!localModelPending.body.membership_analysis&&!localModelPending.body.session_prep_analysis;
  const nativeSavedRecording=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&practicePage==='notebook'&&!settingsOpen&&!practiceOpen&&!privateRecordingEntry&&CAPTURE_WORKSPACE_BUILD&&!!team&&
    !!savedRecordingEntry&&savedRecordingEntry.identity===authenticated&&savedRecordingEntry.workspaceId===workspace?.id&&journal.current?.scope===savedRecordingEntry.scope;
  const savedRecordingNotebookOpen=nativeSavedRecording&&savedRecordingNotebook===savedRecordingEntry;
  const savedRecordingFocused=nativeSavedRecording&&!savedRecordingNotebookOpen;
  const nativeChat=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&!!workspace&&practicePage==='notebook'&&mobilePanel==='Conversation'&&
    !settingsOpen&&!practiceOpen&&!privateRecordingEntry&&(!savedRecordingEntry||savedRecordingNotebookOpen)&&!scribeRecordingOpen&&!scribeSourceBusy&&!reviewHandoffId&&!conflict&&!recoveryBlocked&&!recoveryOffers.length&&(!pending||busy||nativeConversationPending);
  const nativeWorkspace=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&!nativeHome&&!nativeChat&&!privateRecordingEntry&&!settingsOpen&&!practiceOpen;
  const nativeClinicalPlan=(nativeChat||chiefNoteCompose)&&bot?.role==='chief'&&!!workspace?.appointment_id&&!!workspace.note?.latest&&authenticated===identity&&authenticated===previousIdentity.current&&
    !!authenticated&&!!journal.current&&journal.current.serverScope===team?.recovery_scope?{
      owner:authenticated,scope:journal.current.scope,generation:generation.current,selection:noteSelection(workspace.note.latest,workspace.revision),
      content:workspace.note.latest.content,sourcesChanged:workspace.note.latest.sources_changed}:null;
  const phoneNoteMatches=chiefNoteCompose&&!!workspace?.note?.latest&&!!phoneNoteTask&&
    workspace.note.latest.id===phoneNoteTask.selection.note_id&&workspace.note.latest.version===phoneNoteTask.selection.note_version&&
    workspace.note.latest.content_hash===phoneNoteTask.selection.content_hash&&workspace.note.latest.source_fingerprint===phoneNoteTask.selection.source_fingerprint&&
    workspace.note.latest.content===phoneNoteTask.content;
  const phoneNoteDirectionsError=chiefNoteCompose?clinicalTeamDirectionsError(thought):null;
  const phoneNoteDirectionsUnsupported=chiefNoteCompose&&thought!==''&&!!team&&!clinicalTeamDirectionsSupported(team);
  const phoneNoteTeamReady=!!team&&team.revision>0&&team.llm.enabled&&['chief','follow_up','research'].every(role=>team.configuration.bots.some(item=>
    item.role===role&&item.enabled&&!item.retired&&item.include_evidence&&!item.blocked_capabilities?.includes('model_answer')&&!item.blocked_capabilities?.includes('private_draft_handoff')));
  const phoneNoteAlreadyRequested=chiefNoteCompose&&!!workspace&&clinicalTeamRequestAlreadySaved(workspace,thought);
  const phoneNoteTaskBlocked=phoneNoteAlreadyRequested||!phoneNoteMatches||!!phoneNoteDirectionsError||phoneNoteDirectionsUnsupported||!phoneNoteTeamReady||
    !workspace?.appointment_id||workspace.revision>=500||!!workspace.note?.latest?.sources_changed||note!==latestNote||
    !!workspace.note?.latest&&clinicalNoteSnapshotSize(workspace.note.latest,workspace.revision)>20000;
  function submitPhoneNoteTask(){
    if(!chiefNoteCompose||phoneNoteTaskBlocked||!workspace?.note?.latest)return;
    // Only the same human-selected note is eligible. prepareClinicalDrafts
    // rechecks the owner, exact source and verbatim words before admission.
    void prepareClinicalDrafts(noteSelection(workspace.note.latest,workspace.revision)).catch(()=>{});
  }
  useLayoutEffect(()=>{
    if(!savedRecordingFocused||!nativeChatOwner||!savedRecordingEntry)return;
    const owner=nativeChatOwner,current=generation.current,host=savedRecordingHost.current;
    const scroll=()=>{if(previousIdentity.current===owner&&owner.nativeSession?.isCurrent()&&generation.current===current&&host===savedRecordingHost.current&&host?.isConnected)
      host?.scrollIntoView?.({block:'start'});};
    if(!window.requestAnimationFrame){scroll();return;}
    const frame=window.requestAnimationFrame(scroll);return()=>window.cancelAnimationFrame?.(frame);
  },[savedRecordingFocused,nativeChatOwner,savedRecordingEntry?.recordingId,savedRecordingEntry?.workspaceId,savedRecordingEntry?.visitResolved]);
  const inlineModelRecovery=nativeChat&&nativeConversationPending;
  const nativeComposerEditable=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&!conflict&&!recoveryBlocked&&recoveryState!=='failed'&&!recoveryOffers.length&&
    !scribeSourceBusy&&!handoffReviewPending&&!schedulingPatientBusy&&!agentResearchBusy&&!captureNavigationLocked&&!captureDraftLocked&&!connectionEditorsLocked&&!activityBusy&&!accessBusy&&(!clinicalPreparing||modelBusy.current||!!clinicalPreparation.current)&&
    (!pending||pending.type==='ask')&&(!busy||modelBusy.current);
  const chatGeneration=generation.current;
  const localQuestionRepresented=pending?.type==='ask'&&workspace?.entries.some(entry=>entry.model_request?.request.kind==='conversation'&&
    entry.model_request.request.idempotency_key===pending.body.idempotency_key&&entry.model_request.request_sha256===modelHashes[pending.body.idempotency_key]);
  const recoveryAppearance=useRef<string|null>(null);
  // Reveal newly displayed recovery content; a hidden check, draft save or
  // typing must not move the reader while the same recovery is retained.
  if(!inlineModelRecovery)recoveryAppearance.current=null;
  else if(!busy)recoveryAppearance.current=JSON.stringify([localModelPending.body.idempotency_key,modelObservation?.receipt.outcome??null,!!replacementDraft]);
  const mobileChatFrame=useMobileChatFrame({active:nativeChat&&!phoneChiefToolsVisible,owner:nativeChatOwner,scope:`${chatGeneration}:${workspace?.id??''}:${selected}`,
    messages:JSON.stringify([turns.map(entry=>[entry.id,entry.reply?.content??null]),
      pending?.type==='ask'&&pending.body.role===selected&&!localQuestionRepresented?pending.body.idempotency_key:null,recoveryAppearance.current,
      [chiefNoteCompose,phoneNoteTask?.selection.note_id,phoneNoteTask?.selection.note_version,clinicalPreparing,busy,message],
      chiefNoteCompose?workspace?.handoffs?.map(handoff=>[handoff.id,handoff.status,handoff.result_entry_id,handoff.review_status]):null]),
    isCurrent:()=>previousIdentity.current===nativeChatOwner&&generation.current===chatGeneration&&!!nativeChatOwner?.nativeSession?.isCurrent()});
  function openPhoneChatTools(){setPhoneChatToolsOpen(true);if(mobileChatFrame.scrollRef.current)mobileChatFrame.scrollRef.current.scrollTop=0;}
  function reviewContext():import('./session/review').ReviewContext{return {authenticated,previousIdentity,actionLocked,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,recoveryBlocked,phoneChatToolsOpen,setPhoneChatToolsOpen,setClinicalTeamExpanded,focusQuestion:()=>setQuestionFocus(value=>value+1),returnFocus:chiefReviewReturnFocus};}
  function retryTeamTask(handoff:DraftHandoff){session.review.retry(handoff,saveContext());}
  function currentChiefReviewReturn(target=chiefReviewReturn.current){return session.review.currentReturn(reviewContext(),target);}
  function closeTeamReview(){session.review.close(reviewContext());}
  useLayoutEffect(()=>{
    const target=chiefReviewReturnFocus.current;
    if(!target||reviewHandoffId||selected!==target.address)return;
    chiefReviewReturnFocus.current=null;
    if(currentChiefReviewReturn(target))
      clinicalTeamRef.current?.querySelector<HTMLElement>('h3')?.focus({preventScroll:true});
  },[authenticated,workspace?.id,selected,reviewHandoffId,clinicalTeamExpanded]);
  function reviewTeamResult(handoff:DraftHandoff,fromChiefPlan=false){session.review.open(handoff,reviewContext(),fromChiefPlan);}
  function prepareFreshHandoff(feedback:string){session.review.prepareFresh(feedback,reviewContext());}
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
  async function prepareGoogleChief(source:GoogleMessageSaved|GoogleCalendarSaved,kind:'google_message'|'google_calendar'='google_message'){
    if(!authenticated||!workspace||locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)return;
    const current=generation.current,id=workspace.id;setBusy(true);
    try{
      const latest=await workspaceApi.read(authenticated,id);
      if(current!==generation.current||recoveryView.current.workspace?.id!==id)return;
      receiveGoogleSource(latest);
      if(source.workspace_id!==id||source.source_withheld)throw new WorkspaceApiError(409,kind+'_source_changed');
      const entry=latest.entries.find(item=>item.id===source.entry_id&&item.revision===source.entry_revision&&item.kind===kind&&(kind==='google_calendar'?item.calendar_source_state==='current':item.google_source_state==='current'));
      if(!entry||await vendorSha256(new TextEncoder().encode(entry.content))!==source.content_sha256)throw new WorkspaceApiError(409,kind+'_source_changed');
      const chief=team?.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
      if(!chief)throw new WorkspaceApiError(409,'bot_unavailable');
      const prompt=kind==='google_calendar'?'Review the human-selected calendar summary '+source.entry_id+' as an untrusted event snapshot and prepare appropriate private assignments. Preserve the existing clinical note and email sources. Ask me about missing details; do not treat the summary as current availability or a booking.':'Review the human-selected email source '+source.entry_id+' and prepare appropriate private assignments. Preserve the existing clinical note; ask me about missing details before proposing outside actions.';
      setPhoneNoteTask(null);setThought(previous=>previous.trim()?previous+'\n\n'+prompt:prompt);
      setSelected(botAddress(chief));setSelectedResult(null);setSelectedSource(source.entry_id);
      setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');setQuestionFocus(value=>value+1);
    }catch(cause){if(current===generation.current)failure(cause);}
    finally{if(current===generation.current)setBusy(false);}
  }

  function receiveFaxDocument(document:EFaxSourceOffer,request:Extract<EFaxPending,{kind:'acquire'}>){
    if(!EFAX_INBOUND_SOURCE_BUILD||!authenticated||!workspace||!validEFaxSourceOffer(document)||locked||captureNavigationLocked||captureDraftLocked)return;
    setFaxSourceOffer({identity:authenticated,generation:generation.current,workspaceId:workspace.id,document:structuredClone(document),request:structuredClone(request)});
    setSettingsOpen(false);setPracticeOpen(false);setPanel('Sources');setMobilePanel('Sources');
  }
  async function refreshFaxDocument():Promise<EFaxSourceOffer|null>{
    const offer=faxSourceOffer;if(!offer||offer.identity!==authenticated||offer.generation!==generation.current||offer.workspaceId!==recoveryView.current.workspace?.id||!accountAccess)return null;
    await accountAccess.authorize();const account=await accountIdentityApi.read(offer.identity);
    if(offer.generation!==generation.current||offer.workspaceId!==recoveryView.current.workspace?.id)return null;
    const receipt=await efaxInboundApi.resolve(offer.identity,{box_id:account.box_id,owner_id:account.actor_id},offer.request);
    if(offer.generation!==generation.current||offer.workspaceId!==recoveryView.current.workspace?.id||efaxMissing(receipt)||receipt.state!=='acquired'||!receipt.content_available||receipt.source_withheld||!receipt.document||!receipt.operation_id)return null;
    const document={operation_id:receipt.operation_id,document_sha256:receipt.document.sha256,pages:receipt.document.pages};
    return vendorCanonical(document)===vendorCanonical(offer.document)?document:null;
  }
  async function prepareFaxChief(source:{receipt:EFaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry}){
    if(!authenticated||!workspace||locked||connectionEditorsLocked||activityBusy||accessBusy||scribeSourceBusy||handoffReviewPending||schedulingPatientBusy||captureNavigationLocked||captureDraftLocked)return;
    const current=generation.current,id=workspace.id;setBusy(true);
    try{
      const latest=await workspaceApi.read(authenticated,id);
      if(current!==generation.current||recoveryView.current.workspace?.id!==id)return;
      receiveGoogleSource(latest);
      const receipt=source.receipt,entry=latest.entries.find(e=>e.id===receipt.entry_id);
      if(receipt.scope.workspace_id!==id||receipt.source_withheld||!entry||entry.kind!=='efax_inbound_source'||entry.fax_source_state!=='current'||entry.revision!==receipt.entry_revision||await vendorSha256(new TextEncoder().encode(entry.content))!==receipt.content_sha256)throw new WorkspaceApiError(409,'efax_inbound_source_unavailable');
      const chief=team?.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
      if(!chief)throw new WorkspaceApiError(409,'bot_unavailable');
      const prompt='Review the human-selected received-fax passage '+receipt.entry_id+' and prepare appropriate private assignments. This is manually entered selected text, without OCR or full-document coverage. Preserve the existing clinical note, email and calendar sources; ask me about missing information before proposing outside actions.';
      setPhoneNoteTask(null);setThought(previous=>previous.trim()?previous+'\n\n'+prompt:prompt);setSelected(botAddress(chief));setSelectedResult(null);setSelectedSource(entry.id);
      setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');setQuestionFocus(value=>value+1);
    }catch(cause){if(current===generation.current)failure(cause);}
    finally{if(current===generation.current)setBusy(false);}
  }

  function receiveProviderFaxDocument(document:FaxSourceOffer,request:Extract<FaxPending,{kind:'acquire'}>){
    if(!FAX_INBOUND_SOURCE_BUILD||!authenticated||!workspace||!validFaxSourceOffer(document)||locked||captureNavigationLocked||captureDraftLocked)return;
    setProviderFaxSourceOffer({identity:authenticated,generation:generation.current,workspaceId:workspace.id,document:structuredClone(document),request:structuredClone(request)});
    setSettingsOpen(false);setPracticeOpen(false);setPanel('Sources');setMobilePanel('Sources');
  }
  async function refreshProviderFaxDocument():Promise<FaxSourceOffer|null>{
    const offer=providerFaxSourceOffer;if(!offer||offer.identity!==authenticated||offer.generation!==generation.current||offer.workspaceId!==recoveryView.current.workspace?.id||!accountAccess)return null;
    await accountAccess.authorize();const account=await accountIdentityApi.read(offer.identity);
    if(offer.generation!==generation.current||offer.workspaceId!==recoveryView.current.workspace?.id)return null;
    const receipt=await faxInboundApi.resolve(offer.identity,{box_id:account.box_id,owner_id:account.actor_id},offer.request);
    if(offer.generation!==generation.current||offer.workspaceId!==recoveryView.current.workspace?.id||receipt.state!=='acquired'||receipt.source_withheld||!receipt.document_sha256||!receipt.pages||!receipt.operation_id)return null;
    const document={operation_id:receipt.operation_id,document_sha256:receipt.document_sha256,pages:receipt.pages};
    return vendorCanonical(document)===vendorCanonical(offer.document)?document:null;
  }
  async function prepareProviderFaxChief(source:{receipt:FaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry}){
    if(!authenticated||!workspace||locked||connectionEditorsLocked||activityBusy||accessBusy||scribeSourceBusy||handoffReviewPending||schedulingPatientBusy||captureNavigationLocked||captureDraftLocked)return;
    const current=generation.current,id=workspace.id;setBusy(true);
    try{
      const latest=await workspaceApi.read(authenticated,id);
      if(current!==generation.current||recoveryView.current.workspace?.id!==id)return;
      receiveGoogleSource(latest);
      const receipt=source.receipt,entry=latest.entries.find(e=>e.id===receipt.entry_id);
      if(receipt.scope.workspace_id!==id||receipt.source_withheld||!entry||entry.kind!=='fax_inbound_source'||entry.practice_fax_source_state!=='current'||entry.revision!==receipt.entry_revision||await vendorSha256(new TextEncoder().encode(entry.content))!==receipt.content_sha256)throw new WorkspaceApiError(409,'fax_inbound_source_unavailable');
      const chief=team?.configuration.bots.find(item=>item.role==='chief'&&item.enabled&&!item.retired);
      if(!chief)throw new WorkspaceApiError(409,'bot_unavailable');
      const prompt='Review the human-selected received-fax passage '+receipt.entry_id+' and prepare appropriate private assignments. This is manually entered selected text, without OCR or full-document coverage. Preserve the existing clinical note, email and calendar sources; ask me about missing information before proposing outside actions.';
      setPhoneNoteTask(null);setThought(previous=>previous.trim()?previous+'\n\n'+prompt:prompt);setSelected(botAddress(chief));setSelectedResult(null);setSelectedSource(entry.id);
      setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');setQuestionFocus(value=>value+1);
    }catch(cause){if(current===generation.current)failure(cause);}
    finally{if(current===generation.current)setBusy(false);}
  }

  const nativeNoteShortcut=nativeClinicalPlan&&<section className="chief-saved-note-shortcut" aria-label="Saved visit note next steps">
            <span>Saved visit note · version {nativeClinicalPlan.selection.note_version}
              {note!==latestNote?<small>Save your note changes first.</small>:nativeClinicalPlan.sourcesChanged?<small>Review the updated note first.</small>:null}</span>
            <button type="button" aria-label={`Plan from saved visit note version ${nativeClinicalPlan.selection.note_version}`} disabled={locked||viewNavigationLocked||captureNavigationLocked||captureDraftLocked||note!==latestNote||nativeClinicalPlan.sourcesChanged}
              onClick={()=>openClinicalTeamDrafts(nativeClinicalPlan.selection.note_id,false,nativeClinicalPlan,true)}>Follow-up + Research</button>
          </section>;
  const clinicalTeamDrafts=bot?.role==='chief'&&authenticated&&team&&workspace&&<details ref={clinicalTeamRef} className="clinical-team-disclosure" open={clinicalTeamExpanded} onToggle={event=>setClinicalTeamExpanded(event.currentTarget.open)}><summary>Saved note for follow-up and research</summary>
            <ClinicalTeamDraftsPanel workspace={workspace} team={team} locked={locked||captureNavigationLocked||captureDraftLocked||note!==latestNote}
              ownerDirections={thought} onDirectionsChange={phoneChiefConversation?updateThought:undefined} compactPlan={(nativeChat||chiefNoteCompose)&&(phoneChiefToolsVisible||chiefNoteCompose)} composerPlan={chiefNoteCompose&&!phoneChiefToolsVisible}
              directionsLocked={(nativeChatOwner?!nativeComposerEditable:locked)||!bot.enabled||!!bot.retired} preparing={clinicalPreparing} onPrepare={prepareClinicalDrafts} authority={authenticated}
              onRetry={retryTeamTask}
              onShare={async body=>{await save({type:'clinicalNoteShare',body});}}
              onAskChief={async content=>{if(locked||captureNavigationLocked||captureDraftLocked||note!==latestNote||thought.trim()||!team.revision)return;
                await saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body:{expected_revision:workspace.revision,team_revision:team.revision,
                  idempotency_key:crypto.randomUUID(),role:botAddress(bot),content}},'submit');}}
              onReview={id=>{const handoff=workspace.handoffs?.find(item=>item.id===id);if(handoff)reviewTeamResult(handoff,true);}}/>
          </details>;
  const teamDrafts=workspace&&<details className="team-work-disclosure" open={teamWorkExpanded} onToggle={event=>setTeamWorkExpanded(event.currentTarget.open)}>
    <summary>Team drafts · {(workspace.handoffs??[]).filter(handoff=>handoff.status==='completed').length} saved</summary>
    <TeamWorkPanel handoffs={workspace.handoffs??[]} entries={workspace.entries} locked={locked} onRetry={retryTeamTask} onReview={reviewTeamResult}/>
  </details>;
  const chiefStarters=bot?.role==='chief'&&!!team?.revision&&<ChiefStartActions compact={phoneLayout()} locked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked||!bot.enabled||!!bot.retired}
    modelEnabled={team.llm.enabled&&!bot.blocked_capabilities?.includes('model_answer')} sourceAllowed={bot.include_notebook||bot.include_evidence}
    hasSavedContext={chiefSavedContext} notesDirty={note!==latestNote} hasQuestion={!!thought.trim()}
    canDelegate={!bot.blocked_capabilities?.includes('private_draft_handoff')} onChoose={prepareChiefQuestion}/>;
  const modelRecovery=<>
      {localModelPending&&!busy&&<section className="team-recovery" aria-label="Unconfirmed model request"><p>{inlineModelRecovery?'Chief hasn’t confirmed this message yet. Check its status before retrying.':'The retained request is unconfirmed. Check its saved result; checking never starts another model call.'}</p>
        {localModelPending.type==='ask'&&localModelPending.body.research_analysis&&<details className="research-model-selection"><summary>Retained selected-source request</summary><p>{localModelPending.body.content}</p><p>Only this exact question and saved public-source selection belong to this key.</p><ul>{localModelPending.body.research_analysis.entries.map(anchor=><li key={anchor.entry_id}>Saved packet revision {anchor.entry_revision} · {anchor.entry_id}<small>Lookup {anchor.run_id} · save proof {anchor.save_request_sha256}</small></li>)}</ul></details>}
        {localModelPending.type==='ask'&&localModelPending.body.session_prep_analysis&&<details><summary>Retained Session Prep question</summary><p>{localModelPending.body.content}</p><p>This request includes the selected Session Prep brief, version {localModelPending.body.session_prep_analysis.brief_version}. Checking its result retains that exact selection.</p></details>}
        {localModelPending.type==='ask'&&localModelPending.body.membership_analysis&&<details><summary>Retained Membership/Billing review request</summary><p>{localModelPending.body.content}</p><p>This exact selected {localModelPending.body.membership_analysis.kind} record and consent belong to the saved request. A new review requires current evidence and fresh consent.</p></details>}
        {localModelPending.type==='ask'&&localModelPending.body.inbox_analysis&&<details><summary>Retained Inbox draft request</summary><p>{localModelPending.body.content}</p><p>Message {localModelPending.body.inbox_analysis.item_id}, source {localModelPending.body.inbox_analysis.source_id}, local version {localModelPending.body.inbox_analysis.item_version}. This exact selection and consent belong to the saved request.</p></details>}
        {clinicalModelPending&&<details><summary>Retained saved-note plan · version {clinicalModelPending.note_version}</summary><p>{clinicalRequestDisplay(localModelPending.type==='ask'?localModelPending.body.content:'')}</p></details>}
        {modelObservation&&<p>Last verified result: {modelObservation.receipt.outcome.replaceAll('_',' ')}. {modelObservation.receipt.outcome==='not_found'?(localModelPending.origin==='durable_admission_v1'?
          'No admission for this key was recorded as of the read. Sending this saved request reuses the same key and body.':'The earlier provider outcome is unknown. An absent legacy record does not prove it was never sent.'):
          'An unknown or failed outcome does not establish remote cancellation or refund the attempt.'}</p>}
        <button disabled={busy||recoveryBlocked} onClick={()=>void saveModel(localModelPending,'resolve')}>{inlineModelRecovery?'Check message':'Check saved result'}</button>
        {modelObservation?.receipt.outcome==='not_found'&&localModelPending.origin==='durable_admission_v1'&&<button disabled={busy||recoveryBlocked}
          onClick={()=>void saveModel(localModelPending,'submit')}>{inlineModelRecovery?'Retry message':'Send this saved request'}</button>}
        {modelObservation&&!clinicalModelPending&&!(localModelPending.type==='ask'&&(localModelPending.body.research_analysis||localModelPending.body.inbox_analysis||localModelPending.body.membership_analysis||localModelPending.body.session_prep_analysis))&&['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome)&&<button disabled={busy||recoveryBlocked} onClick={()=>setReplacementDraft({
          content:localModelPending.type==='ask'?localModelPending.body.content:'',role:localModelPending.type==='ask'?localModelPending.body.role:selected,acknowledged:false})}>Start another attempt</button>}
        {localModelPending.type==='ask'&&(localModelPending.body.research_analysis||localModelPending.body.inbox_analysis||localModelPending.body.membership_analysis||localModelPending.body.session_prep_analysis)&&modelObservation&&['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome)&&<div className="research-model-recovery">
          <label><input type="checkbox" checked={replacementDraft?.acknowledged??false} disabled={busy||recoveryBlocked} onChange={event=>setReplacementDraft({content:localModelPending.body.content,role:localModelPending.body.role,acknowledged:event.target.checked})}/>I understand the earlier model outcome may remain unconfirmed.</label>
          <button disabled={busy||recoveryBlocked||!replacementDraft?.acknowledged} onClick={()=>void prepareNewSelectedAnalysis()}>Review sources for a new request</button>
        </div>}
        {clinicalModelPending&&localModelPending.type==='ask'&&modelObservation&&['unknown','failed','abandoned','not_found'].includes(modelObservation.receipt.outcome)&&<div>
          <label><input type="checkbox" checked={replacementDraft?.acknowledged??false} disabled={busy||recoveryBlocked} onChange={event=>setReplacementDraft({content:localModelPending.body.content,role:localModelPending.body.role,acknowledged:event.target.checked})}/>I understand the earlier model outcome may remain unconfirmed.</label>
          <button disabled={busy||recoveryBlocked||!replacementDraft?.acknowledged} onClick={()=>void prepareNewClinicalDrafts()}>Review saved note and directions for a new request</button>
        </div>}
        {replacementDraft&&!clinicalModelPending&&!(localModelPending.type==='ask'&&(localModelPending.body.research_analysis||localModelPending.body.inbox_analysis||localModelPending.body.membership_analysis||localModelPending.body.session_prep_analysis))&&<div><p>A new attempt uses a new key and the current saved context. The prior exact binding is retained in the local transition record; this does not resolve an earlier uncertain provider outcome.</p>
          {localModelPending.type==='ask'&&<><label>Bot for new attempt<select value={replacementDraft.role} disabled={busy} onChange={e=>setReplacementDraft({...replacementDraft,role:e.target.value})}>
            {team?.configuration.bots.filter(b=>!b.retired&&b.enabled).map(b=><option key={botAddress(b)} value={botAddress(b)}>{b.name}</option>)}</select></label>
            <label>Review new question<textarea maxLength={4000} value={replacementDraft.content} disabled={busy} onChange={e=>setReplacementDraft({...replacementDraft,content:e.target.value})}/></label></>}
          {localModelPending.origin!=='durable_admission_v1'&&<label><input type="checkbox" checked={replacementDraft.acknowledged} disabled={busy} onChange={e=>setReplacementDraft({...replacementDraft,acknowledged:e.target.checked})}/>
            I understand the earlier provider outcome is unknown and this explicitly supersedes the local request.</label>}
          <button disabled={busy||recoveryBlocked||localModelPending.origin!=='durable_admission_v1'&&!replacementDraft.acknowledged||localModelPending.type==='ask'&&!replacementDraft.content.trim()}
            onClick={()=>void replaceModelRequest()}>Send new attempt</button><button disabled={busy} onClick={()=>setReplacementDraft(null)}>Keep previous request</button></div>}
      </section>}
  </>;
  const notebookHeading=<div className="team-notebook-title"><h2>{nativePrivateNote?'Notes':'Jotted notes'}</h2><span className="team-pill">{note === latestNote ? "Saved" : "Not saved to notebook"}</span></div>;
  const notebookActions=<div key="notebook-actions" className="team-task-actions">{!nativePrivateNote&&notebookHeading}
    <button className="team-primary" disabled={locked || !note.trim()||note===latestNote} onClick={()=>append("scratchpad",note)}>{nativePrivateNote?'Save notes':'Save notebook revision'}</button>
    <button className="team-primary" disabled={locked||!note.trim()||!scribe?.enabled||scribe.retired||!scribe.include_notebook||!team?.llm.enabled||!!scribe.blocked_capabilities?.includes('model_answer')} onClick={requestScribeDraft}>{nativePrivateNote?'Create draft note':'Draft note from my notes'}</button></div>;
  const notebookEditor=<form key="notebook-editor" onSubmit={event => { event.preventDefault(); append("scratchpad", note); }}>{nativePrivateNote&&notebookHeading}<label className="team-sr-only" htmlFor="team-notebook">Jotted notes</label>
    <textarea ref={notebookRef} id="team-notebook" className="workspace-notepad team-notepad" rows={nativePrivateNote?8:14} maxLength={20000} value={note} disabled={recoveryBlocked||conflict||!!pending&&pending.type!=='team'} onChange={e => setNote(e.target.value)} placeholder={nativePrivateNote?'Write your notes…':'Type or paste intake details, visit notes, or questions…'} />
    <p className="team-fine">{nativePrivateNote?'Save notes to make them available to your bots. Create draft note saves them first and asks Scribe for a draft to review.':'Your bots use saved notebook entries. Working copies on this device are separate from saved entries.'}</p></form>;
  const hasWorkspaceIdentity=!!(authenticated||identity);
  const showExecutionProof=!!onExit&&import.meta.env.VITE_SHOW_EXECUTION_PROOF==='true';
  const errorBanner=error&&<div className="team-banner error workspace-error-banner" role="alert"><p>{error}</p><div className="workspace-error-actions">
    {readRetry&&<button disabled={busy||homeBusy||!!pending||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={()=>void readRetry.run()}>Try again</button>}
    <button onClick={()=>setError('')}>Dismiss</button></div></div>;
  return <EditorRecoveryContext.Provider value={editorAccess}><main className="team-workspace" style={{'--workspace-nav-height':`${navigationHeight}px`} as CSSProperties} data-page={practicePage} data-native-home={nativeHome} data-native-chat={nativeChat} data-native-workspace={nativeWorkspace} data-recording-open={!!privateRecordingEntry} data-recording-focused={!!privateRecordingEntry&&!recordingMinimized} data-settings-open={settingsOpen && !practiceOpen} data-settings-rendered={settingsOpen&&hasWorkspaceIdentity} data-settings-navigation-locked={connectionNavigationLocked}>
    <aside ref={sidebar} className="team-sidebar" hidden={nativeWorkspace}>
      <div className="team-brand"><span className="team-logo" aria-hidden="true">✳</span>cosmas<span>OS</span><small className="team-phone-preview">Synthetic preview</small>{accountControls&&phoneLayout()&&!nativeHome&&!nativeWorkspace&&!nativeChat&&<div className="team-phone-account-controls">{accountControls}</div>}</div>
      <p className="team-sidebar-label">YOUR WORKSPACE</p>
      <nav ref={navigation} className="practice-navigation" aria-label="Workspace navigation">
        {authenticated&&<button className={`team-nav-item ${practicePage==='home'&&!settingsOpen&&!practiceOpen?'active':''}`} aria-current={practicePage==='home'&&!settingsOpen&&!practiceOpen?'page':undefined} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={goHome}><WorkspaceNavIcon page="home"/>Home</button>}
        <button className={`team-nav-item ${!settingsOpen&&!practiceOpen&&(practicePage==='visits'||phoneLayout()&&practicePage==='notebook')?'active':''}`} aria-current={!settingsOpen&&!practiceOpen&&(practicePage==='visits'||phoneLayout()&&practicePage==='notebook')?'page':undefined} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={()=>void (authenticated?loadEncounters():open())}><WorkspaceNavIcon page="visits"/>Visits and notes</button>
        {workspace&&<button className={`team-nav-item team-nav-secondary ${practicePage==='notebook'&&!settingsOpen&&!practiceOpen?'active':''}`} aria-current={practicePage==='notebook'&&!settingsOpen&&!practiceOpen&&!phoneLayout()?'page':undefined} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={goNotebook}>Current notebook</button>}
        {hasWorkspaceIdentity&&<button className={`team-nav-item ${practiceOpen?'active':''}`} aria-current={practiceOpen?'page':undefined} disabled={viewNavigationLocked||busy||!!pending||captureNavigationLocked||captureDraftLocked} onClick={()=>leaveTeamSettings(()=>{routeSequence.current++;routeApplying.current=false;routeReady.current=true;clearPageError();setSettingsOpen(false);setPracticeOpen(true);setPracticeOpened(true);})}><WorkspaceNavIcon page="work"/>Practice work</button>}
        {authenticated&&CONNECTION_ONBOARDING_BUILD&&<button className="team-nav-item team-nav-secondary" disabled={viewNavigationLocked||busy||!!pending} onClick={()=>void openSettings('connections')}>Connections</button>}
        {hasWorkspaceIdentity&&<button className={`team-nav-item ${settingsOpen&&!practiceOpen?'active':''}`} aria-current={settingsOpen&&!practiceOpen?'page':undefined} disabled={viewNavigationLocked} onClick={()=>void openSettings()}><WorkspaceNavIcon page="settings"/>Settings</button>}
      </nav>
      <div className="team-roster-heading"><p className="team-sidebar-label">PROVIDER TEAM</p>
        {team && <button className="team-icon-button" disabled={connectionNavigationLocked || busy || !!pending && pending.type !== "team"} onClick={() => void openSettings()} aria-label="Configure Provider Team">⚙</button>}</div>
      <nav aria-label="Provider Team" className="team-roster">{team?.members.map(member => {
        const address = botAddress(member);
        const config = team.configuration.bots.find(b => botAddress(b) === address)!;
        const privateScribe=member.role==='scribe'&&CAPTURE_WORKSPACE_BUILD&&!!authenticated&&config.enabled&&!config.retired&&!!team.revision;
        return <button key={address} disabled={connectionNavigationLocked||!workspace&&!privateScribe||privateScribe&&workspace?.private_draft?.state==='unlinked'&&practicePage==='notebook'&&(locked||captureNavigationLocked||captureDraftLocked)} aria-pressed={selected === address} onClick={() => leaveTeamSettings(() => {
          if(privateScribe&&workspace?.private_draft?.state==='unlinked'&&practicePage==='notebook'){startNotebookRecording();return;}
          if(privateScribe&&(!workspace||practicePage==='home')){setSettingsOpen(false);setPracticeOpen(false);setPracticePage('home');setPrivateRecordingRequest(value=>value+1);return;}
          setPracticeOpen(false); setSelectedResult(null); setSelected(address); setSettingsOpen(false);setPracticePage("notebook"); setMobilePanel(member.role === "scribe" ? "Notebook" : "Conversation"); if (member.role === "scribe") setPanel("Notebook"); })}>
          <BotAvatar role={member.role} /><span><strong>{config.name}</strong>
            <small><i className={config.enabled && team.revision ? "ready" : "paused"} />{config.retired ? "Retired · history kept" : !team.revision ? "Set up your team" : !config.enabled ? "Paused" : config.blocked_capabilities?.includes("model_answer") ? "AI answers blocked" : "On"}</small></span>
        </button>;
      })}</nav>
      <div className="team-sidebar-bottom"><p><span className="team-local-dot" />{authenticated ? "Signed-in workspace" : "Local workspace"}</p><small>Invented data · private to you</small></div>
    </aside>
    <div className="team-main">
      {nativeHome||nativeWorkspace?<header className="native-home-header">
        {nativeWorkspace&&practicePage!=='home'&&<button className="team-subtle" aria-label="Home" disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={goHome}>‹ Home</button>}
        <strong>{nativeSavedRecording?'Scribe':'CosmaBot'}</strong>
        <div className="native-workspace-actions">
        {nativeSavedRecording&&<button className="team-subtle" disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} aria-label={savedRecordingNotebookOpen?'Back to Scribe':'Open notebook'} onClick={()=>{
          if(savedRecordingNotebookOpen)setSavedRecordingNotebook(null);else {setSavedRecordingNotebook(savedRecordingEntry);setPanel('Notebook');setMobilePanel('Notebook');}
        }}>{savedRecordingNotebookOpen?'Back to Scribe':'Notebook'}</button>}
        <details className="native-home-menu"><summary>More</summary><nav aria-label="More workspace actions">
          {(workspace||showExecutionProof||(settingsOpen||practiceOpen)&&hasWorkspaceIdentity)&&<button className={showExecutionProof?'workspace-execution-proof':undefined} onClick={()=>void exitWorkspace(false)}>{showExecutionProof?"Open execution proof":"Close notebook"}</button>}
          <button disabled={connectionNavigationLocked} onClick={()=>void openSettings()}>Settings</button>
          <button disabled={connectionNavigationLocked||busy||!!pending||captureDraftLocked||captureNavigationLocked}
            onClick={()=>leaveTeamSettings(()=>{setSettingsOpen(false);setPracticeOpen(true);setPracticeOpened(true);})}>Practice work</button>
          {accountControls}
          <span className="team-fine">Synthetic preview</span>
        </nav></details></div>
      </header>:<header className={`team-topbar${accountControls ? " team-topbar-authenticated" : ""}`}><span>Provider workspace <span className="team-divider">/</span> {practiceOpen ? "Practice work" : settingsOpen ? "Settings" : practicePage==="home"?"Home":practicePage==="visits"?"Visits and notes":"Notebook"}</span>
        <div className="row">{(workspace||showExecutionProof||(settingsOpen||practiceOpen)&&hasWorkspaceIdentity)&&<button className={`team-subtle${showExecutionProof?' workspace-execution-proof':''}`} onClick={() => void exitWorkspace(false)}>{showExecutionProof ? "Open execution proof" : "Close notebook"}</button>}
          {(authenticated || identity) && <button disabled={connectionNavigationLocked} onClick={() => void openSettings()}>Team settings</button>}
          {(authenticated || identity) && <button disabled={connectionNavigationLocked || !practiceOpen && (busy || !!pending || captureDraftLocked || captureNavigationLocked)}
          onClick={() => leaveTeamSettings(()=>{setSettingsOpen(false);setPracticeOpen(!practiceOpen);setPracticeOpened(true);})}>{practiceOpen ? "Back to notebook" : "Practice work"}</button>}
          <span className="team-pill">Synthetic preview</span>{!phoneLayout()&&accountControls}</div></header>}
      {confirmTeamExit&&<WorkspaceDialog title="Unsaved team changes" onClose={()=>{setConfirmTeamExit(false);setTeamSaveExit(false);}}>
        <p>Your team has unsaved changes. Save them, discard this local draft, or keep editing.</p>
        {pending?.type==='team'?<p>The team save is unconfirmed. Its exact request is retained; check or retry it before discarding.</p>:null}
        <button className="team-primary" disabled={busy||!!pending||!teamDraft||!validTeamConfiguration(teamDraft)||!!team&&setupChange(team.configuration,teamDraft!)&&!(setupApproval?.revision===team.revision&&setupApproval.configurationKey===JSON.stringify(teamDraft))} onClick={()=>{setTeamSaveExit(true);saveTeam();}}>Save changes</button>
        <button disabled={busy||pending?.type==='team'} onClick={()=>void discardTeamExit()}>Discard changes</button>
        <button onClick={()=>{setConfirmTeamExit(false);setTeamSaveExit(false);}}>Keep editing</button>
        <button onClick={finishTeamExit}>Keep draft and continue</button>
        {team&&teamDraft&&setupChange(team.configuration,teamDraft)&&!(setupApproval?.revision===team.revision&&setupApproval.configurationKey===JSON.stringify(teamDraft))&&<p>Review the current capability changes on the Team review screen to enable Save.</p>}
      </WorkspaceDialog>}
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
      <div className="workspace-draft-save-status">
        {recoveryState === "saving" && <p className="team-fine" role="status">Saving notebook and team drafts on this device…</p>}
        {recoveryState === "saved" && <p hidden={!!privateRecordingEntry||nativeChat||nativePrivateNote&&practicePage==='notebook'&&!settingsOpen&&!practiceOpen||phoneLayout()&&practicePage==='home'&&!settingsOpen&&!practiceOpen} className="team-fine">Working copies saved on this device. Save a note version separately for review.</p>}
      </div>
      {practiceOpen && errorBanner}
      {practiceOpened && (authenticated || identity) && <AccountRecoveryContext.Provider value={accountAccess}><fieldset disabled={recoveryBlocked} hidden={!practiceOpen} style={{border:0,padding:0,margin:0,minWidth:0}}><PracticeHub identity={(authenticated || identity)!} onDenied={failure} onBusyChange={reportInboxBusy} onDraftInbox={authenticated?selection=>{setInboxNavigation({selection,identity:authenticated,generation:generation.current});}:undefined}><PracticeWork identity={(authenticated || identity)!}
        onChanged={() => { if (workspace) setConflict(true); }} onAccessLost={failure} />
        {ROUTINES_BUILD && authenticated && team && team.revision > 0 && <WorkRoutines identity={authenticated} team={team} onAccessLost={failure} onRefreshTeam={refreshRoutineTeam} />}
        {authenticated && team?.revision === 0 && <div className="team-banner"><p>Set up your private team to schedule work briefs.</p><button onClick={() => void openSettings()}>Set up your team</button></div>}</PracticeHub></fieldset></AccountRecoveryContext.Provider>}
      <div className="workspace-main-content" hidden={practiceOpen}>
      {settingsOpen&&!hasWorkspaceIdentity&&<section className="settings-hub" aria-labelledby="offline-settings-title"><h1 id="offline-settings-title">Settings</h1><p>Settings are available after your workspace connects.</p><button className="settings-done" onClick={closeSettings}>Done</button></section>}
      {connectionError&&connectionError.identity===(authenticated??identity)&&<div className="team-banner error" role="alert">{connectionError.message}</div>}
      {errorBanner}
      {message && <div className="team-banner" role="status">{message}</div>}
      {conflict && <div className="team-recovery"><p>Your text has not been overwritten. Load the latest history and team, compare changes, then save a new revision.</p>
        <button disabled={busy} onClick={() => void refresh()}>Load latest — keep my text</button></div>}
      {pending?.type==='clinicalNoteShare'&&!busy&&<section className="team-recovery" aria-label="Unconfirmed saved note share">
        <p>The exact note share is retained. Checking its saved result does not send another share or ask a bot.</p>
        <button disabled={recoveryBlocked} onClick={()=>void save(pending,'resolve')}>Check saved note share</button>
        {clinicalShareCheck?.operation===pending&&clinicalShareCheck.owner===identity&&clinicalShareCheck.generation===generation.current&&
          clinicalShareCheck.receipt.outcome==='not_found'&&(clinicalShareCheck.receipt.workspace.revision===pending.body.expected_revision?
            <button disabled={recoveryBlocked} onClick={()=>void save(pending)}>Retry same note share</button>:
            clinicalShareCheck.receipt.workspace.revision>pending.body.expected_revision&&<button disabled={recoveryBlocked} onClick={()=>void closeRejectedClinicalShare()}>Close rejected note share</button>)}
      </section>}
      {pending && pending.type!=='clinicalNoteShare' && !localModelPending && !busy && <div className="team-recovery"><p>The previous save is unconfirmed. Retry before editing; the same request will be reused.</p>
        <button disabled={recoveryBlocked} onClick={() => void save(pending)}>Retry same save</button></div>}
      {!inlineModelRecovery&&modelRecovery}
      {!localModelPending&&previousModelRequest&&<details className="team-recovery"><summary>Previous request retained as superseded history</summary>
        <p>The previous {previousModelRequest.operation.type==='ask'?'question':'draft retry'} was last checked as {previousModelRequest.outcome.replaceAll('_',' ')} at {previousModelRequest.observed_at}. Its original body and binding remain on this device. A later request does not resolve that earlier provider uncertainty.</p></details>}
      {activityEnabled && settingsOpen && activityContextBusy && <p className="team-fine" role="status">Checking optional AI activity access…</p>}
      {activityEnabled && settingsOpen && activityContextError && <div className="team-banner error" role="alert"><p>{activityContextError}</p><button disabled={locked || activityContextBusy} onClick={()=>setActivityAttempt(value=>value+1)}>Recheck AI activity access</button></div>}
      {(authenticated || identity) && <AccountRecoveryContext.Provider value={accountAccess}><SettingsHub key={generation.current} open={settingsOpen} navigationLocked={viewNavigationLocked} beforeLeaveTeam={leaveTeamSettings}
        onOpenMessagingWork={authenticated?openMessagingWork:undefined} messagingWorkLabel={workspace?'Open fax work for this visit':'Choose a visit for fax work'}
        messagingWorkBlocked={locked||captureNavigationLocked||captureDraftLocked}
        onReviewFaxDocument={EFAX_INBOUND_SOURCE_BUILD&&visitLinked?receiveFaxDocument:undefined}
        onReviewProviderFaxDocument={FAX_INBOUND_SOURCE_BUILD&&visitLinked?receiveProviderFaxDocument:undefined}
        initialScreen={settingsEntry} guidedConnections={CONNECTION_ONBOARDING_BUILD} connectionIdentity={authenticated ?? undefined} onConnectionAccessLost={failure}
        members={authenticated&&practiceAccess?<PracticeAccessPanel identity={authenticated} access={practiceAccess} onBusyChange={reportAccessBusy}/>:undefined}
        google={GOOGLE_CONNECTION_BUILD&&authenticated?<AccountRecoveryContext.Provider value={accountAccess}>
          <GoogleConnectionPanel identity={authenticated} onBusyChange={reportGoogleBusy} onAuthenticationLost={failure}
            messageWorkLocked={locked||captureNavigationLocked||captureDraftLocked||connectionLocks.googleMessages||connectionLocks.googleCalendar}
            onOpenMessageWork={GOOGLE_MESSAGE_BUILD?()=>{setGoogleCalendarOpen(false);setGoogleMessageOpen(true);}:undefined}
            calendarWorkLocked={locked||captureNavigationLocked||captureDraftLocked||connectionLocks.googleCalendar||connectionLocks.googleMessages}
            onOpenCalendarWork={GOOGLE_CALENDAR_BUILD?()=>{setGoogleMessageOpen(false);setGoogleCalendarOpen(true);}:undefined}
            messageWork={GOOGLE_MESSAGE_BUILD&&googleMessageOpen?controls=><GoogleMessageMount identity={authenticated}
              workspace={visitLinked&&workspace?{id:workspace.id,label:workspace.label,revision:workspace.revision}:null}
              currentSources={workspace?.entries.filter(entry=>entry.kind==='google_message'&&!!entry.google_source_state)
                .map(entry=>({entry_id:entry.id,state:entry.google_source_state!}))}
              locked={locked||captureNavigationLocked||captureDraftLocked||connectionLocks.google||connectionLocks.googleCalendar}
              recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked||connectionLocks.google||connectionLocks.googleCalendar}
              onBusyChange={reportGoogleMessageBusy} onAuthenticationLost={failure} onSaved={receiveGoogleSource}
              onRequestFullMailAccess={controls.requestFullMailAccess} fullMailAccessBusy={controls.fullMailAccessBusy}
              onRefreshVisit={refreshGoogleVisit} onAskChief={source=>void prepareGoogleChief(source)}
              onChooseVisit={()=>{if(locked||connectionNavigationLocked)return;googleVisitSelection.current='message';setSettingsOpen(false);void loadEncounters();}}/>:undefined}
            calendarWork={GOOGLE_CALENDAR_BUILD&&googleCalendarOpen?controls=><GoogleCalendarMount identity={authenticated}
              workspace={visitLinked&&workspace?{id:workspace.id,label:workspace.label,revision:workspace.revision}:null}
              currentSources={workspace?.entries.filter(entry=>entry.kind==='google_calendar'&&!!entry.calendar_source_state).map(entry=>({entry_id:entry.id,state:entry.calendar_source_state!}))}
              locked={locked||captureNavigationLocked||captureDraftLocked||connectionLocks.google||connectionLocks.googleMessages}
              recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked||connectionLocks.google||connectionLocks.googleMessages}
              onBusyChange={reportGoogleCalendarBusy} onAuthenticationLost={failure} onSaved={receiveGoogleSource}
              onRequestCalendarAccess={controls.requestCalendarAccess} calendarAccessBusy={controls.calendarAccessBusy}
              onRefreshVisit={refreshGoogleVisit} onAskChief={source=>void prepareGoogleChief(source,'google_calendar')}
              onChooseVisit={()=>{if(locked||connectionNavigationLocked)return;googleVisitSelection.current='calendar';setSettingsOpen(false);void loadEncounters();}}/>:undefined}/>
        </AccountRecoveryContext.Provider>:undefined}
        microsoft={MICROSOFT_CONNECTION_BUILD&&authenticated?<MicrosoftConnectionPanel identity={authenticated} onBusyChange={reportMicrosoftBusy} onAuthenticationLost={failure}/>:undefined}
        scheduling={SCHEDULING_LOGIN_BUILD&&authenticated?<SchedulingConnectionPanel identity={authenticated} onBusyChange={reportSchedulingBusy} onAuthenticationLost={failure} onObserved={reportSchedulingObservation}/>:undefined}
        core={CORE_CONNECTION_BUILD&&authenticated?<CoreConnectionPanel identity={authenticated} onBusyChange={reportCoreBusy} onAuthenticationLost={failure} openBlocked={locked||captureNavigationLocked||captureDraftLocked} onOpenNotebook={command=>open(undefined,command)}/>:undefined}
        teamSummary={team?.revision ? `${team.configuration.bots.filter(bot => !bot.retired).length} coworkers · Names, instructions & preferences` : 'Choose your coworkers and make them yours'}
        teamDirty={!!team && !!teamDraft && teamConfigurationChanged(team.configuration,teamDraft)} onClose={closeSettings}
        team={team && teamDraft ? <TeamConfigurationFlow resetToken={setupEpoch} active={settingsOpen} identity={(authenticated || identity)!}
          team={team} draft={teamDraft} setDraft={setTeamDraft} selected={selected} setSelected={setSelected}
          locked={locked} inputLocked={recoveryBlocked||conflict||pending?.type==='team'||activityBusy} setupAvailable={setupProjection?.team_revision === team.revision}
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
      /></AccountRecoveryContext.Provider>}
      {privateRecordingEntry&&<div className="private-recording-host" ref={recordingHost}><PrivateRecordingPanel minimized={recordingMinimized} onExpand={()=>setRecordingMinimized(false)} onMinimize={()=>setRecordingMinimized(true)} identity={privateRecordingEntry.identity} scope={privateRecordingEntry.scope}
        platform={privateRecordingEntry.identity.mode==='clerk_jwt'&&privateRecordingEntry.identity.nativeSession?'ios':'desktop'}
        isCurrent={()=>recordingCurrent(privateRecordingEntry)} authorize={privateRecordingEntry.authorize}
        title={privateRecordingEntry.title} recordingId={privateRecordingEntry.recordingId} prepareNotebook={privateRecordingEntry.prepareNotebook}
        onTranscribe={CAPTURE_WORKSPACE_BUILD?async(result,recordingId)=>{
          const entry=privateRecordingEntry;if(!recordingCurrent(entry))throw new WorkspaceApiError(403);
          await returnPrivateRecordingNotebook(entry,result);setPrivateRecordingEntry(null);setPrivateRecordingBusy(false);
          if(authenticated===entry.identity&&journal.current?.scope===entry.scope)
            setSavedRecordingEntry({recordingId,scope:entry.scope,platform:entry.identity.mode==='clerk_jwt'&&entry.identity.nativeSession?'ios':'desktop',workspaceId:result.workspace.id,identity:entry.identity,originWorkspace:result.workspace});
        }:undefined}
        onBusyChange={setPrivateRecordingBusy} onSaved={()=>setPrivateRecordingListEpoch(value=>value+1)} onAccessLost={failure}
        onNotebookPrepared={(result,recordingId)=>session.recording.attachNotebook(privateRecordingEntry,result,recordingId)}
        onClose={()=>{const returnToNotebook=!!privateRecordingEntry.returnWorkspaceId&&workspace?.id===privateRecordingEntry.returnWorkspaceId&&recordingCurrent(privateRecordingEntry);
          setPrivateRecordingEntry(null);setPrivateRecordingBusy(false);setSettingsOpen(false);setPracticeOpen(false);setPracticePage(returnToNotebook?'notebook':'home');setPrivateRecordingListEpoch(value=>value+1);}}
        onNotebook={async result=>{if(!recordingCurrent(privateRecordingEntry))throw new WorkspaceApiError(403);
          await returnPrivateRecordingNotebook(privateRecordingEntry,result);setPrivateRecordingEntry(null);setPrivateRecordingBusy(false);setPrivateRecordingListEpoch(value=>value+1);}}/></div>}
      {authenticated&&<div ref={recordingHome} tabIndex={-1} hidden={!!privateRecordingEntry&&!recordingMinimized||settingsOpen||practicePage!=='home'}><PracticeHome identity={authenticated} recovery={accountAccess??null} team={team} teamUnchanged={initialTeamUnchanged}
        nativeCompact={nativeHome}
        locked={!!privateRecordingEntry||busy||!!pending||conflict||recoveryState==="failed"||recoveryBlocked||captureNavigationLocked||captureDraftLocked} onBusyChange={setHomeBusy} onAccessLost={failure}
        onUseTeam={()=>{if(initialTeamUnchanged)saveTeam();else void openSettings();}} onSettings={()=>void openSettings()} onVisits={()=>void loadEncounters()}
        onConnections={()=>void openSettings('connections')} onPracticeWork={()=>{setPracticeOpen(true);setPracticeOpened(true);}}
        onRecord={CAPTURE_WORKSPACE_BUILD?startPrivateRecording:undefined}
        recordingActive={!!privateRecordingEntry} openRecordingRequest={privateRecordingRequest}
        recordings={privateRecordings&&privateRecordings.identity===authenticated&&privateRecordings.generation===generation.current&&privateRecordings.scope===journal.current?.scope?privateRecordings.rows:undefined} onReopenRecording={reopenPrivateRecording}
        onOpened={openPrivateNotebook} onNoteOpened={value=>openPrivateNotebook(value,'notebook')}/></div>}
      <section hidden={settingsOpen||practicePage!=='visits'} className={`team-welcome${encounters ? " team-welcome-choosing" : ""}`}><p className="team-kicker">{encounters ? "YOUR VISITS" : "YOUR PRACTICE"}</p>
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
        {workspace&&practicePage==='visits'&&!settingsOpen&&<button className="team-phone-notebook-return" disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={goNotebook}>Current notebook</button>}
        {authenticated&&encounters&&<VisitCatalog identity={authenticated} visits={encounters} locked={busy||!!pending} recordingActive={!!privateRecordingEntry}
          onOpen={appointmentId=>void open(appointmentId)} onRecord={CAPTURE_WORKSPACE_BUILD&&(!team||team.capture?.enabled)?appointmentId=>void open(appointmentId,undefined,undefined,true):undefined}
          onPrivateNote={workspaceId=>{if(privateRecordingEntry||pending||busy)return;void workspaceApi.openPrivateDraft(authenticated,workspaceId).then(openPrivateNotebook).catch(failure);}}
          onConnections={()=>void openSettings('core')}/>}
        <p className="team-fine">Notes and private drafts do not need email or calendar setup.</p>
      </section>
      {workspace&&<div className="workspace-notebook" data-native-private-note={nativePrivateNote} hidden={practicePage!=="notebook"}>
        <section hidden={settingsOpen||savedRecordingFocused} className="team-encounter-heading"><div><p className="team-kicker">{workspace.private_draft?.state==='unlinked'?'PRIVATE NOTE':'ENCOUNTER NOTEBOOK'}</p><h1>{workspace.notebook?.title??workspace.label}</h1>
          <p>{workspace.private_draft?.state==='unlinked'?'No patient yet · Unlinked note':workspace.label+' · Linked visit'}{workspace.notebook?.created_at?' · '+new Date(workspace.notebook.created_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}):''}</p>
          <button className="team-subtle" disabled={busy || !!pending || handoffReviewPending || !!privateRecordingEntry || privateRecordingBusy} onClick={() => void refresh()}>Refresh encounter</button>
          {import.meta.env.VITE_COSMANEURA_RECORD_ENABLED === "true" && authenticated && visitLinked && team?.capture?.enabled &&
            <CoreRecordLink key={workspace.id} identity={authenticated} workspaceId={workspace.id}
              locked={busy || !!pending || captureNavigationLocked || recoveryBlocked} onDenied={failure} />}</div>
          <nav aria-label="Encounter stage" className="team-stages" hidden={nativePrivateNote}>{["Before", "During", "After"].map(value => <button key={value} aria-pressed={stage === value} onClick={() => {
            setStage(value);const role=({Before:'visit_prep',During:'scribe',After:'follow_up'})[value];
            const helper=team?.configuration.bots.find(bot=>bot.role===role&&!bot.retired&&!bot.instance_id);if(helper)setSelected(botAddress(helper));
            setPanel(value==='After'?'Review':'Notebook');setMobilePanel(value==='After'?'Review':'Notebook');
          }}>{value}</button>)}</nav>
        </section>
        <div ref={savedRecordingHost} className="saved-recording-flow" data-focused={savedRecordingFocused} hidden={savedRecordingNotebookOpen}>
        {practicePage==='notebook'&&CAPTURE_WORKSPACE_BUILD&&authenticated&&team&&savedRecordingEntry?.identity===authenticated&&savedRecordingEntry.workspaceId===workspace.id&&!savedRecordingEntry.visitResolved&&!savedRecordingEntry.binding&&
          <RecordingVisitPanel entry={savedRecordingEntry} identity={authenticated} origin={workspace} team={team} locked={locked||captureNavigationLocked||captureDraftLocked||note!==latestNote}
            taskBot={scribe?{selection:{address:botAddress(scribe),team_revision:team.revision},name:scribe.name,enabled:scribe.enabled&&team.revision>0,includeNotebook:scribe.include_notebook}:undefined}
            isCurrent={()=>authenticated===privateRecordingLive.current.authenticated&&journal.current?.scope===savedRecordingEntry.scope}
            onSelected={async(target,binding,transcriptionGesture)=>{const entry=savedRecordingEntry,selectedOwner=privateRecordingLive.current,selectedRoute=routeSequence.current;
              if(selectedOwner.authenticated!==entry.identity||selectedOwner.generation!==generation.current||journal.current?.scope!==entry.scope)return;
              const openingGeneration=generation.current+1;await openPrivateNotebook({identity:authenticated,workspace:target,team});
              if(privateRecordingLive.current.authenticated===entry.identity&&generation.current===openingGeneration&&routeSequence.current===selectedRoute&&
                journal.current?.scope===entry.scope&&journal.current.value===selectedOwner.editorJournal&&journal.current.serverScope===selectedOwner.editorScope)
                setSavedRecordingEntry({...entry,workspaceId:target.id,originWorkspace:entry.originWorkspace??workspace,visitResolved:true,...(binding?{binding}:{}),transcriptionGesture});}}/>}
        {practicePage==='notebook'&&CAPTURE_WORKSPACE_BUILD&&authenticated&&team&&savedRecordingEntry?.identity===authenticated&&savedRecordingEntry.workspaceId===workspace.id&&(!!savedRecordingEntry.binding||savedRecordingEntry.visitResolved===true)&&
          <SavedRecordingTranscriptionPanel key={savedRecordingEntry.recordingId} entry={savedRecordingEntry} identity={authenticated} workspace={workspace} team={team}
            isCurrent={()=>authenticated===privateRecordingLive.current.authenticated&&journal.current?.scope===savedRecordingEntry.scope}
            locked={locked} notesEnabled={CAPTURE_NOTES_BUILD&&team.capture?.notes_enabled===true} onDraftLock={setCaptureDraftLocked}
            onReviewDraft={useCoreDraft} onCurrentDraft={setObservedCaptureDraft} scratchpad={workspace.entries.filter(e=>e.kind==='scratchpad').at(-1)}
            notebookDirty={note!==latestNote} onNotebook={()=>{setSavedRecordingNotebook(savedRecordingEntry);setPanel('Notebook');setMobilePanel('Notebook');}}
            onRecordings={goHome} onNavigationLock={setCaptureNavigationLocked}
            taskBot={scribe?{selection:{address:botAddress(scribe),team_revision:team.revision},name:scribe.name,enabled:scribe.enabled&&team.revision>0,includeNotebook:scribe.include_notebook}:undefined}/>}
        </div>
        {authenticated&&workspace.private_draft&&!savedRecordingEntry&&<PrivateDraftLinkPanel identity={authenticated} workspace={workspace} recovery={editorAccess??null} forTranscription={!!savedRecordingEntry} compact={nativePrivateNote}
          recoveryLocked={busy||!!pending||recoveryBlocked||captureNavigationLocked||captureDraftLocked}
          locked={busy||homeBusy||!!pending||conflict||recoveryOffers.some(offer=>offer.address===`workspace:${workspace.id}`)||recoveryBlocked||captureNavigationLocked||captureDraftLocked||note!==latestNote}
          onAccessLost={failure} onSaved={latest=>{setWorkspace(latest);setMessage('Private draft linked to the confirmed visit. Your saved history is retained.');}}/>}
        {team?.revision===0&&<div hidden={settingsOpen} className="team-initial-action"><InitialTeamAction
          names={team.configuration.bots.filter(item=>item.enabled&&!item.retired).map(item=>item.name)}
          locked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} unchanged={initialTeamUnchanged}
          onUse={()=>{if(initialTeamUnchanged&&!locked&&!connectionNavigationLocked&&!captureNavigationLocked&&!captureDraftLocked)saveTeam();}}
          onSettings={()=>void openSettings()}/></div>}
        {!savedRecordingEntry && CAPTURE_WORKSPACE_BUILD && authenticated && visitLinked && team?.capture?.enabled &&
          <div hidden={(settingsOpen||practiceOpen)&&!captureNavigationLocked||phoneChiefConversation&&!scribeRecordingOpen&&!captureNavigationLocked}><CapturePanel key={workspace.id} workspaceId={workspace.id} identity={authenticated} encounterLabel={workspace.label}
            notesEnabled={CAPTURE_NOTES_BUILD && team.capture.notes_enabled === true} onDraftLock={setCaptureDraftLocked} onNavigationLock={setCaptureNavigationLocked} onExpandedChange={setScribeRecordingOpen}
            correctionsEnabled={CAPTURE_CORRECTIONS_BUILD && team.capture.corrections_enabled === true}
            scratchpad={workspace.entries.filter(e => e.kind === "scratchpad").at(-1)} notebookDirty={note !== latestNote}
            taskBot={scribe ? {selection: {address: botAddress(scribe), team_revision: team.revision},
              name: scribe.name, enabled: scribe.enabled && team.revision > 0, includeNotebook: scribe.include_notebook} : undefined}
            openRequest={locked || settingsOpen || practiceOpen || practicePage!=="notebook" ? 0 : captureRequest} preferencesScope={team.recovery_scope}
            onNotebook={() => { setPanel("Notebook"); setMobilePanel("Notebook"); }}
            onReviewDraft={useCoreDraft} onCurrentDraft={setObservedCaptureDraft} reviewLocked={locked} /></div>}
        {CAPTURE_WORKSPACE_BUILD && authenticated && visitLinked && team?.capture?.enabled && !settingsOpen && !practiceOpen &&
          <div hidden={phoneChiefConversation&&!scribeSourceBusy}><ExistingScribeSourcePanel key={`scribe-source:${workspace.id}`} workspace={workspace} identity={authenticated}
            openRequest={settingsOpen||practiceOpen?0:recordingSourceRequest}
            locked={baseLocked || captureNavigationLocked || captureDraftLocked || note !== latestNote}
            onBusyChange={setScribeSourceBusy} onAccessLost={failure} onSaved={latest=>{
              setWorkspace(previous=>previous?.id===latest.id&&previous.revision<=latest.revision?latest:previous);
              if(latest.id===workspace.id&&latest.revision>=workspace.revision&&note===latestNote)
                setNote(latest.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'');
              setPanel('Sources');setMobilePanel('Sources');
            }}/></div>}
        {visitLinked && bot?.role === "scribe" && !(CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled) && !settingsOpen &&
          <section className="capture-panel" aria-label="Scribe recording"><header>
            <div className="capture-heading"><h2><span aria-hidden="true">🎙️</span> {bot.name} recording</h2>
              <p className="capture-description">Record a visit here and review Scribe’s draft afterward.</p>
              <div className="capture-state" role="status">Recording needs a connection</div>
              <p className="capture-description">Connect Scribe for this practice to use the recorder.</p></div>
            <button className="team-primary capture-record" disabled={locked || connectionNavigationLocked} onClick={() => void openSettings('connections')}>Set up recording</button>
          </header></section>}
        <div className="workspace-notebook-body" data-native-chat={nativeChat} data-chief-phone={phoneChief} data-chief-tools={phoneChiefToolsVisible} data-view={mobilePanel==='Conversation'?'conversation':'workspace'} hidden={settingsOpen||savedRecordingFocused}>
        <nav className="team-view-switch" aria-label="Conversation and Workspace">
          <button aria-label="Conversation view" aria-pressed={mobilePanel==='Conversation'&&!phoneChiefToolsVisible} onClick={()=>{setMobilePanel('Conversation');setPhoneChatToolsOpen(false);}}>Conversation</button>
          <button aria-label={phoneChief?'Open private note':'Workspace view'} aria-pressed={mobilePanel!=='Conversation'} onClick={()=>{if(phoneChief){chiefNotebookFocus.current={workspace:workspace.id,generation:generation.current};setPanel('Notebook');setMobilePanel('Notebook');}else setMobilePanel(panel);}}>{phoneChief?'Private note':'Workspace'}</button>
          {CAPTURE_WORKSPACE_BUILD&&authenticated&&workspace.private_draft?.state==='unlinked'&&!visitLinked&&
            <button aria-label="Start a private recording" disabled={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={startNotebookRecording}>
              <span aria-hidden="true">🎙️ </span>Record privately</button>}
          {!savedRecordingEntry&&CAPTURE_WORKSPACE_BUILD&&authenticated&&visitLinked&&team?.capture?.enabled&&
            <button aria-label="Open visit recorder" disabled={locked||captureDraftLocked||!scribe?.enabled} onClick={()=>setCaptureRequest(value=>value+1)}>
              <span aria-hidden="true">🎙️ </span>Record visit</button>}
          {nativeSavedRecording?<button aria-label={nativeChat?'Back to Scribe':'Open Scribe review'} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={()=>setSavedRecordingNotebook(null)}>Scribe</button>:
          phoneChief&&scribe?.enabled&&!scribe.retired&&<button aria-label="Open Scribe" disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked||!!privateRecordingEntry} onClick={()=>{
            setSelected(botAddress(scribe));setSelectedResult(null);setPhoneChatToolsOpen(false);setPanel('Notebook');setMobilePanel('Notebook');
          }}>Scribe</button>}
        </nav>
        {!nativeChat&&!phoneChiefConversation&&teamDrafts}
        {identity && reviewHandoffId && workspace.handoffs?.some(h=>h.id===reviewHandoffId) &&
          <HandoffReviewPanel key={`${workspace.id}:${reviewHandoffId}`} workspace={workspace}
            handoff={workspace.handoffs.find(h=>h.id===reviewHandoffId)!} identity={identity}
            locked={actionLocked||captureNavigationLocked||captureDraftLocked}
            recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked}
            onPendingChange={setHandoffReviewPending}
            onAccessLost={failure} onRefresh={refreshHandoffReview}
            onFreshAssignment={prepareFreshHandoff}
            onSaved={latest=>setWorkspace(previous=>previous?.id===latest.id&&previous.revision<=latest.revision?latest:previous)}
            closeLabel={currentChiefReviewReturn()?'Return to Chief':undefined}
            closeLocked={!!currentChiefReviewReturn()&&(actionLocked||viewNavigationLocked||captureNavigationLocked||captureDraftLocked)}
            onClose={closeTeamReview}
            onRevisionPrepared={id=>{setReviewHandoffId(id);setHandoffReviewPending(false);}}/>}
        <nav className="team-mobile-tabs team-scribe-tabs" aria-label={nativePrivateNote?"Private note view":"Visit view"}>
          {(bot?.role === "scribe" ? ["Notebook", "Conversation", "Review"] : ["Conversation", "Notebook", "Sources", "Review", "Work"]).map(value => <button key={value} data-panel={value} aria-pressed={mobilePanel === value}
            onClick={() => { setMobilePanel(value); if (value !== "Conversation") setPanel(value); }}>{bot?.role === "scribe" ? ({Notebook:nativePrivateNote?"Notes":"Visit notes",Conversation:"Ask Scribe",Review:"Review note"})[value] : nativePrivateNote&&value==="Notebook"?"Notes":value}</button>)}
          {bot?.role === "scribe" && <details data-menu className="team-visit-more"><summary>More</summary><div>{["Sources", "Work"].map(value => <button key={value} aria-pressed={mobilePanel === value}
            onClick={event => {setPanel(value); setMobilePanel(value); const menu = event.currentTarget.closest('details'); if (menu) menu.open = false;}}>{value === "Sources" ? "Saved sources" : "Follow-up work"}</button>)}</div></details>}
        </nav>
        <ol className="notebook-progress" aria-label="Note progress" hidden={nativePrivateNote}>
          {['Notes','Draft','Review','Saved'].map((step,index)=><li key={step} aria-current={index===(reviewState==='saved'?3:busy&&pending?.type==='ask'?1:panel==='Review'?2:0)?'step':undefined}>{step}</li>)}
        </ol>
        <div className="team-content" data-mobile-panel={mobilePanel} data-scribe-focus="true"><section className="team-conversation" aria-label="Encounter conversation">
          <header ref={conversationHeaderRef} className="team-conversation-header">{nativeChat&&<button className="native-chat-home" aria-label="Home" disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={goHome}>‹ Home</button>}<BotAvatar role={bot?.role ?? "scribe"}
            active={busy && pending?.type === "ask" && pending.body.role === selected||workspace.entries.some(e=>modelActive(e)&&e.model_request?.bot.address===selected)}
            enabled={!!bot?.enabled && !bot.retired && !!team?.revision && !settingsOpen && !practiceOpen} />
            <div><h2>{bot?.name ?? "Your team"}</h2><p>{template?.description}</p></div>
            {phoneChiefConversation?<button className="team-subtle" aria-controls={`chief-tools-${workspace.id}`} aria-expanded={phoneChiefToolsVisible}
              disabled={viewNavigationLocked} onClick={()=>phoneChiefToolsVisible?returnToPhoneChat():openPhoneChatTools()}>Tools</button>:
              <button className="team-subtle" onClick={() => setSettingsOpen(true)}>Skills & settings</button>}</header>
          <div className="mobile-chat-scroll" ref={mobileChatFrame.scrollRef} onScroll={mobileChatFrame.onScroll}
            role={nativeChat?'region':undefined} aria-label={nativeChat?(phoneChiefToolsVisible?'Chief tools':'Conversation history'):undefined} tabIndex={nativeChat?0:undefined}>
          <div id={`chief-tools-${workspace.id}`} className="team-conversation-tools" hidden={phoneChiefConversation&&!phoneChiefToolsVisible}>
          {phoneChiefConversation&&<header className="chief-tools-heading"><h3>Chief tools</h3><button className="team-subtle" disabled={viewNavigationLocked} onClick={returnToPhoneChat}>Back to chat</button></header>}
          {phoneChiefToolsVisible&&thought!==''&&!(nativeChat&&clinicalTeamExpanded)&&<p className="team-fine chief-tools-draft" role="status">Your directions are kept in this plan. Prepare Follow-up and Research includes them with the saved note.</p>}
          {(nativeChat||phoneChiefConversation)&&teamDrafts}
          {(!chiefNoteCompose||phoneChiefToolsVisible)&&clinicalTeamDrafts}
          {prepAvailable && bot && authenticated && team &&
            <SessionPrepPanel key={prepEpoch} workspaceId={workspace.id} identity={authenticated}
              bot={{address: botAddress(bot), team_revision: team.revision}}
              enabled={bot.enabled && bot.include_evidence && team.revision > 0} locked={locked} onAccessLost={failure}
              onBriefViewed={at=>setBriefViewed(at?{workspace:workspace.id,owner:authenticated,teamRevision:team.revision,at}:null)}
              selected={!!selectedPrep} onSelect={team.llm.enabled&&!bot.blocked_capabilities?.includes("model_answer")?
                selection=>{setPrepSelection(selection?{scope:prepScope,selection}:null);if(selection){setPhoneNoteTask(null);setPhoneChatToolsOpen(false);}}:undefined} />}
          {visitLinked && bot && supportsSkill(bot, "encounter_prep") && ENCOUNTER_PREP_BUILD && authenticated && team?.capture?.prep_enabled &&
            <details className={prepAvailable?"team-additional-prep":undefined} open={prepAvailable?undefined:true}>
            <summary hidden={!prepAvailable}>Other saved visit context</summary><EncounterPrepPanel workspaceId={workspace.id} identity={authenticated}
              bot={{address: botAddress(bot), team_revision: team.revision}} name={bot.name}
              enabled={bot.enabled && bot.include_evidence && team.revision > 0} locked={locked}
              entryRevision={workspace.revision} workEnabled={team.capture.prep_work_enabled===true} onAccessLost={failure}
              onChanged={revision=>{if(revision!==workspace.revision){setConflict(true);void refresh();}}} /></details>}
          {visitLinked && bot && supportsSkill(bot,"calendar_availability") && SCHEDULING_PATIENT_BUILD && authenticated && team &&
            <SchedulingPatientPanel key={`${workspace.id}:${connectionGeneration}`} workspace={workspace} identity={authenticated} observationStamp={schedulingObservation}
              enabled={!!team.scheduling?.enabled && bot.enabled && team.revision>0}
              locked={actionLocked||handoffReviewPending||connectionEditorsLocked||captureNavigationLocked||captureDraftLocked}
              recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||handoffReviewPending||connectionEditorsLocked||captureNavigationLocked||captureDraftLocked}
              onBusyChange={reportSchedulingPatientBusy} onAccessLost={failure}/>}
          {visitLinked && bot && supportsSkill(bot, "calendar_availability") && SCHEDULING_BUILD && authenticated && team && (team.scheduling?.enabled || APPOINTMENTS_BUILD) &&
            <SchedulingPanel workspaceId={workspace.id} identity={authenticated}
              bot={{address: botAddress(bot), team_revision: team.revision}} name={bot.name}
              enabled={!!team.scheduling?.enabled && bot.enabled && bot.include_evidence && team.revision > 0} locked={locked} onAccessLost={failure} />}
          {visitLinked&&bot&&supportsSkill(bot,"membership_review")&&authenticated&&team&&<MembershipAnalysisPanel
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
          {bot?.role === "research" && <>{authenticated && team ? <ResearchPanelLoader key={`${workspace.id}:${botAddress(bot)}`}
            identity={authenticated} workspaceId={workspace.id} workspaceRevision={workspace.revision} bot={{address:botAddress(bot),team_revision:team.revision}}
            enabled={bot.enabled&&!bot.retired&&team.revision>0} locked={locked||captureNavigationLocked||captureDraftLocked}
            analysis={{workspace,model:team.llm,modelBlocked:bot.blocked_capabilities?.includes('model_answer'),onSubmit:async body=>{
              if(locked||captureNavigationLocked||captureDraftLocked||!team.llm.enabled||!bot.enabled||bot.retired||bot.blocked_capabilities?.includes('model_answer')||body.role!==botAddress(bot)||body.expected_revision!==workspace.revision||body.team_revision!==team.revision||!body.research_analysis)return;
              setSavedResearchChat(true);await saveModel({type:'ask',model_contract:1,origin:'durable_admission_v1',body},'submit');
            }}}
            onDenied={failure} onChanged={revision=>{if(revision!==workspace.revision){setConflict(true);void refresh();}}}/>
            : <p className="research-status">Sign in to use private Research settings and check public source connections.</p>}
            <button className="team-subtle" aria-expanded={savedResearchChat} onClick={()=>setSavedResearchChat(value=>!value)}>Saved encounter conversation</button></>}
          {authenticated && <details><summary>Team connector tools</summary><ConnectorToolsPanel identity={authenticated}
            locked={locked||captureNavigationLocked||captureDraftLocked} onAuthenticationLost={failure}/></details>}
          {bot?.role==='research'&&authenticated&&agentResearchRecovery&&<AgentResearchReviewPanel
            identity={authenticated} workspaceId={workspace.id} recovery={agentResearchRecovery}
            locked={lockedWithoutAgentResearch||captureNavigationLocked||captureDraftLocked} onBusyChange={reportAgentResearchBusy} onAuthenticationLost={failure}
            onReady={proposal=>{if(locked||proposal.bot!==selected)return;setSavedResearchChat(true);
              setThought(previous=>previous.trim()?previous+'\n\n'+`Run the reviewed public query for revision ${proposal.revision_id} and report its actual result.`:
                `Run the reviewed public query for revision ${proposal.revision_id} and report its actual result.`);
              setMobilePanel('Conversation');setQuestionFocus(value=>value+1);}}/>}
          {(nativeChat||phoneChiefConversation)&&chiefStarters}
          {phoneChiefConversation&&<button className="team-subtle chief-tools-settings" disabled={viewNavigationLocked} onClick={()=>void openSettings()}>Skills & settings</button>}
          </div>
          <div hidden={phoneChiefToolsVisible || bot?.role==='research'&&!savedResearchChat || visitPrepReader&&!turns.length&&pending?.type!=='ask'} className="team-messages" aria-live="polite" aria-relevant="additions">
            {!turns.length && !visitPrepReader && !chiefNoteCompose && <div className="team-conversation-empty"><BotAvatar role={bot?.role ?? "scribe"} large greeting={!busy}
              enabled={!!bot?.enabled && !bot.retired && !!team?.revision && !settingsOpen && !practiceOpen} />
              <h3>{phoneChiefConversation?"What would you like to work on?":stage === "Before" ? "A clear start to the visit" : stage === "During" ? "Space to think and take notes" : "Keep the next step in view"}</h3>
              <p>{team?.llm.enabled ? phoneChiefConversation?"Write naturally. Chief can help organize your notes and coordinate your team.":"Ask a question, organize your notes, or think through the next step. Your team works from the saved context you choose." : "Review saved sources with your team. Advanced skills will connect here as their services become ready."}</p>
              {bot?.role!=='chief'&&<button disabled={locked || !team?.revision || !bot?.enabled} onClick={() => ask(template?.prompt)}>{template?.prompt ?? "Review this encounter"}<span aria-hidden="true"> ↗</span></button>}</div>}
            {turns.map(entry => <div className="team-turn" key={entry.id} id={`turn-${entry.id}`} tabIndex={-1}><article className="team-human-message"><small>{entry.kind === "handoff_result" ? "Brief from Chief" : "You"}</small><p>{clinicalRequestDisplay(entry.content)}</p></article>
              {entry.reply && <article className="team-bot-message"><header><BotAvatar role={entry.reply.role} />
                <strong>{entry.reply.agent_name}</strong><span className="team-pill">{entry.reply.backend === "azure_gpt41_work_status_v1" ? "Saved work status" : entry.reply.backend === "azure_gpt41_unavailable" ? "GPT-4.1 unavailable" : entry.reply.backend.startsWith("azure_gpt41") ? "GPT-4.1" : "Local review"}</span>{(entry.kind === "handoff_result" || entry.model_request?.request.kind==='conversation'&&(entry.model_request.request.inbox_analysis||entry.model_request.request.membership_analysis)) && <span className="team-pill pending">{entry.kind === "handoff_result" ? savedDraftReviewLabel(entry) : "Unreviewed draft"}</span>}</header>
                <WorkspaceMarkdown content={entry.reply.content}/><div className="team-citations">{entry.reply.citations.map((citation) => ["membership_work","payment_work"].includes(citation.kind)?<button key={citation.entry_id} onClick={()=>{setPanel("Work");setMobilePanel("Work");}}>{citation.label} · r{citation.revision}</button>:["inbox_message","inbox_triage","session_prep"].includes(citation.kind)?<span key={citation.entry_id}>{citation.label} · r{citation.revision}</span>:<button key={citation.entry_id}
                  onClick={() => { setPanel("Sources"); setMobilePanel("Sources"); setSelectedSource(citation.entry_id); }}>{citation.label}</button>)}</div>
                <details className="team-fine"><summary>{latestSourceRevision > entry.reply.context_revision ? "Newer sources available — ask again to review them" : "Source details"}</summary>Saved context through revision {entry.reply.context_revision}</details>
              </article>}
              {!entry.reply&&entry.model_request&&<article className="team-bot-message"><header><BotAvatar role={entry.model_request.bot.role} active={modelActive(entry)}/>
                <strong>{entry.model_request.bot.name}</strong></header><p>{modelStateLabel(entry.model_request.admission.state)}</p>
                <p className="team-fine">A saved request is not a completed draft or clinical evidence.</p>
                {entry.model_request.request.kind==='conversation'&&<button disabled={busy||recoveryBlocked} onClick={()=>void checkEntryResult(entry)}>Check saved result</button>}</article>}

            </div>)}
            {pending?.type === "ask" && !localQuestionRepresented && <div className="team-turn"><article className="team-human-message"><small>You · {busy?'request in progress':'unconfirmed request'}</small><p>{clinicalRequestDisplay(pending.body.content)}</p></article>
              {busy && <p className="team-thinking" role="status">{team?.configuration.bots.find(b => botAddress(b) === pending.body.role)?.name} is {team?.llm.enabled ? "thinking" : "reviewing"}…</p>}</div>}
            {(!chiefNoteCompose||!phoneNoteMatches)&&nativeNoteShortcut}
            {chiefNoteCompose&&!phoneChiefToolsVisible&&clinicalTeamDrafts}
            <div ref={conversationEnd} />
          </div>
          {nativeChat&&(clinicalPreparing||busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected||inlineModelRecovery||message)&&
            <p id="team-request-progress" className="team-fine native-chat-progress" role="status">{clinicalPreparing?'Preparing your private drafts…':busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected?
              `Waiting for ${bot?.name??'your teammate'}’s result. You can keep typing.`:inlineModelRecovery?'Your last message is unconfirmed. Check its saved result above.':message}</p>}
          {inlineModelRecovery&&modelRecovery}
          </div>
          <div hidden={phoneChiefToolsVisible || bot?.role==='research'&&!savedResearchChat} className="team-composer-wrap">
            {!nativeChat&&!phoneChiefConversation&&chiefStarters}
            {!team?.revision ? <p className="team-fine">You can save notes now. Use your team above to start a conversation.</p> :
            <form className="team-composer" onSubmit={event => { event.preventDefault();if(chiefNoteCompose)submitPhoneNoteTask();else ask(); }}>
              {chiefNoteCompose&&<div className="chief-note-compose-context" role="status"><span>Follow-up + Research · v{phoneNoteTask!.selection.note_version}</span>
                <button type="button" className="team-subtle" disabled={viewNavigationLocked} aria-label="Return to regular message" onClick={()=>{setPhoneNoteTask(null);setQuestionFocus(value=>value+1);}}>Message Chief</button></div>}
              {chiefNoteCompose&&(!phoneNoteMatches?<p className="chief-note-compose-attention" role="status">The saved note changed. Choose its current version above; your directions are kept.</p>:phoneNoteDirectionsError?<p className="chief-note-compose-attention" role="status">{phoneNoteDirectionsError}</p>:phoneNoteDirectionsUnsupported?<p className="chief-note-compose-attention" role="status">This practice service needs an update to include your directions with the saved note. Your text is kept.</p>:phoneNoteAlreadyRequested?<p className="chief-note-compose-attention" role="status">These exact drafts are already requested. Review their saved result above.</p>:!phoneNoteTeamReady?<p className="chief-note-compose-attention" role="status">Enable Chief, Follow-up and Research with private draft handoffs to prepare these drafts.</p>:null)}
              {selectedPrep&&!chiefNoteCompose&&<div className="session-prep-included" role="status"><span>Session Prep included · v{selectedPrep.brief_version}</span>
                <button type="button" className="team-subtle" disabled={locked} onClick={()=>setPrepSelection(null)} aria-label="Remove Session Prep from this question">Remove</button></div>}
              {!nativeChat&&busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected&&<p id="team-request-progress" className="team-fine" role="status">
                {`${authenticated?'Your request is saved on this device. ':''}Waiting for ${bot?.name??'your teammate'}’s result. Keep this visit open; review the answer when it appears.`}
              </p>}
              <label className="team-sr-only" htmlFor="team-question">{chiefNoteCompose?'Directions for Chief':'Thought or question'}</label>
              <textarea ref={questionRef} id="team-question" className={chiefNoteCompose?'clinical-team-directions':undefined} aria-describedby={busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected?"team-request-progress":undefined} rows={2} maxLength={4000} disabled={phoneChiefToolsVisible || (nativeChatOwner?!nativeComposerEditable:locked) || !bot?.enabled || !!bot?.retired} value={thought} onChange={e => updateThought(e.target.value)} placeholder={bot?.retired ? `${bot.name} is retired. Saved history remains available.` : bot?.enabled ? chiefNoteCompose?'Optional directions for these drafts…':phoneChiefConversation?`Message ${bot.name}…`:`Ask ${bot.name} about this encounter…` : `${bot?.name} is paused. Enable in settings.`}
                onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing&&
                  !(authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession)){event.preventDefault();if(!locked){if(chiefNoteCompose)submitPhoneNoteTask();else if(thought.trim())ask();}}}}/>
              <div><span>{bot?.name} <span className="team-fine">· {selectedPrep?"saved encounter + selected brief":"saved encounter only"}</span></span><button className="team-send" disabled={locked || !!nativeChatOwner&&!nativeComposerEditable || (chiefNoteCompose?phoneNoteTaskBlocked:!thought.trim()) || !bot?.enabled}
                onPointerDown={event=>{if(nativeChatOwner&&document.activeElement===questionRef.current)event.preventDefault();}} aria-label={chiefNoteCompose?'Prepare Follow-up and Research':'Send message'}>↑</button></div>
            </form>}
            <p className="team-fine">{bot?.blocked_capabilities?.includes("model_answer") ? "AI answers are unavailable for this teammate. You can still check saved sources." : team?.llm.enabled ? phoneChiefConversation?"Review Chief’s answer and sources before using them.":"Ask about this visit. Check the answer and its sources before using it." : "Saved notes are available. AI chat needs a service connection."} {!phoneChiefConversation&&(CAPTURE_WORKSPACE_BUILD&&authenticated&&workspace.private_draft?.state==='unlinked'&&!visitLinked ? "Record privately with Scribe. Choose a patient or visit later." : CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled ? "Use the Scribe visit controls for consented recording." : "Recording is not connected.")}</p>
          </div>
        </section><aside className="team-notebook-panel">
          <nav aria-label="Encounter materials" className="team-material-tabs">{["Notebook", "Sources", "Review", "Work"].map(value => <button key={value} aria-pressed={panel === value} onClick={() => setPanel(value)}>{value}</button>)}</nav>
          <div className="team-task-context" aria-label="Current task" hidden={nativePrivateNote}><strong>{({Notebook:"Visit notebook",Sources:"Check saved sources",Review:"Review visit note",Work:"Drafts and human follow-up"} as Record<string,string>)[panel]}</strong>
            <span>{panel==='Work'?'Confirm who owns the next action.':panel==='Sources'?'Read the material behind the note.':panel==='Review'?'Save the note, then record your review.':'Save your jottings, then review the visit note.'}</span></div>
          <div className="team-material-content" ref={materialRef}>
            {panel==='Work'&&<EncounterWorkSummary workspace={reviewWorkspace!} identity={authenticated||identity||undefined} locked={locked||connectionNavigationLocked}
              onReview={()=>{setPanel('Review');setMobilePanel('Review');}} onPracticeWork={()=>{setPracticeOpen(true);setPracticeOpened(true);}} onAccessLost={failure}/>}
            <div hidden={panel !== "Review"}>
              {workspace.note?.latest&&<p className="team-fine">Prepare Follow-up and Research shares this exact saved note, version {workspace.note.latest.version}, with your private team and asks Chief for drafts. It does not send a patient email or run a public search.</p>}
              <NoteReview key={workspace.id} active={panel === "Review"} workspace={reviewWorkspace!} locked={locked || captureDraftLocked} onStateChange={setReviewState}
              onTeamDrafts={authenticated&&team?.configuration.bots.some(item=>item.role==='chief'&&item.enabled&&!item.retired)?openClinicalTeamDrafts:undefined}
              onSave={operation => void save(operation)} onSources={() => { setPanel("Sources"); setMobilePanel("Sources"); }} /></div>
            {visitLinked&&<div hidden={panel !== "Work"}><FollowUpWork key={workspace.id} workspace={reviewWorkspace!} locked={locked || captureDraftLocked}
              onSave={operation => void save(operation)} onReview={() => {setPanel("Review");setMobilePanel("Review");}} /></div>}
            {panel === "Notebook" && <>
              {nativePrivateNote&&notebookEditor}
              {notebookActions}
              {visitLinked && stage === "During" && !(CAPTURE_WORKSPACE_BUILD && authenticated && team?.capture?.enabled) && <div className="team-capture"><span>Recording awaits Scribe connection</span><button disabled>Start recording</button><button disabled>Voice instruction</button></div>}
              {!nativePrivateNote&&<p className="team-fine">Your working notebook. Shape the visit note in Review when you are ready.</p>}
              {!nativePrivateNote&&notebookEditor}
              <details className="team-history"><summary>Saved notebook history</summary>{workspace.entries.filter(e => e.kind === "scratchpad").map(e => <article key={e.id}><small>Revision {e.revision}</small><p>{e.content}</p></article>)}</details>
            </>}
            {faxSourceOffer&&authenticated===faxSourceOffer.identity&&generation.current===faxSourceOffer.generation&&workspace.id===faxSourceOffer.workspaceId&&<div hidden={panel!=='Sources'}><EFaxSourceReviewMount identity={faxSourceOffer.identity} offered={faxSourceOffer.document} visit={{id:workspace.id,label:workspace.label,revision:workspace.revision}} locked={locked||captureNavigationLocked||captureDraftLocked} currentSources={workspace.entries.filter(e=>e.kind==='efax_inbound_source'&&e.fax_source_state).map(e=>({entry_id:e.id,state:e.fax_source_state!}))} onBusyChange={reportFaxSourceBusy} onAuthenticationLost={failure} onSaved={(_,latest)=>receiveGoogleSource(latest)} onAskChief={value=>void prepareFaxChief(value)} onRefreshDocument={refreshFaxDocument}/></div>}
            {providerFaxSourceOffer&&authenticated===providerFaxSourceOffer.identity&&generation.current===providerFaxSourceOffer.generation&&workspace.id===providerFaxSourceOffer.workspaceId&&<div hidden={panel!=='Sources'}><FaxSourceReviewMount identity={providerFaxSourceOffer.identity} offered={providerFaxSourceOffer.document} visit={{id:workspace.id,label:workspace.label,revision:workspace.revision}} locked={locked||captureNavigationLocked||captureDraftLocked} currentSources={workspace.entries.filter(e=>e.kind==='fax_inbound_source'&&e.practice_fax_source_state).map(e=>({entry_id:e.id,state:e.practice_fax_source_state!}))} onBusyChange={reportProviderFaxSourceBusy} onAuthenticationLost={failure} onSaved={(_,latest)=>receiveGoogleSource(latest)} onAskChief={value=>void prepareProviderFaxChief(value)} onRefreshDocument={refreshProviderFaxDocument}/></div>}
            {panel === "Sources" && <EncounterSources workspace={workspace} selectedSource={selectedSource} locked={locked}
              briefViewedAt={briefViewed?.workspace===workspace.id&&briefViewed.owner===authenticated&&briefViewed.teamRevision===team?.revision?briefViewed.at:undefined}
              onPrep={team?.configuration.bots.some(member=>member.role==='visit_prep'&&member.enabled)?()=>{const reader=team.configuration.bots.find(member=>member.role==='visit_prep'&&member.enabled)!;setSelected(botAddress(reader));setMobilePanel('Conversation');}:undefined}
              source={source} evidence={evidence} setSource={setSource} setEvidence={setEvidence}
              onSave={() => append("evidence", evidence, source)} onNotebook={() => { setPanel("Notebook"); setMobilePanel("Notebook"); }} />}
            {panel === "Work" && <>
              <h2>Linked work</h2><p className="team-fine">Existing work and approvals stay together. Private notes are not copied.</p>
              {workspace.entries.filter(e => e.kind === "work_link").map(e => <article className="team-work-card" key={e.id}>{e.ticket ? <><span className="team-kicker">EXISTING WORK</span><h3>{e.ticket.lane.replaceAll("_", " ")}</h3><span className="team-pill">{e.ticket.state.replaceAll("_", " ")}</span></> : "Linked work is no longer available in this encounter."}</article>)}
              {workspace.work_candidates.filter(t => !workspace.follow_ups?.some(f => f.ticket_id === t.id) && !workspace.entries.some(e => e.ticket?.id === t.id)).map(t => <button className="team-link-work" key={t.id} disabled={locked} onClick={() => void save({ type: "link", body: { expected_revision: workspace.revision, idempotency_key: crypto.randomUUID(), ticket_id: t.id } })}>Link existing {t.lane.replaceAll("_", " ")} work</button>)}
              {authenticated && visitLinked && <div ref={faxWorkRef} tabIndex={-1} aria-label="Messaging and fax work"><VendorWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked}
                followUpBots={team?.members.filter(bot=>bot.role==='follow_up'&&bot.agent_id&&team.configuration.bots.some(settings=>settings.role==='follow_up'&&(settings.instance_id??null)===(bot.instance_id??null)&&settings.enabled&&!settings.retired&&!settings.blocked_capabilities?.includes('model_answer'))).map(bot=>({agent_id:bot.agent_id!,name:bot.name}))}
                onChanged={()=>{setConflict(true);void refresh();}} /></div>}
              {authenticated && visitLinked && FINANCE_WORK_BUILD && <FinanceWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked} />}
              {authenticated && visitLinked && PORTAL_WORK_BUILD && <PortalWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked} />}
              {authenticated && visitLinked && MEMBERSHIP_WORK_BUILD && <MembershipWorkspaceMount identity={authenticated} workspaceId={workspace.id} locked={locked} />}
              {!authenticated && <p className="team-fine">Open a signed workspace to prepare and review messages and faxes.</p>}</>}
          </div>
        </aside></div></div>
      </div>}
      </div>
    </div>
  </main></EditorRecoveryContext.Provider>;
}
