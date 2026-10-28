// @vitest-environment node
import {describe,expect,it,vi} from 'vitest';
import {notebookDraft} from '../draft-journal';
import {memoryDraftStorage} from '../draft-test-fixture';
import type {ClinicalNoteShareReceipt} from '../clinical-team-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from '../workspace-api';
import {WorkspaceSession} from './workspace-session';
import type {PendingSave} from './model';
import type {SaveContext} from './saves';

const workspace:Workspace={id:'00000000-0000-4000-8000-000000000041',appointment_id:null,label:'Invented note',revision:1,entries:[],work_candidates:[]};
const team:ProviderTeam={revision:1,recovery_scope:'a'.repeat(64),template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},
  configuration:{practice_context:'DPC',bots:[{role:'chief',name:'Chief',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[]};
const authenticated:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const operation:Extract<PendingSave,{type:'entry'}>={type:'entry',body:{expected_revision:1,idempotency_key:'00000000-0000-4000-8000-000000000042',kind:'scratchpad',content:'Invented working note'}};
const result={entry_id:'00000000-0000-4000-8000-000000000046',workspace:{...workspace,revision:2},entry_revision:2};
function context(session:WorkspaceSession):SaveContext {
  return {notebookDraft,saveModel:vi.fn(),teamSaved:vi.fn(),coreNoteLinked:vi.fn(),
    failure:cause=>session.lifecycle.failure(cause,{clear:session.clear,recoveryFailed:()=>session.setRecoveryState('failed'),invalidateSetup:()=>{}})};
}
function open(session:WorkspaceSession){session.setIdentity({boxId:'invented-box',actorId:'invented-human'});session.setWorkspace(workspace);session.setTeam(team);session.setNote(operation.body.content);}
async function durable(session:WorkspaceSession){open(session);session.setIdentity(authenticated);await session.recovery.prepare({authenticated,team,workspace,generation:session.generation.current,apiBase:'http://127.0.0.1:8000',native:false,draftStorage:memoryDraftStorage()});}

describe('shared exact workspace saves',()=>{
  it('retries the identical retained request after a lost reply without changing its body or key',async()=>{
    const append=vi.fn().mockRejectedValueOnce(new Error('Lost reply')).mockResolvedValueOnce(result);
    const session=new WorkspaceSession({saves:{workspace:{append}}});open(session);
    await session.saves.save(operation,context(session));
    expect(session.getSnapshot().pending).toBe(operation);expect(session.getSnapshot().readRetry).toBeNull();
    await session.saves.save(session.getSnapshot().pending!,context(session));
    expect(append).toHaveBeenCalledTimes(2);
    expect(append.mock.calls[0][2]).toBe(operation.body);expect(append.mock.calls[1][2]).toBe(operation.body);
    expect(session.getSnapshot()).toMatchObject({pending:null,workspace:result.workspace,note:'Invented working note'});
  });

  it('persists the exact request before transmission and withholds completion until acknowledgment',async()=>{
    const append=vi.fn().mockResolvedValue(result),session=new WorkspaceSession({saves:{workspace:{append}}});await durable(session);
    const journal=session.recovery.journal.current!.value,persist=journal.persist.bind(journal);
    let release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve;});
    vi.spyOn(journal,'persist').mockImplementationOnce(async(address,value)=>{await gate;return persist(address,value);});
    const saving=session.saves.save(operation,{...context(session),authenticated});
    expect(append).not.toHaveBeenCalled();expect(session.getSnapshot().message).toBe('');
    release();await saving;
    expect(append).toHaveBeenCalledOnce();expect(session.getSnapshot().message).toBe('Saved revision 2.');
    expect((await journal.load(`workspace:${workspace.id}`))?.pending).toBeNull();session.recovery.close();
  });

  it('does not transmit when durable storage cannot acknowledge a new request',async()=>{
    const append=vi.fn(),session=new WorkspaceSession({saves:{workspace:{append}}});await durable(session);
    vi.spyOn(session.recovery.journal.current!.value,'persist').mockRejectedValue(new Error('Local store unavailable'));
    await session.saves.save(operation,{...context(session),authenticated});
    expect(append).not.toHaveBeenCalled();expect(session.getSnapshot()).toMatchObject({pending:null,recoveryState:'failed',note:operation.body.content});
    session.recovery.close();
  });

  it('rechecks authority after local persistence and before transmission',async()=>{
    const append=vi.fn(),session=new WorkspaceSession({saves:{workspace:{append}}});await durable(session);
    let allowed=true;
    const journal=session.recovery.journal.current!.value,persist=journal.persist.bind(journal);
    vi.spyOn(journal,'persist').mockImplementation(async(address,value)=>{await persist(address,value);allowed=false;});
    await session.saves.save(operation,{...context(session),authenticated},'submit',()=>allowed);
    expect(append).not.toHaveBeenCalled();expect(session.getSnapshot().pending).toBe(operation);
    session.recovery.close();
  });

  it('drops a late successful receipt after the workspace is invalidated',async()=>{
    let release!:(value:typeof result)=>void;
    const append=vi.fn(()=>new Promise<typeof result>(resolve=>{release=resolve;}));
    const session=new WorkspaceSession({saves:{workspace:{append}}});open(session);
    const saving=session.saves.save(operation,context(session));session.clear();session.setMessage('New session');
    release(result);await saving;
    expect(session.getSnapshot()).toMatchObject({workspace:null,pending:null,message:'New session',busy:false});
  });

  it('retains an exact team save until the current team can be read independently',async()=>{
    const saveTeam=vi.fn(async()=>team),readTeam=vi.fn().mockRejectedValue(new WorkspaceApiError(503));
    const session=new WorkspaceSession({saves:{workspace:{saveTeam,team:readTeam}}});open(session);
    const retained:PendingSave={type:'team',body:{expected_revision:1,idempotency_key:'00000000-0000-4000-8000-000000000043',configuration:team.configuration}};
    const host=context(session);await session.saves.save(retained,host);
    expect(session.getSnapshot().pending).toBe(retained);expect(host.teamSaved).not.toHaveBeenCalled();
    expect(session.getSnapshot().message).not.toContain('saved');
  });

  it('checks an absent share without replaying it and only closes it after an advanced revision',async()=>{
    const share=vi.fn(),resolve=vi.fn();
    const session=new WorkspaceSession({saves:{clinical:{share,resolve}}});await durable(session);
    const retained:Extract<PendingSave,{type:'clinicalNoteShare'}>={type:'clinicalNoteShare',body:{expected_revision:1,
      idempotency_key:'00000000-0000-4000-8000-000000000044',note_id:'00000000-0000-4000-8000-000000000045',note_version:1,
      content_hash:'b'.repeat(64),source_fingerprint:'c'.repeat(64),share_with_team:true}};
    const receipt:ClinicalNoteShareReceipt={contract:'clinical-note-share.v1',outcome:'not_found',source_entry_id:null,source_entry_revision:null,workspace};
    resolve.mockResolvedValue(receipt);await session.saves.save(retained,{...context(session),authenticated},'resolve');
    expect(share).not.toHaveBeenCalled();expect(resolve.mock.calls[0][2]).toBe(retained.body);
    await session.saves.closeRejectedClinicalShare({authenticated,notebookDraft});expect(session.getSnapshot().pending).toBe(retained);
    resolve.mockResolvedValue({...receipt,workspace:result.workspace});
    await session.saves.save(retained,{...context(session),authenticated},'resolve');
    await session.saves.closeRejectedClinicalShare({authenticated,notebookDraft});
    expect(session.getSnapshot()).toMatchObject({pending:null,clinicalShareCheck:null,note:operation.body.content,workspace:result.workspace});
    expect(share).not.toHaveBeenCalled();session.recovery.close();
  });
});
