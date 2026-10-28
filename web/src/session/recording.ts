import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from '../workspace-api';
import {listPrivateRecordings,PrivateRecordingRuntime} from '../private-recording-runtime';
import type {WorkspaceSession} from './workspace-session';
import type {PrivateRecordingEntry,PrivateNotebookResult,RecordingOwner} from './recording-model';
export type RecordingContext={
  authenticated?:AuthenticatedWorkspaceIdentity;authorize:(()=>Promise<void>)|null;
  captureEnabled:boolean;locked:boolean;connectionNavigationLocked:boolean;captureNavigationLocked:boolean;captureDraftLocked:boolean;
  expand:()=>void;showNotebook:()=>void;openNotebook:(result:PrivateNotebookResult)=>Promise<void>;
};
export type RecordingDependencies={openPrivateDraft?:typeof workspaceApi.openPrivateDraft;list?:typeof listPrivateRecordings};

/** Recording identity and continuation belong to the session, never a layout. */
export class WorkspaceRecording {
  readonly live:{current:RecordingOwner}={current:{authenticated:undefined,editorJournal:undefined,editorScope:undefined,generation:0}};
  private readonly openPrivateDraft:typeof workspaceApi.openPrivateDraft;
  private readonly listRecordings:typeof listPrivateRecordings;
  constructor(private readonly session:WorkspaceSession,deps:RecordingDependencies={}){
    this.openPrivateDraft=deps.openPrivateDraft??((...args)=>workspaceApi.openPrivateDraft(...args));this.listRecordings=deps.list??listPrivateRecordings;
  }
  readonly isCurrent=(entry:PrivateRecordingEntry):boolean=>{
    const live=this.live.current;
    return this.session.generation.current===entry.generation&&this.session.recovery.journal.current?.value===entry.journal&&
      live.authenticated===entry.identity&&live.editorJournal===entry.journal&&live.editorScope===entry.serverScope&&live.generation===entry.generation&&
      (entry.identity.mode==='desktop_native'?entry.identity.isCurrent():!entry.identity.nativeSession||entry.identity.nativeSession.isCurrent());
  };
  list(authenticated:AuthenticatedWorkspaceIdentity,platform:'ios'|'desktop'):()=>void {
    const current=this.session.recovery.journal.current;if(!current)return()=>{};
    const {scope,value:currentJournal,serverScope}=current,currentGeneration=this.session.generation.current;let active=true;
    void this.listRecordings(scope,platform).then(rows=>{
      const live=this.live.current;
      if(active&&this.session.generation.current===currentGeneration&&live.authenticated===authenticated&&live.generation===currentGeneration&&live.editorJournal===currentJournal&&live.editorScope===serverScope&&this.session.recovery.journal.current?.scope===scope)
        this.session.setPrivateRecordings({identity:authenticated,scope,generation:currentGeneration,rows});
    }).catch(()=>{if(active)this.session.setPrivateRecordings(null);});
    return()=>{active=false;};
  }
  start(input:{title:string;prepareNotebook:(title?:string)=>Promise<PrivateNotebookResult>},context:RecordingContext){
    const {busy,privateRecordingEntry}=this.session.getSnapshot();
    const {generation,setPrivateRecordingEntry}=this.session;
    const {journal}=this.session.recovery;
    const {authenticated,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked}=context;
    if(!authenticated||!context.authorize||!journal.current||privateRecordingEntry||connectionNavigationLocked||busy||captureNavigationLocked||captureDraftLocked)return;
    const current=journal.current;
    context.expand();setPrivateRecordingEntry({identity:authenticated,journal:current.value,scope:current.scope,serverScope:current.serverScope,generation:generation.current,title:input.title,prepareNotebook:input.prepareNotebook,authorize:context.authorize});
  }
  startNotebook(context:RecordingContext){
    const {workspace}=this.session.getSnapshot();
    const {generation,setPrivateRecordingEntry}=this.session;
    const {journal,scheduledDraftSave}=this.session.recovery;
    const {authenticated,locked,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked}=context;
    if(!context.captureEnabled||!authenticated||!context.authorize||!journal.current||!workspace||
      workspace.private_draft?.state!=='unlinked'||workspace.appointment_id||locked||connectionNavigationLocked||captureNavigationLocked||captureDraftLocked)return;
    const current=journal.current,owner=authenticated,workspaceId=workspace.id;
    const entry:PrivateRecordingEntry={identity:owner,journal:current.value,scope:current.scope,
      serverScope:current.serverScope,generation:generation.current,returnWorkspaceId:workspaceId,
      title:workspace.notebook?.title??workspace.private_draft.title,authorize:context.authorize,
      prepareNotebook:async()=>{
        if(!this.isCurrent(entry))throw new WorkspaceApiError(403);
        await entry.authorize();if(!this.isCurrent(entry))throw new WorkspaceApiError(403);
        const result=await this.openPrivateDraft(owner,workspaceId);
        if(!this.isCurrent(entry)||result.identity!==owner||result.workspace.id!==workspaceId||
          result.team.recovery_scope!==entry.serverScope||result.workspace.appointment_id||result.workspace.private_draft?.state!=='unlinked')throw new WorkspaceApiError(403);
        return result;
      }};
    // The existing editor remains mounted. Audio preparation neither creates a
    // notebook nor replaces working text with the later signed notebook read.
    void scheduledDraftSave.current?.run().catch(()=>{});
    context.expand();setPrivateRecordingEntry(entry);
  }
  async returnNotebook(entry:PrivateRecordingEntry,result:PrivateNotebookResult,context:RecordingContext){
    const {workspace}=this.session.getSnapshot();
    const {setPrivateRecordingEntry,setPrivateRecordingBusy,setWorkspace}=this.session;
    if(!this.isCurrent(entry)||result.identity!==entry.identity||result.team.recovery_scope!==entry.serverScope)throw new WorkspaceApiError(403);
    if(!entry.returnWorkspaceId){
      // Retire this stopped recorder before changing notebook generation. Its
      // access-loss monitor must not clear the newly opened private editor.
      setPrivateRecordingEntry(previous=>previous===entry?null:previous);setPrivateRecordingBusy(false);
      await context.openNotebook(result);return;
    }
    if(result.workspace.id!==entry.returnWorkspaceId||workspace?.id!==entry.returnWorkspaceId||result.team.recovery_scope!==entry.serverScope)
      throw new WorkspaceApiError(403);
    setWorkspace(previous=>previous?.id===result.workspace.id&&previous.revision<=result.workspace.revision?result.workspace:previous);
    context.showNotebook();
  }
  reopen(recordingId:string,context:RecordingContext){
    const {busy,privateRecordings}=this.session.getSnapshot();
    const {generation,setPrivateRecordingEntry}=this.session;
    const {journal}=this.session.recovery;
    const {authenticated,connectionNavigationLocked,captureNavigationLocked,captureDraftLocked}=context;
    if(!authenticated||!context.authorize||!journal.current||connectionNavigationLocked||busy||captureNavigationLocked||captureDraftLocked)return;
    const current=journal.current;
    const row=privateRecordings?.identity===authenticated&&privateRecordings.generation===generation.current&&privateRecordings.scope===current.scope?privateRecordings.rows.find(value=>value.recordingId===recordingId):undefined;
    if(!row)return;
    const owner=authenticated;
    context.expand();
    setPrivateRecordingEntry({identity:owner,journal:current.value,scope:current.scope,serverScope:current.serverScope,generation:generation.current,title:row.title,recordingId,
      authorize:context.authorize,...(row.workspaceId?{prepareNotebook:()=>this.openPrivateDraft(owner,row.workspaceId!)}:{})});
  }
  async attachNotebook(entry:PrivateRecordingEntry,result:PrivateNotebookResult,recordingId:string|undefined):Promise<void>{
    if(!recordingId||!this.isCurrent(entry)||result.identity!==entry.identity)return;
    await entry.authorize();if(!this.isCurrent(entry))return;
    const saved=await PrivateRecordingRuntime.open({scope:entry.scope,platform:entry.identity.mode==='clerk_jwt'&&entry.identity.nativeSession?'ios':'desktop',isCurrent:()=>this.isCurrent(entry)},
      {recordingId,title:entry.title});
    try{await saved.attachWorkspace(result.workspace.id,true);}finally{await saved.close();}
    if(this.isCurrent(entry))this.session.setPrivateRecordingListEpoch(value=>value+1);
  }
}
