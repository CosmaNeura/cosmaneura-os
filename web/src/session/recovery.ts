import {DraftJournal,editorAddress,teamDraft as recoveryTeamDraft,type NotebookDraft,type RecoveryOffer} from '../draft-journal';
import {privateDraftScope,DraftStoreError,type DraftStore} from '../draft-store';
import type {AccountRecoveryAccess} from '../account-recovery';
import type {EditorRecoveryAccess} from '../editor-recovery';
import {validateAgentResearchRecovery,type AgentResearchRecoveryAccess} from '../agent-research-recovery';
import {botAddress,workspaceApi,requireRecoveryScope,validRecoveryScope,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from '../workspace-api';
import type {ChiefNoteTask} from './model';
import type {WorkspaceSession} from './workspace-session';

export type DraftStorage=(options:{scope:string;native:boolean})=>Promise<DraftStore>;
export type RecoveryRead={
  authenticated?:AuthenticatedWorkspaceIdentity;
  team:ProviderTeam;
  workspace:Workspace|null;
  generation:number;
  reloadParent?:boolean;
  apiBase:string;
  native:boolean;
  draftStorage:DraftStorage;
};
export type RecoveryOwner={
  authenticated?:AuthenticatedWorkspaceIdentity;
  currentAuthenticated:()=>AuthenticatedWorkspaceIdentity|undefined;
  currentTeam:()=>ProviderTeam|null;
};
export type ScheduledDraftSave={run:()=>Promise<void>;cancel:()=>void;drain:()=>Promise<void>};
export type RecoveryDependencies=Pick<typeof workspaceApi,'team'|'read'>;
export type RestoredDraftView={kind:'team'}|{kind:'workspace';material:'Conversation'|'Work'|'Review'|'Notebook';noteTask?:ChiefNoteTask;helper?:string};

/** Account-scoped draft storage outlives either presentation. */
export class WorkspaceRecovery {
  readonly journal:{current:{scope:string;serverScope:string;value:DraftJournal}|null}={current:null};
  readonly scheduledDraftSave:{current:ScheduledDraftSave|null}={current:null};
  readonly draftsSuspended={current:false};
  readonly nativeModelSettling={current:false};

  private readonly api:RecoveryDependencies;
  constructor(private readonly session:WorkspaceSession,deps:Partial<RecoveryDependencies>={}) {
    this.api={team:(...args)=>workspaceApi.team(...args),read:(...args)=>workspaceApi.read(...args),...deps};
  }

  accountAccess(authenticated:AuthenticatedWorkspaceIdentity|undefined,editorScope:string|null|undefined,editorJournal:DraftJournal|undefined,ready:boolean):AccountRecoveryAccess|null|undefined {
    if(!authenticated)return undefined;
    if(!ready||!editorJournal||!validRecoveryScope(editorScope))return null;
    return {journal:editorJournal,recoveryScope:editorScope,authorize:async()=>{
      const latest=await this.api.team(authenticated);
      // Account editors follow the account scope across notebook navigation.
      if(requireRecoveryScope(latest)!==editorScope||this.journal.current?.value!==editorJournal)throw new WorkspaceApiError(403);
    }};
  }

  editorAccess(authenticated:AuthenticatedWorkspaceIdentity|undefined,editorScope:string|undefined,editorJournal:DraftJournal|undefined,editorWorkspace:string|undefined,ready:boolean,blocked:boolean,failure:(cause:unknown)=>void):EditorRecoveryAccess|null|undefined {
    if(!authenticated)return undefined;
    if(blocked||!editorJournal||!editorWorkspace||!ready)return null;
    return {journal:editorJournal,workspaceId:editorWorkspace,recoveryScope:editorScope,authorize:async()=>{
      const current=this.session.generation.current;
      const team=await this.api.team(authenticated);
      if(current!==this.session.generation.current||team.recovery_scope!==editorScope)throw new WorkspaceApiError(403);
      const latest=await this.api.read(authenticated,editorWorkspace);
      if(current!==this.session.generation.current||this.journal.current?.value!==editorJournal)throw new WorkspaceApiError(403);
      const view=this.session.getSnapshot();
      if(view.workspace?.id!==latest.id)throw new WorkspaceApiError(403);
      const saved=view.workspace.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'';
      if(latest.revision!==view.workspace.revision&&view.note!==saved&&(latest.entries.filter(entry=>entry.kind==='scratchpad').at(-1)?.content??'')!==saved)this.session.setConflict(true);
      this.session.setWorkspace(latest);return latest;
    },denied:cause=>{
      if(cause&&typeof cause==='object'&&'status' in cause&&[401,403,404].includes(Number(cause.status)))failure(new WorkspaceApiError(Number(cause.status)));
    }};
  }

  agentResearchAccess(editorAccess:EditorRecoveryAccess|null|undefined,workspaceId:string|undefined):AgentResearchRecoveryAccess|null {
    if(!editorAccess||!workspaceId)return null;
    const address=editorAddress(workspaceId,'agent-research-review');
    return {authorize:async()=>{await editorAccess.authorize();},load:async()=>{
      const value=await editorAccess.journal.load(address);if(value===null)return null;
      if(value?.kind!=='editor'||value.editor!=='agent-research-review')throw new DraftStoreError('integrity');
      return validateAgentResearchRecovery(value.data,workspaceId);
    },persist:async value=>{await editorAccess.journal.persist(address,value===null?null:{kind:'editor',workspaceId,editor:'agent-research-review',data:value,pending:value.pending?.revision_id??null});}};
  }

  close():void {
    const old=this.journal.current?.value,save=this.scheduledDraftSave.current;
    this.journal.current=null;this.scheduledDraftSave.current=null;
    // Complete the last local snapshot before closing its account-scoped store.
    // No server request is sent, even when the draft contains a pending request.
    void (save?.run()??Promise.resolve()).catch(()=>{}).finally(()=>old?.close());
  }

  checkOwner(authenticated:AuthenticatedWorkspaceIdentity|undefined,team:ProviderTeam):void {
    if(!authenticated)return;
    const scope=requireRecoveryScope(team);
    if(this.journal.current&&this.journal.current.serverScope!==scope)throw new WorkspaceApiError(403);
  }

  async prepare(input:RecoveryRead):Promise<void> {
    const {authenticated,team,workspace,generation:current,reloadParent=false}=input;
    if(!authenticated)return;
    this.checkOwner(authenticated,team);
    const serverScope=requireRecoveryScope(team);
    const scope=await privateDraftScope(serverScope,input.apiBase);
    if(current!==this.session.generation.current)return;
    if(this.journal.current?.scope!==scope) {
      this.journal.current?.value.close();this.journal.current=null;
      const store=await input.draftStorage({scope,native:input.native});
      if(current!==this.session.generation.current){store.close();return;}
      this.journal.current={scope,serverScope,value:new DraftJournal(store)};
    }
    const active=this.journal.current.value;
    const addresses=['team',...(workspace?[`workspace:${workspace.id}`,
      editorAddress(workspace.id,'private-note'),editorAddress(workspace.id,'core-note'),editorAddress(workspace.id,'transcript')]:[])];
    const offers:RecoveryOffer[]=[];
    for(const address of addresses) {
      if(active.has(address)&&!reloadParent)continue;
      const draft=await active.load(address);
      if(current!==this.session.generation.current||this.journal.current?.value!==active)return;
      if(draft&&(draft.kind==='team'||draft.kind==='workspace'))offers.push({address,draft});
    }
    this.session.setRecoveryOffers(previous=>[...previous.filter(offer=>!reloadParent||!addresses.includes(offer.address)),...offers]);
    this.session.setRecoveryState('');this.session.setRecoveryEpoch(value=>value+1);
  }

  async afterRead(input:RecoveryRead,failure:(cause:unknown)=>void):Promise<void> {
    try {await this.prepare(input);}
    catch(cause) {if(input.generation===this.session.generation.current) {
      if(cause instanceof WorkspaceApiError&&cause.status===403)failure(cause);
      else this.session.setRecoveryState('failed');
    }}
  }

  flush(owner:RecoveryOwner):void {
    const {authenticated}=owner;
    if(owner.currentAuthenticated()!==authenticated||
      authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession&&!authenticated.nativeSession.isCurrent())return;
    if(authenticated&&(!validRecoveryScope(owner.currentTeam()?.recovery_scope)||
      this.journal.current?.serverScope!==owner.currentTeam()?.recovery_scope))return;
    void this.scheduledDraftSave.current?.run().catch(()=>{});
  }

  schedule(owner:RecoveryOwner,notebookDraft:(pending:NotebookDraft['pending'])=>NotebookDraft|null):(()=>void)|undefined {
    const session=this.session,{authenticated}=owner;
    const {team,teamDraft,workspace,busy,pending,recoveryState,recoveryOffers}=session.getSnapshot();
    session.setRecoveryState(previous=>previous==='saved'?'':previous);
    const active=this.journal.current?.value;
    const nativePending=authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession&&pending?.type==='ask'?pending:null;
    if(!active||this.nativeModelSettling.current||(busy||pending)&&!nativePending||recoveryState==='failed'||
      authenticated?.mode==='clerk_jwt'&&authenticated.nativeSession&&!authenticated.nativeSession.isCurrent()||
      authenticated&&(!validRecoveryScope(team?.recovery_scope)||this.journal.current?.serverScope!==team?.recovery_scope))return;
    const current=session.generation.current;
    let canceled=false,flight:Promise<void>|null=null;
    const writes:Array<()=>Promise<void>>=[];
    if(!busy&&!pending&&team&&teamDraft&&active.has('team')&&!recoveryOffers.some(offer=>offer.address==='team'))
      writes.push(()=>active.persist('team',recoveryTeamDraft(team,teamDraft,null)));
    if(workspace&&active.has(`workspace:${workspace.id}`)&&!recoveryOffers.some(offer=>offer.address===`workspace:${workspace.id}`))
      writes.push(()=>active.persist(`workspace:${workspace.id}`,notebookDraft(nativePending)));
    if(!writes.length)return;
    const run=()=>{
      clearTimeout(timer);
      if(!flight) {
        if(current===session.generation.current)session.setRecoveryState(previous=>previous==='failed'?previous:'saving');
        flight=Promise.all(writes.map(write=>write())).then(()=>{
          if(!canceled&&current===session.generation.current)session.setRecoveryState(previous=>previous==='failed'?previous:'saved');
        }).catch(error=>{if(!canceled&&current===session.generation.current)session.setRecoveryState('failed');throw error;});
      }
      return flight;
    };
    const timer=setTimeout(()=>{void run().catch(()=>{});},180);
    const save={run,cancel:()=>{clearTimeout(timer);canceled=true;},drain:()=>flight??Promise.resolve()};
    this.scheduledDraftSave.current=save;
    if(this.draftsSuspended.current)this.flush(owner);
    return()=>{save.cancel();if(this.scheduledDraftSave.current===save)this.scheduledDraftSave.current=null;};
  }

  async discard(offer:RecoveryOffer):Promise<void> {
    const session=this.session,{busy,pending}=session.getSnapshot();
    if(busy||pending||offer.draft.pending)return;
    const current=session.generation.current;session.setBusy(true);
    try {
      await this.journal.current?.value.persist(offer.address,null);
      if(current===session.generation.current)session.setRecoveryOffers(previous=>previous.filter(value=>value.address!==offer.address));
    } catch {if(current===session.generation.current)session.setRecoveryState('failed');}
    finally {if(current===session.generation.current)session.setBusy(false);}
  }

  async restore(offer:RecoveryOffer,context:{authenticated?:AuthenticatedWorkspaceIdentity;
    failure:(cause:unknown)=>void;show:(view:RestoredDraftView)=>void}):Promise<void> {
    const session=this.session,{busy,pending,team,workspace}=session.getSnapshot(),{authenticated}=context;
    if(busy||pending||!authenticated)return;
    const draft=offer.draft,current=session.generation.current;session.setBusy(true);
    try {
      // Revalidate the current human and patient boundary before revealing text.
      const latestTeam=await this.api.team(authenticated);
      if(current!==session.generation.current)return;
      if(!latestTeam.recovery_scope||latestTeam.recovery_scope!==team?.recovery_scope)throw new WorkspaceApiError(403);
      const latest=draft.kind==='workspace'?await this.api.read(authenticated,draft.workspaceId):null;
      if(current!==session.generation.current)return;
      session.setTeam(latestTeam);
      if(draft.kind==='team') {
        session.setTeamDraft(draft.configuration);context.show({kind:'team'});
        if(draft.pending)session.setPending({type:'team',body:draft.pending});
        else if(latestTeam.revision!==draft.baseRevision)session.setConflict(true);
      } else if(latest&&workspace?.id===draft.workspaceId) {
        session.setWorkspace(latest);session.setNote(draft.note);session.setThought(draft.thought);session.setEvidence(draft.evidence);session.setSource(draft.source);
        let noteTask:ChiefNoteTask|undefined,helper:string|undefined;
        if(draft.chief_note_task&&this.journal.current) {
          const task=draft.chief_note_task,saved=latest.note?.latest,chief=latestTeam.configuration.bots.find(item=>item.role==='chief');
          const matches=!!saved&&saved.id===task.note_id&&saved.version===task.note_version&&saved.content_hash===task.content_hash&&saved.source_fingerprint===task.source_fingerprint;
          noteTask={owner:authenticated,scope:this.journal.current.scope,generation:current,workspaceId:latest.id,
            selection:{expected_revision:latest.revision,idempotency_key:crypto.randomUUID(),note_id:task.note_id,note_version:task.note_version,
              content_hash:task.content_hash,source_fingerprint:task.source_fingerprint,share_with_team:true},content:matches?saved.content:''};
          if(chief)helper=botAddress(chief);
        }
        const material=draft.chief_note_task?'Conversation':draft.pending?.type.startsWith('followUp')?'Work':
          draft.pending&&['note','review','coreNoteLink'].includes(draft.pending.type)?'Review':'Notebook';
        context.show({kind:'workspace',material,noteTask,helper});
        if(draft.pending)session.setPending(draft.pending);
        else if(latest.revision!==draft.baseRevision)session.setConflict(true);
        session.setPreviousModelRequest(draft.previous_model_request??((draft.pending?.type==='ask'||draft.pending?.type==='retry')?draft.pending.previous_model_request:null)??null);
      } else return;
      session.setRecoveryOffers(previous=>previous.filter(value=>value.address!==offer.address));
      session.setMessage("Recovered this device's draft. Check it against the current saved history before continuing. Unconfirmed requests are retried only when you choose.");
    } catch(cause) {if(current===session.generation.current)context.failure(cause);}
    finally {if(current===session.generation.current)session.setBusy(false);}
  }

  async exit(discard:boolean,context:{navigationLocked:boolean;hasUnsavedWork:()=>boolean;
    confirm:()=>void;clear:()=>void;onExit?:()=>void}):Promise<void> {
    const session=this.session;
    if(context.navigationLocked) {
      session.setError('Save or recover your unfinished edits before closing. Unconfirmed requests are retained.');return;
    }
    if(!discard&&(context.hasUnsavedWork()||session.getSnapshot().recoveryOffers.length)){context.confirm();return;}
    const active=this.journal.current?.value,current=session.generation.current;
    if(active) {
      this.scheduledDraftSave.current?.cancel();this.scheduledDraftSave.current=null;session.setBusy(true);
      try {
        for(const [address,record] of active.records) {
          const body=record.value?.body as {kind?:unknown;pending?:unknown}|undefined;
          // Child editors own their nested exact requests and proof history.
          if(body?.kind==='account-editor'||body?.kind==='editor')continue;
          if(!body?.pending)await active.persist(address,null);
        }
      } catch {if(current===session.generation.current){session.setRecoveryState('failed');session.setBusy(false);}return;}
    }
    if(current===session.generation.current){context.clear();context.onExit?.();}
  }
}
