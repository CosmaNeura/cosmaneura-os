// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {notebookDraft} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import {CLINICAL_NOTE_LABEL,noteSelection,parseClinicalTeamRequest,type ShareSavedNoteInput,type ClinicalNoteShareReceipt} from '../clinical-team-contract';
import {vendorSha256} from '../vendor-contract';
import {modelCanonical} from '../model-work-request';
import type {AuthenticatedWorkspaceIdentity,PrivateNote,ProviderTeam,Workspace} from '../workspace-api';
import type {ClinicalContext} from './clinical';
import {WorkspaceSession} from './workspace-session';

const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
async function fixture(){
  const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
  const previousIdentity:{current:AuthenticatedWorkspaceIdentity|undefined}={current:authenticated};
  const content='Invented saved note for private review';
  const note:PrivateNote={id:id(31),version:1,workspace_revision:2,content,content_hash:await vendorSha256(new TextEncoder().encode(modelCanonical({content}))),source_reply_id:null,source_revision:1,source_fingerprint:'b'.repeat(64),sources_changed:false,review:null,created_at:'2026-10-20T12:00:00Z'};
  let current:Workspace={id:id(30),appointment_id:id(29),label:'Invented visit',revision:2,work_candidates:[],note:{latest:note,history:[note]},entries:[]};
  const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:true,model:'gpt-4.1'},configuration:{bots:['chief','follow_up','research'].map(role=>({role:role as 'chief'|'follow_up'|'research',name:role,enabled:true,response_style:'brief',include_evidence:true,include_notebook:true}))},members:[{role:'chief',name:'Chief',agent_id:id(50),initials:'CH',description:'Invented chief',prompt:'Invented',capabilities:[{key:'workspace.clinical.drafts',label:'Drafts',state:'enabled',connector:'Team',contract:'clinical-team-drafts.request.v2'}]}]};
  const share=vi.fn(async(_owner,_wid,input:ShareSavedNoteInput):Promise<ClinicalNoteShareReceipt>=>{
    const entry={id:id(32),revision:3,kind:'conversation' as const,source_label:CLINICAL_NOTE_LABEL,origin:'human_note_share',content:JSON.stringify({contract:'clinical-note-team-source.v1',request:input,note:{id:note.id,version:note.version,content_hash:note.content_hash,source_fingerprint:note.source_fingerprint,content}}),reply:null,ticket:null,created_at:'2026-10-20T12:00:00Z'};
    current={...current,revision:3,entries:[entry]};return {contract:'clinical-note-share.v1',outcome:'saved',source_entry_id:entry.id,source_entry_revision:entry.revision,workspace:current};
  });
  const read=vi.fn(async()=>current),saveModel=vi.fn<ClinicalContext['saveModel']>(async()=>{}),failure=vi.fn();
  const session=new WorkspaceSession({clinical:{read,team:async()=>team},saves:{clinical:{share}}});
  session.setIdentity(authenticated);session.setWorkspace(current);session.setTeam(team);session.models.updateThought('Keep this invented direction verbatim.');
  await session.recovery.prepare({authenticated,team,workspace:current,generation:0,apiBase:'http://127.0.0.1:8000',native:false,draftStorage:memoryDraftStorage()});
  session.clinical.safety.current={blocked:false,busy:false,pending:null};
  const context:ClinicalContext={authenticated,locked:false,viewNavigationLocked:false,captureNavigationLocked:false,captureDraftLocked:false,recoveryBlocked:false,latestNote:'',previousIdentity,privateRecordingLive:{current:{authenticated}},
    currentIdentity:{get current(){return session.getSnapshot().identity;}},recoveryView:{get current(){return session.getSnapshot();}},currentTeam:{get current(){return session.getSnapshot().team;}},failure,modelFailure:failure,notebookDraft,saveModel,
    save:(operation,mode,authority)=>session.saves.save(operation,{authenticated,notebookDraft,failure,saveModel,teamSaved:()=>{},coreNoteLinked:()=>{}},mode,authority),showReplacement:vi.fn()};
  return {session,context,share,read,saveModel,input:noteSelection(note,2),previousIdentity};
}

describe('shared exact saved-note preparation',()=>{
  it('shares the selected saved note, confirms it again, then submits verbatim directions with its exact version and hash',async()=>{
    const f=await fixture();await f.session.clinical.prepare(f.input,f.context);
    expect(f.share.mock.calls[0][2]).toEqual(f.input);expect(f.read).toHaveBeenCalledOnce();expect(f.saveModel).toHaveBeenCalledOnce();
    const [operation,mode,confirmed]=f.saveModel.mock.calls[0];expect(mode).toBe('submit');expect(operation.type).toBe('ask');
    if(operation.type!=='ask')throw Error('Expected model request');
    expect(parseClinicalTeamRequest(operation.body.content)).toEqual({contract:'clinical-team-drafts.request.v2',source_entry_id:id(32),note_id:f.input.note_id,note_version:1,content_hash:f.input.content_hash,owner_directions:'Keep this invented direction verbatim.'});
    expect(operation.body.expected_revision).toBe(3);expect(confirmed?.composer?.content).toBe('Keep this invented direction verbatim.');
    expect(f.session.getSnapshot().clinicalPreparing).toBe(false);f.session.recovery.close();
  });
  it('does not admit a model request if the directions were edited during the fresh source read',async()=>{
    const f=await fixture();f.read.mockImplementation(async()=>{f.session.models.updateThought('Changed direction');return f.session.getSnapshot().workspace!;});
    await f.session.clinical.prepare(f.input,f.context);expect(f.share).toHaveBeenCalledOnce();expect(f.saveModel).not.toHaveBeenCalled();
    expect(f.session.getSnapshot().thought).toBe('Changed direction');f.session.recovery.close();
  });
  it('drops the result if the authenticated owner changes without waiting for a generation effect',async()=>{
    const f=await fixture();f.read.mockImplementation(async()=>{f.previousIdentity.current={mode:'clerk_jwt',getToken:async()=>null};return f.session.getSnapshot().workspace!;});
    await f.session.clinical.prepare(f.input,f.context);expect(f.saveModel).not.toHaveBeenCalled();expect(f.context.failure).not.toHaveBeenCalled();f.session.recovery.close();
  });
  it('retains an absent exact share without starting Chief or claiming completion',async()=>{
    const f=await fixture();f.share.mockImplementation(async()=>({contract:'clinical-note-share.v1',outcome:'not_found',source_entry_id:null,source_entry_revision:null,workspace:f.session.getSnapshot().workspace!}));
    await f.session.clinical.prepare(f.input,f.context);expect(f.session.getSnapshot().pending).toEqual({type:'clinicalNoteShare',body:f.input});expect(f.saveModel).not.toHaveBeenCalled();f.session.recovery.close();
  });
  it('does not share a source whose selected version no longer matches',async()=>{
    const f=await fixture();await f.session.clinical.prepare({...f.input,note_version:2},f.context);expect(f.share).not.toHaveBeenCalled();expect(f.saveModel).not.toHaveBeenCalled();f.session.recovery.close();
  });
});
