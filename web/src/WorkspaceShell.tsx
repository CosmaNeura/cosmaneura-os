import {MessagesInbox,NewMessagePicker,MessagesThreadHeader,ConversationDetails,LayoutSetting} from './MessagesPresentation';
import {nativePresentationFeedback,setNativePresentation} from './native-presentation';
import {NotebookTitleEditor} from './NotebookTitleEditor';
import type {InboxRenameTarget,InboxPreferencesHost} from './session/inbox-preferences';
import type {ConversationSummary} from './conversations-api';
import {projectConversation} from './session/entries';
import {ConversationEntries} from './ConversationEntries';
import {hasSavedBotContext,latestNotebookText} from './session/composer';
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
import {readWorkspaceRoute,workspaceRouteHash,type WorkspaceRoute} from './workspace-route';
import {deferredWorkspacePanel} from './DeferredWorkspacePanel';
import type {SessionPrepAnalysis} from "./session-prep-analysis-contract";
import {PracticeAccessPanel} from './PracticeAccessPanel';
import {WorkspaceConnectionRecoveryContext,type PracticeAccessContext} from './PracticeAccessGate';
import { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from "react";
import { TeamConfigurationFlow } from "./TeamConfigurationFlow";
import {subscribeNativeWorkspaceForeground} from './native-workspace-foreground';
import {useMobileChatFrame} from './MobileChatFrame';
import {useMessageComposerSize} from './useMessageComposerSize';
import type {AiActivitySelection} from "./model-activity-contract";
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
import { openDraftStore, type DraftStore } from "./draft-store";
import { notebookDraft as makeNotebookDraft, type RecoveryOffer } from "./draft-journal";
import { EditorRecoveryContext } from "./editor-recovery";
import { AccountRecoveryContext } from "./account-recovery";
import { supportsSkill, validRecoveryScope } from "./workspace-api";
import { BotAvatar } from "./BotAvatar";
import { TeamWorkPanel } from "./TeamWorkPanel";
import { HandoffReviewPanel } from "./HandoffReviewPanel";
import {modelActive, type ModelOperation} from "./model-work-request";
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
import {EhrReadTask} from './EhrReadTask';
import {EhrReadProviders} from './EhrReadProviders';
import {EHR_READ_BUILD} from './ehr-read-api';
import type {EhrReadSaved} from './ehr-read-recovery';
import { GOOGLE_MESSAGE_BUILD } from './google-message-api';
import type {GoogleMessageSaved} from './google-message-recovery';
import {EFaxSourceReviewMount} from './EFaxSourceReviewMount';
import {FaxSourceReviewMount} from './FaxSourceReviewMount';
import {FAX_INBOUND_SOURCE_BUILD,type FaxSourceOffer,type FaxSourceReceipt} from './fax-inbound-source-api';
import type {FaxPending} from './fax-inbound-api';
import {EFAX_INBOUND_SOURCE_BUILD,type EFaxSourceOffer,type EFaxSourceReceipt} from './efax-inbound-source-api';
import type {EFaxPending} from './efax-inbound-api';
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
import { WorkspaceApiError, botAddress, type AppendInput,
  type AuthenticatedWorkspaceIdentity, type DraftHandoff, type ProviderTeam, type Workspace, type WorkspaceEntry, type WorkspaceIdentity } from "./workspace-api";
import "./encounter-workspace.css";
import "./messages-presentation.css";


const MembershipAnalysisPanel=deferredWorkspacePanel(()=>import('./MembershipAnalysisPanel').then(module=>module.MembershipAnalysisPanel),'Membership review');
const InboxAnalysisPanel=deferredWorkspacePanel(()=>import('./InboxAnalysisPanel').then(module=>module.InboxAnalysisPanel),'Inbox review');
const PracticeWork=deferredWorkspacePanel(()=>import('./PracticeWork').then(module=>module.PracticeWork),'Practice work');
const PracticeHub=deferredWorkspacePanel(()=>import('./PracticeHub').then(module=>module.PracticeHub),'Practice');
const WorkRoutines=deferredWorkspacePanel(()=>import('./WorkRoutines').then(module=>module.WorkRoutines),'Work briefs');

const isFollowUpRecovery = (draft: RecoveryOffer["draft"]) => draft.kind === "workspace" && draft.pending?.type.startsWith("followUp") === true;
const phoneLayout = () => window.matchMedia?.('(max-width: 600px)')?.matches ?? false;
const deviceStorage=()=>{try{return window.localStorage;}catch{return undefined;}};
const HISTORY_POSITION='cosmas.workspace-history.v1';
function workspaceHistoryPosition(value:unknown):number|null{
  const position=value&&typeof value==='object'?(value as Record<string,unknown>)[HISTORY_POSITION]:null;
  return typeof position==='number'&&Number.isSafeInteger(position)&&position>=0&&position<=1_000_000_000?position:null;
}

export function WorkspaceShell({ onExit, authenticated, accountControls, practiceAccess, draftStorage = openDraftStore }: {
  onExit?: () => void; authenticated?: AuthenticatedWorkspaceIdentity; accountControls?: ReactNode;
  practiceAccess?:PracticeAccessContext;
  draftStorage?: (options: { scope: string; native: boolean }) => Promise<DraftStore>;
}) {
  const [session]=useState(()=>new WorkspaceSession({presentation:{enabled:import.meta.env.VITE_MESSAGES_ENABLED==='true',phone:phoneLayout(),storage:deviceStorage()},initialPage:authenticated?'home':'visits',navigation:{initialRoute:readWorkspaceRoute(window.location.hash)}}));
  const inboxOrganization=useSyncExternalStore(session.inboxPreferences.subscribe,session.inboxPreferences.getSnapshot,session.inboxPreferences.getSnapshot);
  const [inboxRename,setInboxRename]=useState<{target:InboxRenameTarget;identity:AuthenticatedWorkspaceIdentity;scope:string|undefined}|null>(null);
  const {presentationError,conversationInbox,conversationLoading,conversationError,conversationBusy,recordingTransition,researchPending,activityProof,activityBusy,activityContextBusy,activityContextError,activityAttempt,selectedSource,faxSourceOffer,providerFaxSourceOffer,faxSourceBusy,providerFaxSourceBusy,phoneNoteTask,reviewHandoffId,handoffReviewPending,selectedResult,savedResearchChat,settingsOpen,practicePage,practiceOpen,practiceOpened,selected,panel,mobilePanel,stage,entryIntent,researchEntry,settingsEntry,inboxSelection,privateRecordingBusy,privateRecordingEntry,savedRecordingEntry,savedRecordingNotebook,privateRecordings,privateRecordingListEpoch,privateRecordingRequest,clinicalPreparing,homeBusy,setupApproval,setupProjection,setupEpoch,confirmTeamExit,teamSaveExit,identity,connectionError,busy,pending,conflict,message,error,readRetry,
    workspace,encounters,team,teamDraft,note,thought,evidence,source,ehrReview,previousModelRequest,clinicalShareCheck,modelObservation,replacementDraft,modelHashes,schedulingObservation,recoveryOffers,recoveryState,recoveryEpoch}=useWorkspaceSession(session);
  const {setActivityProof,setActivityBusy,setActivityContextBusy,setActivityContextError,setActivityAttempt,setSelectedSource,setFaxSourceBusy,setProviderFaxSourceBusy,setPhoneNoteTask,setReviewHandoffId,setHandoffReviewPending,setSelectedResult,setSavedResearchChat,setSettingsOpen,setPracticePage,setPracticeOpen,setPracticeOpened,setSelected,setPanel,setMobilePanel,setStage,setEntryIntent,setResearchEntry,setSettingsEntry,setInboxSelection,setPrivateRecordingBusy,setPrivateRecordingEntry,setSavedRecordingEntry,setSavedRecordingNotebook,setPrivateRecordingListEpoch,setPrivateRecordingRequest,setClinicalPreparing,setHomeBusy,setSetupApproval,setSetupProjection,setSetupEpoch,setConfirmTeamExit,setTeamSaveExit,setConnectionError,setConflict,setMessage,setError,generation,
    setWorkspace,setTeamDraft,setNote,setThought,setEvidence,setSource,setClinicalShareCheck,setModelObservation,setReplacementDraft,setModelHashes,setSchedulingObservation,setRecoveryState}=session;
  const messagesMode=session.presentation.current()==='messages';
  const [newMessage,setNewMessage]=useState(false),[conversationDetails,setConversationDetails]=useState(false);
  const [contextBot,setContextBot]=useState<string|null>(null),[messagesTaskChoice,setMessagesTask]=useState<'Tools'|'Activity'|null>(null);
  const [captureTransition,setCaptureTransition]=useState(false),[homePending,setHomePending]=useState(false),[privateLinkPending,setPrivateLinkPending]=useState(false);
  const contextBotRef=useRef(contextBot);contextBotRef.current=contextBot;
  const connectionRecovery=useContext(WorkspaceConnectionRecoveryContext);
  const recoveredConnection=useRef({identity:authenticated,sequence:connectionRecovery&&connectionRecovery.identity===authenticated?connectionRecovery.sequence:0});
  const [inboxNavigation,setInboxNavigation]=useState<{selection:InboxDraftSelection;identity:WorkspaceIdentity;generation:number}|null>(null);
  const inboxNavigationConsumed=useRef<object|null>(null);
  const [recordingMinimized,setRecordingMinimized]=useState(false);
  const savedRecordingHost=useRef<HTMLDivElement>(null);
  const recordingHome=useRef<HTMLDivElement|null>(null),recordingHost=useRef<HTMLDivElement|null>(null),previousRecordingOpen=useRef(false);
  const [googleMessageOpen,setGoogleMessageOpen]=useState(false);
  const [googleCalendarOpen,setGoogleCalendarOpen]=useState(false);
  const googleVisitSelection=useRef<'message'|'calendar'|false>(false);
  const ehrVisitSelection=useRef(false);
  const ehrOpeningIntent=useRef(0),ehrOpeningCleanup=useRef<(()=>void)|null>(null);
  const googleReturn=useRef(GOOGLE_CONNECTION_BUILD&&['#google-connected','#google-sign-in'].includes(window.location.hash));
  const microsoftReturn=useRef(MICROSOFT_CONNECTION_BUILD&&['#microsoft-connected','#microsoft-sign-in'].includes(window.location.hash));
  const schedulingReturn=useRef(SCHEDULING_LOGIN_BUILD&&['#scheduling-connected','#scheduling-sign-in'].includes(window.location.hash));
  const [connectionLocks, setConnectionLocks] = useState({google:false,googleMessages:false,googleCalendar:false,ehr:false,microsoft:false,scheduling:false,core:false,messaging:false, payments:false, portals:false, inbox:false});
  const activityEnabled = import.meta.env.VITE_AI_ACTIVITY_ENABLED === "true";
  const {activityNavigation}=session;
  const connectionEditorsLocked = Object.values(connectionLocks).some(Boolean);
  const [accessBusy,setAccessBusy]=useState(false);
  const [scribeSourceBusy,setScribeSourceBusy]=useState(false);
  const [schedulingPatientBusy,setSchedulingPatientBusy]=useState(false);
  const [agentResearchBusy,setAgentResearchBusy]=useState(false);
  const {preparation:clinicalPreparation,safety:clinicalSafety}=session.clinical;
  const navigationWorkLocks={researchPending,connectionEditorsLocked,activityBusy,accessBusy,scribeSourceBusy,handoffReviewPending,schedulingPatientBusy,agentResearchBusy,efax:faxSourceBusy,fax:providerFaxSourceBusy,clinicalPreparing};
  const liveNavigationWorkLocks=useRef(navigationWorkLocks);liveNavigationWorkLocks.current=navigationWorkLocks;
  const viewNavigationLocked = Object.values(navigationWorkLocks).some(Boolean);
  function sourceViewNavigationLocked(ownSource?:'efax'|'fax'){
    return Object.entries(liveNavigationWorkLocks.current).some(([key,blocked])=>key!==ownSource&&blocked);
  }
  const connectionNavigationLocked = !!privateRecordingEntry || privateRecordingBusy || viewNavigationLocked;
  const workspaceFrame=useRef<HTMLElement>(null);
  useEffect(()=>{setNativePresentation(messagesMode?'messages':'workspace');return()=>setNativePresentation('workspace');},[messagesMode]);
  const sidebar=useRef<HTMLElement>(null),navigation=useRef<HTMLElement>(null);
  const [navigationHeight,setNavigationHeight]=useState(80);
  useLayoutEffect(()=>{
    if(!phoneLayout())return;
    window.scrollTo?.({top:0,left:0,behavior:'instant'});
    if(sidebar.current)sidebar.current.scrollTop=0;
  },[practicePage,settingsOpen,practiceOpen,workspace?.id]);
  useLayoutEffect(()=>{
    const root=workspaceFrame.current;if(!root||!messagesMode)return;
    // Measure after page focus/scroll restoration. A host notice can also resize
    // above the app without changing the visual viewport itself.
    const measure=()=>{if(!phoneLayout())return;const height=Math.max(220,(window.visualViewport?.height??window.innerHeight)-Math.max(0,root.getBoundingClientRect().top)),value=`${height}px`,compact=String(height<600);
      if(root.style.getPropertyValue('--messages-height')!==value)root.style.setProperty('--messages-height',value);
      if(root.dataset.messagesCompact!==compact)root.dataset.messagesCompact=compact;};
    measure();window.addEventListener('resize',measure);window.addEventListener('scroll',measure);window.visualViewport?.addEventListener('resize',measure);
    const observer=typeof ResizeObserver==='function'?new ResizeObserver(measure):null;if(root.parentElement)observer?.observe(root.parentElement);
    return()=>{observer?.disconnect();window.removeEventListener('resize',measure);window.removeEventListener('scroll',measure);window.visualViewport?.removeEventListener('resize',measure);};
  },[messagesMode,settingsOpen,practicePage,workspace?.id]);
  useLayoutEffect(()=>{
    const nav=navigation.current;if(!nav)return;
    const measure=()=>setNavigationHeight(nav.getBoundingClientRect().height);
    measure();
    if(typeof ResizeObserver==='undefined')return;
    // Safe-area padding changes the space reserved for the tabs.
    const observer=new ResizeObserver(measure);observer.observe(nav,{box:'border-box'});return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    const closed=previousRecordingOpen.current&&!privateRecordingEntry;previousRecordingOpen.current=!!privateRecordingEntry;
    if(closed&&authenticated&&(practicePage==='home'||messagesMode&&practicePage==='notebook')&&!settingsOpen&&!practiceOpen){
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
  // Workspace Tools stays the same complete task when the presentation changes.
  const messagesTask=phoneChatToolsOpen&&mobilePanel==='Conversation'?(messagesTaskChoice??'Tools'):null;
  const [clinicalTeamExpanded,setClinicalTeamExpanded]=useState(false);
  const chiefReviewReturn=session.review.returnTarget;
  const chiefReviewReturnFocus=useRef<typeof chiefReviewReturn.current>(null);
  const clinicalTeamRef=useRef<HTMLDetailsElement|null>(null);
  const clinicalTeamFocus=useRef<{owner:AuthenticatedWorkspaceIdentity;workspaceId:string;generation:number}|null>(null);
  useEffect(()=>{setPhoneChatToolsOpen(false);setClinicalTeamExpanded(false);setPhoneNoteTask(null);clinicalTeamFocus.current=null;chiefReviewReturn.current=null;chiefReviewReturnFocus.current=null;clinicalPreparation.current=null;setClinicalPreparing(false);},[authenticated,workspace?.id]);
  const [reviewState,setReviewState]=useState<'editing'|'review'|'saved'>('editing');
  const {currentThought,modelBusy}=session.models;currentThought.current=thought;
  function updateThought(value:string){session.models.updateThought(value);}
  const [prepSelection,setPrepSelection]=useState<{scope:symbol;selection:SessionPrepAnalysis}|null>(null);
  const [prepEpoch,setPrepEpoch]=useState(0);
  const questionRef=useRef<HTMLTextAreaElement|null>(null);
  useMessageComposerSize(questionRef,messagesMode,thought,`${workspace?.id??''}:${selected}`);
  const notebookDraft=(w:Workspace,n:string,t:string,e:string,s:string,p:PendingSave|null,previous=previousModelRequest)=>{
    const task=phoneNoteTask&&phoneNoteTask.owner===authenticated&&phoneNoteTask.owner===previousIdentity.current&&phoneNoteTask.generation===generation.current&&
      phoneNoteTask.workspaceId===w.id&&phoneNoteTask.scope===journal.current?.scope?phoneNoteTask:null;
    const separate=session.presentation.enabled&&!p&&!previous;
    return makeNotebookDraft(w,n,separate?'':t,e,s,p,previous,!separate&&task?{contract:'chief-note-task.compose.v1',note_id:task.selection.note_id,
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
  const reportEhrBusy = useCallback((blocked:boolean)=>{
    if(generation.current===connectionGeneration)setConnectionLocks(previous=>previous.ehr===blocked?previous:{...previous,ehr:blocked});
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
    return () => { ehrOpeningIntent.current++;ehrOpeningCleanup.current?.();session.invalidate(); activityNavigation.current?.abort(); closeDraftJournal(); document.title = previousTitle; };
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
    if(messagesMode||authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession)return;
    conversationEnd.current?.scrollIntoView?.({ block: "nearest" });
  }, [authenticated,workspace?.revision, pending]);
  useEffect(()=>session.models.observePendingHash(),[pending]);
  useEffect(()=>session.loading.startup(loadingContext(),()=>authenticated?consumeWorkspaceStartupTeam(practiceAccess?.startupTeam,authenticated):null),[authenticated,team]);
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
  useEffect(()=>{
    const nativeOwner=authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?authenticated:null;
    let nativeVisible=nativeOwner?.nativeSession?.isCurrent()??false;
    return session.observations.watch({modelFailure,
      visible:()=>nativeOwner?nativeVisible&&nativeOwner.nativeSession!.isCurrent():document.visibilityState!=='hidden',
      subscribeVisibility:changed=>{
        if(nativeOwner)return subscribeNativeWorkspaceForeground(nativeOwner,()=>{nativeVisible=true;changed();},()=>{nativeVisible=false;changed();});
        document.addEventListener('visibilitychange',changed);window.addEventListener?.('focus',changed);
        return()=>{document.removeEventListener('visibilitychange',changed);window.removeEventListener?.('focus',changed);};
      }});
  },[workspace,identity,authenticated,busy,pending,conflict,handoffReviewPending]);

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
    setConnectionLocks({google:false,googleMessages:false,googleCalendar:false,ehr:false,microsoft:false,scheduling:false,core:false,messaging:false, payments:false, portals:false, inbox:false});
    setGoogleMessageOpen(false);setGoogleCalendarOpen(false);googleVisitSelection.current=false;
    ehrVisitSelection.current=false;
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
  function navigationContext(ownSource?:'efax'|'fax'):import('./session/navigation').NavigationContext{const viewLocked=sourceViewNavigationLocked(ownSource);return {...loadingContext(),viewNavigationLocked:viewLocked,connectionNavigationLocked:!!privateRecordingEntry||privateRecordingBusy||viewLocked,captureNavigationLocked,captureDraftLocked,minimizeRecording:()=>setRecordingMinimized(true),hasUnsavedWork,replaceRoute:target=>writeHistoryRoute(target,false),openPrivateNotebook,loadEncounters,currentTeam};}
  function goHome(){setContextBot(null);setMessagesTask(null);setConversationDetails(false);session.navigation.goHome(navigationContext());}
  function conversationHost(allowHomeResult=false,ownSource?:'efax'|'fax'):import('./session/conversations').ConversationHost|null{
    const owner=authenticated,owned=journal.current;if(!owner||!owned||!accountAccess)return null;
    return {identity:owner,journal:owned.value,scope:owned.scope,current:()=>previousIdentity.current===owner&&journal.current?.value===owned.value&&(owner.mode==='desktop_native'?owner.isCurrent():!owner.nativeSession||owner.nativeSession.isCurrent()),
      blocked:()=>{const view=session.getSnapshot();return view.busy||!!view.pending||view.conflict||view.clinicalPreparing||view.recoveryState==='failed'||privateLinkPending||sourceViewNavigationLocked(ownSource)||captureNavigationLocked||captureDraftLocked||!!view.privateRecordingEntry||view.privateRecordingBusy||!allowHomeResult&&(view.homeBusy||homePending);},
      authorize:accountAccess.authorize,navigate:target=>session.navigation.applyRoute(target,navigationContext(ownSource)),failure};
  }
  function openConversation(workspaceId:string,address:string,row?:ConversationSummary,allowHomeResult=false){
    const host=conversationHost(allowHomeResult);if(!host)return Promise.resolve();setMessagesTask(null);setConversationDetails(false);setPhoneChatToolsOpen(false);
    return session.conversations.open(workspaceId,address,host,row).then(opened=>{const view=session.getSnapshot();if(opened&&view.practicePage==='notebook'&&!view.settingsOpen&&!view.practiceOpen&&view.workspace?.id===workspaceId&&view.selected===address&&view.team?.configuration.bots.some(bot=>botAddress(bot)===address&&bot.role==='visit_prep')&&messagesMode)showConversationTask('Tools');});
  }
  async function chooseConversationContext(address:string){
    const host=conversationHost();if(!host||host.blocked()||conversationBusy)return;
    try{if(!await session.conversations.retain(host)||!host.current())return;
      setNewMessage(false);setConversationDetails(false);setMessagesTask(null);setContextBot(address);setSettingsOpen(false);setPracticeOpen(false);
      const chosen=session.getSnapshot().team?.configuration.bots.find(item=>botAddress(item)===address);
      if(chosen?.role==='research'){setResearchEntry(true);await loadEncounters();}else setPracticePage('home');
    }catch{setRecoveryState('failed');}
  }
  async function contextOpened(result:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam},view:'default'|'notebook'='default'){
    const address=contextBotRef.current;await openPrivateNotebook(result,view);
    if(address&&previousIdentity.current===result.identity&&session.getSnapshot().workspace?.id===result.workspace.id){setContextBot(null);await openConversation(result.workspace.id,address,undefined,true);}
  }
  const taskFocusPending=useRef(false),taskScrollReturn=useRef<number|null>(null);
  function showConversationTask(task:'Review'|'Notebook'|'Sources'|'Work'|'Activity'|'Tools'){
    if(viewNavigationLocked||captureNavigationLocked||captureDraftLocked)return;setConversationDetails(false);
    taskFocusPending.current=true;taskScrollReturn.current=mobileChatFrame.scrollRef.current?.scrollTop??null;
    if(task==='Activity'||task==='Tools'){setMessagesTask(task);setMobilePanel('Conversation');setPhoneChatToolsOpen(true);setTeamWorkExpanded(task==='Activity');}
    else{setMessagesTask(null);setPanel(task);setMobilePanel(task);setPhoneChatToolsOpen(false);}
  }
  function returnToMessagesChat(){if(viewNavigationLocked||captureNavigationLocked||captureDraftLocked)return;setMessagesTask(null);setMobilePanel('Conversation');setPhoneChatToolsOpen(false);setQuestionFocus(value=>value+1);}

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
      afterOpen:()=>{if(ehrVisitSelection.current){ehrVisitSelection.current=false;setSettingsEntry('ehr');setSettingsOpen(true);}else if(googleVisitSelection.current){const service=googleVisitSelection.current;googleVisitSelection.current=false;setSettingsEntry('google');setGoogleMessageOpen(service==='message');setGoogleCalendarOpen(service==='calendar');setSettingsOpen(true);}},
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
  function ask(content=thought){
    const owner=generation.current,context=workspace?.id;
    const request=session.models.ask(selected,selectedPrep,modelContext(),content);if(!request)return;
    if(messagesMode)nativePresentationFeedback('send');
    void request.then(()=>{
      if(messagesMode&&generation.current===owner&&session.getSnapshot().workspace?.id===context&&(session.getSnapshot().pending||session.getSnapshot().error))nativePresentationFeedback('warning');
    });
  }
  function composerContext():import('./session/composer').ComposerContext{return {locked,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked,recoveryBlocked,focus:()=>setQuestionFocus(value=>value+1),closeTools:()=>setPhoneChatToolsOpen(false),save:saveContext()};}
  function prepareChiefQuestion(prompt:string){session.composer.prepareChief(prompt,composerContext());}
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
  const phoneChief=(messagesMode||phoneLayout())&&bot?.role==='chief';
  const phoneChiefConversation=phoneChief&&mobilePanel==='Conversation';
  const chiefNoteCompose=bot?.role==='chief'&&mobilePanel==='Conversation'&&!!phoneNoteTask&&phoneNoteTask.owner===authenticated&&phoneNoteTask.owner===previousIdentity.current&&
    phoneNoteTask.generation===generation.current&&phoneNoteTask.workspaceId===workspace?.id&&phoneNoteTask.scope===journal.current?.scope&&
    !!authenticated&&(authenticated.mode!=='clerk_jwt'||!authenticated.nativeSession||authenticated.nativeSession.isCurrent());
  const phoneChiefToolsVisible=messagesMode?!!messagesTask||phoneChiefConversation&&phoneChatToolsOpen:phoneChiefConversation&&(phoneChatToolsOpen||viewNavigationLocked&&!chiefNoteCompose);
  const visitLinked=!!workspace?.appointment_id;
  const ehrReviewOwned=EHR_READ_BUILD&&!!authenticated&&!!workspace&&ehrReview?.identity===authenticated&&ehrReview.generation===generation.current&&ehrReview.workspaceId===workspace.id;
  const ehrReviewOpen=ehrReviewOwned&&ehrReview.open&&practicePage==='notebook'&&!settingsOpen&&!practiceOpen;
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
  const latestNote = latestNotebookText(workspace);
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
    session.clinical.open(noteId,prepare,expected,inComposer,clinicalContext(),{focus:value=>{clinicalTeamFocus.current=value;},show:compose=>{setPhoneChatToolsOpen(!compose);setClinicalTeamExpanded(true);},focusQuestion:()=>setQuestionFocus(value=>value+1)});
  }
  function clinicalContext():import('./session/clinical').ClinicalContext {return {...modelContext(),locked,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,recoveryBlocked,latestNote,previousIdentity,privateRecordingLive,currentIdentity,recoveryView,currentTeam,failure,save,saveModel,showReplacement:role=>{setSelected(role);setSettingsOpen(false);setPracticeOpen(false);setMobilePanel('Conversation');setPhoneChatToolsOpen(true);setClinicalTeamExpanded(true);}};}
  function prepareClinicalDrafts(input:ShareSavedNoteInput){return session.clinical.prepare(input,clinicalContext());}
  function returnToPhoneChat(){setMessagesTask(null);setPhoneChatToolsOpen(false);setQuestionFocus(value=>value+1);}
  function requestScribeDraft(){session.composer.requestScribe(composerContext());}
  useEffect(()=>{session.composer.continueScribe(composerContext());},[busy,workspace?.revision,pending,conflict,recoveryBlocked]);
  const {ready:routeReady,applying:routeApplying,sequence:routeSequence,route}=session.navigation;
  const historyPosition=useRef(workspaceHistoryPosition(history.state)??0),historyRestoring=useRef<number|null>(null),historyHandling=useRef<number|null>(null),historyOperation=useRef(0);
  function writeHistoryRoute(target:WorkspaceRoute,push:boolean){
    const position=historyPosition.current+(push?1:0),state={...(history.state&&typeof history.state==='object'?history.state:{}),[HISTORY_POSITION]:position};
    if(push)history.pushState(state,'',workspaceRouteHash(target));else history.replaceState(state,'',workspaceRouteHash(target));
    historyPosition.current=position;
  }
  function restoreConsumedHistory(from:number,to:number|null){
    if(to!==null&&from!==to){historyRestoring.current=from;history.go(from-to);}
    // Old/unmarked entries have no direction information. Keep the popped
    // parent intact and recreate our current entry rather than overwriting it.
    else writeHistoryRoute(route(),true);
  }
  useEffect(()=>{if(workspaceHistoryPosition(history.state)===null){const state={...(history.state&&typeof history.state==='object'?history.state:{}),[HISTORY_POSITION]:historyPosition.current};history.replaceState(state,'');}},[]);
  function applyRoute(target:WorkspaceRoute){return session.navigation.applyRoute(target,navigationContext());}
  useEffect(()=>{
    if(!team||recoveryBlocked||routeReady.current||routeApplying.current)return;
    const target=readWorkspaceRoute(window.location.hash);if(target)void applyRoute(target);else routeReady.current=true;
  },[team,recoveryBlocked]);
  const historyNavigation=useRef<(target:WorkspaceRoute,from:number,to:number|null)=>Promise<void>>(async()=>{});
  historyNavigation.current=async(target,from,to)=>{
    const operation=++historyOperation.current;historyHandling.current=operation;const origin=workspaceRouteHash(route());
    try{
      if(ehrReviewOpen){closeEhrTask();restoreConsumedHistory(from,to);return;}
      if(messagesMode){
        const dialog=[...document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]')].find(element=>!element.closest('[hidden]'));
        if(dialog){
          // Consume dismissal in the original entry. Replacing the popped
          // entry would delete Inbox; reversing the traversal preserves Back
          // and Forward while using the sheet's existing dismiss action.
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
          restoreConsumedHistory(from,to);return;
        }
        if(messagesTask){returnToMessagesChat();restoreConsumedHistory(from,to);return;}
      }
      const context={...navigationContext(),replaceRoute:(actual:WorkspaceRoute)=>{if(historyHandling.current!==operation)writeHistoryRoute(actual,false);}};
      const host=conversationHost(),conversation=host?{...host,navigate:(target:WorkspaceRoute)=>session.navigation.applyRoute(target,context)}:null;
      const followed=await session.navigation.followHistory(target,context,conversation);
      if(historyHandling.current!==operation)return;
      if(!followed&&workspaceRouteHash(route())===origin){restoreConsumedHistory(from,to);return;}
      writeHistoryRoute(route(),false);
      if(followed){setContextBot(null);setMessagesTask(null);setPhoneChatToolsOpen(false);}
    }finally{if(historyHandling.current===operation)historyHandling.current=null;}
  };
  useEffect(()=>{const back=(event:PopStateEvent)=>{
    const from=historyPosition.current,to=workspaceHistoryPosition(event.state);if(to!==null)historyPosition.current=to;
    if(historyRestoring.current!==null){
      const expected=historyRestoring.current;historyRestoring.current=null;
      if(to===expected){writeHistoryRoute(route(),false);return;}
    }
    const target=readWorkspaceRoute(window.location.hash);if(target)void historyNavigation.current(target,from,to);
  };
    window.addEventListener?.('popstate',back);return()=>window.removeEventListener?.('popstate',back);
  },[]);
  useEffect(()=>{
    if(historyHandling.current!==null||historyRestoring.current!==null||!routeReady.current||routeApplying.current||!team||practicePage==='notebook'&&!workspace)return;
    const hash=workspaceRouteHash(route());if(window.location.hash===hash)return;
    writeHistoryRoute(route(),window.location.hash.startsWith('#cosmas/'));
  },[practicePage,settingsOpen,practiceOpen,workspace?.id,selected,mobilePanel,team,conversationBusy]);
  useEffect(()=>{
    const closeMenus=(event:MouseEvent|KeyboardEvent)=>document.querySelectorAll<HTMLDetailsElement>('details[data-menu][open]').forEach(menu=>{
      if(event instanceof KeyboardEvent&&event.key==='Escape'){menu.open=false;menu.querySelector<HTMLElement>('summary')?.focus();}
      else if(event instanceof MouseEvent&&!menu.contains(event.target as Node))menu.open=false;
    });
    document.addEventListener('click',closeMenus);document.addEventListener('keydown',closeMenus);
    return()=>{document.removeEventListener('click',closeMenus);document.removeEventListener('keydown',closeMenus);};
  },[]);
  const chiefSavedContext=hasSavedBotContext(workspace,bot);
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
  const accountAccess=useMemo(()=>session.recovery.accountAccess(authenticated,editorScope,editorJournal,accountScopeReady),[authenticated,editorJournal,editorScope,accountScopeReady]);
  function inboxPreferencesHost():InboxPreferencesHost|null{
    const owner=authenticated,recovery=accountAccess;if(!owner||!recovery)return null;
    return {identity:owner,recovery,current:()=>previousIdentity.current===owner&&journal.current?.value===recovery.journal&&journal.current?.serverScope===recovery.recoveryScope,
      denied:cause=>{if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status))failure(cause);}};
  }
  useEffect(()=>{if(session.presentation.enabled)void session.inboxPreferences.bind(inboxPreferencesHost());},[authenticated,accountAccess]);
  useEffect(()=>setInboxRename(null),[authenticated]);
  function closeInboxRename(){setInboxRename(null);queueMicrotask(()=>document.getElementById('messages-title')?.focus());}
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
  const activityLive=session.activity.live;
  activityLive.current = {authenticated,editorJournal,editorScope,settingsOpen,practiceOpen,activityContext,activityBlocked,workspace,note};
  function activityContextHost():import('./session/activity').ActivityContext{return {authenticated,activityContext,activityEnabled,accountAccess,editorJournal,editorScope,currentTeam,currentTeamDraft,hasUnsavedWork,failure,resetCapture:()=>{setObservedCaptureDraft(null);setCaptureRequest(0);}};}
  useEffect(()=>session.activity.watch(activityContextHost()),[activityEnabled,authenticated,accountAccess,editorJournal,editorScope,settingsOpen,practiceOpen,connectionGeneration,activityAttempt]);

  function openActivityEncounter(selection:AiActivitySelection){return session.activity.open(selection,activityContextHost());}
  const editorReady = !!editorWorkspace && ["private-note","core-note","transcript"].every(kind =>
    editorJournal?.has(`editor:${editorWorkspace}:${kind}`));
  const editorAccess=useMemo(()=>session.recovery.editorAccess(authenticated,editorScope,editorJournal,editorWorkspace,editorReady,recoveryBlocked,failure),[authenticated,editorScope,editorJournal,editorWorkspace,editorReady,recoveryBlocked]);
  useEffect(()=>{
    if(!session.presentation.enabled||!authenticated||!workspace||!editorJournal||conversationBusy||reviewHandoffId||selectedResult||recoveryOffers.length||recoveryBlocked)return;
    const host=conversationHost();if(!host)return;
    void session.conversations.observe(host).catch(()=>{if(host.current())setRecoveryState('failed');});
  },[authenticated,workspace?.id,selected,thought,phoneNoteTask,conversationBusy,recoveryOffers.length,recoveryBlocked,editorJournal]);
  useEffect(()=>{
    if(!session.presentation.enabled||!authenticated||!team?.revision||!accountAccess||settingsOpen||practiceOpen||practicePage!=='home'||contextBot)return;
    void session.conversations.refresh(authenticated,false,failure);
  },[authenticated,team?.revision,accountAccess,practicePage,settingsOpen,practiceOpen,contextBot,connectionGeneration]);
  useEffect(()=>{setContextBot(null);setNewMessage(false);setConversationDetails(false);setMessagesTask(null);},[authenticated]);
  const agentResearchRecovery=useMemo(()=>session.recovery.agentResearchAccess(editorAccess,editorWorkspace),[editorAccess,editorWorkspace]);
  const conversation=projectConversation(workspace,team,selected),turns=conversation.turns;
  const localModelPending=pending?.type==='ask'||pending?.type==='retry'?pending:null;
  const clinicalModelPending=localModelPending?.type==='ask'?parseClinicalTeamRequest(localModelPending.body.content):null;
  const nativeChatOwner=authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?authenticated:null;
  const nativePrivateNote=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&workspace?.private_draft?.state==='unlinked'&&!visitLinked;
  const nativeHome=!messagesMode&&!!nativeChatOwner&&phoneLayout()&&(practicePage==='home'||messagesMode&&practicePage==='notebook')&&!settingsOpen&&!practiceOpen&&!privateRecordingEntry&&!savedRecordingEntry;
  const nativeConversationPending=bot?.role==='chief'&&localModelPending?.type==='ask'&&localModelPending.body.role===selected&&
    !localModelPending.body.research_analysis&&!localModelPending.body.inbox_analysis&&!localModelPending.body.membership_analysis&&!localModelPending.body.session_prep_analysis;
  const nativeSavedRecording=!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&practicePage==='notebook'&&!settingsOpen&&!practiceOpen&&!privateRecordingEntry&&CAPTURE_WORKSPACE_BUILD&&!!team&&
    !!savedRecordingEntry&&savedRecordingEntry.identity===authenticated&&savedRecordingEntry.workspaceId===workspace?.id&&journal.current?.scope===savedRecordingEntry.scope;
  const savedRecordingNotebookOpen=nativeSavedRecording&&savedRecordingNotebook===savedRecordingEntry;
  const savedRecordingFocused=nativeSavedRecording&&!savedRecordingNotebookOpen;
  const nativeChat=!ehrReviewOpen&&!messagesMode&&!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&!!workspace&&practicePage==='notebook'&&mobilePanel==='Conversation'&&
    !settingsOpen&&!practiceOpen&&!privateRecordingEntry&&(!savedRecordingEntry||savedRecordingNotebookOpen)&&!scribeRecordingOpen&&!scribeSourceBusy&&!reviewHandoffId&&!conflict&&!recoveryBlocked&&!recoveryOffers.length&&(!pending||busy||nativeConversationPending);
  const nativeWorkspace=!ehrReviewOpen&&!messagesMode&&!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()&&phoneLayout()&&!nativeHome&&!nativeChat&&!privateRecordingEntry&&!settingsOpen&&!practiceOpen;
  const nativeClinicalPlan=(messagesMode||nativeChat||chiefNoteCompose)&&bot?.role==='chief'&&!!workspace?.appointment_id&&!!workspace.note?.latest&&authenticated===identity&&authenticated===previousIdentity.current&&
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
  // Blocking recovery can need more vertical space than a keyboard-sized
  // chat viewport. Keep its actions in document flow until it is resolved.
  const messagesRecoveryFlow=confirmCaptureExit||recoveryOffers.length>0||recoveryState==='failed'||recoveryBlocked||conflict||!!pending&&!busy;
  const messagesChat=!ehrReviewOpen&&!!workspace&&messagesMode&&practicePage==='notebook'&&!settingsOpen&&!practiceOpen&&mobilePanel==='Conversation'&&!messagesTask&&!phoneChiefToolsVisible&&!reviewHandoffId&&(!privateRecordingEntry||recordingMinimized)&&!messagesRecoveryFlow;
  const sharedChatOwner=session.presentation.enabled?authenticated??null:nativeChatOwner;
  const frameAddress=session.review.returnTarget.current?.address??session.review.conversationReturn.current?.address??selected;
  // Review temporarily selects its recipient; arrivals still belong to the chat we return to.
  const frameConversation=frameAddress===selected?conversation:projectConversation(workspace,team,frameAddress);
  const mobileChatFrame=useMobileChatFrame({active:session.presentation.enabled?!!workspace:nativeChat&&!phoneChiefToolsVisible,owner:sharedChatOwner,scope:`${chatGeneration}:${workspace?.id??''}:${frameAddress}`,
    // The jump counts incoming replies, not review cards or their changing
    // status: those cards may be earlier in history than the latest message.
    arrivals:frameConversation.entries.flatMap(row=>row.kind==='turn'&&row.entry.reply?[`reply:${row.id}`]:[]),
    onBottomVisible:()=>void acknowledgeDisplayedConversation(),
    messages:JSON.stringify([turns.map(entry=>[entry.id,entry.reply?.content??null]),
      pending?.type==='ask'&&pending.body.role===selected&&!localQuestionRepresented?pending.body.idempotency_key:null,recoveryAppearance.current,
      [chiefNoteCompose,phoneNoteTask?.selection.note_id,phoneNoteTask?.selection.note_version,clinicalPreparing,busy,message],
      messagesChat?[confirmCaptureExit,recoveryOffers.map(offer=>offer.address),recoveryState,error,conversationError,connectionError?.message,conflict,!!clinicalShareCheck,!!replacementDraft,pending?.type??null]:null,
      chiefNoteCompose?workspace?.handoffs?.map(handoff=>[handoff.id,handoff.status,handoff.result_entry_id,handoff.review_status]):null]),
    isCurrent:()=>previousIdentity.current===sharedChatOwner&&generation.current===chatGeneration&&!!sharedChatOwner&&(sharedChatOwner.mode!=='clerk_jwt'||!sharedChatOwner.nativeSession||sharedChatOwner.nativeSession.isCurrent())});
  const historyVisible=useRef<()=>boolean>(()=>false);
  historyVisible.current=()=>{
    if(!session.presentation.enabled||document.visibilityState==='hidden'||draftsSuspended.current||conversationBusy||practicePage!=='notebook'||settingsOpen||practiceOpen||reviewHandoffId||selectedResult||messagesTask||phoneChatToolsOpen||conversationDetails||newMessage||contextBot||mobilePanel!=='Conversation'||
      bot?.role==='research'&&!savedResearchChat||privateRecordingEntry&&!recordingMinimized||savedRecordingEntry&&savedRecordingFocused)return false;
    if([...document.querySelectorAll('[role="dialog"][aria-modal="true"]')].some(dialog=>!dialog.closest('[hidden]')))return false;
    const history=mobileChatFrame.scrollRef.current,owner=messagesMode?history:history?.querySelector<HTMLElement>('.team-messages'),end=conversationEnd.current;
    if(!owner||!end||owner.clientHeight<=0||owner.scrollHeight-owner.clientHeight-owner.scrollTop>2)return false;
    const bounds=owner.getBoundingClientRect(),last=end.getBoundingClientRect(),viewport=window.visualViewport;
    const top=viewport?.offsetTop??0,bottom=top+(viewport?.height??window.innerHeight);
    return last.top>=Math.max(top,bounds.top)&&last.bottom<=Math.min(bottom,bounds.bottom)+1;
  };
  async function acknowledgeDisplayedConversation(){
    const host=conversationHost();if(!host||!historyVisible.current())return;
    await session.conversations.acknowledgeVisible(host,()=>historyVisible.current());
    await session.conversations.acknowledgeDisplayed(host,()=>historyVisible.current());
  }
  useEffect(()=>{void acknowledgeDisplayedConversation();},[workspace,conversationBusy,selected,mobilePanel,savedResearchChat,settingsOpen,practiceOpen,reviewHandoffId,messagesTask,phoneChatToolsOpen,conversationDetails,newMessage,contextBot,recordingMinimized,messagesMode]);
  const observeDisplayedHistory=useRef(acknowledgeDisplayedConversation);observeDisplayedHistory.current=acknowledgeDisplayedConversation;
  useEffect(()=>{
    const visible=()=>void observeDisplayedHistory.current();
    document.addEventListener('visibilitychange',visible);document.addEventListener('focusin',visible);window.addEventListener?.('focus',visible);window.addEventListener?.('scroll',visible,true);
    const nativeOwner=authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession?authenticated:null;
    const removeNative=nativeOwner?subscribeNativeWorkspaceForeground(nativeOwner,visible,()=>{}):undefined;
    return()=>{document.removeEventListener('visibilitychange',visible);document.removeEventListener('focusin',visible);window.removeEventListener?.('focus',visible);window.removeEventListener?.('scroll',visible,true);removeNative?.();};
  },[authenticated]);
  function openPhoneChatTools(){setMessagesTask('Tools');setPhoneChatToolsOpen(true);if(mobileChatFrame.scrollRef.current)mobileChatFrame.scrollRef.current.scrollTop=0;}
  function reviewContext():import('./session/review').ReviewContext{return {authenticated,previousIdentity,actionLocked,viewNavigationLocked,captureNavigationLocked,captureDraftLocked,recoveryBlocked,phoneChatToolsOpen,setPhoneChatToolsOpen,setClinicalTeamExpanded,focusQuestion:()=>setQuestionFocus(value=>value+1),returnFocus:chiefReviewReturnFocus};}
  function retryTeamTask(handoff:DraftHandoff){session.review.retry(handoff,saveContext());}
  function currentChiefReviewReturn(target=chiefReviewReturn.current){return session.review.currentReturn(reviewContext(),target);}
  function conversationReviewCloseLabel(){
    const target=session.review.currentConversationReturn(reviewContext());
    if(!target)return undefined;
    const name=team?.configuration.bots.find(item=>botAddress(item)===target.address)?.name;
    return name?`Back to ${name}`:'Back to chat';
  }
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
  function sourceContext(ownSource?:'efax'|'fax'):import('./session/sources').SourceContext{const viewLocked=sourceViewNavigationLocked(ownSource);return {authenticated,locked,connectionNavigationLocked:!!privateRecordingEntry||privateRecordingBusy||viewLocked,captureNavigationLocked,captureDraftLocked,connectionEditorsLocked,activityBusy,accessBusy,scribeSourceBusy,schedulingPatientBusy,accountAccess,failure,conversationHost:conversationHost(false,ownSource),focusQuestion:()=>setQuestionFocus(value=>value+1)};}
  function receiveGoogleSource(latest:Workspace){return session.sources.receive(latest);}
  function refreshGoogleVisit(){return session.sources.refresh(sourceContext());}
  function prepareGoogleChief(source:GoogleMessageSaved|GoogleCalendarSaved,kind:'google_message'|'google_calendar'='google_message'){return session.sources.prepareGoogle(sourceContext(),source,kind);}
  const ehrReturnFocus=useRef<{element:HTMLElement|null;scroll:number|null}|null>(null);
  async function openEhrTask(origin:'conversation'|'sources'|'connections'){
    const target=document.activeElement instanceof HTMLElement?document.activeElement:null,scroll=mobileChatFrame.scrollRef.current?.scrollTop??null;
    const context=sourceContext(),host=context.conversationHost;if(!host)return;
    const entry=workspaceFrame.current?.querySelector<HTMLElement>(origin==='connections'?'[aria-label="Choose a visit for appointment review"]':origin==='sources'?'.ehr-source-action':conversationDetails?'.messages-details':'.ehr-chief-action');
    if(!entry||entry.closest('[hidden]'))return;
    ehrOpeningCleanup.current?.();const intent=++ehrOpeningIntent.current,view=session.getSnapshot();
    const sameView=()=>{const now=session.getSnapshot();return (['practicePage','practiceOpen','settingsOpen','settingsEntry','panel','mobilePanel'] as const).every(key=>view[key]===now[key]);};
    const invalidate=()=>{if(ehrOpeningIntent.current===intent)ehrOpeningIntent.current++;};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')invalidate();};
    // A later click or Escape is a new user choice, even when a nested Settings
    // screen changes without advancing the workspace route. Capture starts
    // after the initiating click's capture phase and lasts only for this await.
    document.addEventListener('click',invalidate,true);document.addEventListener('keydown',escape,true);
    const cleanup=()=>{document.removeEventListener('click',invalidate,true);document.removeEventListener('keydown',escape,true);};ehrOpeningCleanup.current=cleanup;
    try{
      const current=()=>ehrOpeningIntent.current===intent&&sameView()&&entry.isConnected&&!entry.closest('[hidden]')&&host.current();
      if(await session.sources.openEhr({...context,conversationHost:{...host,current}},origin)){ehrReturnFocus.current={element:target,scroll};setConversationDetails(false);setMessagesTask(null);setPhoneChatToolsOpen(false);}
    }finally{cleanup();if(ehrOpeningCleanup.current===cleanup)ehrOpeningCleanup.current=null;}
  }
  function closeEhrTask(){if(session.sources.closeEhr(sourceContext())){const returned=ehrReturnFocus.current,current=generation.current,route=session.navigation.sequence.current,view=session.getSnapshot();requestAnimationFrame(()=>{
    const now=session.getSnapshot();if(current!==generation.current||route!==session.navigation.sequence.current||now.identity!==view.identity||now.workspace?.id!==view.workspace?.id||now.ehrReview?.open||now.mobilePanel!==view.mobilePanel||now.settingsOpen!==view.settingsOpen||now.practicePage!==view.practicePage)return;
    if(returned?.scroll!==null&&returned?.scroll!==undefined&&mobileChatFrame.scrollRef.current)mobileChatFrame.scrollRef.current.scrollTop=returned.scroll;
    const target=returned?.element;if(target?.isConnected&&!target.closest('[hidden]'))target.focus({preventScroll:true});else{const fallback=workspaceFrame.current?.querySelector<HTMLElement>('.messages-thread-header > button:last-child')??conversationHeaderRef.current?.querySelector<HTMLElement>('h2');if(fallback&&!fallback.closest('[hidden]')){fallback.tabIndex=-1;fallback.focus({preventScroll:true});}}
  });}}
  function prepareEhrChief(source:EhrReadSaved){return session.sources.prepareEhr(sourceContext(),source);}


  function receiveFaxDocument(document:EFaxSourceOffer,request:Extract<EFaxPending,{kind:'acquire'}>){return session.sources.receiveFax(sourceContext(),document,request);}
  function refreshFaxDocument(){return session.sources.refreshFax(sourceContext());}
  function prepareFaxChief(source:{receipt:EFaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry}){return session.sources.prepareFax(sourceContext('efax'),source);}

  function receiveProviderFaxDocument(document:FaxSourceOffer,request:Extract<FaxPending,{kind:'acquire'}>){return session.sources.receiveProviderFax(sourceContext(),document,request);}
  function refreshProviderFaxDocument(){return session.sources.refreshProviderFax(sourceContext());}
  function prepareProviderFaxChief(source:{receipt:FaxSourceReceipt;workspace:Workspace;entry:WorkspaceEntry}){return session.sources.prepareProviderFax(sourceContext('fax'),source);}

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
              onAskChief={content=>session.composer.askChief(content,composerContext())}
              onReview={id=>{const handoff=workspace.handoffs?.find(item=>item.id===id);if(handoff)reviewTeamResult(handoff,true);}}/>
          </details>;
  const teamDrafts=workspace&&<details className="team-work-disclosure" open={teamWorkExpanded} onToggle={event=>setTeamWorkExpanded(event.currentTarget.open)}>
    <summary>Team drafts · {(workspace.handoffs??[]).filter(handoff=>handoff.status==='completed').length} saved</summary>
    <TeamWorkPanel handoffs={workspace.handoffs??[]} entries={workspace.entries} locked={locked} onRetry={retryTeamTask} onReview={reviewTeamResult}/>
  </details>;
  const chiefStarters=bot?.role==='chief'&&!!team?.revision&&<ChiefStartActions compact={phoneLayout()} minimal={messagesMode&&!messagesTask} locked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked||!bot.enabled||!!bot.retired}
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
  const presentationBlocked=busy||!!pending||clinicalPreparing||viewNavigationLocked||captureTransition||captureDraftLocked||recordingTransition||homeBusy||homePending||privateLinkPending||recoveryState==='failed'||conflict||!!recoveryOffers.length;
  const contextChoice=contextBot?team?.configuration.bots.find(item=>botAddress(item)===contextBot):null;
  const messagesTaskLabel=messagesTask??(mobilePanel!=='Conversation'?({Notebook:'Notes',Sources:'Saved sources',Review:'Review note',Work:'Follow-up and linked work'} as Record<string,string>)[mobilePanel]:null);

  useEffect(()=>{
    if(!messagesMode||settingsOpen||practiceOpen)return;
    if(messagesTaskLabel&&taskFocusPending.current){
      taskFocusPending.current=false;
      if(mobileChatFrame.scrollRef.current)mobileChatFrame.scrollRef.current.scrollTop=0;
      const heading=workspaceFrame.current?.querySelector<HTMLElement>('.messages-thread-header h1');
      heading?.focus({preventScroll:true});heading?.scrollIntoView?.({block:'start'});
    }else if(!messagesTaskLabel&&taskScrollReturn.current!==null){
      if(mobileChatFrame.scrollRef.current)mobileChatFrame.scrollRef.current.scrollTop=taskScrollReturn.current;
      taskScrollReturn.current=null;mobileChatFrame.onScroll();
    }
  },[messagesMode,messagesTaskLabel,settingsOpen,practiceOpen]);

  const showExecutionProof=!!onExit&&import.meta.env.VITE_SHOW_EXECUTION_PROOF==='true';
  const errorBanner=error&&<div className="team-banner error workspace-error-banner" role="alert"><p>{error}</p><div className="workspace-error-actions">
    {readRetry&&<button disabled={busy||homeBusy||!!pending||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={()=>void readRetry.run()}>Try again</button>}
    <button onClick={()=>setError('')}>Dismiss</button></div></div>;
  // Recovery belongs to the scrollable conversation on phones. Keeping
  // these controls above the fixed chat frame can make them unreachable when
  // the keyboard or enlarged text leaves little vertical space.
  const recoveryNotices=<>
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
      <div className="workspace-draft-save-status" hidden={messagesMode&&recoveryState!=='saving'}>
        {recoveryState === "saving" && <p className="team-fine" role="status">Saving notebook and team drafts on this device…</p>}
        {recoveryState === "saved" && <p hidden={messagesMode||!!privateRecordingEntry||nativeChat||nativePrivateNote&&practicePage==='notebook'&&!settingsOpen&&!practiceOpen||phoneLayout()&&practicePage==='home'&&!settingsOpen&&!practiceOpen} className="team-fine">Working copies saved on this device. Save a note version separately for review.</p>}
      </div>
  </>;
  const workspaceNotices=<>
      {messagesMode&&conversationError&&practicePage==='notebook'&&!settingsOpen&&<p className="team-banner" role="alert">{conversationError}</p>}
      {connectionError&&connectionError.identity===(authenticated??identity)&&<div className="team-banner error" role="alert">{connectionError.message}</div>}
      {errorBanner}
      {message && !(messagesMode&&message==='Conversation saved.') && <div className={message==='Conversation saved.'?'team-fine':'team-banner'} role="status">{message==='Conversation saved.'?'Delivered':message}</div>}
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
  </>;
  return <EditorRecoveryContext.Provider value={editorAccess}><main ref={workspaceFrame} className="team-workspace" data-messages-chat={messagesChat} data-recovery-ready={!recoveryBlocked} data-session-pending={pending?.type??''} data-session-conflict={conflict} data-editor-ready={editorReady} data-presentation={messagesMode?'messages':'workspace'} data-native-presentation={!!nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()} data-messages-task={messagesTask??''} style={{'--workspace-nav-height':`${navigationHeight}px`} as CSSProperties} data-page={practicePage} data-native-home={nativeHome} data-native-chat={nativeChat} data-native-workspace={nativeWorkspace} data-recording-open={!!privateRecordingEntry} data-recording-focused={!!privateRecordingEntry&&!recordingMinimized} data-settings-open={settingsOpen && !practiceOpen} data-settings-rendered={settingsOpen&&hasWorkspaceIdentity} data-settings-navigation-locked={connectionNavigationLocked}>
    <aside ref={sidebar} className="team-sidebar" hidden={nativeWorkspace&&!messagesMode}>
      <div className="team-brand"><span className="team-logo" aria-hidden="true">✳</span>cosmas<span>OS</span><small className="team-phone-preview">Synthetic preview</small>{accountControls&&phoneLayout()&&!nativeHome&&!nativeWorkspace&&!nativeChat&&<div className="team-phone-account-controls">{accountControls}</div>}</div>
      <p className="team-sidebar-label">YOUR WORKSPACE</p>
      <nav ref={navigation} className="practice-navigation" aria-label="Workspace navigation">
        {authenticated&&<button className={`team-nav-item ${(practicePage==='home'||messagesMode&&practicePage==='notebook')&&!settingsOpen&&!practiceOpen?'active':''}`} aria-current={(practicePage==='home'||messagesMode&&practicePage==='notebook')&&!settingsOpen&&!practiceOpen?'page':undefined} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} aria-label={messagesMode?'Messages':undefined} onClick={goHome}><WorkspaceNavIcon page="home"/>{messagesMode?'Chats':'Home'}</button>}
        <button className={`team-nav-item ${!settingsOpen&&!practiceOpen&&(practicePage==='visits'||!messagesMode&&phoneLayout()&&practicePage==='notebook')?'active':''}`} aria-current={!settingsOpen&&!practiceOpen&&(practicePage==='visits'||!messagesMode&&phoneLayout()&&practicePage==='notebook')?'page':undefined} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} aria-label={messagesMode?'Visits and notes':undefined} onClick={()=>void (authenticated?loadEncounters():open())}><WorkspaceNavIcon page="visits"/>{messagesMode?'Visits':'Visits and notes'}</button>
        {workspace&&<button className={`team-nav-item team-nav-secondary ${practicePage==='notebook'&&!settingsOpen&&!practiceOpen?'active':''}`} aria-current={practicePage==='notebook'&&!settingsOpen&&!practiceOpen&&!phoneLayout()?'page':undefined} disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={goNotebook}>Current notebook</button>}
        {hasWorkspaceIdentity&&<button aria-label={messagesMode?'Practice work':undefined} className={`team-nav-item ${practiceOpen?'active':''}`} aria-current={practiceOpen?'page':undefined} disabled={viewNavigationLocked||busy||!!pending||captureNavigationLocked||captureDraftLocked} onClick={()=>leaveTeamSettings(()=>{routeSequence.current++;routeApplying.current=false;routeReady.current=true;clearPageError();setSettingsOpen(false);setPracticeOpen(true);setPracticeOpened(true);})}><WorkspaceNavIcon page="work"/>{messagesMode?'Work':'Practice work'}</button>}
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
          if(session.presentation.enabled&&workspace&&authenticated){void openConversation(workspace.id,address);return;}
          setPracticeOpen(false); setSelectedResult(null); setSelected(address); setSettingsOpen(false);setPracticePage("notebook"); setMobilePanel(member.role === "scribe" ? "Notebook" : "Conversation"); if (member.role === "scribe") setPanel("Notebook"); })}>
          <BotAvatar role={member.role} /><span><strong>{config.name}</strong>
            <small><i className={config.enabled && team.revision ? "ready" : "paused"} />{config.retired ? "Retired · history kept" : !team.revision ? "Set up your team" : !config.enabled ? "Paused" : config.blocked_capabilities?.includes("model_answer") ? "AI answers blocked" : "On"}</small></span>
        </button>;
      })}</nav>
      <div className="team-sidebar-bottom"><p><span className="team-local-dot" />{authenticated ? "Signed-in workspace" : "Local workspace"}</p><small>Invented data · private to you</small></div>
    </aside>
    <div className="team-main">
      {newMessage&&team&&<NewMessagePicker team={team} locked={conversationBusy||homeBusy||homePending||viewNavigationLocked} onChoose={address=>void chooseConversationContext(address)} onClose={()=>setNewMessage(false)}/>}
      {conversationDetails&&workspace&&<ConversationDetails name={bot?.name??'Conversation'} context={workspace.notebook?.title??workspace.label} contextKind={workspace.appointment_id?`Linked visit · ${workspace.label}`:'Private note · no visit linked'} locked={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClose={()=>setConversationDetails(false)} onTask={showConversationTask} onReviewAppointment={EHR_READ_BUILD&&authenticated&&visitLinked?()=>void openEhrTask('conversation'):undefined}/>}
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
      {!messagesChat&&recoveryNotices}
      {practiceOpen && errorBanner}
      {practiceOpened && (authenticated || identity) && <AccountRecoveryContext.Provider value={accountAccess}><fieldset disabled={recoveryBlocked} hidden={!practiceOpen} style={{border:0,padding:0,margin:0,minWidth:0}}><PracticeHub identity={(authenticated || identity)!} onDenied={failure} onBusyChange={reportInboxBusy} onDraftInbox={authenticated?selection=>{setInboxNavigation({selection,identity:authenticated,generation:generation.current});}:undefined}><PracticeWork identity={(authenticated || identity)!}
        onChanged={() => { if (workspace) setConflict(true); }} onAccessLost={failure} />
        {ROUTINES_BUILD && authenticated && team && team.revision > 0 && <WorkRoutines identity={authenticated} team={team} onAccessLost={failure} onRefreshTeam={refreshRoutineTeam} />}
        {authenticated && team?.revision === 0 && <div className="team-banner"><p>Set up your private team to schedule work briefs.</p><button onClick={() => void openSettings()}>Set up your team</button></div>}</PracticeHub></fieldset></AccountRecoveryContext.Provider>}
      <div className="workspace-main-content" hidden={practiceOpen}>
      {messagesMode&&authenticated&&!settingsOpen&&practicePage==='home'&&!contextBot&&(!privateRecordingEntry||recordingMinimized)&&<MessagesInbox inbox={conversationInbox} team={team} loading={conversationLoading} error={conversationError} organization={inboxOrganization}
        locked={conversationBusy||busy||!!pending||homeBusy||homePending||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked}
        onNew={()=>setNewMessage(true)} onChief={address=>void chooseConversationContext(address)} onSettings={()=>void openSettings()}
        onOpen={row=>void openConversation(row.workspace_id,row.bot.address,row)} onRefresh={()=>void session.conversations.refresh(authenticated,false,failure)} onMore={()=>void session.conversations.refresh(authenticated,true,failure)} onUnread={row=>void session.conversations.markUnread(row,authenticated,failure)}
        onOrganize={(row,change)=>session.inboxPreferences.set(row,change)} onRestoreAll={()=>session.inboxPreferences.restoreAll()} onInspect={row=>void session.inboxPreferences.inspect(row)} onCloseMenu={()=>session.inboxPreferences.closeMenu()}
        onReloadOrganization={()=>void session.inboxPreferences.bind(inboxPreferencesHost(),true)} onRename={target=>setInboxRename({target,identity:authenticated,scope:accountAccess?.recoveryScope})}/>}
      {inboxRename&&inboxRename.identity===authenticated&&accountAccess?.recoveryScope===inboxRename.scope&&<WorkspaceDialog title="Rename notebook" closeLabel="Close rename notebook" onClose={closeInboxRename}>
        <NotebookTitleEditor identity={inboxRename.identity} recovery={accountAccess??null} workspaceId={inboxRename.target.workspaceId} title={inboxRename.target.title} titleRevision={inboxRename.target.titleRevision} onClose={closeInboxRename} onAccessLost={failure}
          onSaved={receipt=>{setWorkspace(current=>current?.id===receipt.workspace_id&&current.notebook?{...current,notebook:{...current.notebook,title:receipt.title,title_revision:receipt.title_revision}}:current);closeInboxRename();void session.conversations.refresh(inboxRename.identity,false,failure);}}/>
      </WorkspaceDialog>}
      {contextChoice&&!settingsOpen&&(!privateRecordingEntry||recordingMinimized)&&<header className="messages-context-choice"><button disabled={homeBusy||homePending} onClick={()=>{setContextBot(null);goHome();}}>‹ Messages</button><h1>{contextChoice.name}</h1><p>{contextChoice.role==='research'?'Choose the visit for this research.':'Choose the visit or private note for this conversation.'}</p></header>}

      {settingsOpen&&!hasWorkspaceIdentity&&<section className="settings-hub" aria-labelledby="offline-settings-title"><h1 id="offline-settings-title">Settings</h1><p>Settings are available after your workspace connects.</p><button className="settings-done" onClick={closeSettings}>Done</button></section>}
      {!messagesChat&&workspaceNotices}
      {activityEnabled && settingsOpen && activityContextBusy && <p className="team-fine" role="status">Checking optional AI activity access…</p>}
      {activityEnabled && settingsOpen && activityContextError && <div className="team-banner error" role="alert"><p>{activityContextError}</p><button disabled={locked || activityContextBusy} onClick={()=>setActivityAttempt(value=>value+1)}>Recheck AI activity access</button></div>}
      {(authenticated || identity) && <AccountRecoveryContext.Provider value={accountAccess}><SettingsHub appearance={session.presentation.enabled&&!!team?.revision?<LayoutSetting value={session.presentation.current()} blocked={presentationBlocked} error={presentationError} onChoose={value=>{if(session.presentation.choose(value,presentationBlocked))nativePresentationFeedback('selection');}}/>:undefined} key={generation.current} open={settingsOpen} nativePresentation={nativeChatOwner&&nativeChatOwner.nativeSession!.isCurrent()?(messagesMode?'messages':'workspace'):undefined} navigationLocked={viewNavigationLocked} beforeLeaveTeam={leaveTeamSettings}
        onOpenMessagingWork={authenticated?openMessagingWork:undefined} messagingWorkLabel={workspace?'Open fax work for this visit':'Choose a visit for fax work'}
        messagingWorkBlocked={locked||captureNavigationLocked||captureDraftLocked}
        onReviewFaxDocument={EFAX_INBOUND_SOURCE_BUILD&&visitLinked?receiveFaxDocument:undefined}
        onReviewProviderFaxDocument={FAX_INBOUND_SOURCE_BUILD&&visitLinked?receiveProviderFaxDocument:undefined}
        initialScreen={settingsEntry} guidedConnections={CONNECTION_ONBOARDING_BUILD} connectionIdentity={authenticated ?? undefined} onConnectionAccessLost={failure}
        members={authenticated&&practiceAccess?<PracticeAccessPanel identity={authenticated} access={practiceAccess} onBusyChange={reportAccessBusy}/>:undefined}
        ehr={EHR_READ_BUILD&&authenticated?<section aria-label="Choose a visit for appointment review"><p>{visitLinked?'Review the patient and appointment in this visit. Your conversation draft stays in place.':'Choose the existing visit that will receive your reviewed appointment details.'}</p>
          <button className="team-primary" disabled={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={()=>{if(locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)return;if(visitLinked)void openEhrTask('connections');else{ehrVisitSelection.current=true;setSettingsOpen(false);void loadEncounters();}}}>{visitLinked?'Review an appointment':'Choose a visit'}</button></section>:undefined}
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
      {privateRecordingEntry&&<div className="private-recording-host" ref={recordingHost}><PrivateRecordingPanel minimized={recordingMinimized} onExpand={()=>{setRecordingMinimized(false);setSettingsOpen(false);setPracticeOpen(false);}} onMinimize={()=>setRecordingMinimized(true)} identity={privateRecordingEntry.identity} scope={privateRecordingEntry.scope}
        platform={privateRecordingEntry.identity.mode==='clerk_jwt'&&privateRecordingEntry.identity.nativeSession?'ios':'desktop'}
        isCurrent={()=>recordingCurrent(privateRecordingEntry)} authorize={privateRecordingEntry.authorize}
        title={privateRecordingEntry.title} recordingId={privateRecordingEntry.recordingId} prepareNotebook={privateRecordingEntry.prepareNotebook}
        onTranscribe={CAPTURE_WORKSPACE_BUILD?async(result,recordingId)=>{
          const entry=privateRecordingEntry;if(!recordingCurrent(entry))throw new WorkspaceApiError(403);
          await returnPrivateRecordingNotebook(entry,result);setPrivateRecordingEntry(null);setPrivateRecordingBusy(false);
          if(authenticated===entry.identity&&journal.current?.scope===entry.scope)
            setSavedRecordingEntry({recordingId,scope:entry.scope,platform:entry.identity.mode==='clerk_jwt'&&entry.identity.nativeSession?'ios':'desktop',workspaceId:result.workspace.id,identity:entry.identity,originWorkspace:result.workspace});
        }:undefined}
        onTransitionChange={session.setRecordingTransition} onBusyChange={setPrivateRecordingBusy} onSaved={()=>setPrivateRecordingListEpoch(value=>value+1)} onAccessLost={failure}
        onNotebookPrepared={(result,recordingId)=>session.recording.attachNotebook(privateRecordingEntry,result,recordingId)}
        onClose={()=>{const returnToNotebook=!!privateRecordingEntry.returnWorkspaceId&&workspace?.id===privateRecordingEntry.returnWorkspaceId&&recordingCurrent(privateRecordingEntry);
          setPrivateRecordingEntry(null);setPrivateRecordingBusy(false);setSettingsOpen(false);setPracticeOpen(false);setPracticePage(returnToNotebook?'notebook':'home');setPrivateRecordingListEpoch(value=>value+1);}}
        onNotebook={async result=>{if(!recordingCurrent(privateRecordingEntry))throw new WorkspaceApiError(403);
          await returnPrivateRecordingNotebook(privateRecordingEntry,result);setPrivateRecordingEntry(null);setPrivateRecordingBusy(false);setPrivateRecordingListEpoch(value=>value+1);}}/></div>}
      {authenticated&&<div ref={recordingHome} tabIndex={-1} hidden={!!privateRecordingEntry&&!recordingMinimized||settingsOpen||practicePage!=='home'||messagesMode&&!contextBot}><PracticeHome identity={authenticated} recovery={accountAccess??null} team={team} teamUnchanged={initialTeamUnchanged}
        nativeCompact={nativeHome} conversationContext={contextChoice?{name:contextChoice.name,scribe:contextChoice.role==='scribe'}:undefined} onPendingChange={setHomePending}
        locked={!!privateRecordingEntry||busy||!!pending||conflict||recoveryState==="failed"||recoveryBlocked||captureNavigationLocked||captureDraftLocked} onBusyChange={setHomeBusy} onAccessLost={failure}
        onUseTeam={()=>{if(initialTeamUnchanged)saveTeam();else void openSettings();}} onSettings={()=>void openSettings()} onVisits={()=>void loadEncounters()}
        onConnections={()=>void openSettings('connections')} onPracticeWork={()=>{setPracticeOpen(true);setPracticeOpened(true);}}
        onRecord={CAPTURE_WORKSPACE_BUILD?startPrivateRecording:undefined}
        recordingActive={!!privateRecordingEntry} openRecordingRequest={privateRecordingRequest}
        recordings={privateRecordings&&privateRecordings.identity===authenticated&&privateRecordings.generation===generation.current&&privateRecordings.scope===journal.current?.scope?privateRecordings.rows:undefined} onReopenRecording={reopenPrivateRecording}
        onOpened={value=>contextOpened(value)} onNoteOpened={value=>contextOpened(value,'notebook')}/></div>}
      <section hidden={settingsOpen||practicePage!=='visits'} data-conversation-picker={!!contextChoice} className={`team-welcome${encounters ? " team-welcome-choosing" : ""}`}><p className="team-kicker">{encounters ? "YOUR VISITS" : "YOUR PRACTICE"}</p>
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
        {authenticated&&encounters&&<VisitCatalog identity={authenticated} visits={encounters} visitsOnly={contextChoice?.role==='research'} locked={busy||!!pending} recordingActive={!!privateRecordingEntry}
          onOpen={appointmentId=>{const target=contextBot;void open(appointmentId).then(()=>{const current=session.getSnapshot().workspace;if(target&&current?.appointment_id===appointmentId){setContextBot(null);return openConversation(current.id,target);}});}} onRecord={!contextChoice&&CAPTURE_WORKSPACE_BUILD&&(!team||team.capture?.enabled)?appointmentId=>void open(appointmentId,undefined,undefined,true):undefined}
          onPrivateNote={workspaceId=>{void session.loading.openSavedPrivate(workspaceId,{authenticated,failure,opened:openPrivateNotebook});}}
          onConnections={()=>void openSettings('core')}/>}
        <p className="team-fine">Notes and private drafts do not need email or calendar setup.</p>
      </section>
      {ehrReviewOwned&&authenticated&&workspace&&<EhrReadTask open={ehrReviewOpen} context={workspace.notebook?.title??workspace.label}
        returnLabel={ehrReview.origin==='connections'?'Back to connections':ehrReview.origin==='sources'?'Back to saved sources':`Back to ${bot?.name??'chat'}`}
        returnBlocked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} onReturn={closeEhrTask}>
        <EhrReadProviders identity={authenticated} active={ehrReviewOpen} workspace={{id:workspace.id,label:workspace.label,revision:workspace.revision}}
          currentSources={workspace.entries.filter(entry=>entry.kind==='ehr_read_source'&&!!entry.ehr_source_state).map(entry=>({id:entry.id,state:entry.ehr_source_state!}))}
          locked={locked||captureNavigationLocked||captureDraftLocked||Object.entries(connectionLocks).some(([key,value])=>key!=='ehr'&&value)}
          recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked||Object.entries(connectionLocks).some(([key,value])=>key!=='ehr'&&value)}
          onBusyChange={reportEhrBusy} onAuthenticationLost={failure} onSaved={receiveGoogleSource}
          onRefreshVisit={refreshGoogleVisit} onAskChief={source=>void prepareEhrChief(source)}/>
      </EhrReadTask>}
      {workspace&&<div className="workspace-notebook" data-native-private-note={nativePrivateNote} hidden={practicePage!=="notebook"||ehrReviewOpen}>
        {messagesMode&&!settingsOpen&&!savedRecordingFocused&&!reviewHandoffId&&<MessagesThreadHeader name={bot?.name??'Conversation'} role={bot?.role??'chief'} context={workspace.notebook?.title??workspace.label} contextKind={workspace.appointment_id?`Linked visit · ${workspace.label}`:'Private note · no visit linked'} task={messagesTaskLabel}
          locked={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onBack={goHome} onContext={()=>void chooseConversationContext(selected)} onDetails={()=>setConversationDetails(true)} onReturn={returnToMessagesChat}/>}

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
        <div hidden={messagesMode&&(!!reviewHandoffId||mobilePanel!=='Notebook')&&!privateLinkPending}>{authenticated&&workspace.private_draft&&!savedRecordingEntry&&<PrivateDraftLinkPanel identity={authenticated} workspace={workspace} recovery={editorAccess??null} forTranscription={!!savedRecordingEntry} compact={nativePrivateNote}
          recoveryLocked={busy||!!pending||recoveryBlocked||captureNavigationLocked||captureDraftLocked}
          locked={busy||homeBusy||!!pending||conflict||recoveryOffers.some(offer=>offer.address===`workspace:${workspace.id}`)||recoveryBlocked||captureNavigationLocked||captureDraftLocked||note!==latestNote}
          onPendingChange={setPrivateLinkPending} onAccessLost={failure} onSaved={latest=>{setWorkspace(latest);setMessage('Private draft linked to the confirmed visit. Your saved history is retained.');}}/>}</div>
        {team?.revision===0&&<div hidden={settingsOpen} className="team-initial-action"><InitialTeamAction
          names={team.configuration.bots.filter(item=>item.enabled&&!item.retired).map(item=>item.name)}
          locked={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} unchanged={initialTeamUnchanged}
          onUse={()=>{if(initialTeamUnchanged&&!locked&&!connectionNavigationLocked&&!captureNavigationLocked&&!captureDraftLocked)saveTeam();}}
          onSettings={()=>void openSettings()}/></div>}
        {!savedRecordingEntry && CAPTURE_WORKSPACE_BUILD && authenticated && visitLinked && team?.capture?.enabled &&
          <div hidden={(settingsOpen||practiceOpen)&&!captureNavigationLocked||(messagesMode?(!!reviewHandoffId||mobilePanel!=='Notebook'):phoneChiefConversation)&&!scribeRecordingOpen&&!captureNavigationLocked}><CapturePanel key={workspace.id} workspaceId={workspace.id} identity={authenticated} encounterLabel={workspace.label}
            notesEnabled={CAPTURE_NOTES_BUILD && team.capture.notes_enabled === true} onDraftLock={setCaptureDraftLocked} onNavigationLock={setCaptureNavigationLocked} onTransitionChange={setCaptureTransition} onExpandedChange={setScribeRecordingOpen}
            correctionsEnabled={CAPTURE_CORRECTIONS_BUILD && team.capture.corrections_enabled === true}
            scratchpad={workspace.entries.filter(e => e.kind === "scratchpad").at(-1)} notebookDirty={note !== latestNote}
            taskBot={scribe ? {selection: {address: botAddress(scribe), team_revision: team.revision},
              name: scribe.name, enabled: scribe.enabled && team.revision > 0, includeNotebook: scribe.include_notebook} : undefined}
            openRequest={locked || settingsOpen || practiceOpen || practicePage!=="notebook" ? 0 : captureRequest} preferencesScope={team.recovery_scope}
            onNotebook={() => { setPanel("Notebook"); setMobilePanel("Notebook"); }}
            onReviewDraft={useCoreDraft} onCurrentDraft={setObservedCaptureDraft} reviewLocked={locked} /></div>}
        {CAPTURE_WORKSPACE_BUILD && authenticated && visitLinked && team?.capture?.enabled && !settingsOpen && !practiceOpen &&
          <div hidden={(messagesMode?(!!reviewHandoffId||mobilePanel!=='Notebook'):phoneChiefConversation)&&!scribeSourceBusy}><ExistingScribeSourcePanel key={`scribe-source:${workspace.id}`} workspace={workspace} identity={authenticated}
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
        <div className="workspace-notebook-body" data-messages-material={mobilePanel} data-handoff-open={!!reviewHandoffId} data-native-chat={nativeChat} data-chief-phone={phoneChief} data-chief-tools={phoneChiefToolsVisible} data-view={mobilePanel==='Conversation'?'conversation':'workspace'} hidden={settingsOpen||savedRecordingFocused}>
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
        
        {identity && reviewHandoffId && workspace.handoffs?.some(h=>h.id===reviewHandoffId) &&
          <HandoffReviewPanel key={`${workspace.id}:${reviewHandoffId}`} workspace={workspace}
            handoff={workspace.handoffs.find(h=>h.id===reviewHandoffId)!} identity={identity}
            locked={actionLocked||captureNavigationLocked||captureDraftLocked}
            recoveryLocked={busy||!!pending||!!recoveryOffers.length||recoveryState==='failed'||recoveryBlocked||scribeSourceBusy||captureNavigationLocked||captureDraftLocked}
            onPendingChange={setHandoffReviewPending}
            onAccessLost={failure} onRefresh={refreshHandoffReview}
            onFreshAssignment={prepareFreshHandoff}
            onSaved={latest=>{if(messagesMode&&workspace.id===latest.id&&workspace.revision<=latest.revision)nativePresentationFeedback('success');setWorkspace(previous=>previous?.id===latest.id&&previous.revision<=latest.revision?latest:previous);}}
            closeLabel={currentChiefReviewReturn()?'Return to Chief':conversationReviewCloseLabel()}
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
            role={nativeChat||messagesMode?'region':undefined} aria-label={messagesMode?(messagesTaskLabel??(bot?.role==='research'&&!savedResearchChat?'Research workspace':'Conversation history')):nativeChat?(phoneChiefToolsVisible?'Chief tools':'Conversation history'):undefined} tabIndex={nativeChat||messagesMode?0:undefined}>
          <div id={`chief-tools-${workspace.id}`} className="team-conversation-tools" hidden={messagesMode?!messagesTask&&!phoneChiefToolsVisible&&bot?.role!=='research':phoneChiefConversation&&!phoneChiefToolsVisible}>
          {phoneChiefConversation&&<header className="chief-tools-heading"><h3>Chief tools</h3><button className="team-subtle" disabled={viewNavigationLocked} onClick={returnToPhoneChat}>Back to chat</button></header>}
          {phoneChiefToolsVisible&&thought!==''&&!(nativeChat&&clinicalTeamExpanded)&&<p className="team-fine chief-tools-draft" role="status">Your directions are kept in this plan. Prepare Follow-up and Research includes them with the saved note.</p>}
          {EHR_READ_BUILD&&authenticated&&visitLinked&&bot?.role==='chief'&&<button className="ehr-chief-action" disabled={viewNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={()=>void openEhrTask('conversation')}>Review an appointment</button>}
          <div className="messages-activity-host" hidden={messagesMode&&messagesTask!=='Activity'}>{teamDrafts}</div>
          
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
            onBusyChange={session.setResearchPending} onDenied={failure} onChanged={revision=>{if(revision!==workspace.revision){setConflict(true);void refresh();}}}/>
            : <p className="research-status">Sign in to use private Research settings and check public source connections.</p>}
            <button className="team-subtle" aria-expanded={savedResearchChat} onClick={()=>setSavedResearchChat(value=>!value)}>Saved encounter conversation</button></>}
          {authenticated && <details hidden={messagesMode&&messagesTask!=='Tools'}><summary>Team connector tools</summary><ConnectorToolsPanel identity={authenticated}
            locked={locked||captureNavigationLocked||captureDraftLocked} onAuthenticationLost={failure}/></details>}
          {bot?.role==='research'&&authenticated&&agentResearchRecovery&&<AgentResearchReviewPanel
            identity={authenticated} workspaceId={workspace.id} recovery={agentResearchRecovery}
            locked={lockedWithoutAgentResearch||captureNavigationLocked||captureDraftLocked} onBusyChange={reportAgentResearchBusy} onAuthenticationLost={failure}
            onReady={proposal=>{if(locked||proposal.bot!==selected)return;setSavedResearchChat(true);
              setThought(previous=>previous.trim()?previous+'\n\n'+`Run the reviewed public query for revision ${proposal.revision_id} and report its actual result.`:
                `Run the reviewed public query for revision ${proposal.revision_id} and report its actual result.`);
              setMobilePanel('Conversation');setQuestionFocus(value=>value+1);}}/>}
          {(!messagesMode&&(nativeChat||phoneChiefConversation)||messagesMode&&messagesTask==='Tools')&&chiefStarters}
          {phoneChiefConversation&&<button className="team-subtle chief-tools-settings" disabled={viewNavigationLocked} onClick={()=>void openSettings()}>Skills & settings</button>}
          </div>
          <div className="clinical-plan-host team-conversation-tools" hidden={messagesMode?messagesTask!=='Tools'&&!chiefNoteCompose:phoneChiefConversation&&!phoneChiefToolsVisible&&!chiefNoteCompose}>{clinicalTeamDrafts}</div>
          {/* Keep transient notices before the transcript so its visible end
              still proves the latest reply was displayed for read tracking. */}
          {messagesChat&&<div className="messages-recovery-notices">{recoveryNotices}{workspaceNotices}</div>}
          <div hidden={phoneChiefToolsVisible || bot?.role==='research'&&!savedResearchChat || visitPrepReader&&!turns.length&&pending?.type!=='ask'} className="team-messages" aria-live="polite" aria-relevant="additions">
            {!turns.length && !visitPrepReader && !chiefNoteCompose && <div className="team-conversation-empty"><BotAvatar role={bot?.role ?? "scribe"} large greeting={!busy}
              enabled={!!bot?.enabled && !bot.retired && !!team?.revision && !settingsOpen && !practiceOpen} />
              <h3>{messagesMode?`A private conversation with ${bot?.name??'your teammate'}`:phoneChiefConversation?"What would you like to work on?":stage === "Before" ? "A clear start to the visit" : stage === "During" ? "Space to think and take notes" : "Keep the next step in view"}</h3>
              <p>{team?.llm.enabled ? phoneChiefConversation?"Write naturally. Chief can help organize your notes and coordinate your team.":"Ask a question, organize your notes, or think through the next step. Your team works from the saved context you choose." : "Review saved sources with your team. Advanced skills will connect here as their services become ready."}</p>
              {messagesMode&&bot?.role==='chief'&&chiefStarters}
              {bot?.role!=='chief'&&<button disabled={locked || !team?.revision || !bot?.enabled} onClick={() => {if(session.presentation.enabled){updateThought(template?.prompt??'Review this encounter');setQuestionFocus(value=>value+1);}else ask(template?.prompt);}}>{template?.prompt ?? "Review this encounter"}<span aria-hidden="true"> ↗</span></button>}</div>}
            <ConversationEntries presentation={messagesMode?'messages':'workspace'} projection={conversation} latestSourceRevision={latestSourceRevision} busy={busy} recoveryBlocked={recoveryBlocked} locked={locked}
              onWork={()=>{setPanel('Work');setMobilePanel('Work');}} onSource={id=>{setPanel('Sources');setMobilePanel('Sources');setSelectedSource(id);}}
              onCheck={checkEntryResult} onAction={action=>{
                if(action.kind==='review_note'){setPanel('Review');setMobilePanel('Review');}
                else if(action.kind==='review_work'){setPanel('Work');setMobilePanel('Work');}
                else {const handoff=workspace.handoffs?.find(item=>item.id===action.id);if(handoff){if(action.kind==='retry_handoff')retryTeamTask(handoff);else reviewTeamResult(handoff,true);}}
              }}/>
            {pending?.type === "ask" && !localQuestionRepresented && <div className="team-turn"><article className="team-human-message"><small>You · {busy?'request in progress':'unconfirmed request'}</small><p>{clinicalRequestDisplay(pending.body.content)}</p></article>
              {busy && <p className="team-thinking" role="status">{team?.configuration.bots.find(b => botAddress(b) === pending.body.role)?.name} is {team?.llm.enabled ? "thinking" : "reviewing"}…</p>}</div>}
            {(!chiefNoteCompose||!phoneNoteMatches)&&nativeNoteShortcut}
            
            <div ref={conversationEnd} />
          </div>
          {nativeChat&&(clinicalPreparing||busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected||inlineModelRecovery||message)&&
            <p id="team-request-progress" className="team-fine native-chat-progress" role="status">{clinicalPreparing?'Preparing your private drafts…':busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected?
              `Waiting for ${bot?.name??'your teammate'}’s result. You can keep typing.`:inlineModelRecovery?'Your last message is unconfirmed. Check its saved result above.':message}</p>}
          {inlineModelRecovery&&modelRecovery}
          </div>
          {messagesMode&&mobileChatFrame.newMessages>0&&!messagesTask&&!phoneChiefToolsVisible&&<button className="messages-new-replies" aria-live="polite" onClick={mobileChatFrame.jumpToLatest}>{mobileChatFrame.newMessages} new {mobileChatFrame.newMessages===1?'message':'messages'} ↓</button>}
          <div hidden={phoneChiefToolsVisible || bot?.role==='research'&&!savedResearchChat} className="team-composer-wrap">
            {!messagesMode&&!nativeChat&&!phoneChiefConversation&&chiefStarters}
            {!team?.revision ? <p className="team-fine">You can save notes now. Use your team above to start a conversation.</p> :
            <form className="team-composer" onSubmit={event => { event.preventDefault();if(conversationBusy)return;if(chiefNoteCompose)submitPhoneNoteTask();else ask(); }}>
              {chiefNoteCompose&&<div className="chief-note-compose-context" role="status"><span>Follow-up + Research · v{phoneNoteTask!.selection.note_version}</span>
                <button type="button" className="team-subtle" disabled={viewNavigationLocked} aria-label="Return to regular message" onClick={()=>{setPhoneNoteTask(null);setQuestionFocus(value=>value+1);}}>Message Chief</button></div>}
              {chiefNoteCompose&&(!phoneNoteMatches?<p className="chief-note-compose-attention" role="status">The saved note changed. Choose its current version above; your directions are kept.</p>:phoneNoteDirectionsError?<p className="chief-note-compose-attention" role="status">{phoneNoteDirectionsError}</p>:phoneNoteDirectionsUnsupported?<p className="chief-note-compose-attention" role="status">This practice service needs an update to include your directions with the saved note. Your text is kept.</p>:phoneNoteAlreadyRequested?<p className="chief-note-compose-attention" role="status">These exact drafts are already requested. Review their saved result above.</p>:!phoneNoteTeamReady?<p className="chief-note-compose-attention" role="status">Enable Chief, Follow-up and Research with private draft handoffs to prepare these drafts.</p>:null)}
              {selectedPrep&&!chiefNoteCompose&&<div className="session-prep-included" role="status"><span>Session Prep included · v{selectedPrep.brief_version}</span>
                <button type="button" className="team-subtle" disabled={locked} onClick={()=>setPrepSelection(null)} aria-label="Remove Session Prep from this question">Remove</button></div>}
              {!nativeChat&&busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected&&<p id="team-request-progress" className="team-fine" role="status">
                {`${authenticated?'Your request is saved on this device. ':''}Waiting for ${bot?.name??'your teammate'}’s result. Keep this visit open; review the answer when it appears.`}
              </p>}
              <label className="team-sr-only" htmlFor="team-question">{chiefNoteCompose?'Directions for Chief':'Thought or question'}</label>
              <textarea ref={questionRef} id="team-question" className={chiefNoteCompose?'clinical-team-directions':undefined} aria-describedby={busy&&localModelPending?.type==='ask'&&localModelPending.body.role===selected?"team-request-progress":undefined} rows={messagesMode?1:2} maxLength={4000} disabled={conversationBusy || phoneChiefToolsVisible || (nativeChatOwner?!nativeComposerEditable:locked) || !bot?.enabled || !!bot?.retired} value={thought} onChange={e => updateThought(e.target.value)} placeholder={bot?.retired ? `${bot.name} is retired. Saved history remains available.` : bot?.enabled ? chiefNoteCompose?'Optional directions for these drafts…':messagesMode?'Message…':phoneChiefConversation?`Message ${bot.name}…`:`Ask ${bot.name} about this encounter…` : `${bot?.name} is paused. Enable in settings.`}
                onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing&&
                  !(authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession)){event.preventDefault();if(!conversationBusy&&!locked){if(chiefNoteCompose)submitPhoneNoteTask();else if(thought.trim())ask();}}}}/>
              <div><span>{bot?.name} <span className="team-fine">· {selectedPrep?"saved encounter + selected brief":"saved encounter only"}</span></span><button className="team-send" disabled={conversationBusy || locked || !!nativeChatOwner&&!nativeComposerEditable || (chiefNoteCompose?phoneNoteTaskBlocked:!thought.trim()) || !bot?.enabled}
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
              {messagesMode&&CAPTURE_WORKSPACE_BUILD&&authenticated&&workspace.private_draft?.state==='unlinked'&&!privateRecordingEntry&&<button disabled={locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked} onClick={startNotebookRecording}>Record privately</button>}
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
              onReviewAppointment={EHR_READ_BUILD&&authenticated&&visitLinked?()=>void openEhrTask('sources'):undefined} appointmentReviewLocked={viewNavigationLocked||captureNavigationLocked||captureDraftLocked}
              briefViewedAt={briefViewed?.workspace===workspace.id&&briefViewed.owner===authenticated&&briefViewed.teamRevision===team?.revision?briefViewed.at:undefined}
              onPrep={team?.configuration.bots.some(member=>member.role==='visit_prep'&&member.enabled)?()=>{const reader=team.configuration.bots.find(member=>member.role==='visit_prep'&&member.enabled)!;if(session.presentation.enabled){void openConversation(workspace.id,botAddress(reader)).then(()=>{if(session.getSnapshot().selected===botAddress(reader))showConversationTask('Tools');});}else{setSelected(botAddress(reader));setMobilePanel('Conversation');}}:undefined}
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
